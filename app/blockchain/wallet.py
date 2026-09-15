from __future__ import annotations

import base58
from typing import Optional

from solders.keypair import Keypair
from solders.pubkey import Pubkey

from app.config import get_logger, get_settings

logger = get_logger(category="security")


class WalletServiceError(Exception):
    pass


class WalletService:
    def __init__(self, private_key_b58: Optional[str] = None) -> None:
        settings = get_settings()
        key_str = private_key_b58 or settings.BOT_PRIVATE_KEY.get_secret_value()

        if not key_str:
            raise WalletServiceError("No private key configured")

        try:
            secret_bytes = base58.b58decode(key_str)
            self._keypair = Keypair.from_bytes(secret_bytes)
        except Exception as e:
            raise WalletServiceError(f"Invalid private key: {e}") from e

        logger.info("wallet_loaded", pubkey=str(self.public_key))

    @property
    def public_key(self) -> Pubkey:
        return self._keypair.pubkey()

    @property
    def address(self) -> str:
        return str(self._keypair.pubkey())

    def sign(self, message: bytes) -> bytes:
        return self._keypair.sign_message(message)

    def sign_transaction(self, transaction) -> bytes:
        return bytes(self._keypair.sign_message(transaction))

    @staticmethod
    def generate_keypair() -> tuple[str, str]:
        kp = Keypair()
        pubkey = str(kp.pubkey())
        secret_b58 = base58.b58encode(bytes(kp)).decode()
        return pubkey, secret_b58

    @staticmethod
    def validate_address(address: str) -> bool:
        try:
            Pubkey.from_string(address)
            return True
        except Exception:
            return False
