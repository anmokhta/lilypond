"""Koillection MCP server — read tools + CRUD with dry-run-by-default writes."""

from __future__ import annotations

import functools
import inspect
import time
from typing import Any, Callable

from mcp.server.mcpserver import MCPServer

try:
    from mcp_types import ToolAnnotations
except Exception:  # noqa: BLE001 — annotations are metadata only
    ToolAnnotations = None  # type: ignore[assignment]

from koillection_mcp import history
from koillection_mcp.client import KoillectionClient, KoillectionError, dumps

mcp = MCPServer(
    "koillection",
    instructions=(
        "Koillection MCP. Use health_check and whoami first. Collections use title "
        "(not name); a subcollection is a collection with a parent. IDs may be UUIDs "
        "or IRIs like /api/collections/<uuid>. WRITE CONTRACT: every create/update/"
        "delete tool defaults to dry_run=true and only previews the payload. Never "
        "apply (dry_run=false) without showing the preview and getting explicit user "
        "confirmation. Deletes also require confirm_title/confirm_name matching the "
        "current value. Tool categories are prefixed in descriptions: [read], "
        "[create], [update], [delete]."
    ),
)

_client: KoillectionClient | None = None


def get_client() -> KoillectionClient:
    global _client
    if _client is None:
        _client = KoillectionClient()
    return _client


# ---------------------------------------------------------------------------
# Tool registration with call-history logging
# ---------------------------------------------------------------------------

_CATEGORY_ANNOTATIONS: dict[str, dict[str, bool]] = {
    "read": {"readOnlyHint": True, "destructiveHint": False},
    "create": {"readOnlyHint": False, "destructiveHint": False},
    "update": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True},
    "delete": {"readOnlyHint": False, "destructiveHint": True},
}


def tool(category: str) -> Callable:
    """Register a tool and log every call to the JSONL history."""

    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            bound = inspect.signature(fn).bind_partial(*args, **kwargs)
            call_args = dict(bound.arguments)
            started = time.perf_counter()
            result: Any = None
            error: str | None = None
            try:
                result = fn(*args, **kwargs)
                return result
            except Exception as exc:  # noqa: BLE001 — record, then propagate
                error = f"{type(exc).__name__}: {exc}"
                raise
            finally:
                ok = error is None
                if ok and isinstance(result, str):
                    try:
                        import json as _json

                        parsed = _json.loads(result)
                        if isinstance(parsed, dict) and "error" in parsed:
                            ok = False
                            error = str(parsed.get("message") or parsed.get("error"))
                    except Exception:  # noqa: BLE001
                        pass
                history.record(
                    tool=fn.__name__,
                    category=category,
                    args=call_args,
                    duration_ms=(time.perf_counter() - started) * 1000,
                    ok=ok,
                    result=result,
                    error=error,
                )

        description = f"[{category}] {(fn.__doc__ or '').strip()}".strip()
        kwargs: dict[str, Any] = {"description": description}
        if ToolAnnotations is not None:
            hints = _CATEGORY_ANNOTATIONS.get(category, {})
            if hints:
                kwargs["annotations"] = ToolAnnotations(**hints)
        return mcp.tool(**kwargs)(wrapper)

    return decorator


def _id_or_iri(value: str, resource: str) -> str:
    """Accept a UUID, IRI path, or URL; return an API path."""
    value = value.strip()
    if value.startswith("/api/"):
        return value
    if value.startswith("http"):
        return value
    return f"/api/{resource}/{value}"


def _iri(value: str, resource: str) -> str:
    """Normalize any id form to a canonical IRI path for payloads."""
    path = _id_or_iri(value, resource)
    if path.startswith("http"):
        from urllib.parse import urlparse

        return urlparse(path).path
    return path


def _clean(payload: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in payload.items() if v is not None}


def _summarize_collection(c: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": c.get("id") or c.get("@id"),
        "title": c.get("title"),
        "parent": c.get("parent"),
        "visibility": c.get("finalVisibility") or c.get("visibility"),
        "color": c.get("color"),
        "itemsDefaultTemplate": c.get("itemsDefaultTemplate"),
    }


