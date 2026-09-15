import os
from unittest.mock import patch

import base58
import pytest
from solders.keypair import Keypair

from app.blockchain.wallet import WalletService, WalletServiceError


class TestWalletService:
    def test_loads_from_key(self, patched_env):
        kp = Keypair()
        secret_b58 = base58.b58encode(bytes(kp)).decode()
        with patch.dict(os.environ, {"BOT_PRIVATE_KEY": secret_b58}):
            wallet = WalletService()
            assert wallet.address == str(kp.pubkey())

    def test_raises_on_empty_key(self, patched_env):
        with patch.dict(os.environ, {"BOT_PRIVATE_KEY": ""}):
            with pytest.raises(WalletServiceError, match="No private key"):
                WalletService()

    def test_raises_on_invalid_key(self, patched_env):
        with patch.dict(os.environ, {"BOT_PRIVATE_KEY": "not-valid-base58!!!invalid"}):
            with pytest.raises(WalletServiceError, match="Invalid private key"):
                WalletService()

    def test_public_key_matches_address(self, patched_env):
        kp = Keypair()
        secret_b58 = base58.b58encode(bytes(kp)).decode()
        with patch.dict(os.environ, {"BOT_PRIVATE_KEY": secret_b58}):
            wallet = WalletService()
            assert wallet.public_key is not None
            assert wallet.address == str(wallet.public_key)

    def test_sign_returns_bytes(self, patched_env):
        kp = Keypair()
        secret_b58 = base58.b58encode(bytes(kp)).decode()
        with patch.dict(os.environ, {"BOT_PRIVATE_KEY": secret_b58}):
            wallet = WalletService()
            sig = wallet.sign(b"test message")
            assert isinstance(sig, bytes)
            assert len(sig) > 0

    def test_generate_keypair_returns_valid_pair(self):
        pubkey, secret_b58 = WalletService.generate_keypair()
        assert isinstance(pubkey, str)
        assert isinstance(secret_b58, str)
        assert len(pubkey) >= 32
        kp = Keypair.from_bytes(base58.b58decode(secret_b58))
        assert str(kp.pubkey()) == pubkey

    def test_validate_address_valid(self):
        assert WalletService.validate_address("11111111111111111111111111111111") is True

    def test_validate_address_invalid(self):
        assert WalletService.validate_address("not-an-address") is False

    def test_private_key_not_in_repr(self, patched_env):
        kp = Keypair()
        secret_b58 = base58.b58encode(bytes(kp)).decode()
        with patch.dict(os.environ, {"BOT_PRIVATE_KEY": secret_b58}):
            wallet = WalletService()
            assert secret_b58 not in repr(wallet)
