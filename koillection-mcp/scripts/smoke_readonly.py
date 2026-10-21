#!/usr/bin/env python3
"""Smoke-test read-only Koillection client. Requires koillection-mcp/.env with password."""

from __future__ import annotations

import sys

from koillection_mcp.client import KoillectionClient, dumps


def main() -> int:
    client = KoillectionClient()
    health = client.health()
    print("health:", dumps(health))
    if not health.get("authenticated"):
        print(
            "FAIL: not authenticated. Set KOILLECTION_PASSWORD in .env "
            "(copy from .env.example) and re-run.",
            file=sys.stderr,
        )
        return 1

    print("whoami:", dumps(client.whoami()))
    cols = client.get_all_members("/api/collections")
    print(f"collections: {len(cols)}")
    for col in cols:
        print(f"  - {col.get('title')} ({col.get('id') or col.get('@id')})")

    coins = next((c for c in cols if (c.get("title") or "").upper() == "COINS"), None)
    if coins:
        cid = coins.get("id") or coins.get("@id")
        path = cid if str(cid).startswith("/") else f"/api/collections/{cid}"
        children = client.get_all_members(f"{path}/children")
        print("COINS children:", [c.get("title") for c in children])

    items = client.get_all_members("/api/items")
    print(f"items: {len(items)}")
    q = "quarter"
    matches = [i for i in items if q in (i.get("name") or "").lower()]
    print(f"search '{q}': {len(matches)} match(es)")
    for item in matches[:10]:
        print(f"  - {item.get('name')}")

    client.close()
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