def _summarize_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item.get("id") or item.get("@id"),
        "name": item.get("name"),
        "quantity": item.get("quantity"),
        "collection": item.get("collection"),
        "visibility": item.get("finalVisibility") or item.get("visibility"),
        "image": item.get("image"),
    }


def _summarize_datum(d: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": d.get("id") or d.get("@id"),
        "label": d.get("label"),
        "type": d.get("type"),
        "value": d.get("value"),
        "position": d.get("position"),
        "item": d.get("item"),
        "collection": d.get("collection"),
        "visibility": d.get("visibility"),
    }


def _err(exc: Exception) -> str:
    return dumps({"error": type(exc).__name__, "message": str(exc)})


def _preview(action: str, method: str, path: str, payload: Any, summary: str, extra: dict | None = None) -> str:
    body: dict[str, Any] = {
        "dry_run": True,
        "applied": False,
        "action": action,
        "method": method,
        "path": path,
        "payload": payload,
        "summary": summary,
        "note": "Preview only. Re-call with dry_run=false to apply.",
    }
    if extra:
        body.update(extra)
    return dumps(body)


def _applied(action: str, result: Any, extra: dict | None = None) -> str:
    body: dict[str, Any] = {"dry_run": False, "applied": True, "action": action, "result": result}
    if extra:
        body.update(extra)
    return dumps(body)


def _put_payload(raw: dict[str, Any], write_keys: list[str], updates: dict[str, Any]) -> dict[str, Any]:
    """Read-modify-write: start from current write-fields, merge updates."""
    payload = {k: raw.get(k) for k in write_keys if raw.get(k) is not None}
    payload.update({k: v for k, v in updates.items() if v is not None})
    return payload


_COLLECTION_WRITE_KEYS = [
    "title", "childrenDisplayConfiguration", "parent", "itemsDisplayConfiguration",
    "color", "itemsDefaultTemplate", "visibility",
]
_ITEM_WRITE_KEYS = ["name", "quantity", "collection", "tags", "relatedItems", "visibility"]
_DATUM_WRITE_KEYS = [
    "item", "collection", "type", "label", "value", "position", "currency", "choiceList", "visibility",
]
_TEMPLATE_WRITE_KEYS = ["name"]
_FIELD_WRITE_KEYS = ["name", "position", "type", "choiceList", "template", "visibility"]
_TAG_WRITE_KEYS = ["label", "description", "category", "visibility"]


# ---------------------------------------------------------------------------
# Safety / discovery reads
# ---------------------------------------------------------------------------


@tool("read")
def health_check() -> str:
    """Check whether the Koillection base URL is reachable and credentials work."""
    try:
        return dumps(get_client().health())
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


@tool("read")
def whoami() -> str:
    """Return which Koillection user the configured JWT belongs to."""
    try:
        return dumps(get_client().whoami())
    except KoillectionError as exc:
        return _err(exc)


@tool("read")
def get_call_history(limit: int = 50) -> str:
    """Return recent MCP call-history records (JSONL log, newest last)."""
    return dumps(history.read_history(limit))


@tool("read")
def list_collections() -> str:
    """List all collections visible to the logged-in user (summaries)."""
    try:
        cols = get_client().get_all_members("/api/collections")
        return dumps([_summarize_collection(c) for c in cols])
    except KoillectionError as exc:
        return _err(exc)


@tool("read")
def get_collection(collection_id: str) -> str:
    """Get one collection by UUID or IRI, including child collection summaries."""
    try:
        client = get_client()
        path = _id_or_iri(collection_id, "collections")
        collection = client.get(path)
        children = client.get_all_members(f"{path}/children")
        return dumps(
            {
                "collection": _summarize_collection(collection),
                "raw": collection,
                "children": [_summarize_collection(c) for c in children],
            }
        )
    except KoillectionError as exc:
        return _err(exc)


