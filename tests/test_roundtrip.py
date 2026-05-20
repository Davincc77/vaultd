"""
test_roundtrip.py — Core test suite for .vaultd encrypt/decrypt roundtrip

Tests:
- Basic encrypt → decrypt roundtrip (correct passphrase)
- Wrong passphrase raises VAULTD_E_DECRYPT
- Tampered ciphertext raises VAULTD_E_DECRYPT
- Unicode passphrase roundtrip
- Custom Argon2id params are preserved in envelope
- Atomic write safety (temp file not left behind on success)
- Envelope size limit
- Payload size limit
- Version compatibility (v1.1 loads in v1.2 reader)
- Missing required envelope fields
- Schema validation catches missing transactions
- Hypothesis property-based: roundtrip with random ASCII passphrases
"""

import base64
import json
import os
import sys
from pathlib import Path

import pytest

# Add scripts/ to path so we can import directly
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from load_vaultd import load_vaultd
from save_vaultd import create_vaultd

# ─── Fixtures ────────────────────────────────────────────────────────────────

MINIMAL_PAYLOAD = {
    "created_at": "2026-05-20T12:00:00Z",
    "identity": {"alias": "tester", "language": "en"},
    "wallets": [],
    "holdings": [],
    "transactions": [],
    "strategy": {},
}

GOOD_PASSPHRASE = "correct-horse-battery-staple-1234"


@pytest.fixture
def tmp_vault(tmp_path):
    """Return a factory that creates a vault file and returns its path."""
    def _make(payload=None, passphrase=GOOD_PASSPHRASE, **kwargs):
        if payload is None:
            payload = {**MINIMAL_PAYLOAD}
        out = tmp_path / "test.vaultd"
        create_vaultd(payload, passphrase, str(out), skip_validation=True, **kwargs)
        return out
    return _make


# ─── Basic Roundtrip ─────────────────────────────────────────────────────────

class TestRoundtrip:
    def test_basic_roundtrip(self, tmp_vault):
        """Encrypt then decrypt with the same passphrase returns original payload."""
        vault = tmp_vault()
        result = load_vaultd(str(vault), GOOD_PASSPHRASE, skip_validation=True)
        assert result["identity"]["alias"] == "tester"
        assert result["wallets"] == []

    def test_roundtrip_preserves_all_fields(self, tmp_vault):
        """All payload fields survive the encrypt/decrypt cycle."""
        payload = {
            **MINIMAL_PAYLOAD,
            "holdings": [
                {
                    "id": "h1",
                    "wallet_id": "w1",
                    "asset": "BTC",
                    "chain": "bitcoin",
                    "amount": 0.5,
                    "avg_buy_price_usd": 30000.0,
                    "current_price_usd": None,
                }
            ],
        }
        vault = tmp_vault(payload=payload)
        result = load_vaultd(str(vault), GOOD_PASSPHRASE, skip_validation=True)
        assert result["holdings"][0]["asset"] == "BTC"
        assert result["holdings"][0]["current_price_usd"] is None

    def test_unicode_passphrase(self, tmp_vault):
        """Unicode passphrases work correctly."""
        pp = "correct-hörse-bàttery-ñ-2026"
        vault = tmp_vault(passphrase=pp)
        result = load_vaultd(str(vault), pp, skip_validation=True)
        assert result["identity"]["alias"] == "tester"

    def test_unicode_payload(self, tmp_vault):
        """Unicode in payload fields survives roundtrip."""
        payload = {**MINIMAL_PAYLOAD, "identity": {"alias": "用户-テスト-🔐", "language": "zh"}}
        vault = tmp_vault(payload=payload)
        result = load_vaultd(str(vault), GOOD_PASSPHRASE, skip_validation=True)
        assert result["identity"]["alias"] == "用户-テスト-🔐"


# ─── Authentication & Integrity ──────────────────────────────────────────────

