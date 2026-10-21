#!/usr/bin/env python3
"""Import the State & Territories Quarters manifest into Koillection.

Reads data/state-territories-quarters/manifest.json (56 designs), expands each
design into Philadelphia + Denver items in the "State & Territories Quarters"
subcollection, uploads reference front/back images, and links each P/D pair via
Related Items. Field definitions are read from the live collection template at
run time; item names dedupe re-runs, and missing data/images/links are filled
in rather than duplicated.

Dry-run by default (nothing is written). Apply with --apply.
  uv run python scripts/import_state_territories_quarters.py [--apply] [--only Delaware,51]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = PROJECT_ROOT / "data" / "state-territories-quarters" / "manifest.json"
IMAGES_DIR = PROJECT_ROOT / "data" / "state-territories-quarters" / "images"
LOG_DIR = PROJECT_ROOT / "logs"

from koillection_mcp.server import (  # noqa: E402
    create_item,
    get_collection_template,
    get_item,
    list_collections,
    list_items,
    set_item_data,
    update_item,
    upload_item_data_image,
    upload_item_image,
)

COLLECTION_TITLE = "State & Territories Quarters"
MINT_FACILITY = {"P": "Philadelphia", "D": "Denver"}


def parse(raw: str) -> dict | list:
    try:
        return json.loads(raw)
    except ValueError:
        return {"raw": raw}


def validate(manifest: dict) -> list[dict]:
    designs = manifest.get("designs") or []
    errors = []
    if len(designs) != 56:
        errors.append(f"expected 56 designs, found {len(designs)}")
    numbers = [d.get("coin_number") for d in designs]
    if sorted(numbers) != list(range(1, 57)):
        errors.append("coin_number values are not exactly 1..56")
    types = {}
    for d in designs:
        types[d.get("jurisdiction_type")] = types.get(d.get("jurisdiction_type"), 0) + 1
        for mint in ("P", "D"):
            if not (d.get("mintage") or {}).get(mint):
                errors.append(f"{d.get('jurisdiction')}: missing {mint} mintage")
        rev = (d.get("reverse") or {}).get("local_image", {}).get("file")
        if not rev or not (IMAGES_DIR / rev).is_file():
            errors.append(f"{d.get('jurisdiction')}: reverse image not staged ({rev})")
    if types != {"State": 50, "District": 1, "Territory": 5}:
        errors.append(f"jurisdiction types are {types}, expected 50 State / 1 District / 5 Territory")
    for mint in ("P", "D"):
        f = (manifest.get("obverse_images_by_mint") or {}).get(mint, {}).get("local", {}).get("file")
        if not f or not (IMAGES_DIR / f).is_file():
            errors.append(f"obverse image for mint {mint} not staged ({f})")
    return errors


def item_name(design: dict, mint: str) -> str:
    return f"{design['coin_number']:03d} — {design['jurisdiction']} — {design['release_year']}-{mint}"


def build_data(design: dict, mint: str, specs: dict, field_types: dict[str, str],
               field_positions: dict[str, int]) -> list[dict]:
    values: dict[str, str] = {
        "Owned": "0",
        "Denomination": specs["denomination"],
        "Country": specs["country"],
        "Series / Design": design["program"],
        "Program": design["program"],
        "Year": str(design["release_year"]),
        "Mint Mark": mint,
        "Mint Facility": MINT_FACILITY[mint],
        "Finish": specs["finish"],
        "Material / Composition": specs["material"],
        "Proof": "0",
        "Graded": "0",
        "Grade": "",
        "Grading Service": "",
        "Condition": "",
        "Color / Toning": "",
        "Diameter (mm)": str(specs["diameter_mm"]),
        "Weight (g)": str(specs["weight_g"]),
        "Thickness (mm)": str(specs["thickness_mm"]),
        "Edge": specs["edge"],
        "Mintage": str(design["mintage"][mint]),
        "Source URL": design["reference_url"],
        "Notes": "",
        "Coin Number": str(design["coin_number"]),
        "Jurisdiction": design["jurisdiction"],
        "Jurisdiction Type": design["jurisdiction_type"],
        "Release Year": str(design["release_year"]),
        "Release Order": str(design["release_order"]),
        "Release Date": design["release_date"],
        "Obverse Portrait": design["obverse"]["portrait"],
        "Obverse Engraver": design["obverse"]["engraver"],
        "Reverse Design Theme": design["reverse"]["design_theme"],
        "Reverse Engraver": design["reverse"]["engraver"],
        "Reverse Inscriptions": json.dumps(design["reverse"]["inscriptions"]),
    }
    if design.get("statehood_date"):
        values["Statehood Date"] = design["statehood_date"]
    entries = []
    for label, value in values.items():
        if label not in field_types:
            continue
        entries.append({
            "label": label,
            "type": field_types[label],
            "value": value,
            "position": field_positions.get(label),
        })
    return entries


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="actually write (default is dry-run preview)")
    ap.add_argument("--only", default="", help="comma-separated jurisdiction names or coin numbers to include")
    args = ap.parse_args()
    apply = args.apply

    manifest = json.loads(MANIFEST_PATH.read_text())
    errors = validate(manifest)
    if errors:
        print("MANIFEST INVALID:")
        for e in errors:
            print(" -", e)
        return 1
    designs = manifest["designs"]
    if args.only:
        wanted = {t.strip() for t in args.only.split(",") if t.strip()}
        designs = [d for d in designs
                   if d["jurisdiction"] in wanted or str(d["coin_number"]) in wanted]
        print(f"--only filter: {len(designs)} design(s)")

    collections = parse(list_collections())
    target = next((c for c in collections if c.get("title") == COLLECTION_TITLE), None)
    if not target:
        print(f"collection '{COLLECTION_TITLE}' not found")
        return 1
    collection_id = target["id"]
    template = parse(get_collection_template(collection_id))
    fields = template.get("fields") or []
    if not fields:
        print("collection has no default template fields; run template setup first")
        return 1
    field_types = {f["name"]: f["type"] for f in fields}
    field_positions = {f["name"]: f.get("position") for f in fields}
    specs = manifest["coin_specs"]

    existing = {i["name"]: i["id"] for i in parse(list_items(collection_id))}
    report: dict = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "apply": apply,
        "collection": COLLECTION_TITLE,
        "created": [], "filled": [], "skipped_existing": [],
        "images_uploaded": 0, "images_planned": 0,
        "links_set": [], "links_planned": [],
        "errors": [],
    }
    ids: dict[str, str] = {}

    for design in designs:
        reverse_path = IMAGES_DIR / design["reverse"]["local_image"]["file"]
        for mint in ("P", "D"):
            name = item_name(design, mint)
            entries = build_data(design, mint, specs, field_types, field_positions)
            obverse_path = IMAGES_DIR / manifest["obverse_images_by_mint"][mint]["local"]["file"]
            item_id = existing.get(name)
            if item_id:
                ids[name] = item_id
                view = parse(get_item(item_id))
                have_labels = {d["label"] for d in view.get("data", [])}
                missing = [e for e in entries if e["label"] not in have_labels]
                if missing:
                    if apply:
                        for e in missing:
                            r = parse(set_item_data(item_id, e["label"], e["type"], e["value"],
                                                    position=e.get("position"), dry_run=False))
                            if "error" in r:
                                report["errors"].append(f"{name}: set {e['label']}: {r.get('message')}")
                        report["filled"].append(name)
                    else:
                        report["filled"].append(f"{name} (dry-run: {len(missing)} fields)")
                else:
                    report["skipped_existing"].append(name)
                # images on existing items: fill only what is missing
                have_front = any(d.get("label") == "Front Image" and d.get("image") for d in view.get("data", []))
                have_back = any(d.get("label") == "Back Image" and d.get("image") for d in view.get("data", []))
                plan = (0 if view["item"].get("image") else 1) + (0 if have_front else 1) + (0 if have_back else 1)
                if apply:
                    if not view["item"].get("image"):
                        upload_item_image(item_id, str(reverse_path), dry_run=False)
                        report["images_uploaded"] += 1
                    if not have_front:
                        upload_item_data_image(item_id, "Front Image", str(obverse_path), dry_run=False)
                        report["images_uploaded"] += 1
                    if not have_back:
                        upload_item_data_image(item_id, "Back Image", str(reverse_path), dry_run=False)
                        report["images_uploaded"] += 1
                else:
                    report["images_planned"] += plan
                continue

            created = parse(create_item(collection_id, name, data=entries, dry_run=not apply))
            if "error" in created:
                report["errors"].append(f"{name}: {created.get('message')}")
                continue
            if not apply:
                report["created"].append(f"{name} (dry-run)")
                report["images_planned"] += 3
                continue
            item_id = created["result"]["id"]
            ids[name] = item_id
            report["created"].append(name)
            for label, path in (("main", reverse_path), ("Front Image", obverse_path), ("Back Image", reverse_path)):
                if label == "main":
                    r = parse(upload_item_image(item_id, str(path), dry_run=False))
                else:
                    r = parse(upload_item_data_image(item_id, label, str(path), dry_run=False))
                if "error" in r:
                    report["errors"].append(f"{name}: upload {label}: {r.get('message')}")
                else:
                    report["images_uploaded"] += 1

    # link each P/D pair both directions (the API does not mirror relations)
    for design in designs:
        p_name, d_name = item_name(design, "P"), item_name(design, "D")
        if not apply:
            report["links_planned"].append(f"{p_name} <-> {d_name}")
            continue
        p_id, d_id = ids.get(p_name), ids.get(d_name)
        if not p_id or not d_id:
            continue
        for src, dst in ((p_id, d_id), (d_id, p_id)):
            view = parse(get_item(src))
            current = view.get("item", {}).get("relatedItems") or []
            if any(str(r).endswith(dst) for r in current):
                continue
            r = parse(update_item(src, related_item_ids=[dst], dry_run=False))
            if "error" in r:
                report["errors"].append(f"link {src}: {r.get('message')}")
        report["links_set"].append(f"{p_name} <-> {d_name}")

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    report_path = LOG_DIR / f"state-territories-import-{stamp}.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({
        "apply": apply,
        "designs": len(designs),
        "items_targeted": len(designs) * 2,
        "created": len(report["created"]),
        "filled": len(report["filled"]),
        "skipped_existing": len(report["skipped_existing"]),
        "images_uploaded": report["images_uploaded"],
        "images_planned": report["images_planned"],
        "links_set": len(report["links_set"]),
        "links_planned": len(report["links_planned"]),
        "errors": report["errors"],
        "report": str(report_path),
    }, indent=2))
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