@tool("read")
def list_templates() -> str:
    """List item templates."""
    try:
        templates = get_client().get_all_members("/api/templates")
        return dumps(
            [
                {"id": t.get("id") or t.get("@id"), "name": t.get("name"), "createdAt": t.get("createdAt")}
                for t in templates
            ]
        )
    except KoillectionError as exc:
        return _err(exc)


@tool("read")
def list_fields(template_id: str | None = None) -> str:
    """List fields. If template_id is set, only fields for that template."""
    try:
        client = get_client()
        if template_id:
            path = _id_or_iri(template_id, "templates")
            fields = client.get_all_members(f"{path}/fields")
        else:
            fields = client.get_all_members("/api/fields")
        return dumps(
            [
                {
                    "id": f.get("id") or f.get("@id"),
                    "name": f.get("name"),
                    "type": f.get("type"),
                    "position": f.get("position"),
                    "template": f.get("template"),
                    "visibility": f.get("visibility"),
                }
                for f in fields
            ]
        )
    except KoillectionError as exc:
        return _err(exc)


@tool("read")
def list_tags() -> str:
    """List tags."""
    try:
        tags = get_client().get_all_members("/api/tags")
        return dumps(
            [
                {
                    "id": t.get("id") or t.get("@id"),
                    "label": t.get("label"),
                    "description": t.get("description"),
                    "category": t.get("category"),
                    "visibility": t.get("visibility"),
                }
                for t in tags
            ]
        )
    except KoillectionError as exc:
        return _err(exc)


@tool("read")
def search_items(query: str, collection_id: str | None = None, limit: int = 50) -> str:
    """Search items by name substring (client-side; API has no search filter)."""
    try:
        client = get_client()
        if collection_id:
            path = _id_or_iri(collection_id, "collections")
            items = client.get_all_members(f"{path}/items")
        else:
            items = client.get_all_members("/api/items")
        q = query.casefold()
        matches = [
            _summarize_item(item)
            for item in items
            if q in str(item.get("name") or "").casefold()
        ]
        return dumps(
            {
                "query": query,
                "collection_id": collection_id,
                "scanned": len(items),
                "matched": len(matches),
                "items": matches[: max(1, min(limit, 200))],
            }
        )
    except KoillectionError as exc:
        return _err(exc)


@tool("read")
def list_items(collection_id: str) -> str:
    """List items in a collection (summaries)."""
    try:
        client = get_client()
        path = _id_or_iri(collection_id, "collections")
        items = client.get_all_members(f"{path}/items")
        return dumps([_summarize_item(i) for i in items])
    except KoillectionError as exc:
        return _err(exc)


@tool("read")
def get_item(item_id: str) -> str:
    """Get one item by UUID or IRI, including its data fields."""
    try:
        client = get_client()
        path = _id_or_iri(item_id, "items")
        item = client.get(path)
        data = client.get_all_members(f"{path}/data")
        return dumps(
            {
                "item": _summarize_item(item),
                "raw": item,
                "data": [_summarize_datum(d) for d in data],
            }
        )
    except KoillectionError as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# Collections / subcollections CRUD
# ---------------------------------------------------------------------------


@tool("create")
def create_collection(
    title: str,
    parent_id: str | None = None,
    color: str | None = None,
    visibility: str | None = None,
    items_default_template_id: str | None = None,
    dry_run: bool = True,
) -> str:
    """Create a collection, or a subcollection when parent_id is set."""
    payload = _clean(
        {
            "title": title,
            "parent": _iri(parent_id, "collections") if parent_id else None,
            "color": color,
            "visibility": visibility,
            "itemsDefaultTemplate": _iri(items_default_template_id, "templates")
            if items_default_template_id
            else None,
        }
    )
    if dry_run:
        return _preview("create_collection", "POST", "/api/collections", payload,
                        f"Create {'subcollection' if parent_id else 'collection'} '{title}'.")
    try:
        created = get_client().post("/api/collections", payload)
        return _applied("create_collection", _summarize_collection(created))
    except KoillectionError as exc:
        return _err(exc)


