"""Print the remaining Apify budget for every configured token.

Read-only and free (it only calls GET /v2/users/me/limits). Handy before a build
to see which tokens still have headroom, and in what order failover will use them.

Usage (from the project root):
    python src/apify_balances.py
"""
from __future__ import annotations

import os
import sys

SRC_DIR = os.path.dirname(os.path.abspath(__file__))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from httputil import get_json  # noqa: E402
from trends_providers.apify import LIMITS_ENDPOINT, _load_tokens, _mask  # noqa: E402


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

    try:
        tokens = _load_tokens()
    except RuntimeError as err:
        print(err, file=sys.stderr)
        return 1

    print(f"{len(tokens)} Apify token(s) configured (failover uses them in this order):\n")
    total_remaining = 0.0
    known = False
    for i, token in enumerate(tokens, 1):
        try:
            data = get_json(
                LIMITS_ENDPOINT, timeout=20, retries=2,
                headers={"Authorization": "Bearer " + token},
            ).get("data") or {}
            mx = (data.get("limits") or {}).get("maxMonthlyUsageUsd")
            cur = (data.get("current") or {}).get("monthlyUsageUsd")
            cycle_end = (data.get("monthlyUsageCycle") or {}).get("endAt", "")[:10]
            if mx is None or cur is None:
                print(f"  {i}. {_mask(token):<22} limits unavailable for this token")
                continue
            remaining = float(mx) - float(cur)
            total_remaining += remaining
            known = True
            print(
                f"  {i}. {_mask(token):<22} used ${float(cur):>8.2f} / ${float(mx):>8.2f}"
                f"   remaining ${remaining:>8.2f}   (cycle ends {cycle_end})"
            )
        except Exception as err:  # noqa: BLE001 -- report, don't crash the whole table
            print(f"  {i}. {_mask(token):<22} ERROR: {err}")

    if known:
        print(f"\nTotal remaining across tokens: ${total_remaining:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
