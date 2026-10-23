"""Display-order helper: stock collection datum + parent sortingProperty."""

from __future__ import annotations

from typing import Any

from koillection_mcp.client import KoillectionClient, KoillectionError

DISPLAY_ORDER_LABEL = "Display order"
DISPLAY_ORDER_TYPE = "number"


def _iri(collection_id: str) -> str:
    if collection_id.startswith("/api/"):
        return collection_id
    if collection_id.startswith("http"):
        from urllib.parse import urlparse

        return urlparse(collection_id).path
    return f"/api/collections/{collection_id}"


def collection_id_of(collection: dict[str, Any]) -> str:
    """UUID or last path segment from @id."""
    raw = collection.get("id") or collection.get("@id") or ""
    text = str(raw)
    if text.startswith("/api/") or text.startswith("http"):
        return text.rstrip("/").rsplit("/", 1)[-1]
    return text


# Back-compat alias used internally
def _id(collection: dict[str, Any]) -> str:
    return collection_id_of(collection)


def list_top_collections(client: KoillectionClient) -> list[dict[str, Any]]:
    cols = client.get_all_members("/api/collections")
    tops = [c for c in cols if not c.get("parent")]
    tops.sort(key=lambda c: (c.get("title") or "").casefold())
    return [
        {
            "id": _id(c),
            "title": c.get("title"),
            "color": c.get("color"),
        }
        for c in tops
    ]


def get_collection(client: KoillectionClient, collection_id: str) -> dict[str, Any]:
    return client.get(_iri(collection_id))


def list_children(client: KoillectionClient, parent_id: str) -> list[dict[str, Any]]:
    path = _iri(parent_id)
    children = client.get_all_members(f"{path}/children")
    out: list[dict[str, Any]] = []
    for child in children:
        cid = _id(child)
        order_value = _read_display_order(client, cid)
        out.append(
            {
                "id": cid,
                "title": child.get("title"),
                "color": child.get("color"),
                "display_order": order_value,
            }
        )
    # Stable default proposal: existing order values first, then title
    out.sort(
        key=lambda c: (
            c["display_order"] is None,
            float(c["display_order"]) if c["display_order"] is not None else 0.0,
            (c.get("title") or "").casefold(),
        )
    )
    return out


def _read_display_order(client: KoillectionClient, collection_id: str) -> float | None:
    data = client.get(f"{_iri(collection_id)}/data")
    members = data.get("hydra:member") or data.get("member") or []
    if isinstance(data, list):
        members = data
    for datum in members:
        if datum.get("label") == DISPLAY_ORDER_LABEL:
            raw = datum.get("value")
            if raw is None or raw == "":
                return None
            try:
                return float(raw)
            except (TypeError, ValueError):
                return None
    return None


def _find_display_order_datum(
    client: KoillectionClient, collection_id: str
) -> dict[str, Any] | None:
    data = client.get(f"{_iri(collection_id)}/data")
    members = data.get("hydra:member") or data.get("member") or []
    if isinstance(data, list):
        members = data
    for datum in members:
        if datum.get("label") == DISPLAY_ORDER_LABEL:
            return datum
    return None


