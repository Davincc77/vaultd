"""
vaultd — AES-256-GCM + Argon2id encrypted crypto portfolio context for AI agents.

.vaultd is a portable investment constitution: a single encrypted file
that carries your full portfolio context and forces every AI session
to be honest to your past decisions and rules.

Usage:
    from vaultd import create_vaultd, load_vaultd

    # Encrypt
    create_vaultd(payload_dict, "my-passphrase", "portfolio.vaultd")

    # Decrypt
    payload = load_vaultd("portfolio.vaultd", "my-passphrase")
"""

__version__ = "2.5.1"
__author__ = "Vince C. (Klickd / Luxlearn)"
__license__ = "CC0-1.0"

from vaultd.core import create_vaultd, load_vaultd, validate_payload

__all__ = ["create_vaultd", "load_vaultd", "validate_payload", "__version__"]