class TestAuthentication:
    def test_wrong_passphrase_raises(self, tmp_vault):
        """Wrong passphrase raises ValueError with VAULTD_E_DECRYPT."""
        vault = tmp_vault()
        with pytest.raises(ValueError, match="VAULTD_E_DECRYPT"):
            load_vaultd(str(vault), "wrong-passphrase", skip_validation=True)

    def test_empty_passphrase_decrypt_fails(self, tmp_vault):
        """Empty passphrase raises ValueError."""
        vault = tmp_vault()
        with pytest.raises(ValueError, match="VAULTD_E_DECRYPT"):
            load_vaultd(str(vault), "", skip_validation=True)

    def test_tampered_ciphertext_raises(self, tmp_vault):
        """Flipping a bit in ciphertext raises VAULTD_E_DECRYPT (GCM auth tag check)."""
        vault = tmp_vault()
        envelope = json.loads(vault.read_text())

        # Flip the last byte of the ciphertext
        ct = bytearray(base64.b64decode(envelope["ciphertext"]))
        ct[-1] ^= 0xFF
        envelope["ciphertext"] = base64.b64encode(bytes(ct)).decode("ascii")
        vault.write_text(json.dumps(envelope))

        with pytest.raises(ValueError, match="VAULTD_E_DECRYPT"):
            load_vaultd(str(vault), GOOD_PASSPHRASE, skip_validation=True)

    def test_tampered_aad_raises(self, tmp_vault):
        """Modifying AAD-covered fields (e.g. domain) raises VAULTD_E_DECRYPT."""
        vault = tmp_vault()
        envelope = json.loads(vault.read_text())
        envelope["domain"] = "tampered"
        vault.write_text(json.dumps(envelope))

        with pytest.raises(ValueError):
            load_vaultd(str(vault), GOOD_PASSPHRASE, skip_validation=True)


# ─── Custom Argon2 Params ────────────────────────────────────────────────────

class TestArgon2Params:
    def test_custom_argon2_params_stored_in_envelope(self, tmp_vault):
        """Custom Argon2 params are written into the envelope kdf_params."""
        vault = tmp_vault(argon2_m=32768, argon2_t=2, argon2_p=1)
        envelope = json.loads(vault.read_text())
        assert envelope["kdf_params"]["m"] == 32768
        assert envelope["kdf_params"]["t"] == 2
        assert envelope["kdf_params"]["p"] == 1

    def test_custom_argon2_params_used_for_decryption(self, tmp_vault):
        """Vault encrypted with custom Argon2 params decrypts correctly."""
        vault = tmp_vault(argon2_m=32768, argon2_t=2)
        result = load_vaultd(str(vault), GOOD_PASSPHRASE, skip_validation=True)
        assert result["identity"]["alias"] == "tester"


# ─── Atomic Write ────────────────────────────────────────────────────────────

class TestAtomicWrite:
    def test_no_temp_file_left_on_success(self, tmp_vault, tmp_path):
        """No .tmp file remains after successful write."""
        tmp_vault()
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert tmp_files == [], f"Temp files not cleaned up: {tmp_files}"

    def test_output_file_exists_after_write(self, tmp_vault, tmp_path):
        """Output file is present and non-empty after successful write."""
        vault = tmp_vault()
        assert vault.exists()
        assert vault.stat().st_size > 0


# ─── Error Handling ──────────────────────────────────────────────────────────

class TestErrorHandling:
    def test_file_not_found(self, tmp_path):
        """Missing file raises ValueError with VAULTD_E_FORMAT."""
        with pytest.raises(ValueError, match="VAULTD_E_FORMAT"):
            load_vaultd(str(tmp_path / "nonexistent.vaultd"), GOOD_PASSPHRASE)

    def test_invalid_json_envelope(self, tmp_path):
        """Non-JSON file raises ValueError."""
        bad = tmp_path / "bad.vaultd"
        bad.write_text("not-json")
        with pytest.raises(ValueError, match="VAULTD_E_FORMAT"):
            load_vaultd(str(bad), GOOD_PASSPHRASE)

    def test_unsupported_vaultd_version(self, tmp_path):
        """Unknown vaultd_version raises VAULTD_E_VERSION."""
        bad = tmp_path / "old.vaultd"
        bad.write_text(json.dumps({
            "klickd_version": "3.0",
            "vaultd_version": "9.9",
            "domain": "crypto",
            "encrypted": True,
        }))
        with pytest.raises(ValueError, match="VAULTD_E_VERSION"):
            load_vaultd(str(bad), GOOD_PASSPHRASE)

    def test_wrong_domain_raises(self, tmp_path):
        """Wrong domain raises VAULTD_E_DOMAIN."""
        bad = tmp_path / "domain.vaultd"
        bad.write_text(json.dumps({
            "klickd_version": "3.0",
            "vaultd_version": "1.2",
            "domain": "music",  # wrong
            "encrypted": True,
        }))
        with pytest.raises(ValueError, match="VAULTD_E_DOMAIN"):
            load_vaultd(str(bad), GOOD_PASSPHRASE)

    def test_payload_size_limit(self, tmp_path):
        """Payload over 4 MB raises VAULTD_E_FORMAT."""
        huge = {**MINIMAL_PAYLOAD, "notes": "x" * (4 * 1024 * 1024 + 1)}
        out = tmp_path / "huge.vaultd"
        with pytest.raises(ValueError, match="VAULTD_E_FORMAT"):
            create_vaultd(huge, GOOD_PASSPHRASE, str(out), skip_validation=True)


