"""FastAPI app: health + Display-order helper (Track B slice 0)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from koillection_mcp.client import KoillectionClient, KoillectionError

from lilypond_sidecar import display_order as order_helper
from lilypond_sidecar.history import record, timed

_PACKAGE_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _PACKAGE_DIR.parents[1]
_TEMPLATES = Jinja2Templates(directory=str(_PACKAGE_DIR / "templates"))

# Load sidecar .env, then allow process env / MCP .env via client
load_dotenv(_PROJECT_ROOT / ".env")
load_dotenv()

app = FastAPI(title="Lilypond sidecar", version="0.1.0")


def _client() -> KoillectionClient:
    return KoillectionClient()


@app.get("/health")
def health() -> dict[str, Any]:
    client = _client()
    try:
        payload = client.health()
        record(
            action="health",
            category="read",
            ok=bool(payload.get("ok")),
            summary={"authenticated": payload.get("authenticated")},
        )
        return payload
    finally:
        client.close()


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    client = _client()
    try:
        health_payload = client.health()
    except Exception as exc:  # noqa: BLE001
        health_payload = {"ok": False, "error": str(exc)}
    finally:
        client.close()
    return _TEMPLATES.TemplateResponse(
        request,
        "index.html",
        {"health": health_payload},
    )


@app.get("/display-order", response_class=HTMLResponse)
def display_order_pick(request: Request) -> HTMLResponse:
    client = _client()
    try:
        collections = order_helper.list_top_collections(client)
        record(
            action="list_top_collections",
            category="read",
            ok=True,
            summary={"count": len(collections)},
        )
    except KoillectionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        client.close()
    return _TEMPLATES.TemplateResponse(
        request,
        "display_order_pick.html",
        {"collections": collections},
    )


@app.get("/display-order/{collection_id}", response_class=HTMLResponse)
def display_order_edit(request: Request, collection_id: str) -> HTMLResponse:
    client = _client()
    try:
        parent = order_helper.get_collection(client, collection_id)
        children = order_helper.propose_orders(order_helper.list_children(client, collection_id))
        cdc = parent.get("childrenDisplayConfiguration") or {}
        record(
            action="display_order_edit",
            category="read",
            args={"collection_id": collection_id},
            ok=True,
            summary={"title": parent.get("title"), "children": len(children)},
        )
    except KoillectionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        client.close()
    return _TEMPLATES.TemplateResponse(
        request,
        "display_order_edit.html",
        {
            "parent": parent,
            "parent_id": order_helper.collection_id_of(parent),
            "children": children,
            "sorting_property": cdc.get("sortingProperty"),
            "label": order_helper.DISPLAY_ORDER_LABEL,
        },
    )


@app.post("/display-order/{collection_id}/preview", response_class=HTMLResponse)
async def display_order_preview(request: Request, collection_id: str) -> HTMLResponse:
    form = dict(await request.form())
    try:
        orders = order_helper.parse_orders_from_form(form)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid order value: {exc}") from exc
    if not orders:
        raise HTTPException(status_code=400, detail="No order values submitted.")

    client = _client()
    with timed() as t:
        try:
            preview = order_helper.build_preview(client, collection_id, orders)
            record(
                action="display_order_preview",
                category="read",
                args={"collection_id": collection_id, "orders": orders},
                dry_run=True,
                ok=True,
                summary={
                    "parent": preview["parent"].get("title"),
                    "child_writes": preview["child_write_count"],
                },
                duration_ms=t.ms,
            )
        except KoillectionError as exc:
            record(
                action="display_order_preview",
                category="read",
                args={"collection_id": collection_id},
                dry_run=True,
                ok=False,
                error=str(exc),
                duration_ms=t.ms,
            )
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        finally:
            client.close()

    # Stash preview JSON in a hidden field for apply (same request cycle via form)
    preview_json = json.dumps(preview)
    return _TEMPLATES.TemplateResponse(
        request,
        "display_order_preview.html",
        {
            "preview": preview,
            "preview_json": preview_json,
            "collection_id": collection_id,
            "orders": orders,
        },
    )


@app.post("/display-order/{collection_id}/apply", response_class=HTMLResponse)
async def display_order_apply(request: Request, collection_id: str) -> HTMLResponse:
    form = dict(await request.form())
    if form.get("confirm") != "apply":
        raise HTTPException(
            status_code=400,
            detail="Explicit confirm required: set confirm=apply after reviewing the preview.",
        )
    try:
        orders = order_helper.parse_orders_from_form(form)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid order value: {exc}") from exc
    if not orders:
        raise HTTPException(status_code=400, detail="No order values submitted.")

    client = _client()
    with timed() as t:
        try:
            # Rebuild preview server-side so apply cannot drift from a tampered hidden JSON blob.
            preview = order_helper.build_preview(client, collection_id, orders)
            result = order_helper.apply_preview(client, preview)
            record(
                action="display_order_apply",
                category="update",
                args={"collection_id": collection_id},
                dry_run=False,
                ok=True,
                summary={
                    "parent": (result.get("parent") or {}).get("title"),
                    "children": len(result.get("children") or []),
                    "sortingProperty": (result.get("parent") or {}).get("sortingProperty"),
                },
                duration_ms=t.ms,
            )
        except KoillectionError as exc:
            record(
                action="display_order_apply",
                category="update",
                args={"collection_id": collection_id},
                dry_run=False,
                ok=False,
                error=str(exc),
                duration_ms=t.ms,
            )
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        finally:
            client.close()

    return _TEMPLATES.TemplateResponse(
        request,
        "display_order_done.html",
        {"result": result, "collection_id": collection_id},
    )


def main() -> None:
    import uvicorn

    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "3121"))
    uvicorn.run("lilypond_sidecar.app:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
