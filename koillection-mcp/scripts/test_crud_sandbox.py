#!/usr/bin/env python3
"""Sandbox CRUD lifecycle test. Creates `_MCP CRUD TEST`, exercises CRUD, tears it down.

Run: uv run python scripts/test_crud_sandbox.py
Everything created here is deleted by the end (delete tools included).
"""

from __future__ import annotations

import json
import sys

from koillection_mcp.server import (
    create_collection,
    create_field,
    create_item,
    create_tag,
    create_template,
    delete_collection,
    delete_field,
    delete_item,
    delete_item_data,
    delete_tag,
    delete_template,
    get_call_history,
    get_collection,
    get_item,
    list_items,
    set_item_data,
    update_collection,
    update_field,
    update_item,
    update_tag,
    update_template,
)

FAILURES: list[str] = []


def parse(raw: str) -> dict:
    try:
        return json.loads(raw)
    except ValueError:
        return {"raw": raw}


def check(label: str, cond: bool, detail: str = "") -> None:
    print(("PASS " if cond else "FAIL ") + label + (f" :: {detail}" if detail and not cond else ""))
    if not cond:
        FAILURES.append(label)


def main() -> int:
    # --- dry-run contract -------------------------------------------------
    preview = parse(create_collection("_MCP CRUD TEST"))
    check("dry-run create_collection", preview.get("dry_run") is True and preview.get("applied") is False)

    # --- structure ---------------------------------------------------------
    sandbox = parse(create_collection("_MCP CRUD TEST", dry_run=False))
    check("create_collection", sandbox.get("applied") is True, json.dumps(sandbox)[:300])
    sandbox_id = sandbox["result"]["id"]

    sub = parse(create_collection("Sandbox Sub", parent_id=sandbox_id, dry_run=False))
    check("create subcollection", sub.get("applied") is True, json.dumps(sub)[:300])
    sub_id = sub["result"]["id"]
    check("subcollection parent", (sub["result"].get("parent") or "").endswith(sandbox_id))

    coll_view = parse(get_collection(sandbox_id))
    check("get_collection children", [c["title"] for c in coll_view.get("children", [])] == ["Sandbox Sub"])

    template = parse(create_template("Sandbox Template", dry_run=False))
    check("create_template", template.get("applied") is True, json.dumps(template)[:300])
    template_id = template["result"]["id"]

    owned = parse(create_field(template_id, "Owned", "checkbox", position=0, dry_run=False))
    check("create checkbox field", owned.get("applied") is True, json.dumps(owned)[:300])
    owned_id = owned["result"]["id"]
    name_f = parse(create_field(template_id, "Note", "text", position=1, dry_run=False))
    check("create text field", name_f.get("applied") is True)
    note_field_id = name_f["result"]["id"]

    tag = parse(create_tag("sandbox-tag", description="crud test", dry_run=False))
    check("create_tag", tag.get("applied") is True, json.dumps(tag)[:300])
    tag_id = tag["result"]["id"]

    # --- items --------------------------------------------------------------
    item1 = parse(
        create_item(
            sub_id,
            "Test Item One",
            quantity=1,
            tag_ids=[tag_id],
            data=[
                {"label": "Owned", "type": "checkbox", "value": "0"},
                {"label": "Note", "type": "text", "value": "first"},
            ],
            dry_run=False,
        )
    )
    check("create_item with data", item1.get("applied") is True, json.dumps(item1)[:400])
    item1_id = item1["result"]["id"]
    check("item has 2 data fields", len(item1.get("data", [])) == 2)

    item2 = parse(create_item(sub_id, "Test Item Two", dry_run=False))
    check("create_item 2", item2.get("applied") is True)
    item2_id = item2["result"]["id"]
    parse(create_item(sub_id, "Test Item Three", dry_run=False))

    items = parse(list_items(sub_id))
    check("list_items count", isinstance(items, list) and len(items) == 3)

    view = parse(get_item(item1_id))
    check("get_item", view["item"]["name"] == "Test Item One" and len(view["data"]) == 2)

    # --- updates -------------------------------------------------------------
    flip = parse(set_item_data(item1_id, "Owned", "checkbox", "1", dry_run=False))
    check("set_item_data upsert update", flip.get("applied") and flip.get("mode") == "updated", json.dumps(flip)[:300])
    view = parse(get_item(item1_id))
    owned_row = next((d for d in view["data"] if d["label"] == "Owned"), {})
    check("owned flipped to 1", str(owned_row.get("value")) == "1", json.dumps(owned_row)[:200])

    add = parse(set_item_data(item1_id, "Location", "text", "Shelf A", dry_run=False))
    check("set_item_data create mode", add.get("mode") == "created")
    rm = parse(delete_item_data(item1_id, "Location", dry_run=False))
    check("delete_item_data", rm.get("applied") is True)

    renamed = parse(update_item(item2_id, name="Test Item Two Renamed", quantity=3, dry_run=False))
    check("update_item", renamed.get("applied") is True and renamed["result"]["name"] == "Test Item Two Renamed")

    moved = parse(update_item(item2_id, collection_id=sandbox_id, dry_run=False))
    check("move item to parent", moved["result"].get("collection", "").endswith(sandbox_id))
    back = parse(update_item(item2_id, collection_id=sub_id, dry_run=False))
    check("move item back", back.get("applied") is True)

    upd_coll = parse(update_collection(sub_id, color="FFCC00", dry_run=False))
    check("update_collection", upd_coll.get("applied") is True and upd_coll["result"].get("color") == "FFCC00",
          json.dumps(upd_coll)[:300])

    upd_template = parse(update_template(template_id, "Sandbox Template v2", dry_run=False))
    check("update_template", upd_template.get("applied") is True)
    upd_field = parse(update_field(note_field_id, position=5, dry_run=False))
    check("update_field", upd_field.get("applied") is True)
    upd_tag = parse(update_tag(tag_id, description="crud test updated", dry_run=False))
    check("update_tag", upd_tag.get("applied") is True)

    # --- deletes (sandbox teardown) -------------------------------------------
    bad = parse(delete_item(item2_id, confirm_name="Wrong Name", dry_run=False))
    check("delete_item rejects bad confirm", "error" in bad)

    gone_item = parse(delete_item(item2_id, confirm_name="Test Item Two Renamed", dry_run=False))
    check("delete_item", gone_item.get("applied") is True)

    prev = parse(delete_collection(sandbox_id, confirm_title="nope"))
    check("delete_collection dry-run", prev.get("dry_run") is True and "will_delete" in prev,
          json.dumps(prev)[:300])

    gone_field = parse(delete_field(owned_id, confirm_name="Owned", dry_run=False))
    check("delete_field", gone_field.get("applied") is True)
    gone_tag = parse(delete_tag(tag_id, confirm_name="sandbox-tag", dry_run=False))
    check("delete_tag", gone_tag.get("applied") is True)
    gone_template = parse(delete_template(template_id, confirm_name="Sandbox Template v2", dry_run=False))
    check("delete_template", gone_template.get("applied") is True)

    gone = parse(delete_collection(sandbox_id, confirm_title="_MCP CRUD TEST", dry_run=False))
    check("delete_collection cascade", gone.get("applied") is True, json.dumps(gone)[:300])

    from koillection_mcp.server import list_collections, search_items

    cols_after = parse(list_collections())
    titles_after = [c.get("title") for c in cols_after] if isinstance(cols_after, list) else []
    check("sandbox gone from list_collections", "_MCP CRUD TEST" not in titles_after, str(titles_after))
    remaining = parse(search_items("Test Item"))
    check("sandbox items deleted", remaining.get("matched") == 0, json.dumps(remaining)[:200])

    hist = parse(get_call_history(200))
    logged = {e.get("tool") for e in hist} if isinstance(hist, list) else set()
    check("history has write tools", {"create_collection", "create_item", "delete_collection"} <= logged,
          str(sorted(logged))[:300])

    print(f"\n{len(FAILURES)} failure(s)")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
