#!/usr/bin/env python
"""Standalone health check.

Exit codes: 0 = healthy, 1 = degraded, 2 = error.
Usage:
    python scripts/healthcheck.py            # full dependency check
    python scripts/healthcheck.py --quick    # local-only checks, no network
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _local_checks() -> tuple[list, str]:
    """Checks that need no network: config loads, state consistency."""
    from app.config.settings import get_settings

    issues: list[str] = []
    try:
        settings = get_settings()
    except Exception as e:
        print(f"FATAL: configuration invalid: {e}")
        sys.exit(2)

    if settings.WEB_UI_ENABLED and not settings.WEB_UI_PASSWORD.get_secret_value():
        issues.append("WEB_UI_PASSWORD empty: dashboard login disabled")

    from app.api.state import get_app_state

    state = get_app_state()
    if state.position_manager is not None:
        open_pos = state.position_manager.open_count()
        print(f"open positions: {open_pos}")
        if open_pos > 0 and state.prices:
            stale = [
                addr
                for addr in state.position_manager.positions
                if addr not in state.prices
            ]
            if stale:
                issues.append(f"{len(stale)} position(s) without fresh price data")

    return issues, settings.APP_ENV.value


async def _network_checks() -> tuple[list[str], str]:
    from app.monitoring.health import HealthChecker

    checker = HealthChecker()
    try:
        checks = await checker.check_all()
        overall = checker.aggregate(checks)
        for c in checks:
            print(f"  {c.name:12s} {c.status:9s} {c.latency_ms or '-':>8} {c.detail}")
        issues = [
            f"{c.name}: {c.status} {c.detail}".strip() for c in checks if c.status != "ok"
        ]
        return issues, overall
    finally:
        await checker.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Meme Trader health check")
    parser.add_argument("--quick", action="store_true", help="skip network checks")
    args = parser.parse_args()

    issues, _env = _local_checks()

    if args.quick:
        overall = "degraded" if issues else "ok"
    else:
        net_issues, overall = asyncio.run(_network_checks())
        issues.extend(net_issues)

    for issue in issues:
        print(f"WARNING: {issue}", file=sys.stderr)

    print(f"overall: {overall}")
    if overall == "error":
        return 2
    if overall == "degraded":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
