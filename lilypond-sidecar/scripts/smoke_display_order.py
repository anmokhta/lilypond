#!/usr/bin/env python3
"""Self-cleaning smoke: sandbox parent+children, preview + apply Display order, verify, delete."""

from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv

# Allow running without install: uv run python scripts/smoke_display_order.py
_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_ROOT / ".env")
load_dotenv(_ROOT.parent / "koillection-mcp" / ".env")

from koillection_mcp.client import KoillectionClient, KoillectionError  # noqa: E402
from lilypond_sidecar.display_order import (  # noqa: E402
    DISPLAY_ORDER_LABEL,
    apply_preview,
    build_preview,
    list_children,
)


def check(name: str, ok: bool, detail: str = "") -> None:
    status = "OK" if ok else "FAIL"
    print(f"[{status}] {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        raise SystemExit(1)


def main() -> None:
    client = KoillectionClient()
    parent_id = None
    child_ids: list[str] = []
    try:
        health = client.health()
        check("health", bool(health.get("ok")), str(health))

        parent = client.post(
            "/api/collections",
            {"title": "_MCP SIDECAR ORDER SMOKE", "visibility": "private"},
        )
        parent_id = parent.get("id") or parent.get("@id")
        parent_iri = parent.get("@id") or f"/api/collections/{parent_id}"
        check("create parent", bool(parent_id), str(parent_id))

        for title in ("Zulu Child", "Alpha Child", "Mike Child"):
            child = client.post(
                "/api/collections",
                {"title": title, "parent": parent_iri, "visibility": "private"},
            )
            cid = child.get("id") or child.get("@id")
            child_ids.append(str(cid).rstrip("/").rsplit("/", 1)[-1])
        check("create children", len(child_ids) == 3, str(child_ids))

        # Desired order: Alpha=10, Mike=20, Zulu=30 (not title order of creation)
        by_title = {c["title"]: c["id"] for c in list_children(client, str(parent_id))}
        orders = {
            by_title["Alpha Child"]: 10,
            by_title["Mike Child"]: 20,
            by_title["Zulu Child"]: 30,
        }

        preview = build_preview(client, str(parent_id), orders)
        check("preview child writes", preview["child_write_count"] == 3)
        check(
            "preview sets sortingProperty",
            preview["parent_write"]["payload"]["childrenDisplayConfiguration"]["sortingProperty"]
            == DISPLAY_ORDER_LABEL,
        )

        result = apply_preview(client, preview)
        check("apply", result.get("applied") is True)
        check(
            "parent sortingProperty applied",
            (result.get("parent") or {}).get("sortingProperty") == DISPLAY_ORDER_LABEL,
        )

        after = list_children(client, str(parent_id))
        got = {c["title"]: c["display_order"] for c in after}
        check("Alpha order 10", got.get("Alpha Child") == 10.0, str(got))
        check("Mike order 20", got.get("Mike Child") == 20.0, str(got))
        check("Zulu order 30", got.get("Zulu Child") == 30.0, str(got))

        # Idempotent update path
        preview2 = build_preview(client, str(parent_id), orders)
        check(
            "second preview uses PUT",
            all(w["mode"] == "update" for w in preview2["child_writes"]),
        )
        apply_preview(client, preview2)
        check("re-apply ok", True)

        print("All smoke checks passed.")
    except KoillectionError as exc:
        print(f"KoillectionError: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    finally:
        # Delete parent cascades children in Koillection
        if parent_id:
            try:
                path = (
                    parent_id
                    if str(parent_id).startswith("/api/")
                    else f"/api/collections/{parent_id}"
                )
                client.delete(path)
                print(f"Cleaned up {path}")
            except Exception as exc:  # noqa: BLE001
                print(f"Cleanup warning: {exc}", file=sys.stderr)
        client.close()


if __name__ == "__main__":
    main()
