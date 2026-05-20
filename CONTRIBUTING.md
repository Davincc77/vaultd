# Contributing to .vaultd

`.vaultd` is CC0 — public domain. Contributions are welcome and require no CLA.

## What we're looking for

- Bug reports in the spec (ambiguous language, inconsistencies)
- Improvements to the schema (new fields, better type definitions)
- Implementations in other languages (JavaScript/TypeScript, Rust, Go)
- Test vectors for edge cases
- Security audit findings

## What we're NOT looking for

- Features that require server-side components (contradicts zero-server principle)
- Private key storage (hard no — see SECURITY.md)
- Breaking changes to the cryptographic envelope without a version bump

## How to contribute

1. Open an issue first to discuss the change
2. Fork the repo
3. Make your changes
4. Add/update test vectors if cryptographic behavior changes
5. Update SPEC.md and CHANGELOG.md
6. Open a PR

## Spec changes

Any change to the cryptographic envelope (KDF params, AAD construction, encryption algorithm) MUST:
- Bump `vaultd_version`
- Add migration path from previous version
- Include new test vectors
- Update SPEC.md with before/after comparison

## Contact

Luxlearn@pm.me
