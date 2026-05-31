"""Print the remaining SerpApi searches for every configured key.

Read-only and free -- the Account API does not count against your quota. Handy
before a build to see which keys still have searches left, and in what order
failover will use them.

Usage (from the project root):
    python src/serpapi_balances.py
"""
from __future__ import annotations

import os
import sys

SRC_DIR = os.path.dirname(os.path.abspath(__file__))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from httputil import build_url, get_json  # noqa: E402
from trends_providers._util import load_keys, mask  # noqa: E402
from trends_providers.serpapi import ACCOUNT_ENDPOINT  # noqa: E402


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

    keys = load_keys("SERPAPI_KEY")
    if not keys:
        print("No SerpApi key found. Add SERPAPI_KEY=... to a .env / serpapi.env file.", file=sys.stderr)
        return 1

    print(f"{len(keys)} SerpApi key(s) configured (failover uses them in this order):\n")
    total_left = 0.0
    known = False
    for i, key in enumerate(keys, 1):
        try:
            data = get_json(build_url(ACCOUNT_ENDPOINT, {"api_key": key}), timeout=20, retries=2)
            left = data.get("total_searches_left")
            used = data.get("this_month_usage")
            cap = data.get("searches_per_month")
            if left is None:
                print(f"  {i}. {mask(key):<20} searches-left unavailable for this key")
                continue
            known = True
            total_left += float(left)
            cap_txt = "" if cap is None else f" / {int(cap)}"
            used_txt = "" if used is None else f"used {int(used)}{cap_txt}   "
            print(f"  {i}. {mask(key):<20} {used_txt}searches left: {int(left)}")
        except Exception as err:  # noqa: BLE001 -- report, don't crash the table
            print(f"  {i}. {mask(key):<20} ERROR: {err}")

    if known:
        print(f"\nTotal searches left across keys: {int(total_left)}")
        print("At 8 searches/build that is about "
              f"{int(total_left // 8)} more builds (daily ~30/mo, weekly ~4/mo).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