def propose_orders(children: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fill missing orders with 10, 20, 30… preserving any existing values where possible."""
    used = {
        int(c["display_order"])
        for c in children
        if c.get("display_order") is not None
    }
    next_val = 10
    proposed: list[dict[str, Any]] = []
    for child in children:
        if child.get("display_order") is not None:
            order = int(child["display_order"])
        else:
            while next_val in used:
                next_val += 10
            order = next_val
            used.add(order)
            next_val += 10
        proposed.append({**child, "proposed_order": order})
    return proposed


def build_preview(
    client: KoillectionClient,
    parent_id: str,
    orders: dict[str, int],
) -> dict[str, Any]:
    """Return exact write plan without applying."""
    parent = get_collection(client, parent_id)
    parent_path = _iri(parent_id)
    children = list_children(client, parent_id)

    child_writes: list[dict[str, Any]] = []
    for child in children:
        cid = child["id"]
        if cid not in orders:
            continue
        new_val = int(orders[cid])
        existing = _find_display_order_datum(client, cid)
        coll_iri = _iri(cid)
        if existing:
            datum_path = existing.get("@id") or f"/api/data/{existing.get('id')}"
            payload = {
                "collection": coll_iri,
                "type": DISPLAY_ORDER_TYPE,
                "label": DISPLAY_ORDER_LABEL,
                "value": str(new_val),
            }
            if existing.get("position") is not None:
                payload["position"] = existing["position"]
            if existing.get("visibility") is not None:
                payload["visibility"] = existing["visibility"]
            child_writes.append(
                {
                    "child_id": cid,
                    "child_title": child.get("title"),
                    "method": "PUT",
                    "path": datum_path,
                    "payload": payload,
                    "mode": "update",
                    "from": child.get("display_order"),
                    "to": new_val,
                }
            )
        else:
            child_writes.append(
                {
                    "child_id": cid,
                    "child_title": child.get("title"),
                    "method": "POST",
                    "path": "/api/data",
                    "payload": {
                        "collection": coll_iri,
                        "type": DISPLAY_ORDER_TYPE,
                        "label": DISPLAY_ORDER_LABEL,
                        "value": str(new_val),
                    },
                    "mode": "create",
                    "from": None,
                    "to": new_val,
                }
            )

    cdc = dict(parent.get("childrenDisplayConfiguration") or {})
    # Match the verified PUT shape (2026-10-22 smoke): title/color/visibility + nested CDC.
    # Omit null optional IRIs so we do not clear itemsDefaultTemplate / parent by accident.
    parent_payload: dict[str, Any] = {
        "title": parent.get("title"),
        "color": parent.get("color"),
        "visibility": parent.get("visibility"),
        "childrenDisplayConfiguration": {
            "label": cdc.get("label"),
            "displayMode": cdc.get("displayMode") or "grid",
            "sortingProperty": DISPLAY_ORDER_LABEL,
            "sortingType": DISPLAY_ORDER_TYPE,
            "sortingDirection": "ASC",
            "showVisibility": cdc.get("showVisibility", True),
            "showActions": cdc.get("showActions", True),
            "showNumberOfChildren": cdc.get("showNumberOfChildren", True),
            "showNumberOfItems": cdc.get("showNumberOfItems", True),
            "showItemQuantities": cdc.get("showItemQuantities", False),
            "columns": cdc.get("columns") or [],
        },
    }
    if parent.get("parent"):
        parent_payload["parent"] = parent.get("parent")
    if parent.get("itemsDefaultTemplate"):
        parent_payload["itemsDefaultTemplate"] = parent.get("itemsDefaultTemplate")

    return {
        "dry_run": True,
        "parent": {
            "id": _id(parent),
            "title": parent.get("title"),
            "current_sortingProperty": cdc.get("sortingProperty"),
            "current_sortingType": cdc.get("sortingType"),
        },
        "parent_write": {
            "method": "PUT",
            "path": parent_path,
            "payload": parent_payload,
        },
        "child_writes": child_writes,
        "child_write_count": len(child_writes),
    }


def apply_preview(client: KoillectionClient, preview: dict[str, Any]) -> dict[str, Any]:
    """Execute a preview plan. Raises KoillectionError on failure."""
    results: list[dict[str, Any]] = []
    for write in preview.get("child_writes") or []:
        method = write["method"]
        path = write["path"]
        payload = write["payload"]
        if method == "POST":
            created = client.post(path, payload)
            results.append(
                {
                    "child_title": write.get("child_title"),
                    "mode": "created",
                    "id": created.get("id") or created.get("@id"),
                }
            )
        elif method == "PUT":
            updated = client.put(path, payload)
            results.append(
                {
                    "child_title": write.get("child_title"),
                    "mode": "updated",
                    "id": updated.get("id") or updated.get("@id"),
                }
            )
        else:
            raise KoillectionError(f"Unsupported method {method}")

    parent_write = preview["parent_write"]
    updated_parent = client.put(parent_write["path"], parent_write["payload"])
    cdc = updated_parent.get("childrenDisplayConfiguration") or {}
    return {
        "applied": True,
        "dry_run": False,
        "parent": {
            "id": updated_parent.get("id") or updated_parent.get("@id"),
            "title": updated_parent.get("title"),
            "sortingProperty": cdc.get("sortingProperty"),
            "sortingType": cdc.get("sortingType"),
            "sortingDirection": cdc.get("sortingDirection"),
        },
        "children": results,
    }


def parse_orders_from_form(form: dict[str, Any]) -> dict[str, int]:
    """Parse order[uuid]=N fields from a form mapping."""
    orders: dict[str, int] = {}
    for key, value in form.items():
        if not key.startswith("order["):
            continue
        # order[<id>]
        cid = key[len("order[") : -1] if key.endswith("]") else key[6:]
        if not cid:
            continue
        text = str(value).strip()
        if not text:
            continue
        orders[cid] = int(float(text))
    return orders
