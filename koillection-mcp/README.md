# koillection-mcp

MCP server for Koillection. Runs as a local stdio process (no Mac app).

Read tools plus full CRUD for collections/subcollections, items, item data, templates, fields, and tags. **Every write tool defaults to `dry_run=true`** (preview only); applying requires `dry_run=false`, and deletes require an exact confirm title/name.

## Setup

```bash
cd koillection-mcp
cp .env.example .env
# Edit .env: set KOILLECTION_PASSWORD (and URL/username if needed)
uv sync
```

## Run (stdio)

```bash
uv run koillection-mcp
```

## Tests

```bash
uv run python scripts/smoke_readonly.py      # read-only auth + listing smoke
uv run python scripts/test_crud_sandbox.py   # full CRUD lifecycle on a throwaway collection (self-cleaning)
uv run python scripts/test_resources_prompts.py  # tool count (33), Args descriptions, resources, prompts
uv run python scripts/import_state_territories_quarters.py          # dry-run preview of the quarters import
uv run python scripts/import_state_territories_quarters.py --apply  # resumable import (dedupe by item name)
```

The quarters import is driven by `data/state-territories-quarters/manifest.json` (56 designs × P/D, gitignored with its staged images): TreasureRealm + Wikipedia + CoinNews data, public-domain U.S. Mint images via Wikimedia Commons.

## Cursor MCP config

Registered in `~/.cursor/mcp.json` as server `koillection` (alongside `homelab-gateway`). Snippet:

```json
{
  "mcpServers": {
    "koillection": {
      "command": "uv",
      "args": [
        "--directory",
        "/Users/andrewmokhtarzadeh/code/lilypond/koillection-mcp",
        "run",
        "koillection-mcp"
      ]
    }
  }
}
```

Reload MCP servers in Cursor after code changes. `python-dotenv` loads `.env` from this directory — keep secrets out of the MCP JSON.

## Claude Desktop config

Same command in `~/Library/Application Support/Claude/claude_desktop_config.json` under `mcpServers.koillection`. Restart Claude Desktop after editing.

## Dry-run contract (all write tools)

1. Call with `dry_run=true` (default) → returns the exact payload(s) and a summary; nothing is written.
2. Show the preview to the user; only on explicit confirmation re-call with `dry_run=false`.
3. Deletes also require `confirm_title` / `confirm_name` exactly matching the current value. Collection deletes cascade (preview reports recursive subcollection/item counts).

Updates are PUT read-modify-write: the server GETs the current object, merges only supplied fields, and PUTs the full payload (Koillection maintainer recommends PUT over PATCH).

## Tools

### Read
| Tool | Purpose |
|---|---|
| `health_check` | Docs reachable + login works |
| `whoami` | Which user the JWT is |
| `get_call_history` | Recent entries from the JSONL call log |
| `list_collections` / `get_collection` | Collections (+ children) |
| `list_templates` / `list_fields` / `list_tags` | Structure |
| `get_template` | One template + position-sorted fields |
| `get_collection_template` | A collection's own default template + fields (explicit `null` when unset — Koillection has **no parent inheritance**) |
| `list_items` / `get_item` / `search_items` | Items (get_item includes data fields) |

### Create
`create_collection` (parent_id → subcollection), `create_item` (with `data` fields), `set_item_data` (upsert by label), `create_template`, `copy_template` (clone fields with drop/rename/retype/add in one dry-run preview), `create_field`, `create_tag`, `upload_item_image` (local file → item main image, multipart), `upload_item_data_image` (local file → an item's image data field by label, created if missing; multipart field `fileImage`)

### Update
`update_collection`, `update_item` (incl. `related_item_ids`; relations are **not** mirrored by the API — set both directions), `update_template`, `update_field`, `update_tag` — all PUT read-modify-write; setting a parent/collection moves the object.

### Delete
`delete_collection`, `delete_item`, `delete_item_data`, `delete_template`, `delete_field`, `delete_tag` — confirm-name required; collections cascade.

## Resources (read-only, `application/json`)

| URI | Content |
|---|---|
| `koillection://collections` | Collection summaries |
| `koillection://collections/{collection_id}` | One collection + children |
| `koillection://collections/{collection_id}/items` | Item summaries |
| `koillection://templates` | Templates with fields |
| `koillection://tags` | Tags |
| `koillection://call-history` | Recent call history |

## Prompts

| Prompt | Drives |
|---|---|
| `setup_collection` | Propose template/fields, preview, confirm, create, verify |
| `populate_from_list` | Parse a pasted list, dedupe, combined dry-run preview, apply, verify |
| `review_collection` | Read-only audit: counts, gaps, duplicates |
| `have_vs_want_summary` | Owned vs wanted split from the Owned checkbox (read-only) |

Every tool and prompt parameter carries a schema `description` (`Annotated[..., Field(...)]`); `scripts/test_resources_prompts.py` verifies descriptions, resources, and prompts.

## Call history (manager-ready)

Every tool call appends one JSON record to `logs/calls.jsonl` (gitignored; override with `KOILLECTION_MCP_LOG_FILE`): schema version, timestamp, server/tool, category, redacted args, `dry_run`, duration, ok/error, short result summary. Tools carry read/create/update/delete categories in descriptions and MCP annotations (`read_only_hint` / `destructive_hint`), and `tools/list` is the tool manifest. A future MCP manager can enumerate tools via the protocol and read this log per server. Logging never breaks a tool call.

## Instance notes

Default base URL: `http://192.168.86.31:3120` (Koillection on `tertius`, port 3120). API version verified as 1.8.4. Known API quirks: item metadata is separate `/api/data` calls (one per field); `GET /api/collections/{id}/items` returns `[]` for a deleted collection instead of 404; image uploads are POST-only multipart (item main image field `file`, datum image field `fileImage`); item reads don't embed `relatedItems` (use `GET /api/items/{id}/related_items`) and relations are not mirrored automatically.