@tool("update")
def update_collection(
    collection_id: str,
    title: str | None = None,
    color: str | None = None,
    visibility: str | None = None,
    parent_id: str | None = None,
    items_default_template_id: str | None = None,
    dry_run: bool = True,
) -> str:
    """Update a collection (PUT read-modify-write). Setting parent_id moves it."""
    try:
        client = get_client()
        path = _id_or_iri(collection_id, "collections")
        raw = client.get(path)
        updates = _clean(
            {
                "title": title,
                "color": color,
                "visibility": visibility,
                "parent": _iri(parent_id, "collections") if parent_id else None,
                "itemsDefaultTemplate": _iri(items_default_template_id, "templates")
                if items_default_template_id
                else None,
            }
        )
        if not updates:
            return dumps({"error": "NoChanges", "message": "No updatable fields supplied."})
        payload = _put_payload(raw, _COLLECTION_WRITE_KEYS, updates)
        if dry_run:
            return _preview("update_collection", "PUT", path, payload,
                            f"Update collection '{raw.get('title')}' fields: {sorted(updates)}.")
        updated = client.put(path, payload)
        return _applied("update_collection", _summarize_collection(updated))
    except KoillectionError as exc:
        return _err(exc)


def _collection_tree_stats(client: KoillectionClient, path: str) -> dict[str, Any]:
    """Recursive child-collection and item counts for delete previews."""
    stats = {"collections": 0, "items": 0, "titles": []}
    queue = [path]
    seen: set[str] = set()
    while queue:
        current = queue.pop(0)
        if current in seen:
            continue
        seen.add(current)
        stats["collections"] += 1
        col = client.get(current)
        stats["titles"].append(col.get("title"))
        items = client.get_all_members(f"{current}/items")
        stats["items"] += len(items)
        for child in client.get_all_members(f"{current}/children"):
            cid = child.get("id") or child.get("@id")
            if cid:
                queue.append(_iri(str(cid), "collections"))
    return stats


@tool("delete")
def delete_collection(collection_id: str, confirm_title: str, dry_run: bool = True) -> str:
    """Delete a collection and everything under it. Requires exact confirm_title."""
    try:
        client = get_client()
        path = _id_or_iri(collection_id, "collections")
        raw = client.get(path)
        title = raw.get("title")
        stats = _collection_tree_stats(client, path)
        preview_extra = {"will_delete": stats, "expected_confirm_title": title}
        if dry_run:
            return _preview(
                "delete_collection", "DELETE", path, None,
                f"Delete collection '{title}' plus {stats['collections'] - 1} subcollection(s) "
                f"and {stats['items']} item(s). This cascades and cannot be undone.",
                extra=preview_extra,
            )
        if confirm_title != title:
            return dumps({"error": "ConfirmationMismatch",
                          "message": f"confirm_title must exactly match '{title}'."})
        client.delete(path)
        return _applied("delete_collection", {"id": collection_id, "title": title}, extra={"deleted": stats})
    except KoillectionError as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# Items CRUD
# ---------------------------------------------------------------------------


@tool("create")
def create_item(
    collection_id: str,
    name: str,
    quantity: int | None = None,
    visibility: str | None = None,
    tag_ids: list[str] | None = None,
    data: list[dict[str, Any]] | None = None,
    dry_run: bool = True,
) -> str:
    """Create an item in a collection, then one data field per `data` entry."""
    collection_iri = _iri(collection_id, "collections")
    payload = _clean(
        {
            "name": name,
            "collection": collection_iri,
            "quantity": quantity,
            "visibility": visibility,
            "tags": [_iri(t, "tags") for t in tag_ids] if tag_ids else None,
        }
    )
    data_payloads = [
        _clean(
            {
                "type": entry.get("type"),
                "label": entry.get("label"),
                "value": entry.get("value"),
                "position": entry.get("position"),
                "visibility": entry.get("visibility"),
            }
        )
        for entry in (data or [])
    ]
    if dry_run:
        return _preview(
            "create_item", "POST", "/api/items", {"item": payload, "data": data_payloads},
            f"Create item '{name}' in {collection_iri} with {len(data_payloads)} data field(s).",
        )
    try:
        client = get_client()
        created = client.post("/api/items", payload)
        item_iri = _iri(str(created.get("id") or created.get("@id")), "items")
        created_data = []
        for entry in data_payloads:
            datum = client.post("/api/data", {**entry, "item": item_iri})
            created_data.append(_summarize_datum(datum))
        return _applied("create_item", _summarize_item(created), extra={"data": created_data})
    except KoillectionError as exc:
        return _err(exc)


