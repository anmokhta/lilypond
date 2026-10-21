#!/usr/bin/env python3
"""Verify Args descriptions, Resources, and Prompts against the live instance.

Run: uv run python scripts/test_resources_prompts.py
"""

from __future__ import annotations

import asyncio
import json
import sys

from koillection_mcp.server import mcp

FAILURES: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(("PASS " if cond else "FAIL ") + label + (f" :: {detail}" if detail and not cond else ""))
    if not cond:
        FAILURES.append(label)


def _text(result) -> str:
    """Extract text from an MCP read/get result."""
    if isinstance(result, list):  # list[ReadResourceContents]
        return "".join(
            getattr(c, "content", None) or getattr(c, "text", "") or "" for c in result
        )
    try:
        contents = result.contents  # ReadResourceResult
        return "".join(getattr(c, "text", "") or "" for c in contents)
    except AttributeError:
        pass
    try:
        messages = result.messages  # GetPromptResult
        parts = []
        for msg in messages:
            content = msg.content
            if isinstance(content, list):
                parts.extend(getattr(c, "text", "") or "" for c in content)
            else:
                parts.append(getattr(content, "text", "") or "")
        return "\n".join(parts)
    except AttributeError:
        return str(result)


async def main() -> int:
    tools = await mcp.list_tools()
    check("tool count is 28", len(tools) == 28, str(len(tools)))
    missing = [
        f"{t.name}.{name}"
        for t in tools
        for name, prop in t.input_schema.get("properties", {}).items()
        if "description" not in prop
        and not any("description" in s for s in (prop.get("anyOf") or []))
    ]
    check("every tool parameter has a description", not missing, ", ".join(missing[:10]))

    resources = await mcp.list_resources()
    templates = await mcp.list_resource_templates()
    static_uris = {str(r.uri) for r in resources}
    template_uris = {t.uri_template for t in templates}
    check(
        "static resources present",
        {"koillection://collections", "koillection://templates", "koillection://tags", "koillection://call-history"}
        <= static_uris,
        str(static_uris),
    )
    check(
        "template resources present",
        {"koillection://collections/{collection_id}", "koillection://collections/{collection_id}/items"}
        <= template_uris,
        str(template_uris),
    )

    collections = json.loads(_text(await mcp.read_resource("koillection://collections")))
    check("collections resource parses", isinstance(collections, list) and len(collections) >= 1)
    coins = next((c for c in collections if c.get("title") == "COINS"), None)
    check("COINS found in resource", coins is not None)
    if coins:
        detail = json.loads(_text(await mcp.read_resource(f"koillection://collections/{coins['id']}")))
        check("collection template resource", detail.get("collection", {}).get("title") == "COINS")
        items = json.loads(_text(await mcp.read_resource(f"koillection://collections/{coins['id']}/items")))
        check("collection items resource", isinstance(items, list))

    prompts = await mcp.list_prompts()
    names = {p.name for p in prompts}
    check(
        "prompts present",
        {"setup_collection", "populate_from_list", "review_collection", "have_vs_want_summary"} <= names,
        str(names),
    )
    # prompt argument descriptions
    for prompt in prompts:
        for arg in prompt.arguments or []:
            desc = getattr(arg, "description", None)
            check(f"prompt arg described: {prompt.name}.{arg.name}", bool(desc))

    samples = {
        "setup_collection": {"title": "Test Setup"},
        "populate_from_list": {"collection": "COINS", "items_text": "Example Coin"},
        "review_collection": {"collection": "COINS"},
        "have_vs_want_summary": {"collection": "COINS"},
    }
    for name, args in samples.items():
        rendered = _text(await mcp.get_prompt(name, args))
        check(f"prompt renders: {name}", len(rendered) > 50, rendered[:80])
    setup_text = _text(await mcp.get_prompt("setup_collection", {"title": "X"}))
    check("setup prompt enforces dry_run", "dry_run" in setup_text)
    owned_text = _text(await mcp.get_prompt("have_vs_want_summary", {"collection": "COINS"}))
    check("owned prompt mentions confirmation", "confirmation" in owned_text)

    print(f"\n{len(FAILURES)} failure(s)")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
