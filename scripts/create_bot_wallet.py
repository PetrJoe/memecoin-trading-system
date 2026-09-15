#!/usr/bin/env python3
"""Generate a new Solana wallet for the trading bot.

Usage:
    python scripts/create_bot_wallet.py

This script generates a new keypair and displays the public address.
The secret key must be backed up securely and added to .env as BOT_PRIVATE_KEY.
"""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.blockchain.wallet import WalletService


def main() -> None:
    pubkey, secret_b58 = WalletService.generate_keypair()

    print("=" * 60)
    print("  NEW BOT WALLET GENERATED")
    print("=" * 60)
    print()
    print(f"  Public Address:  {pubkey}")
    print()
    print("  " + "-" * 56)
    print("  ⚠️  SECRET KEY (base58):")
    print(f"  {secret_b58}")
    print("  " + "-" * 56)
    print()
    print("  INSTRUCTIONS:")
    print("  1. Copy the secret key above")
    print("  2. Add it to your .env file as BOT_PRIVATE_KEY=<secret>")
    print("  3. Back up the secret key securely offline")
    print("  4. Fund the wallet with SOL before trading")
    print()
    print("  ⚠️  NEVER share this secret key with anyone")
    print("  ⚠️  NEVER commit it to version control")
    print("  ⚠️  NEVER send it through Telegram or email")
    print()
    print("=" * 60)


if __name__ == "__main__":
    main()