@tool("update")
def update_item(
    item_id: str,
    name: str | None = None,
    quantity: int | None = None,
    visibility: str | None = None,
    collection_id: str | None = None,
    tag_ids: list[str] | None = None,
    dry_run: bool = True,
) -> str:
    """Update an item (PUT read-modify-write). Setting collection_id moves it."""
    try:
        client = get_client()
        path = _id_or_iri(item_id, "items")
        raw = client.get(path)
        updates = _clean(
            {
                "name": name,
                "quantity": quantity,
                "visibility": visibility,
                "collection": _iri(collection_id, "collections") if collection_id else None,
                "tags": [_iri(t, "tags") for t in tag_ids] if tag_ids is not None else None,
            }
        )
        if not updates:
            return dumps({"error": "NoChanges", "message": "No updatable fields supplied."})
        payload = _put_payload(raw, _ITEM_WRITE_KEYS, updates)
        payload.setdefault("name", raw.get("name"))
        payload.setdefault("collection", raw.get("collection"))
        if dry_run:
            return _preview("update_item", "PUT", path, payload,
                            f"Update item '{raw.get('name')}' fields: {sorted(updates)}.")
        updated = client.put(path, payload)
        return _applied("update_item", _summarize_item(updated))
    except KoillectionError as exc:
        return _err(exc)


@tool("delete")
def delete_item(item_id: str, confirm_name: str, dry_run: bool = True) -> str:
    """Delete an item. Requires confirm_name exactly matching the item name."""
    try:
        client = get_client()
        path = _id_or_iri(item_id, "items")
        raw = client.get(path)
        name = raw.get("name")
        if dry_run:
            return _preview("delete_item", "DELETE", path, None,
                            f"Delete item '{name}'. This cannot be undone.",
                            extra={"expected_confirm_name": name})
        if confirm_name != name:
            return dumps({"error": "ConfirmationMismatch",
                          "message": f"confirm_name must exactly match '{name}'."})
        client.delete(path)
        return _applied("delete_item", {"id": item_id, "name": name})
    except KoillectionError as exc:
        return _err(exc)


@tool("create")
def set_item_data(
    item_id: str,
    label: str,
    type: str,
    value: str,
    position: int | None = None,
    visibility: str | None = None,
    dry_run: bool = True,
) -> str:
    """Create or update one data field on an item, matched by label (upsert)."""
    try:
        client = get_client()
        item_path = _id_or_iri(item_id, "items")
        data = client.get_all_members(f"{item_path}/data")
        existing = next((d for d in data if d.get("label") == label), None)
        if existing:
            datum_path = _iri(str(existing.get("id") or existing.get("@id")), "data")
            updates = _clean({"type": type, "value": value, "position": position, "visibility": visibility})
            payload = _put_payload(existing, _DATUM_WRITE_KEYS, updates)
            payload.setdefault("item", _iri(item_id, "items"))
            if dry_run:
                return _preview("set_item_data", "PUT", datum_path, payload,
                                f"Update data '{label}' on item {item_path}.")
            updated = client.put(datum_path, payload)
            return _applied("set_item_data", _summarize_datum(updated), extra={"mode": "updated"})
        payload = _clean(
            {
                "item": _iri(item_id, "items"),
                "type": type,
                "label": label,
                "value": value,
                "position": position,
                "visibility": visibility,
            }
        )
        if dry_run:
            return _preview("set_item_data", "POST", "/api/data", payload,
                            f"Add data '{label}' to item {item_path}.")
        created = client.post("/api/data", payload)
        return _applied("set_item_data", _summarize_datum(created), extra={"mode": "created"})
    except KoillectionError as exc:
        return _err(exc)


