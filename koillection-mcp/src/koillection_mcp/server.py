"""Koillection MCP server — read tools + CRUD with dry-run-by-default writes."""

from __future__ import annotations

import functools
import hashlib
import inspect
import mimetypes
import time
from pathlib import Path
from typing import Annotated, Any, Callable

from mcp.server.mcpserver import MCPServer
from pydantic import Field

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
        "[create], [update], [delete]. Read-only Resources mirror discovery data "
        "(koillection://collections, /templates, /tags, /call-history). Prompts "
        "setup_collection, populate_from_list, review_collection, and "
        "have_vs_want_summary drive the standard workflows."
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


def _id_or_iri(value: Annotated[str, Field(description="Value as a string. Checkbox uses '0' or '1'; dates use YYYY-MM-DD; lists use a JSON string.")], resource: str) -> str:
    """Accept a UUID, IRI path, or URL; return an API path."""
    value = value.strip()
    if value.startswith("/api/"):
        return value
    if value.startswith("http"):
        return value
    return f"/api/{resource}/{value}"


def _iri(value: Annotated[str, Field(description="Value as a string. Checkbox uses '0' or '1'; dates use YYYY-MM-DD; lists use a JSON string.")], resource: str) -> str:
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
        "relatedItems": item.get("relatedItems"),
    }


def _summarize_datum(d: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": d.get("id") or d.get("@id"),
        "label": d.get("label"),
        "type": d.get("type"),
        "value": d.get("value"),
        "file": d.get("file"),
        "image": d.get("image"),
        "imageSmallThumbnail": d.get("imageSmallThumbnail"),
        "imageLargeThumbnail": d.get("imageLargeThumbnail"),
        "originalFilename": d.get("originalFilename"),
        "position": d.get("position"),
        "item": d.get("item"),
        "collection": d.get("collection"),
        "visibility": d.get("visibility"),
    }


def _err(exc: Exception) -> str:
    return dumps({"error": type(exc).__name__, "message": str(exc)})


_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".webp"}


def _image_file_info(image_path: str) -> dict[str, Any]:
    """Validate a local image file and return metadata only (never bytes)."""
    path = Path(image_path).expanduser()
    if path.suffix.lower() not in _IMAGE_SUFFIXES:
        raise KoillectionError(
            f"Unsupported image extension '{path.suffix}'. Use JPG, PNG, GIF, or WebP."
        )
    if not path.is_file():
        raise KoillectionError(f"Image file not found: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return {
        "path": str(path),
        "filename": path.name,
        "size_bytes": path.stat().st_size,
        "mime_type": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
        "sha256": digest.hexdigest(),
    }


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
    """Check whether the Koillection base URL is reachable and credentials work.

    Args:
    """
    try:
        return dumps(get_client().health())
    except Exception as exc:  # noqa: BLE001
        return _err(exc)


@tool("read")
def whoami() -> str:
    """Return which Koillection user the configured JWT belongs to.

    Args:
    """
    try:
        return dumps(get_client().whoami())
    except KoillectionError as exc:
        return _err(exc)


@tool("read")
def get_call_history(limit: Annotated[int, Field(description='Maximum number of entries to return.')] = 50) -> str:
    """Return recent MCP call-history records (JSONL log, newest last).

    Args:
        limit: Maximum number of entries to return.
    """
    return dumps(history.read_history(limit))


@tool("read")
def list_collections() -> str:
    """List all collections visible to the logged-in user (summaries).

    Args:
    """
    try:
        cols = get_client().get_all_members("/api/collections")
        return dumps([_summarize_collection(c) for c in cols])
    except KoillectionError as exc:
        return _err(exc)


@tool("read")
def get_collection(collection_id: Annotated[str, Field(description='Collection UUID or IRI like /api/collections/<uuid>.')]) -> str:
    """Get one collection by UUID or IRI, including child collection summaries.

    Args:
        collection_id: Collection UUID or IRI like /api/collections/<uuid>.
    """
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


def _summarize_field(f: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": f.get("id") or f.get("@id"),
        "name": f.get("name"),
        "type": f.get("type"),
        "position": f.get("position"),
        "template": f.get("template"),
        "visibility": f.get("visibility"),
        "choiceList": f.get("choiceList"),
    }


def _template_with_fields(client: KoillectionClient, template_path: str) -> dict[str, Any]:
    template = client.get(template_path)
    fields = client.get_all_members(f"{template_path}/fields")
    summarized = [_summarize_field(f) for f in fields]
    summarized.sort(key=lambda f: (f.get("position") if f.get("position") is not None else 0, str(f.get("name"))))
    return {
        "template": {
            "id": template.get("id") or template.get("@id"),
            "name": template.get("name"),
            "createdAt": template.get("createdAt"),
        },
        "fields": summarized,
    }


@tool("read")
def get_template(template_id: Annotated[str, Field(description="Template UUID or IRI like /api/templates/<uuid>.")]) -> str:
    """Get one template with its fields sorted by position.

    Args:
        template_id: Template UUID or IRI like /api/templates/<uuid>.
    """
    try:
        client = get_client()
        path = _id_or_iri(template_id, "templates")
        return dumps(_template_with_fields(client, path))
    except KoillectionError as exc:
        return _err(exc)


