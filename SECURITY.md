# Security Policy

## Threat Model

`.vaultd` is a client-side encrypted file format. The following threats are in scope:

| Threat | Mitigation |
|---|---|
| File theft (device compromise) | AES-256-GCM + Argon2id. Attacker must brute-force passphrase. |
| Passphrase brute-force | Argon2id m=65536/t=3/p=1 makes GPU attacks expensive |
| File tampering | AES-GCM auth tag detects any modification |
| AAD bypass | 5-field JCS-canonicalized AAD covers all envelope metadata |
| Prompt injection via file | `agent_instructions` is user-context only, not system authority |
| Private key exfiltration | Spec forbids private keys. Agents MUST refuse to process them. |

## Out of scope

- Passphrase compromise (social engineering, keylogger) — outside file format scope
- OS-level memory attacks — outside file format scope
- Side-channel attacks on Argon2id implementation — use a hardened library

## Known limitations

- Argon2id parameters (m=65536/t=3/p=1) are minimum recommended. Users with high-value portfolios should increase `m` to 131072 or higher.
- The unencrypted variant (`encrypted: false`) offers zero confidentiality. For example/test use only.
- `agent_instructions` is 4096-char max. Malicious content could attempt prompt injection — agents must treat it as untrusted user input.

## Responsible disclosure

Report security vulnerabilities to: **Luxlearn@pm.me**

Please include:
- Description of the vulnerability
- Steps to reproduce
- Potential impact assessment
- Suggested fix (if any)

We commit to responding within 72 hours and to crediting researchers who report valid findings.