@tool("delete")
def delete_item_data(item_id: str, label: str, dry_run: bool = True) -> str:
    """Delete one data field from an item, matched by label."""
    try:
        client = get_client()
        item_path = _id_or_iri(item_id, "items")
        data = client.get_all_members(f"{item_path}/data")
        existing = next((d for d in data if d.get("label") == label), None)
        if not existing:
            return dumps({"error": "NotFound", "message": f"Item has no data field labelled '{label}'."})
        datum_path = _iri(str(existing.get("id") or existing.get("@id")), "data")
        if dry_run:
            return _preview("delete_item_data", "DELETE", datum_path, None,
                            f"Delete data '{label}' from item {item_path}.")
        client.delete(datum_path)
        return _applied("delete_item_data", {"item": item_path, "label": label})
    except KoillectionError as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# Templates / fields / tags CRUD (supporting structure)
# ---------------------------------------------------------------------------


@tool("create")
def create_template(name: str, dry_run: bool = True) -> str:
    """Create an item template."""
    payload = {"name": name}
    if dry_run:
        return _preview("create_template", "POST", "/api/templates", payload, f"Create template '{name}'.")
    try:
        created = get_client().post("/api/templates", payload)
        return _applied("create_template", {"id": created.get("id") or created.get("@id"), "name": created.get("name")})
    except KoillectionError as exc:
        return _err(exc)


@tool("update")
def update_template(template_id: str, name: str, dry_run: bool = True) -> str:
    """Rename a template (PUT read-modify-write)."""
    try:
        client = get_client()
        path = _id_or_iri(template_id, "templates")
        raw = client.get(path)
        payload = _put_payload(raw, _TEMPLATE_WRITE_KEYS, {"name": name})
        if dry_run:
            return _preview("update_template", "PUT", path, payload, f"Rename template to '{name}'.")
        updated = client.put(path, payload)
        return _applied("update_template", {"id": updated.get("id") or updated.get("@id"), "name": updated.get("name")})
    except KoillectionError as exc:
        return _err(exc)


@tool("delete")
def delete_template(template_id: str, confirm_name: str, dry_run: bool = True) -> str:
    """Delete a template. Requires confirm_name exactly matching."""
    try:
        client = get_client()
        path = _id_or_iri(template_id, "templates")
        raw = client.get(path)
        name = raw.get("name")
        if dry_run:
            return _preview("delete_template", "DELETE", path, None,
                            f"Delete template '{name}'.", extra={"expected_confirm_name": name})
        if confirm_name != name:
            return dumps({"error": "ConfirmationMismatch", "message": f"confirm_name must exactly match '{name}'."})
        client.delete(path)
        return _applied("delete_template", {"id": template_id, "name": name})
    except KoillectionError as exc:
        return _err(exc)


@tool("create")
def create_field(
    template_id: str,
    name: str,
    type: str,
    position: int = 0,
    visibility: str | None = None,
    dry_run: bool = True,
) -> str:
    """Create a field on a template (e.g. type checkbox, text, number, date)."""
    payload = _clean(
        {
            "name": name,
            "position": position,
            "type": type,
            "template": _iri(template_id, "templates"),
            "visibility": visibility,
        }
    )
    if dry_run:
        return _preview("create_field", "POST", "/api/fields", payload,
                        f"Create field '{name}' ({type}) on template {template_id}.")
    try:
        created = get_client().post("/api/fields", payload)
        return _applied(
            "create_field",
            {
                "id": created.get("id") or created.get("@id"),
                "name": created.get("name"),
                "type": created.get("type"),
                "position": created.get("position"),
                "template": created.get("template"),
            },
        )
    except KoillectionError as exc:
        return _err(exc)