@tool("read")
def get_collection_template(collection_id: Annotated[str, Field(description="Collection UUID or IRI like /api/collections/<uuid>.")]) -> str:
    """Resolve a collection's own default items template and its fields.

    Koillection has no parent inheritance: only the collection's own
    itemsDefaultTemplate is returned, never a parent collection's.

    Args:
        collection_id: Collection UUID or IRI like /api/collections/<uuid>.
    """
    try:
        client = get_client()
        path = _id_or_iri(collection_id, "collections")
        collection = client.get(path)
        template_iri = collection.get("itemsDefaultTemplate")
        if not template_iri:
            return dumps(
                {
                    "collection": _summarize_collection(collection),
                    "template": None,
                    "fields": [],
                    "note": "This collection has no default items template. Koillection does not inherit one from a parent collection.",
                }
            )
        resolved = _template_with_fields(client, _iri(str(template_iri), "templates"))
        return dumps(
            {
                "collection": _summarize_collection(collection),
                "template": resolved["template"],
                "fields": resolved["fields"],
            }
        )
    except KoillectionError as exc:
        return _err(exc)


@tool("read")
def list_templates() -> str:
    """List item templates.

    Args:
    """
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
def list_fields(template_id: Annotated[str | None, Field(description='Template UUID or IRI like /api/templates/<uuid>.')] = None) -> str:
    """List fields. If template_id is set, only fields for that template.

    Args:
        template_id: Template UUID or IRI like /api/templates/<uuid>.
    """
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
    """List tags.

    Args:
    """
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
def search_items(query: Annotated[str, Field(description='Case-insensitive substring matched against item names.')], collection_id: Annotated[str | None, Field(description='Collection UUID or IRI like /api/collections/<uuid>.')] = None, limit: Annotated[int, Field(description='Maximum number of entries to return.')] = 50) -> str:
    """Search items by name substring (client-side; API has no search filter).

    Args:
        query: Case-insensitive substring matched against item names.
        collection_id: Collection UUID or IRI like /api/collections/<uuid>.
        limit: Maximum number of entries to return.
    """
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
def list_items(collection_id: Annotated[str, Field(description='Collection UUID or IRI like /api/collections/<uuid>.')]) -> str:
    """List items in a collection (summaries).

    Args:
        collection_id: Collection UUID or IRI like /api/collections/<uuid>.
    """
    try:
        client = get_client()
        path = _id_or_iri(collection_id, "collections")
        items = client.get_all_members(f"{path}/items")
        return dumps([_summarize_item(i) for i in items])
    except KoillectionError as exc:
        return _err(exc)


