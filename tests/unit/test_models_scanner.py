import pytest

from app.scanner.models import (
    DexScreenerPair,
    LiquidityInfo,
    MarketSnapshot,
    PriceChangeInfo,
    TokenInfo,
    TxnInfo,
    VolumeInfo,
)


class TestDexScreenerPair:
    def test_parse_basic_pair(self):
        data = {
            "chainId": "solana",
            "dexId": "raydium",
            "pairAddress": "PairAddr123",
            "baseToken": {
                "address": "TokenAddr123",
                "name": "Test Coin",
                "symbol": "TEST",
            },
            "priceUsd": "0.00123",
            "fdv": 1000000,
            "marketCap": 500000,
        }
        pair = DexScreenerPair.model_validate(data)
        assert pair.chain_id == "solana"
        assert pair.dex_id == "raydium"
        assert pair.pair_address == "PairAddr123"
        assert pair.base_token.symbol == "TEST"
        assert pair.price_usd == "0.00123"
        assert pair.fdv == 1000000

    def test_parse_pair_with_txns(self):
        data = {
            "chainId": "solana",
            "dexId": "raydium",
            "pairAddress": "PairAddr123",
            "baseToken": {"address": "Addr", "name": "T", "symbol": "T"},
            "txns": {
                "m5": {"buys": 10, "sells": 5},
                "h1": {"buys": 100, "sells": 50},
                "h24": {"buys": 1000, "sells": 500},
            },
            "volume": {"m5": 5000, "h1": 50000, "h6": 200000, "h24": 500000},
            "priceChange": {"m5": 2.5, "h1": 10.0, "h6": -5.0, "h24": 25.0},
            "liquidity": {"usd": 100000, "base": 50000, "quote": 50},
        }
        pair = DexScreenerPair.model_validate(data)
        assert pair.txns["m5"].buys == 10
        assert pair.txns["m5"].sells == 5
        assert pair.volume.m5 == 5000
        assert pair.price_change.h1 == 10.0
        assert pair.liquidity.usd == 100000


class TestMarketSnapshot:
    def test_from_pair_basic(self):
        pair = DexScreenerPair(
            chainId="solana",
            dexId="raydium",
            pairAddress="PairAddr123",
            baseToken=TokenInfo(address="TokenAddr123", name="Test Coin", symbol="TEST"),
            priceUsd="0.00123",
            fdv=1000000,
            marketCap=500000,
        )
        snap = MarketSnapshot.from_pair(pair)
        assert snap.token_address == "TokenAddr123"
        assert snap.symbol == "TEST"
        assert snap.price == 0.00123
        assert snap.fdv == 1000000

    def test_from_pair_with_all_fields(self):
        pair = DexScreenerPair(
            chainId="solana",
            dexId="raydium",
            pairAddress="PairAddr",
            baseToken=TokenInfo(address="TokAddr", name="Coin", symbol="COIN"),
            priceUsd="1.5",
            txns={
                "m5": TxnInfo(buys=10, sells=5),
                "h1": TxnInfo(buys=100, sells=50),
                "h24": TxnInfo(buys=1000, sells=500),
            },
            volume=VolumeInfo(m5=5000, h1=50000, h6=200000, h24=500000),
            priceChange=PriceChangeInfo(m5=2.5, h1=10.0, h6=-5.0, h24=25.0),
            liquidity=LiquidityInfo(usd=100000, base=50000, quote=50),
            pairCreatedAt=1700000000000,
        )
        snap = MarketSnapshot.from_pair(pair)
        assert snap.price == 1.5
        assert snap.liquidity == 100000
        assert snap.volume_5m == 5000
        assert snap.volume_1h == 50000
        assert snap.price_change_h1 == 10.0
        assert snap.buys_5m == 10
        assert snap.sells_5m == 5
        assert snap.buys_1h == 100
        assert snap.buys_24h == 1000
        assert snap.dex == "raydium"
        assert snap.pair_created_at is not None

    def test_from_pair_no_optional_fields(self):
        pair = DexScreenerPair(
            chainId="solana",
            dexId="raydium",
            pairAddress="PairAddr",
            baseToken=TokenInfo(address="TokAddr", name="Coin", symbol="COIN"),
            priceUsd=None,
        )
        snap = MarketSnapshot.from_pair(pair)
        assert snap.price == 0.0
        assert snap.liquidity is None
        assert snap.market_cap is None