@tool("update")
def update_field(
    field_id: str,
    name: str | None = None,
    type: str | None = None,
    position: int | None = None,
    visibility: str | None = None,
    dry_run: bool = True,
) -> str:
    """Update a template field (PUT read-modify-write)."""
    try:
        client = get_client()
        path = _id_or_iri(field_id, "fields")
        raw = client.get(path)
        updates = _clean({"name": name, "type": type, "position": position, "visibility": visibility})
        if not updates:
            return dumps({"error": "NoChanges", "message": "No updatable fields supplied."})
        payload = _put_payload(raw, _FIELD_WRITE_KEYS, updates)
        if dry_run:
            return _preview("update_field", "PUT", path, payload,
                            f"Update field '{raw.get('name')}' fields: {sorted(updates)}.")
        updated = client.put(path, payload)
        return _applied("update_field", {"id": updated.get("id") or updated.get("@id"), "name": updated.get("name")})
    except KoillectionError as exc:
        return _err(exc)


@tool("delete")
def delete_field(field_id: str, confirm_name: str, dry_run: bool = True) -> str:
    """Delete a template field. Requires confirm_name exactly matching."""
    try:
        client = get_client()
        path = _id_or_iri(field_id, "fields")
        raw = client.get(path)
        name = raw.get("name")
        if dry_run:
            return _preview("delete_field", "DELETE", path, None,
                            f"Delete field '{name}'.", extra={"expected_confirm_name": name})
        if confirm_name != name:
            return dumps({"error": "ConfirmationMismatch", "message": f"confirm_name must exactly match '{name}'."})
        client.delete(path)
        return _applied("delete_field", {"id": field_id, "name": name})
    except KoillectionError as exc:
        return _err(exc)


@tool("create")
def create_tag(
    label: str,
    description: str | None = None,
    category_id: str | None = None,
    visibility: str | None = None,
    dry_run: bool = True,
) -> str:
    """Create a tag."""
    payload = _clean(
        {
            "label": label,
            "description": description,
            "category": _iri(category_id, "tag_categories") if category_id else None,
            "visibility": visibility,
        }
    )
    if dry_run:
        return _preview("create_tag", "POST", "/api/tags", payload, f"Create tag '{label}'.")
    try:
        created = get_client().post("/api/tags", payload)
        return _applied(
            "create_tag",
            {"id": created.get("id") or created.get("@id"), "label": created.get("label"),
             "description": created.get("description"), "category": created.get("category")},
        )
    except KoillectionError as exc:
        return _err(exc)


@tool("update")
def update_tag(
    tag_id: str,
    label: str | None = None,
    description: str | None = None,
    category_id: str | None = None,
    visibility: str | None = None,
    dry_run: bool = True,
) -> str:
    """Update a tag (PUT read-modify-write)."""
    try:
        client = get_client()
        path = _id_or_iri(tag_id, "tags")
        raw = client.get(path)
        updates = _clean(
            {
                "label": label,
                "description": description,
                "category": _iri(category_id, "tag_categories") if category_id else None,
                "visibility": visibility,
            }
        )
        if not updates:
            return dumps({"error": "NoChanges", "message": "No updatable fields supplied."})
        payload = _put_payload(raw, _TAG_WRITE_KEYS, updates)
        if dry_run:
            return _preview("update_tag", "PUT", path, payload,
                            f"Update tag '{raw.get('label')}' fields: {sorted(updates)}.")
        updated = client.put(path, payload)
        return _applied("update_tag", {"id": updated.get("id") or updated.get("@id"), "label": updated.get("label")})
    except KoillectionError as exc:
        return _err(exc)


@tool("delete")
def delete_tag(tag_id: str, confirm_name: str, dry_run: bool = True) -> str:
    """Delete a tag. Requires confirm_name exactly matching the tag label."""
    try:
        client = get_client()
        path = _id_or_iri(tag_id, "tags")
        raw = client.get(path)
        label = raw.get("label")
        if dry_run:
            return _preview("delete_tag", "DELETE", path, None,
                            f"Delete tag '{label}'.", extra={"expected_confirm_name": label})
        if confirm_name != label:
            return dumps({"error": "ConfirmationMismatch", "message": f"confirm_name must exactly match '{label}'."})
        client.delete(path)
        return _applied("delete_tag", {"id": tag_id, "label": label})
    except KoillectionError as exc:
        return _err(exc)


def main() -> None:
    mcp.run(transport="stdio")