@tool("read")
def get_item(item_id: Annotated[str, Field(description='Item UUID or IRI like /api/items/<uuid>.')]) -> str:
    """Get one item by UUID or IRI, including its data fields.

    Args:
        item_id: Item UUID or IRI like /api/items/<uuid>.
    """
    try:
        client = get_client()
        path = _id_or_iri(item_id, "items")
        item = client.get(path)
        data = client.get_all_members(f"{path}/data")
        related = client.get_all_members(f"{path}/related_items")
        item_summary = _summarize_item(item)
        item_summary["relatedItems"] = [
            str(r.get("id") or r.get("@id")) for r in related if isinstance(r, dict)
        ]
        return dumps(
            {
                "item": item_summary,
                "raw": item,
                "related_items": [_summarize_item(r) for r in related if isinstance(r, dict)],
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
    title: Annotated[str, Field(description='Collection title.')],
    parent_id: Annotated[str | None, Field(description='Parent collection UUID or IRI. Set to create a subcollection under it, or to move a collection.')] = None,
    color: Annotated[str | None, Field(description="Hex color without '#', e.g. FFCC00.")] = None,
    visibility: Annotated[str | None, Field(description='Visibility value as used by Koillection, e.g. public or private.')] = None,
    items_default_template_id: Annotated[str | None, Field(description='Template UUID or IRI like /api/templates/<uuid>.')] = None,
    dry_run: Annotated[bool, Field(description='Preview only when true (default). Pass false only after the preview was shown and the user explicitly confirmed.')] = True,
) -> str:
    """Create a collection, or a subcollection when parent_id is set.

    Args:
        title: Collection title.
        parent_id: Parent collection UUID or IRI. Set to create a subcollection under it, or to move a collection.
        color: Hex color without '#', e.g. FFCC00.
        visibility: Visibility value as used by Koillection, e.g. public or private.
        items_default_template_id: Template UUID or IRI to set as the collection's default items template.
        dry_run: Preview only when true (default). Pass false only after the preview was shown and the user explicitly confirmed.
    """
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
    collection_id: Annotated[str, Field(description='Collection UUID or IRI like /api/collections/<uuid>.')],
    title: Annotated[str | None, Field(description='Collection title.')] = None,
    color: Annotated[str | None, Field(description="Hex color without '#', e.g. FFCC00.")] = None,
    visibility: Annotated[str | None, Field(description='Visibility value as used by Koillection, e.g. public or private.')] = None,
    parent_id: Annotated[str | None, Field(description='Parent collection UUID or IRI. Set to create a subcollection under it, or to move a collection.')] = None,
    items_default_template_id: Annotated[str | None, Field(description='Template UUID or IRI like /api/templates/<uuid>.')] = None,
    dry_run: Annotated[bool, Field(description='Preview only when true (default). Pass false only after the preview was shown and the user explicitly confirmed.')] = True,
) -> str:
    """Update a collection (PUT read-modify-write). Setting parent_id moves it.

    Args:
        collection_id: Collection UUID or IRI like /api/collections/<uuid>.
        title: Collection title.
        color: Hex color without '#', e.g. FFCC00.
        visibility: Visibility value as used by Koillection, e.g. public or private.
        parent_id: Parent collection UUID or IRI. Set to create a subcollection under it, or to move a collection.
        items_default_template_id: Template UUID or IRI to set as the collection's default items template.
        dry_run: Preview only when true (default). Pass false only after the preview was shown and the user explicitly confirmed.
    """
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
def delete_collection(collection_id: Annotated[str, Field(description='Collection UUID or IRI like /api/collections/<uuid>.')], confirm_title: Annotated[str, Field(description='Must exactly match the current title, or the delete is refused.')], dry_run: Annotated[bool, Field(description='Preview only when true (default). Pass false only after the preview was shown and the user explicitly confirmed.')] = True) -> str:
    """Delete a collection and everything under it. Requires exact confirm_title.

    Args:
        collection_id: Collection UUID or IRI like /api/collections/<uuid>.
        confirm_title: Must exactly match the current title, or the delete is refused.
        dry_run: Preview only when true (default). Pass false only after the preview was shown and the user explicitly confirmed.
    """
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
    collection_id: Annotated[str, Field(description='Collection UUID or IRI like /api/collections/<uuid>.')],
    name: Annotated[str, Field(description='Display name.')],
    quantity: Annotated[int | None, Field(description='How many of this item are owned.')] = None,
    visibility: Annotated[str | None, Field(description='Visibility value as used by Koillection, e.g. public or private.')] = None,
    tag_ids: Annotated[list[str] | None, Field(description='Tag UUIDs or IRIs to attach.')] = None,
    data: Annotated[list[dict[str, Any]] | None, Field(description='List of {label, type, value, position?} entries; one /api/data record is created per entry.')] = None,
    dry_run: Annotated[bool, Field(description='Preview only when true (default). Pass false only after the preview was shown and the user explicitly confirmed.')] = True,
) -> str:
    """Create an item in a collection, then one data field per `data` entry.

    Args:
        collection_id: Collection UUID or IRI like /api/collections/<uuid>.
        name: Display name.
        quantity: How many of this item are owned.
        visibility: Visibility value as used by Koillection, e.g. public or private.
        tag_ids: Tag UUIDs or IRIs to attach.
        data: List of {label, type, value, position?} entries; one /api/data record is created per entry.
        dry_run: Preview only when true (default). Pass false only after the preview was shown and the user explicitly confirmed.
    """
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
    item_id: Annotated[str, Field(description='Item UUID or IRI like /api/items/<uuid>.')],
    name: Annotated[str | None, Field(description='Display name.')] = None,
    quantity: Annotated[int | None, Field(description='How many of this item are owned.')] = None,
    visibility: Annotated[str | None, Field(description='Visibility value as used by Koillection, e.g. public or private.')] = None,
    collection_id: Annotated[str | None, Field(description='Collection UUID or IRI like /api/collections/<uuid>.')] = None,
    tag_ids: Annotated[list[str] | None, Field(description='Tag UUIDs or IRIs to attach.')] = None,
    related_item_ids: Annotated[list[str] | None, Field(description='Related item UUIDs or IRIs to set on this item; replaces the current related-items list.')] = None,
    dry_run: Annotated[bool, Field(description='Preview only when true (default). Pass false only after the preview was shown and the user explicitly confirmed.')] = True,
) -> str:
    """Update an item (PUT read-modify-write). Setting collection_id moves it.

    Args:
        item_id: Item UUID or IRI like /api/items/<uuid>.
        name: Display name.
        quantity: How many of this item are owned.
        visibility: Visibility value as used by Koillection, e.g. public or private.
        collection_id: Collection UUID or IRI like /api/collections/<uuid>.
        tag_ids: Tag UUIDs or IRIs to attach.
        related_item_ids: Related item UUIDs or IRIs to set; replaces the current related-items list.
        dry_run: Preview only when true (default). Pass false only after the preview was shown and the user explicitly confirmed.
    """
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
                "relatedItems": [_iri(t, "items") for t in related_item_ids]
                if related_item_ids is not None
                else None,
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
def delete_item(item_id: Annotated[str, Field(description='Item UUID or IRI like /api/items/<uuid>.')], confirm_name: Annotated[str, Field(description='Must exactly match the current name/label, or the delete is refused.')], dry_run: Annotated[bool, Field(description='Preview only when true (default). Pass false only after the preview was shown and the user explicitly confirmed.')] = True) -> str:
    """Delete an item. Requires confirm_name exactly matching the item name.

    Args:
        item_id: Item UUID or IRI like /api/items/<uuid>.
        confirm_name: Must exactly match the current name/label, or the delete is refused.
        dry_run: Preview only when true (default). Pass false only after the preview was shown and the user explicitly confirmed.
    """
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
    item_id: Annotated[str, Field(description='Item UUID or IRI like /api/items/<uuid>.')],
    label: Annotated[str, Field(description='Data/tag label. For item data this is the field label, matched exactly.')],
    type: Annotated[str, Field(description='Field/data type, e.g. text, textarea, checkbox, number, date, rating, country, list.')],
    value: Annotated[str, Field(description="Value as a string. Checkbox uses '0' or '1'; dates use YYYY-MM-DD; lists use a JSON string.")],
    position: Annotated[int | None, Field(description='Sort position within the template/item (lower first).')] = None,
    visibility: Annotated[str | None, Field(description='Visibility value as used by Koillection, e.g. public or private.')] = None,
    dry_run: Annotated[bool, Field(description='Preview only when true (default). Pass false only after the preview was shown and the user explicitly confirmed.')] = True,
) -> str:
    """Create or update one data field on an item, matched by label (upsert).

    Args:
        item_id: Item UUID or IRI like /api/items/<uuid>.
        label: Data/tag label. For item data this is the field label, matched exactly.
        type: Field/data type, e.g. text, textarea, checkbox, number, date, rating, country, list.
        value: Value as a string. Checkbox uses '0' or '1'; dates use YYYY-MM-DD; lists use a JSON string.
        position: Sort position within the template/item (lower first).
        visibility: Visibility value as used by Koillection, e.g. public or private.
        dry_run: Preview only when true (default). Pass false only after the preview was shown and the user explicitly confirmed.
    """
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
def delete_item_data(item_id: Annotated[str, Field(description='Item UUID or IRI like /api/items/<uuid>.')], label: Annotated[str, Field(description='Data/tag label. For item data this is the field label, matched exactly.')], dry_run: Annotated[bool, Field(description='Preview only when true (default). Pass false only after the preview was shown and the user explicitly confirmed.')] = True) -> str:
    """Delete one data field from an item, matched by label.

    Args:
        item_id: Item UUID or IRI like /api/items/<uuid>.
        label: Data/tag label. For item data this is the field label, matched exactly.
        dry_run: Preview only when true (default). Pass false only after the preview was shown and the user explicitly confirmed.
    """
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


