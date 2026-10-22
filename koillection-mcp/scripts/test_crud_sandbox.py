#!/usr/bin/env python3
"""Sandbox CRUD lifecycle test. Creates `_MCP CRUD TEST`, exercises CRUD, tears it down.

Run: uv run python scripts/test_crud_sandbox.py
Everything created here is deleted by the end (delete tools included).
"""

from __future__ import annotations

import base64
import json
import sys
import tempfile
from pathlib import Path

from koillection_mcp.server import (
    copy_template,
    create_choice_list,
    create_collection,
    create_field,
    create_item,
    create_tag,
    create_template,
    delete_choice_list,
    delete_collection,
    delete_field,
    delete_item,
    delete_item_data,
    delete_tag,
    delete_template,
    get_call_history,
    get_collection,
    get_collection_template,
    get_item,
    get_template,
    list_choice_lists,
    list_items,
    list_templates,
    set_item_data,
    update_collection,
    update_field,
    update_item,
    update_tag,
    update_template,
    upload_item_data_image,
    upload_item_image,
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

    # --- choice lists -------------------------------------------------------
    cl_preview = parse(create_choice_list("Sandbox Kinds", ["Alpha", "Beta"]))
    check("create_choice_list dry-run", cl_preview.get("dry_run") is True and cl_preview.get("applied") is False)
    choice_list = parse(create_choice_list("Sandbox Kinds", ["Alpha", "Beta"], dry_run=False))
    check("create_choice_list", choice_list.get("applied") is True, json.dumps(choice_list)[:300])
    choice_list_id = choice_list["result"]["id"]
    lists = parse(list_choice_lists())
    check("list_choice_lists contains sandbox", any(cl.get("id") == choice_list_id and cl.get("choices") == ["Alpha", "Beta"] for cl in lists if isinstance(cl, dict)), json.dumps(lists)[:300])
    bad_field = parse(create_field(template_id, "Bad Kind", "choice-list", position=9))
    check("create_field choice-list requires list", "error" in bad_field, json.dumps(bad_field)[:200])
    bad_field2 = parse(create_field(template_id, "Bad Kind 2", "text", position=9, choice_list_id=choice_list_id))
    check("create_field choice_list_id rejected for text", "error" in bad_field2, json.dumps(bad_field2)[:200])
    choice_template = parse(create_template("Sandbox Choice Template", dry_run=False))
    check("create choice template", choice_template.get("applied") is True, json.dumps(choice_template)[:300])
    choice_template_id = choice_template["result"]["id"]
    kind_field = parse(create_field(choice_template_id, "Sandbox Kind", "choice-list", position=0, choice_list_id=choice_list_id, dry_run=False))
    check("create choice-list field", kind_field.get("applied") is True and bool(kind_field["result"].get("choiceList")), json.dumps(kind_field)[:300])
    kind_field_id = kind_field["result"]["id"]

    # convert a text field to choice-list via update_field
    grade_list = parse(create_choice_list("Sandbox Grades", ["1", "8.5", "9.5", "10"], dry_run=False))
    check("create grade list", grade_list.get("applied") is True, json.dumps(grade_list)[:300])
    grade_list_id = grade_list["result"]["id"]
    grade_text = parse(create_field(choice_template_id, "Sandbox Grade", "text", position=1, dry_run=False))
    grade_field_id = grade_text["result"]["id"]
    bad_conv = parse(update_field(grade_field_id, type="choice-list", dry_run=False))
    check("update_field to choice-list requires list", "error" in bad_conv, json.dumps(bad_conv)[:200])
    converted = parse(update_field(grade_field_id, type="choice-list", choice_list_id=grade_list_id, dry_run=False))
    check("update_field converts to choice-list", converted.get("applied") is True and converted["result"].get("type") == "choice-list" and bool(converted["result"].get("choiceList")), json.dumps(converted)[:300])

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

    # --- image uploads + related items ---------------------------------------
    png_bytes = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8Xw8AAwMCAO+ip1sAAAAASUVORK5CYII="
    )
    with tempfile.TemporaryDirectory() as tmp:
        image_path = Path(tmp) / "pixel.png"
        image_path.write_bytes(png_bytes)
        main_preview = parse(upload_item_image(item1_id, str(image_path)))
        check("upload_item_image dry-run", main_preview.get("dry_run") is True and main_preview.get("applied") is False)
        main_upload = parse(upload_item_image(item1_id, str(image_path), dry_run=False))
        check("upload_item_image apply", main_upload.get("applied") is True, json.dumps(main_upload)[:400])
        data_preview = parse(upload_item_data_image(item1_id, "Front Image", str(image_path)))
        check("upload_item_data_image dry-run", data_preview.get("dry_run") is True and data_preview.get("applied") is False)
        data_upload = parse(upload_item_data_image(item1_id, "Front Image", str(image_path), dry_run=False))
        check("upload_item_data_image apply", data_upload.get("applied") is True, json.dumps(data_upload)[:400])
    view = parse(get_item(item1_id))
    check("main image stored", bool(view["item"].get("image")), json.dumps(view["item"])[:300])
    front = next((d for d in view["data"] if d.get("label") == "Front Image"), {})
    check(
        "data image stored",
        front.get("type") == "image" and bool(front.get("value") or front.get("file") or front.get("image")),
        json.dumps(front)[:300],
    )

    related = parse(update_item(item1_id, related_item_ids=[item2_id], dry_run=False))
    check("update_item related_items apply", related.get("applied") is True, json.dumps(related)[:400])
    view = parse(get_item(item1_id))
    related_iris = view["item"].get("relatedItems") or []
    check("related item recorded", any(str(r).endswith(item2_id) for r in related_iris), json.dumps(related_iris)[:300])
    sibling = parse(get_item(item2_id))
    sibling_iris = sibling["item"].get("relatedItems") or []
    print(f"INFO related-items mirrored by API: {any(str(r).endswith(item1_id) for r in sibling_iris)}")

    # --- updates -------------------------------------------------------------
    flip = parse(set_item_data(item1_id, "Owned", "checkbox", "1", dry_run=False))
    check("set_item_data upsert update", flip.get("applied") and flip.get("mode") == "updated", json.dumps(flip)[:300])
    view = parse(get_item(item1_id))
    owned_row = next((d for d in view["data"] if d["label"] == "Owned"), {})
    check("owned flipped to 1", str(owned_row.get("value")) == "1", json.dumps(owned_row)[:200])

    kind = parse(set_item_data(item1_id, "Sandbox Kind", "choice-list", "Alpha", choice_list_id=choice_list_id, dry_run=False))
    check("set_item_data choice-list create", kind.get("applied") and kind.get("mode") == "created", json.dumps(kind)[:300])
    view = parse(get_item(item1_id))
    kind_row = next((d for d in view["data"] if d["label"] == "Sandbox Kind"), {})
    check("choice-list datum stored", json.loads(str(kind_row.get("value") or "[]")) == ["Alpha"] and bool(kind_row.get("choiceList")), json.dumps(kind_row)[:300])
    kind_upd = parse(set_item_data(item1_id, "Sandbox Kind", "choice-list", "Beta", dry_run=False))
    check("set_item_data choice-list upsert keeps list", kind_upd.get("mode") == "updated", json.dumps(kind_upd)[:300])
    view = parse(get_item(item1_id))
    kind_row = next((d for d in view["data"] if d["label"] == "Sandbox Kind"), {})
    check("choice-list datum updated", json.loads(str(kind_row.get("value") or "[]")) == ["Beta"] and bool(kind_row.get("choiceList")), json.dumps(kind_row)[:300])

    graded = parse(set_item_data(item1_id, "Sandbox Grade", "choice-list", "9.5", choice_list_id=grade_list_id, dry_run=False))
    check("set_item_data graded value", graded.get("applied") and graded.get("mode") == "created", json.dumps(graded)[:300])
    empty_choice = parse(set_item_data(item1_id, "Sandbox Service", "choice-list", "", choice_list_id=grade_list_id, dry_run=False))
    check("set_item_data empty choice", empty_choice.get("applied") is True, json.dumps(empty_choice)[:300])
    view = parse(get_item(item1_id))
    grade_row = next((d for d in view["data"] if d["label"] == "Sandbox Grade"), {})
    svc_row = next((d for d in view["data"] if d["label"] == "Sandbox Service"), {})
    check("graded datum stored", json.loads(str(grade_row.get("value") or "[]")) == ["9.5"], json.dumps(grade_row)[:300])
    check("empty choice datum stored as []", str(svc_row.get("value")) == "[]", json.dumps(svc_row)[:300])

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

    # --- template resolver + copy ----------------------------------------------
    tmpl_view = parse(get_template(template_id))
    check("get_template field order", [f["name"] for f in tmpl_view.get("fields", [])] == ["Owned", "Note"],
          json.dumps(tmpl_view)[:300])

    set_default = parse(update_collection(sandbox_id, items_default_template_id=template_id, dry_run=False))
    check("set collection default template", set_default.get("applied") is True, json.dumps(set_default)[:300])
    resolved = parse(get_collection_template(sandbox_id))
    check("get_collection_template resolves", (resolved.get("template") or {}).get("name") == "Sandbox Template v2")
    sub_resolved = parse(get_collection_template(sub_id))
    check("subcollection reports no inherited default", sub_resolved.get("template") is None)

    templates_before = parse(list_templates())
    copy_preview = parse(
        copy_template(
            template_id,
            "Sandbox Copy",
            rename_fields={"Owned": "Collected"},
            type_overrides={"Note": "textarea"},
            add_fields=[{"name": "State", "type": "text"}],
        )
    )
    check("copy_template dry-run", copy_preview.get("dry_run") is True, json.dumps(copy_preview)[:300])
    result_fields = {f["name"]: f for f in copy_preview.get("result_fields", [])}
    check(
        "copy preview rename/retype/add",
        result_fields.get("Collected", {}).get("change") == "renamed"
        and result_fields.get("Note", {}).get("type") == "textarea"
        and result_fields.get("State", {}).get("change") == "added",
        json.dumps(result_fields)[:300],
    )
    templates_after_dry = parse(list_templates())
    check("copy dry-run created nothing", len(templates_after_dry) == len(templates_before))

    copied = parse(
        copy_template(
            template_id,
            "Sandbox Copy",
            rename_fields={"Owned": "Collected"},
            type_overrides={"Note": "textarea"},
            add_fields=[{"name": "State", "type": "text"}],
            dry_run=False,
        )
    )
    check("copy_template apply", copied.get("applied") is True, json.dumps(copied)[:400])
    copy_id = copied["result"]["id"]
    copy_fields = {f["name"]: f for f in copied.get("fields", [])}
    check("copy fields created", set(copy_fields) == {"Collected", "Note", "State"}, str(set(copy_fields)))

    # independence: rename a copied field, source must be unaffected
    parse(update_field(copy_fields["State"]["id"], name="State Renamed", dry_run=False))
    source_after = parse(get_template(template_id))
    check(
        "copy is independent from source",
        [f["name"] for f in source_after.get("fields", [])] == ["Owned", "Note"],
    )

    assign_copy = parse(update_collection(sub_id, items_default_template_id=copy_id, dry_run=False))
    check("assign copy as subcollection default", assign_copy.get("applied") is True)
    sub_resolved2 = parse(get_collection_template(sub_id))
    check("subcollection default resolves to copy", (sub_resolved2.get("template") or {}).get("name") == "Sandbox Copy")

    for fname in ["Collected", "Note", "State Renamed"]:
        fid = next((f["id"] for f in parse(get_template(copy_id)).get("fields", []) if f["name"] == fname), None)
        if fid:
            parse(delete_field(fid, confirm_name=fname, dry_run=False))
    parse(delete_template(copy_id, confirm_name="Sandbox Copy", dry_run=False))

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
    bad_cl = parse(delete_choice_list(choice_list_id, confirm_name="Wrong Name", dry_run=False))
    check("delete_choice_list rejects bad confirm", "error" in bad_cl)
    gone_kind_field = parse(delete_field(kind_field_id, confirm_name="Sandbox Kind", dry_run=False))
    check("delete choice-list field", gone_kind_field.get("applied") is True)
    gone_grade_field = parse(delete_field(grade_field_id, confirm_name="Sandbox Grade", dry_run=False))
    check("delete converted grade field", gone_grade_field.get("applied") is True)
    gone_choice_template = parse(delete_template(choice_template_id, confirm_name="Sandbox Choice Template", dry_run=False))
    check("delete choice template", gone_choice_template.get("applied") is True)

    gone = parse(delete_collection(sandbox_id, confirm_title="_MCP CRUD TEST", dry_run=False))
    check("delete_collection cascade", gone.get("applied") is True, json.dumps(gone)[:300])

    # choice list can only be deleted once referencing item data is gone (collection cascade above)
    gone_cl = parse(delete_choice_list(choice_list_id, confirm_name="Sandbox Kinds", dry_run=False))
    check("delete_choice_list", gone_cl.get("applied") is True, json.dumps(gone_cl)[:300])
    gone_gl = parse(delete_choice_list(grade_list_id, confirm_name="Sandbox Grades", dry_run=False))
    check("delete grade list", gone_gl.get("applied") is True, json.dumps(gone_gl)[:300])

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
