"""
vaultd-tui — Launch the terminal UI for a .vaultd vault.

Usage:
  vaultd-tui portfolio.vaultd
"""

from __future__ import annotations

import argparse
import getpass
import sys

from vaultd.core import load_vaultd


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="vaultd-tui",
        description="Browse and edit a .vaultd vault in a terminal UI",
    )
    parser.add_argument("vault", help="Path to your .vaultd file")
    parser.add_argument("--skip-validation", action="store_true")
    args = parser.parse_args()

    passphrase = getpass.getpass(f"Passphrase for {args.vault}: ")

    try:
        payload = load_vaultd(args.vault, passphrase, skip_validation=args.skip_validation)
    except ValueError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)

    try:
        from vaultd.tui import launch_tui
        launch_tui(args.vault, payload, passphrase)
    except ImportError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