@tool("create")
def upload_item_image(
    item_id: Annotated[str, Field(description='Item UUID or IRI like /api/items/<uuid>.')],
    image_path: Annotated[str, Field(description='Absolute or relative path to a local JPG, PNG, GIF, or WebP file on the machine running this MCP server.')],
    dry_run: Annotated[bool, Field(description='Preview only when true (default). Pass false only after the preview was shown and the user explicitly confirmed.')] = True,
) -> str:
    """Upload a local image file as an item's main image.

    Args:
        item_id: Item UUID or IRI like /api/items/<uuid>.
        image_path: Path to a local JPG, PNG, GIF, or WebP file.
        dry_run: Preview only when true (default). Pass false only after the preview was shown and the user explicitly confirmed.

    Returns:
        Preview or applied result with file metadata; image bytes are never returned or logged.
    """
    try:
        client = get_client()
        item_path = _id_or_iri(item_id, "items")
        item = client.get(item_path)
        file_info = _image_file_info(image_path)
        target_path = f"{item_path}/image"
        if dry_run:
            return _preview(
                "upload_item_image", "POST", target_path,
                {"multipart_field": "file", "file": file_info},
                f"Upload '{file_info['filename']}' as the main image of '{item.get('name')}'.",
            )
        uploaded = client.post_multipart(target_path, str(file_info["path"]))
        result = _summarize_item(uploaded) if isinstance(uploaded, dict) else _summarize_item(item)
        return _applied("upload_item_image", result, extra={"file": file_info})
    except KoillectionError as exc:
        return _err(exc)


@tool("create")
def upload_item_data_image(
    item_id: Annotated[str, Field(description='Item UUID or IRI like /api/items/<uuid>.')],
    label: Annotated[str, Field(description="Image data label, matched exactly, e.g. 'Front Image'.")],
    image_path: Annotated[str, Field(description='Absolute or relative path to a local JPG, PNG, GIF, or WebP file on the machine running this MCP server.')],
    dry_run: Annotated[bool, Field(description='Preview only when true (default). Pass false only after the preview was shown and the user explicitly confirmed.')] = True,
) -> str:
    """Upload a local image into an item's image data field, creating it by label if needed.

    Args:
        item_id: Item UUID or IRI like /api/items/<uuid>.
        label: Image data label, matched exactly, e.g. 'Front Image'.
        image_path: Path to a local JPG, PNG, GIF, or WebP file.
        dry_run: Preview only when true (default). Pass false only after the preview was shown and the user explicitly confirmed.

    Returns:
        Preview or applied result with the datum summary and file metadata; image bytes are never returned or logged.
    """
    try:
        client = get_client()
        item_path = _id_or_iri(item_id, "items")
        client.get(item_path)
        file_info = _image_file_info(image_path)
        data = client.get_all_members(f"{item_path}/data")
        existing = next((d for d in data if d.get("label") == label), None)
        if existing and existing.get("type") != "image":
            return dumps(
                {
                    "error": "ValidationError",
                    "message": f"Item already has a non-image data field labelled '{label}' ({existing.get('type')}).",
                }
            )
        if existing:
            datum_path = _iri(str(existing.get("id") or existing.get("@id")), "data")
            mode = "existing datum"
        else:
            datum_path = "/api/data (new image datum), then /api/data/<id>/image"
            mode = "new datum"
        if dry_run:
            return _preview(
                "upload_item_data_image", "POST", datum_path,
                {"label": label, "type": "image", "multipart_field": "fileImage", "file": file_info},
                f"Upload '{file_info['filename']}' to image field '{label}' ({mode}) on item {item_path}.",
            )
        if existing:
            datum_id = str(existing.get("id") or existing.get("@id"))
        else:
            created = client.post(
                "/api/data",
                {"item": _iri(item_id, "items"), "type": "image", "label": label, "value": None},
            )
            datum_id = str(created.get("id") or created.get("@id"))
            datum_path = _iri(datum_id, "data")
        client.post_multipart(f"{datum_path}/image", str(file_info["path"]), field_name="fileImage")
        datum = client.get(datum_path)
        return _applied(
            "upload_item_data_image",
            _summarize_datum(datum),
            extra={"file": file_info, "mode": mode},
        )
    except KoillectionError as exc:
        return _err(exc)


# ---------------------------------------------------------------------------
# Templates / fields / tags CRUD (supporting structure)
# ---------------------------------------------------------------------------


