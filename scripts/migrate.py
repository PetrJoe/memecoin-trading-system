#!/usr/bin/env python
"""Run Alembic migrations programmatically.

Usage:
    python scripts/migrate.py            # upgrade to head
    python scripts/migrate.py +1         # upgrade one revision
    python scripts/migrate.py downgrade -1
    python scripts/migrate.py current
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    from alembic import command
    from alembic.config import Config

    ini_path = ROOT / "alembic.ini"
    if not ini_path.exists():
        print(f"error: {ini_path} not found", file=sys.stderr)
        return 1

    cfg = Config(str(ini_path))
    cfg.set_main_option("script_location", str(ROOT / "app" / "database" / "migrations"))

    args = sys.argv[1:] or ["upgrade", "head"]
    if args[0] == "current":
        command.current(cfg)
    elif args[0] == "history":
        command.history(cfg)
    elif args[0] == "upgrade":
        command.upgrade(cfg, args[1] if len(args) > 1 else "head")
    elif args[0] == "downgrade":
        command.downgrade(cfg, args[1] if len(args) > 1 else "-1")
    elif args[0] == "stamp":
        command.stamp(cfg, args[1] if len(args) > 1 else "head")
    else:
        print(f"unknown command: {args[0]}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
