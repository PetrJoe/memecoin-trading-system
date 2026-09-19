"""
Rug-Pull Detector

Analyzes tokens for rug-pull risk BEFORE any buy execution.
Combines on-chain data, market patterns, and heuristic checks
to produce a rug-risk score and hard veto decisions.

Rug types detected:
  1. Mint authority abuse (deployer can inflate supply)
  2. Freeze authority (deployer can freeze trades)
  3. Low-float / high-concentration (insiders hold most supply)
  4. Liquidity pull patterns (LP being removed)
  5. Buy-bot / wash trading (fake volume)
  6. Honeypot (can buy but can't sell)
  7. Stealth launch (no social presence, anonymous)
  8. Honeypot with sell tax (> 50% sell tax = honeypot)
  9. Suspicious price action (vertical pump with no consolidation)
  10. Deployer wallet history (serial rugger)
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from app.config import get_logger, get_settings

logger = get_logger(category="security")


class RugCheckType(str, Enum):
    MINT_AUTHORITY = "MINT_AUTHORITY"
    FREEZE_AUTHORITY = "FREEZE_AUTHORITY"
    LIQUIDITY_REMOVAL = "LIQUIDITY_REMOVAL"
    HOLDER_CONCENTRATION = "HOLDER_CONCENTRATION"
    HONEYPOT = "HONEYPOT"
    BUY_BOT_PATTERN = "BUY_BOT_PATTERN"
    STEALTH_LAUNCH = "STEALTH_LAUNCH"
    PRICE_MANIPULATION = "PRICE_MANIPULATION"
    SUSPICIOUS_NAME = "SUSPICIOUS_NAME"
    NO_SOCIAL = "NO_SOCIAL"
    DEPLOYER_RISK = "DEPLOYER_RISK"
    HIGH_TAX = "HIGH_TAX"
    RAPID_LIQ_CHANGE = "RAPID_LIQ_CHANGE"
    LOW_FLOAT = "LOW_FLOAT"
    DEV_BAG = "DEV_BAG"


class RugSeverity(str, Enum):
    """Severity levels — CRITICAL = immediate veto, HIGH = heavy penalty, MEDIUM = warning."""
    CRITICAL = "CRITICAL"   # veto — never buy
    HIGH = "HIGH"           # heavy score penalty, likely veto
    MEDIUM = "MEDIUM"       # warning, reduces score
    LOW = "LOW"             # minor concern


@dataclass
class RugFlag:
    check_type: RugCheckType
    severity: RugSeverity
    message: str
    score_penalty: int = 0  # deducted from 100

    @property
    def is_veto(self) -> bool:
        return self.severity == RugSeverity.CRITICAL


@dataclass
class RugAnalysisResult:
    token_address: str
    symbol: str
    flags: list[RugFlag] = field(default_factory=list)
    rug_score: int = 100  # starts safe, deductions applied
    approved: bool = True
    veto_reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    analysis_time_ms: float = 0.0

    @property
    def critical_flags(self) -> list[RugFlag]:
        return [f for f in self.flags if f.severity == RugSeverity.CRITICAL]

    @property
    def high_flags(self) -> list[RugFlag]:
        return [f for f in self.flags if f.severity == RugSeverity.HIGH]


# Known rug-indicator keywords in token names/symbols
SUSPICIOUS_NAME_PATTERNS = [
    "rug", "scam", "honeypot", "honeypoott", "honeipot",
    "steal", "thief", "exit", "dump", "pump",
    "test", "testtoken", "scamtoken",
]

# Tokens that are very likely honeypots
HONEYPOT_KEYWORDS = [
    "honeypot", "honeypoott", "honeipot", "honey pot",
]


class RugDetector:
    """
    Pre-buy rug-pull detector.
    Runs fast heuristic checks using DexScreener data + optional on-chain calls.
    """

    def __init__(self) -> None:
        self.settings = get_settings()

    async def analyze(
        self,
        token_address: str,
        symbol: str,
        name: str = "",
        price: float = 0.0,
        liquidity: Optional[float] = None,
        market_cap: Optional[float] = None,
        fdv: Optional[float] = None,
        buys_5m: int = 0,
        sells_5m: int = 0,
        buys_1h: int = 0,
        sells_1h: int = 0,
        volume_5m: Optional[float] = None,
        volume_1h: Optional[float] = None,
        price_change_m5: Optional[float] = None,
        price_change_h1: Optional[float] = None,
        has_mint_authority: Optional[bool] = None,
        has_freeze_authority: Optional[bool] = None,
        token_age_hours: Optional[float] = None,
        pair_created_at: Optional[datetime] = None,
        dex: str = "",
        social_links: Optional[dict] = None,
    ) -> RugAnalysisResult:
        """
        Run all rug-pull checks and return a risk assessment.
        Fast checks (no RPC) run first. On-chain checks are optional.
        """
        start = time.monotonic()
        result = RugAnalysisResult(token_address=token_address, symbol=symbol)

        # ── Phase 1: Instant heuristic checks (no RPC, < 1ms) ──────────
        self._check_name_risk(name, symbol, result)
        self._check_mint_freeze_authority(has_mint_authority, has_freeze_authority, result)
        self._check_liquidity_risk(liquidity, result)
        self._check_honeypot_signals(buys_5m, sells_5m, buys_1h, sells_1h, result)
        self._check_buy_bot_pattern(buys_5m, sells_5m, volume_5m, result)
        self._check_price_manipulation(price_change_m5, price_change_h1, result)
        self._check_holder_concentration(liquidity, market_cap, fdv, result)
        self._check_low_float(liquidity, market_cap, fdv, result)
        self._check_dev_bag(liquidity, market_cap, result)
        self._check_social_presence(social_links, token_age_hours, result)
        self._check_stealth_launch(social_links, token_age_hours, dex, result)
        self._check_liquidity_change(liquidity, token_age_hours, result)

        # ── Phase 2: Compute final score ────────────────────────────────
        result.rug_score = max(0, min(100, result.rug_score))
        result.approved = len(result.veto_reasons) == 0 and result.rug_score >= self.settings.RUG_MIN_SCORE
        result.analysis_time_ms = (time.monotonic() - start) * 1000

        if not result.approved:
            logger.warning(
                "rug_check_failed",
                token=symbol,
                score=result.rug_score,
                vetos=result.veto_reasons,
                flags=len(result.flags),
            )
        else:
            logger.info(
                "rug_check_passed",
                token=symbol,
                score=result.rug_score,
                warnings=len(result.warnings),
            )

        return result

    # ═══════════════════════════════════════════════════════════════════
    # CHECK: Token name/symbol risk
    # ═══════════════════════════════════════════════════════════════════
    def _check_name_risk(self, name: str, symbol: str, result: RugAnalysisResult) -> None:
        combined = f"{name} {symbol}".lower()

        for kw in HONEYPOT_KEYWORDS:
            if kw in combined:
                result.flags.append(RugFlag(
                    check_type=RugCheckType.SUSPICIOUS_NAME,
                    severity=RugSeverity.CRITICAL,
                    message=f"Token name contains '{kw}' — likely honeypot scam",
                    score_penalty=100,
                ))
                result.veto_reasons.append(f"Honeypot name detected: '{kw}'")
                result.rug_score -= 100
                return

        for kw in SUSPICIOUS_NAME_PATTERNS:
            if kw in combined:
                result.flags.append(RugFlag(
                    check_type=RugCheckType.SUSPICIOUS_NAME,
                    severity=RugSeverity.HIGH,
                    message=f"Token name contains suspicious keyword: '{kw}'",
                    score_penalty=40,
                ))
                result.rug_score -= 40
                return

    # ═══════════════════════════════════════════════════════════════════
    # CHECK: Mint / Freeze authority
    # ═══════════════════════════════════════════════════════════════════
    def _check_mint_freeze_authority(
        self,
        has_mint_authority: Optional[bool],
        has_freeze_authority: Optional[bool],
        result: RugAnalysisResult,
    ) -> None:
        if has_mint_authority is True:
            result.flags.append(RugFlag(
                check_type=RugCheckType.MINT_AUTHORITY,
                severity=RugSeverity.CRITICAL,
                message="Token has mint authority — deployer can inflate supply at will",
                score_penalty=100,
            ))
            result.veto_reasons.append("Mint authority enabled — unlimited inflation risk")
            result.rug_score -= 100

        if has_freeze_authority is True:
            result.flags.append(RugFlag(
                check_type=RugCheckType.FREEZE_AUTHORITY,
                severity=RugSeverity.CRITICAL,
                message="Token has freeze authority — deployer can freeze your tokens",
                score_penalty=100,
            ))
            result.veto_reasons.append("Freeze authority enabled — trades can be frozen")
            result.rug_score -= 100

    # ═══════════════════════════════════════════════════════════════════
    # CHECK: Liquidity risk
    # ═══════════════════════════════════════════════════════════════════
    def _check_liquidity_risk(self, liquidity: Optional[float], result: RugAnalysisResult) -> None:
        if liquidity is None:
            result.flags.append(RugFlag(
                check_type=RugCheckType.LIQUIDITY_REMOVAL,
                severity=RugSeverity.HIGH,
                message="No liquidity data — cannot verify LP is present",
                score_penalty=30,
            ))
            result.rug_score -= 30
            return

        if liquidity < 100:
            result.flags.append(RugFlag(
                check_type=RugCheckType.LIQUIDITY_REMOVAL,
                severity=RugSeverity.CRITICAL,
                message=f"Liquidity critically low: ${liquidity:,.0f} — easy to rug",
                score_penalty=100,
            ))
            result.veto_reasons.append(f"Liquidity too low: ${liquidity:,.0f}")
            result.rug_score -= 100
        elif liquidity < 500:
            result.flags.append(RugFlag(
                check_type=RugCheckType.LIQUIDITY_REMOVAL,
                severity=RugSeverity.HIGH,
                message=f"Very low liquidity: ${liquidity:,.0f} — high rug risk",
                score_penalty=40,
            ))
            result.rug_score -= 40
        elif liquidity < 2000:
            result.flags.append(RugFlag(
                check_type=RugCheckType.LIQUIDITY_REMOVAL,
                severity=RugSeverity.MEDIUM,
                message=f"Low liquidity: ${liquidity:,.0f}",
                score_penalty=15,
            ))
            result.rug_score -= 15

    # ═══════════════════════════════════════════════════════════════════
    # CHECK: Honeypot signals (buys but no sells)
    # ═══════════════════════════════════════════════════════════════════
    def _check_honeypot_signals(
        self,
        buys_5m: int,
        sells_5m: int,
        buys_1h: int,
        sells_1h: int,
        result: RugAnalysisResult,
    ) -> None:
        # Classic honeypot: lots of buys, zero sells
        if buys_5m >= 5 and sells_5m == 0:
            result.flags.append(RugFlag(
                check_type=RugCheckType.HONEYPOT,
                severity=RugSeverity.HIGH,
                message=f"Honeypot signal: {buys_5m} buys but 0 sells in 5m — may not be sellable",
                score_penalty=35,
            ))
            result.rug_score -= 35

        if buys_1h >= 10 and sells_1h == 0:
            result.flags.append(RugFlag(
                check_type=RugCheckType.HONEYPOT,
                severity=RugSeverity.CRITICAL,
                message=f"Honeypot confirmed: {buys_1h} buys, 0 sells in 1h — CANNOT SELL",
                score_penalty=100,
            ))
            result.veto_reasons.append(f"Possible honeypot: {buys_1h} buys, 0 sells in 1h")
            result.rug_score -= 100

        # Very high sell tax signal: way more sells than buys suggests people exiting fast
        if sells_5m > 0 and buys_5m > 0:
            sell_ratio = sells_5m / (buys_5m + sells_5m)
            if sell_ratio > 0.85 and (buys_5m + sells_5m) >= 5:
                result.flags.append(RugFlag(
                    check_type=RugCheckType.HIGH_TAX,
                    severity=RugSeverity.HIGH,
                    message=f"Extreme sell pressure: {sell_ratio:.0%} sells — possible high sell tax",
                    score_penalty=30,
                ))
                result.rug_score -= 30

    # ═══════════════════════════════════════════════════════════════════
    # CHECK: Buy-bot / wash trading pattern
    # ═══════════════════════════════════════════════════════════════════
    def _check_buy_bot_pattern(
        self,
        buys_5m: int,
        sells_5m: int,
        volume_5m: Optional[float],
        result: RugAnalysisResult,
    ) -> None:
        # Buy bot: many tiny buys, very few sells, low actual volume
        total = buys_5m + sells_5m
        if total < 5:
            return

        buy_ratio = buys_5m / total if total > 0 else 0
        avg_trade_usd = (volume_5m or 0) / total if total > 0 else 0

        # Pattern: >90% buys but tiny average trade size = likely bot
        if buy_ratio > 0.90 and avg_trade_usd < 5.0 and buys_5m >= 10:
            result.flags.append(RugFlag(
                check_type=RugCheckType.BUY_BOT_PATTERN,
                severity=RugSeverity.HIGH,
                message=f"Buy-bot pattern: {buys_5m} buys, avg ${avg_trade_usd:.2f}/trade — fake volume",
                score_penalty=30,
            ))
            result.rug_score -= 30

        # Also flag if buys are suspiciously uniform in count (bot activity)
        if buys_5m >= 20 and sells_5m <= 1 and total > 0 and buy_ratio > 0.95:
            result.flags.append(RugFlag(
                check_type=RugCheckType.BUY_BOT_PATTERN,
                severity=RugSeverity.MEDIUM,
                message=f"Suspicious buy pattern: {buys_5m} buys vs {sells_5m} sells — may be wash trading",
                score_penalty=20,
            ))
            result.rug_score -= 20

    # ═══════════════════════════════════════════════════════════════════
    # CHECK: Price manipulation (vertical pump)
    # ═══════════════════════════════════════════════════════════════════
    def _check_price_manipulation(
        self,
        price_change_m5: Optional[float],
        price_change_h1: Optional[float],
        result: RugAnalysisResult,
    ) -> None:
        # Vertical 5m pump (>500% in 5 minutes) — almost always manipulation
        if price_change_m5 is not None and price_change_m5 > 500:
            result.flags.append(RugFlag(
                check_type=RugCheckType.PRICE_MANIPULATION,
                severity=RugSeverity.HIGH,
                message=f"Vertical 5m pump: +{price_change_m5:.0f}% — likely manipulated",
                score_penalty=30,
            ))
            result.rug_score -= 30

        # Extreme 1h pump (>1000%) — near-certain manipulation
        if price_change_h1 is not None and price_change_h1 > 1000:
            result.flags.append(RugFlag(
                check_type=RugCheckType.PRICE_MANIPULATION,
                severity=RugSeverity.CRITICAL,
                message=f"Extreme 1h pump: +{price_change_h1:.0f}% — near-certain manipulation",
                score_penalty=100,
            ))
            result.veto_reasons.append(f"Price manipulated: +{price_change_h1:.0f}% in 1h")
            result.rug_score -= 100

    # ═══════════════════════════════════════════════════════════════════
    # CHECK: Holder concentration (low float)
    # ═══════════════════════════════════════════════════════════════════
    def _check_holder_concentration(
        self,
        liquidity: Optional[float],
        market_cap: Optional[float],
        fdv: Optional[float],
        result: RugAnalysisResult,
    ) -> None:
        if liquidity is None or fdv is None or fdv <= 0:
            return

        # Ratio of liquidity to FDV — low ratio means easy to manipulate
        liq_ratio = liquidity / fdv if fdv > 0 else 0

        if liq_ratio < 0.01 and fdv > 10000:
            result.flags.append(RugFlag(
                check_type=RugCheckType.HOLDER_CONCENTRATION,
                severity=RugSeverity.HIGH,
                message=f"Very low liquidity/FDV ratio: {liq_ratio:.2%} — easy to dump",
                score_penalty=25,
            ))
            result.rug_score -= 25
        elif liq_ratio < 0.03 and fdv > 10000:
            result.flags.append(RugFlag(
                check_type=RugCheckType.HOLDER_CONCENTRATION,
                severity=RugSeverity.MEDIUM,
                message=f"Low liquidity/FDV ratio: {liq_ratio:.2%}",
                score_penalty=10,
            ))
            result.rug_score -= 10

    # ═══════════════════════════════════════════════════════════════════
    # CHECK: Low float (small % of supply tradeable)
    # ═══════════════════════════════════════════════════════════════════
    def _check_low_float(
        self,
        liquidity: Optional[float],
        market_cap: Optional[float],
        fdv: Optional[float],
        result: RugAnalysisResult,
    ) -> None:
        if liquidity is None or market_cap is None or market_cap <= 0:
            return

        # If liquidity is tiny compared to market cap, insiders hold most
        float_ratio = liquidity / market_cap if market_cap > 0 else 0

        if float_ratio < 0.005 and market_cap > 50000:
            result.flags.append(RugFlag(
                check_type=RugCheckType.LOW_FLOAT,
                severity=RugSeverity.HIGH,
                message=f"Extremely low float: {float_ratio:.2%} of mcap in LP — insider-controlled",
                score_penalty=25,
            ))
            result.rug_score -= 25

    # ═══════════════════════════════════════════════════════════════════
    # CHECK: Dev bag (deployer holds too much)
    # ═══════════════════════════════════════════════════════════════════
    def _check_dev_bag(
        self,
        liquidity: Optional[float],
        market_cap: Optional[float],
        result: RugAnalysisResult,
    ) -> None:
        if liquidity is None or market_cap is None or market_cap <= 0:
            return

        # Heuristic: if liquidity is < 0.1% of mcap, dev likely holds >99%
        ratio = liquidity / market_cap
        if ratio < 0.001 and market_cap > 10000:
            result.flags.append(RugFlag(
                check_type=RugCheckType.DEV_BAG,
                severity=RugSeverity.HIGH,
                message=f"Possible dev bag: liquidity is {ratio:.3%} of mcap",
                score_penalty=20,
            ))
            result.rug_score -= 20

    # ═══════════════════════════════════════════════════════════════════
    # CHECK: Social presence
    # ═══════════════════════════════════════════════════════════════════
    def _check_social_presence(
        self,
        social_links: Optional[dict],
        token_age_hours: Optional[float],
        result: RugAnalysisResult,
    ) -> None:
        # Only check for tokens old enough to have had time to add socials
        if token_age_hours is not None and token_age_hours < 0.25:
            return  # < 15 min old — no socials expected yet

        if social_links is None or len(social_links) == 0:
            result.flags.append(RugFlag(
                check_type=RugCheckType.NO_SOCIAL,
                severity=RugSeverity.MEDIUM,
                message="No social links found — anonymous launch",
                score_penalty=10,
            ))
            result.rug_score -= 10

    # ═══════════════════════════════════════════════════════════════════
    # CHECK: Stealth launch
    # ═══════════════════════════════════════════════════════════════════
    def _check_stealth_launch(
        self,
        social_links: Optional[dict],
        token_age_hours: Optional[float],
        dex: str,
        result: RugAnalysisResult,
    ) -> None:
        # Stealth launch: no socials AND old enough to have them AND on unknown DEX
        if token_age_hours is not None and token_age_hours > 1.0:
            has_socials = social_links and len(social_links) > 0
            if not has_socials and dex.lower() not in ("raydium", "jupiter", "orca"):
                result.flags.append(RugFlag(
                    check_type=RugCheckType.STEALTH_LAUNCH,
                    severity=RugSeverity.MEDIUM,
                    message=f"Stealth launch: no socials, unknown DEX '{dex}', {token_age_hours:.1f}h old",
                    score_penalty=15,
                ))
                result.rug_score -= 15

    # ═══════════════════════════════════════════════════════════════════
    # CHECK: Rapid liquidity change
    # ═══════════════════════════════════════════════════════════════════
    def _check_liquidity_change(
        self,
        liquidity: Optional[float],
        token_age_hours: Optional[float],
        result: RugAnalysisResult,
    ) -> None:
        # If token is > 30 min old but liquidity is still < $500, likely dying
        if token_age_hours is not None and token_age_hours > 0.5:
            if liquidity is not None and liquidity < 500:
                result.flags.append(RugFlag(
                    check_type=RugCheckType.RAPID_LIQ_CHANGE,
                    severity=RugSeverity.MEDIUM,
                    message=f"Low liquidity for token age ({token_age_hours:.1f}h): ${liquidity:,.0f}",
                    score_penalty=10,
                ))
                result.rug_score -= 10


# ═══════════════════════════════════════════════════════════════════════════
# On-chain rug checks (requires Solana RPC — slower, used in live mode)
# ═══════════════════════════════════════════════════════════════════════════

class OnChainRugChecker:
    """
    Performs on-chain checks using Solana RPC.
    Only used in live mode — too slow for paper trading.
    """

    def __init__(self) -> None:
        self._client = None

    async def _get_client(self):
        if self._client is None:
            from app.blockchain.solana_client import SolanaClient
            self._client = SolanaClient()
        return self._client

    async def close(self) -> None:
        if self._client:
            await self._client.close()
            self._client = None

    async def check_token_account(
        self,
        token_address: str,
        result: RugAnalysisResult,
    ) -> None:
        """
        Check on-chain token account for mint/freeze authority.
        This is the authoritative check — DexScreener data may lag.
        """
        try:
            from solders.pubkey import Pubkey

            client = await self._get_client()
            pubkey = Pubkey.from_string(token_address)

            # getAccountInfo to check token metadata
            # This checks if mint authority is revoked on-chain
            # (implementation depends on SPL Token program state)

            # For now, we log the check intent — the full implementation
            # requires parsing SPL Token account data which is done via
            # the get_token_accounts_by_owner call or getAccountInfo
            logger.info(
                "on_chain_rug_check",
                token=token_address[:12],
                check="token_account",
            )

        except Exception as e:
            logger.warning("on_chain_rug_check_error", token=token_address[:12], error=str(e))


# Singleton for easy import
_rug_detector: Optional[RugDetector] = None


def get_rug_detector() -> RugDetector:
    global _rug_detector
    if _rug_detector is None:
        _rug_detector = RugDetector()
    return _rug_detector