_ALLOWED_FIELD_TYPES = {
    "text", "textarea", "number", "country", "date", "rating", "list",
    "choice-list", "checkbox", "link", "image", "sign", "file", "video",
}


@tool("create")
def copy_template(
    source_template_id: Annotated[str, Field(description="Source template UUID or IRI to copy fields from.")],
    new_name: Annotated[str, Field(description="Name for the new template.")],
    drop_fields: Annotated[list[str] | None, Field(description="Source field names to omit from the copy.")] = None,
    rename_fields: Annotated[dict[str, str] | None, Field(description="Map of source field name -> new name.")] = None,
    type_overrides: Annotated[dict[str, str] | None, Field(description="Map of source field name -> new Koillection field type.")] = None,
    add_fields: Annotated[list[dict[str, Any]] | None, Field(description="Extra fields to add: {name, type, position?, visibility?}.")] = None,
    dry_run: Annotated[bool, Field(description="Preview only when true (default). Pass false only after the preview was shown and the user explicitly confirmed.")] = True,
) -> str:
    """Copy a template's fields into a new template, with modifications.

    Args:
        source_template_id: Source template UUID or IRI to copy fields from.
        new_name: Name for the new template.
        drop_fields: Source field names to omit from the copy.
        rename_fields: Map of source field name -> new name.
        type_overrides: Map of source field name -> new Koillection field type.
        add_fields: Extra fields to add: {name, type, position?, visibility?}.
        dry_run: Preview only when true (default). Pass false only after the preview was shown and the user explicitly confirmed.
    """
    drop_fields = drop_fields or []
    rename_fields = rename_fields or {}
    type_overrides = type_overrides or {}
    add_fields = add_fields or []
    try:
        client = get_client()
        source_path = _id_or_iri(source_template_id, "templates")
        source = _template_with_fields(client, source_path)
        source_fields = source["fields"]
        by_name = {f["name"]: f for f in source_fields}

        errors: list[str] = []
        for label, names in (("drop_fields", drop_fields), ("rename_fields", list(rename_fields)), ("type_overrides", list(type_overrides))):
            for field_name in names:
                if field_name not in by_name:
                    errors.append(f"{label}: no source field named '{field_name}'")
        for field_name, new_type in type_overrides.items():
            if new_type not in _ALLOWED_FIELD_TYPES:
                errors.append(f"type_overrides: '{new_type}' is not a Koillection field type")

        result_fields: list[dict[str, Any]] = []
        dropped: list[str] = []
        for f in source_fields:
            fname = f["name"]
            if fname in drop_fields:
                dropped.append(fname)
                continue
            new_field_name = rename_fields.get(fname, fname)
            new_type = type_overrides.get(fname, f["type"])
            change = "kept"
            if new_field_name != fname and new_type != f["type"]:
                change = "renamed+retyped"
            elif new_field_name != fname:
                change = "renamed"
            elif new_type != f["type"]:
                change = "retyped"
            result_fields.append(
                {
                    "source_name": fname,
                    "name": new_field_name,
                    "type": new_type,
                    "position": f.get("position"),
                    "visibility": f.get("visibility"),
                    "choiceList": f.get("choiceList"),
                    "change": change,
                }
            )
        next_position = max([f["position"] for f in result_fields if f.get("position") is not None], default=-1) + 1
        for entry in add_fields:
            entry_name = entry.get("name")
            entry_type = entry.get("type")
            if not entry_name or not entry_type:
                errors.append(f"add_fields: each entry needs name and type, got {entry}")
                continue
            if entry_type not in _ALLOWED_FIELD_TYPES:
                errors.append(f"add_fields: '{entry_type}' is not a Koillection field type")
            position = entry.get("position")
            if position is None:
                position = next_position
                next_position += 1
            result_fields.append(
                {
                    "source_name": None,
                    "name": entry_name,
                    "type": entry_type,
                    "position": position,
                    "visibility": entry.get("visibility"),
                    "choiceList": entry.get("choiceList"),
                    "change": "added",
                }
            )
        seen_names: set[str] = set()
        for f in result_fields:
            if f["name"] in seen_names:
                errors.append(f"duplicate resulting field name '{f['name']}'")
            seen_names.add(f["name"])
        if errors:
            return dumps({"error": "ValidationError", "message": "; ".join(errors)})

        result_fields.sort(key=lambda f: (f["position"] if f.get("position") is not None else 0, str(f["name"])))
        field_payloads = [
            _clean(
                {
                    "name": f["name"],
                    "position": f["position"],
                    "type": f["type"],
                    "visibility": f.get("visibility"),
                    "choiceList": f.get("choiceList"),
                }
            )
            for f in result_fields
        ]
        if dry_run:
            return _preview(
                "copy_template",
                "POST",
                "/api/templates + /api/fields",
                {"template": {"name": new_name}, "fields": field_payloads},
                f"Copy template '{source['template'].get('name')}' to '{new_name}' with {len(result_fields)} field(s).",
                extra={"source_fields": source_fields, "result_fields": result_fields, "dropped": dropped},
            )
        created_template = client.post("/api/templates", {"name": new_name})
        new_template_iri = _iri(str(created_template.get("id") or created_template.get("@id")), "templates")
        created_fields: list[dict[str, Any]] = []
        try:
            for payload in field_payloads:
                datum = client.post("/api/fields", {**payload, "template": new_template_iri})
                created_fields.append(_summarize_field(datum))
        except KoillectionError as exc:
            return dumps(
                {
                    "error": type(exc).__name__,
                    "message": str(exc),
                    "partial_failure": True,
                    "created_template": {"id": created_template.get("id") or created_template.get("@id"), "name": new_name},
                    "created_fields": created_fields,
                    "note": "Template copy partially applied. Finish manually or delete_template with confirmation.",
                }
            )
        return _applied(
            "copy_template",
            {"id": created_template.get("id") or created_template.get("@id"), "name": new_name},
            extra={"fields": created_fields, "source_template": source["template"]},
        )
    except KoillectionError as exc:
        return _err(exc)