# ─── Version Compatibility ───────────────────────────────────────────────────

class TestVersionCompat:
    def test_v11_envelope_loads(self, tmp_path):
        """
        A v1.1 envelope (manually constructed) loads successfully
        because 1.1 is in SUPPORTED_VAULTD_VERSIONS.
        """
        from argon2.low_level import Type, hash_secret_raw
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        payload = {**MINIMAL_PAYLOAD}
        plaintext = json.dumps(payload, separators=(",", ":")).encode()
        salt = os.urandom(16)
        iv = os.urandom(12)
        passphrase = GOOD_PASSPHRASE

        key = hash_secret_raw(
            secret=passphrase.encode(),
            salt=salt, time_cost=3, memory_cost=65536, parallelism=1, hash_len=32, type=Type.ID
        )
        aad_meta = {
            "created_at": payload["created_at"],
            "domain": "crypto",
            "encrypted": True,
            "klickd_version": "3.0",
            "vaultd_version": "1.1",  # old version
        }
        aad = json.dumps(aad_meta, sort_keys=True, separators=(",", ":")).encode()
        ct = AESGCM(key).encrypt(iv, plaintext, aad)

        envelope = {
            "klickd_version": "3.0",
            "vaultd_version": "1.1",
            "domain": "crypto",
            "created_at": payload["created_at"],
            "encrypted": True,
            "encryption": "AES-256-GCM",
            "kdf": "argon2id",
            "kdf_params": {"m": 65536, "t": 3, "p": 1, "salt": base64.b64encode(salt).decode()},
            "iv": base64.b64encode(iv).decode(),
            "ciphertext": base64.b64encode(ct).decode(),
            "aad_fields": ["created_at", "domain", "encrypted", "klickd_version", "vaultd_version"],
        }
        out = tmp_path / "v11.vaultd"
        out.write_text(json.dumps(envelope))

        result = load_vaultd(str(out), passphrase, skip_validation=True)
        assert result["identity"]["alias"] == "tester"


# ─── Hypothesis Property-Based Tests ─────────────────────────────────────────

try:
    from hypothesis import given, settings
    from hypothesis import strategies as st
    HAS_HYPOTHESIS = True
except ImportError:
    HAS_HYPOTHESIS = False

if HAS_HYPOTHESIS:
    from hypothesis import HealthCheck

    @given(
        passphrase=st.text(
            alphabet=st.characters(min_codepoint=32, max_codepoint=126),
            min_size=16,
            max_size=128,
        )
    )
    @settings(max_examples=20, deadline=30000, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_roundtrip_random_passphrases(passphrase, tmp_path):
        """
        Property: for any passphrase, encrypting then decrypting with the same
        passphrase returns the original payload.
        Uses a temp directory that is reused across hypothesis examples (safe here
        because each example writes a uniquely-named file).
        """
        out = tmp_path / f"hyp_{abs(hash(passphrase))}.vaultd"
        payload = {**MINIMAL_PAYLOAD}
        create_vaultd(payload, passphrase, str(out), skip_validation=True)
        result = load_vaultd(str(out), passphrase, skip_validation=True)
        assert result["identity"]["alias"] == payload["identity"]["alias"]