@tool("create")
def create_template(name: Annotated[str, Field(description='Display name.')], dry_run: Annotated[bool, Field(description='Preview only when true (default). Pass false only after the preview was shown and the user explicitly confirmed.')] = True) -> str:
    """Create an item template.

    Args:
        name: Display name.
        dry_run: Preview only when true (default). Pass false only after the preview was shown and the user explicitly confirmed.
    """
    payload = {"name": name}
    if dry_run:
        return _preview("create_template", "POST", "/api/templates", payload, f"Create template '{name}'.")
    try:
        created = get_client().post("/api/templates", payload)
        return _applied("create_template", {"id": created.get("id") or created.get("@id"), "name": created.get("name")})
    except KoillectionError as exc:
        return _err(exc)


@tool("update")
def update_template(template_id: Annotated[str, Field(description='Template UUID or IRI like /api/templates/<uuid>.')], name: Annotated[str, Field(description='Display name.')], dry_run: Annotated[bool, Field(description='Preview only when true (default). Pass false only after the preview was shown and the user explicitly confirmed.')] = True) -> str:
    """Rename a template (PUT read-modify-write).

    Args:
        template_id: Template UUID or IRI like /api/templates/<uuid>.
        name: Display name.
        dry_run: Preview only when true (default). Pass false only after the preview was shown and the user explicitly confirmed.
    """
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
def delete_template(template_id: Annotated[str, Field(description='Template UUID or IRI like /api/templates/<uuid>.')], confirm_name: Annotated[str, Field(description='Must exactly match the current name/label, or the delete is refused.')], dry_run: Annotated[bool, Field(description='Preview only when true (default). Pass false only after the preview was shown and the user explicitly confirmed.')] = True) -> str:
    """Delete a template. Requires confirm_name exactly matching.

    Args:
        template_id: Template UUID or IRI like /api/templates/<uuid>.
        confirm_name: Must exactly match the current name/label, or the delete is refused.
        dry_run: Preview only when true (default). Pass false only after the preview was shown and the user explicitly confirmed.
    """
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
    template_id: Annotated[str, Field(description='Template UUID or IRI like /api/templates/<uuid>.')],
    name: Annotated[str, Field(description='Display name.')],
    type: Annotated[str, Field(description='Field/data type, e.g. text, textarea, checkbox, number, date, rating, country, list.')],
    position: Annotated[int, Field(description='Sort position within the template/item (lower first).')] = 0,
    visibility: Annotated[str | None, Field(description='Visibility value as used by Koillection, e.g. public or private.')] = None,
    dry_run: Annotated[bool, Field(description='Preview only when true (default). Pass false only after the preview was shown and the user explicitly confirmed.')] = True,
) -> str:
    """Create a field on a template (e.g. type checkbox, text, number, date).

    Args:
        template_id: Template UUID or IRI like /api/templates/<uuid>.
        name: Display name.
        type: Field/data type, e.g. text, textarea, checkbox, number, date, rating, country, list.
        position: Sort position within the template/item (lower first).
        visibility: Visibility value as used by Koillection, e.g. public or private.
        dry_run: Preview only when true (default). Pass false only after the preview was shown and the user explicitly confirmed.
    """
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
    field_id: Annotated[str, Field(description='Field UUID or IRI like /api/fields/<uuid>.')],
    name: Annotated[str | None, Field(description='Display name.')] = None,
    type: Annotated[str | None, Field(description='Field/data type, e.g. text, textarea, checkbox, number, date, rating, country, list.')] = None,
    position: Annotated[int | None, Field(description='Sort position within the template/item (lower first).')] = None,
    visibility: Annotated[str | None, Field(description='Visibility value as used by Koillection, e.g. public or private.')] = None,
    dry_run: Annotated[bool, Field(description='Preview only when true (default). Pass false only after the preview was shown and the user explicitly confirmed.')] = True,
) -> str:
    """Update a template field (PUT read-modify-write).

    Args:
        field_id: Field UUID or IRI like /api/fields/<uuid>.
        name: Display name.
        type: Field/data type, e.g. text, textarea, checkbox, number, date, rating, country, list.
        position: Sort position within the template/item (lower first).
        visibility: Visibility value as used by Koillection, e.g. public or private.
        dry_run: Preview only when true (default). Pass false only after the preview was shown and the user explicitly confirmed.
    """
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
def delete_field(field_id: Annotated[str, Field(description='Field UUID or IRI like /api/fields/<uuid>.')], confirm_name: Annotated[str, Field(description='Must exactly match the current name/label, or the delete is refused.')], dry_run: Annotated[bool, Field(description='Preview only when true (default). Pass false only after the preview was shown and the user explicitly confirmed.')] = True) -> str:
    """Delete a template field. Requires confirm_name exactly matching.

    Args:
        field_id: Field UUID or IRI like /api/fields/<uuid>.
        confirm_name: Must exactly match the current name/label, or the delete is refused.
        dry_run: Preview only when true (default). Pass false only after the preview was shown and the user explicitly confirmed.
    """
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
    label: Annotated[str, Field(description='Data/tag label. For item data this is the field label, matched exactly.')],
    description: Annotated[str | None, Field(description='Free-text description.')] = None,
    category_id: Annotated[str | None, Field(description='Tag category UUID or IRI like /api/tag_categories/<uuid>.')] = None,
    visibility: Annotated[str | None, Field(description='Visibility value as used by Koillection, e.g. public or private.')] = None,
    dry_run: Annotated[bool, Field(description='Preview only when true (default). Pass false only after the preview was shown and the user explicitly confirmed.')] = True,
) -> str:
    """Create a tag.

    Args:
        label: Data/tag label. For item data this is the field label, matched exactly.
        description: Free-text description.
        category_id: Tag category UUID or IRI like /api/tag_categories/<uuid>.
        visibility: Visibility value as used by Koillection, e.g. public or private.
        dry_run: Preview only when true (default). Pass false only after the preview was shown and the user explicitly confirmed.
    """
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
    tag_id: Annotated[str, Field(description='Tag UUID or IRI like /api/tags/<uuid>.')],
    label: Annotated[str | None, Field(description='Data/tag label. For item data this is the field label, matched exactly.')] = None,
    description: Annotated[str | None, Field(description='Free-text description.')] = None,
    category_id: Annotated[str | None, Field(description='Tag category UUID or IRI like /api/tag_categories/<uuid>.')] = None,
    visibility: Annotated[str | None, Field(description='Visibility value as used by Koillection, e.g. public or private.')] = None,
    dry_run: Annotated[bool, Field(description='Preview only when true (default). Pass false only after the preview was shown and the user explicitly confirmed.')] = True,
) -> str:
    """Update a tag (PUT read-modify-write).

    Args:
        tag_id: Tag UUID or IRI like /api/tags/<uuid>.
        label: Data/tag label. For item data this is the field label, matched exactly.
        description: Free-text description.
        category_id: Tag category UUID or IRI like /api/tag_categories/<uuid>.
        visibility: Visibility value as used by Koillection, e.g. public or private.
        dry_run: Preview only when true (default). Pass false only after the preview was shown and the user explicitly confirmed.
    """
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
def delete_tag(tag_id: Annotated[str, Field(description='Tag UUID or IRI like /api/tags/<uuid>.')], confirm_name: Annotated[str, Field(description='Must exactly match the current name/label, or the delete is refused.')], dry_run: Annotated[bool, Field(description='Preview only when true (default). Pass false only after the preview was shown and the user explicitly confirmed.')] = True) -> str:
    """Delete a tag. Requires confirm_name exactly matching the tag label.

    Args:
        tag_id: Tag UUID or IRI like /api/tags/<uuid>.
        confirm_name: Must exactly match the current name/label, or the delete is refused.
        dry_run: Preview only when true (default). Pass false only after the preview was shown and the user explicitly confirmed.
    """
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


# ---------------------------------------------------------------------------
# Resources (read-only discovery)
# ---------------------------------------------------------------------------


def _resource(name: str, uri: str, description: str) -> Callable:
    """Register a JSON resource and log reads to the call history."""

    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            bound = inspect.signature(fn).bind_partial(*args, **kwargs)
            started = time.perf_counter()
            result: Any = None
            error: str | None = None
            try:
                result = fn(*args, **kwargs)
                return result
            except Exception as exc:  # noqa: BLE001
                error = f"{type(exc).__name__}: {exc}"
                raise
            finally:
                history.record(
                    tool=f"resource:{name}",
                    category="resource",
                    args=dict(bound.arguments),
                    duration_ms=(time.perf_counter() - started) * 1000,
                    ok=error is None,
                    result=result,
                    error=error,
                )

        return mcp.resource(uri, name=name, description=description, mime_type="application/json")(wrapper)

    return decorator


@_resource("collections", "koillection://collections", "All Koillection collections (summaries).")
def res_collections() -> str:
    """Resource: list all collections."""
    try:
        cols = get_client().get_all_members("/api/collections")
        return dumps([_summarize_collection(c) for c in cols])
    except KoillectionError as exc:
        return _err(exc)


@_resource("collection", "koillection://collections/{collection_id}", "One collection with its subcollections.")
def res_collection(collection_id: str) -> str:
    """Resource: one collection by UUID plus child summaries."""
    try:
        client = get_client()
        path = _id_or_iri(collection_id, "collections")
        collection = client.get(path)
        children = client.get_all_members(f"{path}/children")
        return dumps(
            {
                "collection": _summarize_collection(collection),
                "children": [_summarize_collection(c) for c in children],
            }
        )
    except KoillectionError as exc:
        return _err(exc)


@_resource("collection_items", "koillection://collections/{collection_id}/items", "Items in one collection.")
def res_collection_items(collection_id: str) -> str:
    """Resource: item summaries for one collection."""
    try:
        client = get_client()
        path = _id_or_iri(collection_id, "collections")
        items = client.get_all_members(f"{path}/items")
        return dumps([_summarize_item(i) for i in items])
    except KoillectionError as exc:
        return _err(exc)


@_resource("templates", "koillection://templates", "Templates with their fields.")
def res_templates() -> str:
    """Resource: templates including field definitions."""
    try:
        client = get_client()
        templates = client.get_all_members("/api/templates")
        out = []
        for t in templates:
            tid = str(t.get("id") or t.get("@id"))
            path = _id_or_iri(tid, "templates")
            try:
                fields = client.get_all_members(f"{path}/fields")
            except KoillectionError:
                fields = []
            out.append(
                {
                    "id": t.get("id") or t.get("@id"),
                    "name": t.get("name"),
                    "fields": [
                        {
                            "id": f.get("id") or f.get("@id"),
                            "name": f.get("name"),
                            "type": f.get("type"),
                            "position": f.get("position"),
                        }
                        for f in fields
                    ],
                }
            )
        return dumps(out)
    except KoillectionError as exc:
        return _err(exc)


@_resource("tags", "koillection://tags", "All tags.")
def res_tags() -> str:
    """Resource: list all tags."""
    try:
        tags = get_client().get_all_members("/api/tags")
        return dumps(
            [
                {
                    "id": t.get("id") or t.get("@id"),
                    "label": t.get("label"),
                    "description": t.get("description"),
                    "category": t.get("category"),
                }
                for t in tags
            ]
        )
    except KoillectionError as exc:
        return _err(exc)


@_resource("call_history", "koillection://call-history", "Recent MCP call history (JSONL log, latest 50).")
def res_call_history() -> str:
    """Resource: recent call-history records."""
    return dumps(history.read_history(50))


# ---------------------------------------------------------------------------
# Prompts (workflow templates)
# ---------------------------------------------------------------------------


@mcp.prompt(description="Set up a new Koillection collection with template and fields, preview-first.")
def setup_collection(
    title: Annotated[str, Field(description="Title for the new collection.")],
    parent_title: Annotated[str | None, Field(description="Optional existing parent collection title or ID; set to create a subcollection.")] = None,
    field_ideas: Annotated[str | None, Field(description="Optional free-text ideas for fields to track, e.g. 'year, mint, owned checkbox, condition'.")] = None,
) -> str:
    """Prompt: guide setup of a new collection."""
    parent_line = f"Parent: {parent_title} (resolve it with list_collections first)." if parent_title else "Parent: none (top-level collection)."
    fields_line = f"Field ideas from the user: {field_ideas}" if field_ideas else "Field ideas: ask the user which fields matter; do not assume a fixed schema."
    return (
        f"Set up a new Koillection collection titled '{title}'.\n"
        f"{parent_line}\n"
        f"{fields_line}\n\n"
        "Steps:\n"
        "1. Call health_check and whoami, then list_collections and list_templates to see what already exists. Do not create duplicates.\n"
        "2. Propose a template and field list (include an 'Owned' checkbox field if this is a collect-what-you-have set). Show the proposal and wait for approval.\n"
        "3. For every create, call the tool with dry_run=true first and show the preview. Only apply with dry_run=false after explicit confirmation.\n"
        "4. Create in order: collection (or subcollection), template, fields, then optionally assign the template.\n"
        "5. Verify with get_collection and list_fields, and summarize what was created with IDs."
    )


@mcp.prompt(description="Populate a collection from a pasted list, with dedupe and a combined preview.")
def populate_from_list(
    collection: Annotated[str, Field(description="Target collection title, UUID, or IRI.")],
    items_text: Annotated[str, Field(description="The list to import, one item per line; field values may follow commas or key: value pairs.")],
) -> str:
    """Prompt: guide populating a collection from a static list."""
    return (
        f"Populate Koillection collection '{collection}' from this list:\n\n{items_text}\n\n"
        "Steps:\n"
        "1. Call health_check, resolve the collection with list_collections, then list_items on it.\n"
        "2. Parse the list into items. Skip any whose name already exists in the collection (report skips).\n"
        "3. Read the collection's field definitions at run time (template/fields); never hard-code field names. Map list values to data fields; flag unmapped values instead of inventing fields.\n"
        "4. Call create_item with dry_run=true for every new item and present ONE combined preview. Do not apply anything yet.\n"
        "5. Only after explicit confirmation, re-call with dry_run=false. Then verify with list_items (count) and get_item on a spot-check item."
    )


@mcp.prompt(description="Review/audit one collection read-only: counts, gaps, duplicates.")
def review_collection(
    collection: Annotated[str, Field(description="Collection title, UUID, or IRI to review.")],
) -> str:
    """Prompt: guide a read-only collection review."""
    return (
        f"Review the Koillection collection '{collection}'. This is read-only: change nothing.\n\n"
        "Steps:\n"
        "1. Call health_check, resolve the collection, then get_collection (note subcollections) and list_items.\n"
        "2. Check templates/fields that apply, and read a sample of items with get_item to see which data fields are actually filled.\n"
        "3. Report: item and subcollection counts, duplicate names, items with no data fields, fields that are always empty, and anything that looks misplaced.\n"
        "4. End with suggested next actions, but do not apply any change without a separate confirmed request."
    )


@mcp.prompt(description="Summarize owned vs wanted items in a collection from its Owned checkbox. Read-only.")
def have_vs_want_summary(
    collection: Annotated[str, Field(description="Collection title, UUID, or IRI to summarize.")],
    owned_label: Annotated[str, Field(description="Label of the owned checkbox data field.")] = "Owned",
) -> str:
    """Prompt: guide a have-vs-want summary."""
    return (
        f"Summarize have-vs-want for Koillection collection '{collection}' using the '{owned_label}' checkbox.\n\n"
        "Steps:\n"
        "1. Call health_check, resolve the collection, then list_items on it.\n"
        f"2. For every item, call get_item and read its '{owned_label}' data field: value '1' means owned; '0' or missing means wanted.\n"
        "3. Report two lists (owned, wanted) with counts and the owned percentage.\n"
        "4. Do NOT change any listing in this workflow. If the user later wants updates, each flip needs a set_item_data dry_run preview and explicit confirmation first."
    )


def main() -> None:
    mcp.run(transport="stdio")
