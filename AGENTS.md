# AGENTS.md

Canonical guidance for any AI agent working in this repo (Cursor, Claude Code, others). Claude-specific notes are in [`CLAUDE.md`](CLAUDE.md).

## Project

**lilypond** — tools for Koillection, a self-hosted collection manager running on the `tertius` Docker host. This is Goal 1 of a sequenced homelab MCP project:

| Goal | What | Status |
|---|---|---|
| 1 | Koillection MCP (Track A), then an embedded-AI side client (Track B) | Track A CRUD done (2026-10-20); population next; Track B not started |
| 2 | MCP fleet + central manager (incl. a possible Mac manager app) | Draft only — plan gets rebuilt after Goal 1 |
| 3 | Homelab systems wireframe | Parked |

Do not build Goal 2/3 work early. Goal 1 findings that feed Goal 2 go in the Goal 1 doc's "What Goal 1 must teach us for Goal 2" section.

### Document map

| File | Role |
|---|---|
| [`goal-1-koillection-mcp.md`](goal-1-koillection-mcp.md) | Active plan: phases, acceptance tests, verified facts, findings |
| [`koillection-mcp/README.md`](koillection-mcp/README.md) | Server README: tools, dry-run contract, call history, client wiring |
| [`README.md`](README.md) | Repo overview and roadmap |
| [`homelab-mcp-summary.md`](homelab-mcp-summary.md), [`goal-2-*.md`](goal-2-mcp-fleet-and-central-manager.md), [`goal-3-*.md`](goal-3-homelab-systems-wireframe.md) | Later goals; background only |
| [`.cursor/rules/mcp-development.mdc`](.cursor/rules/mcp-development.mdc) | Cursor rule applied when editing MCP code |

### Hosts

- `tertius` (192.168.86.31) — Docker host: Koillection (`koillection` + `koillection-db`, port 3120), Plex stack, mediarr, smart home, Portainer.
- `nasdaq` — Synology NAS, undocumented. Ultra.cc seedbox — not Docker.

## MCP engineering standard

Based on [Build an MCP server (2026-07-28)](https://modelcontextprotocol.io/docs/2026-07-28/develop/build-server) (Python track) and the official Python SDK 2.x.

### Shape

- One server per package under `koillection-mcp/`; entry point `koillection_mcp:main` → `mcp.run(transport="stdio")`.
- All three capability types (since 2026-10-20): Tools (read + CRUD), read-only Resources (`koillection://collections`, `/templates`, `/tags`, `/call-history`, plus templated collection/items URIs), and Prompts (`setup_collection`, `populate_from_list`, `review_collection`, `have_vs_want_summary`). Adding new capabilities still requires a plan update.
- Python ≥ 3.12, `uv` for env/deps, `mcp[cli] >= 2`, server built on `MCPServer` (`mcp.server.mcpserver`). HTTP calls to Koillection live in `client.py` only; tool registration lives in `server.py` only.

### Tool design

- Names are `snake_case`, prefixed by category in the description: `[read]`, `[create]`, `[update]`, `[delete]`.
- Every tool has MCP annotations: reads `read_only_hint`, deletes `destructive_hint` (set via `ToolAnnotations`).
- The SDK builds schemas from type hints and docstrings: **every tool docstring must document each parameter (an `Args:` section)** and say what is returned.
- Tools return JSON strings. Errors are returned, not raised, as `{"error": "<Type>", "message": "..."}` so the model can recover.
- IDs are accepted as UUID, IRI (`/api/collections/<uuid>`), or URL, and normalized before use.

### This project's write contract (non-negotiable)

- Every create/update/delete tool takes `dry_run: bool = True`. Dry run returns the exact method/path/payload and writes nothing.
- Applying (`dry_run=false`) happens only after the preview has been shown and the user explicitly confirmed.
- Deletes additionally require `confirm_title`/`confirm_name` exactly matching the current value; collection delete previews report recursive subcollection/item counts (deletes cascade).
- Updates are PUT read-modify-write (GET, merge supplied fields, PUT full payload) — never PATCH, never partial PUT.
- Item metadata is separate `/api/data` records: one POST per field at create; `set_item_data` upserts by label.

### Logging and history

- **STDIO: never write to stdout** — it corrupts JSON-RPC. No `print()` anywhere under `koillection-mcp/src/`. Diagnostics go to stderr (Python `logging`, one logger per module) or to files.
- Every tool call appends one JSONL record to `koillection-mcp/logs/calls.jsonl` (override: `KOILLECTION_MCP_LOG_FILE`): schema version, UTC timestamp, server/tool/category, redacted args, `dry_run`, duration, ok/error, payload-free summary. Logging must never break a tool call.
- Secrets are redacted from history; passwords/tokens never appear in args or results.

### Transports and client wiring

- Now: stdio, spawned by the client. Cursor config (`~/.cursor/mcp.json`) and Claude Desktop config (`~/Library/Application Support/Claude/claude_desktop_config.json`) both use:
  `uv --directory /Users/andrewmokhtarzadeh/code/lilypond/koillection-mcp run koillection-mcp`
  Use absolute paths (full path to `uv` if the client can't find it), and fully quit/restart the client (Cmd+Q) after changes.
- If a server doesn't appear: check client logs (`~/Library/Logs/Claude/mcp*.log` for Claude Desktop; Cursor MCP settings panel), config JSON syntax, and absolute paths.
- Later (separate plans): streamable HTTP for ChatGPT and for a future MCP manager. Manager conventions already established: `tools/list` is the manifest; per-server JSONL history is the audit trail; stdio servers must be spawned from config, they have no discoverable endpoint.

### Testing checklist (run before calling work done)

```bash
cd koillection-mcp
uv sync
uv run python scripts/smoke_readonly.py       # auth + reads against tertius
uv run python scripts/test_crud_sandbox.py    # writes: full lifecycle on _MCP CRUD TEST, self-cleaning
uv run python scripts/test_resources_prompts.py  # Args descriptions, resources, prompts
```

Plus: confirm the tool count via `mcp.list_tools()` (36 as of 2026-10-21, incl. `list_choice_lists` / `create_choice_list` / `delete_choice_list`) after registration changes, and spot-check `get_call_history` after write-path changes.

Template patterns: `get_collection_template` resolves a collection's **own** default (Koillection has no parent inheritance — report `null`, never walk up). `copy_template` is the MCP-emulated clone (Koillection has no clone API): one dry-run diff (drop/rename/retype/add) before applying, new field records so copies are independent, partial-failure reporting instead of silent continuation.

## Compliance audit — 2026-10-20

Audit of the current server against the build-server guide. Gaps are follow-ups; fixing them is separate work, not part of routine edits.

| # | Item | Status |
|---|---|---|
| 1 | `MCPServer` on Python SDK 2.3.0 (`mcp[cli]`), `uv` project, `mcp.run(transport="stdio")` | Pass |
| 2 | No `print()` / stdout writes under `koillection-mcp/src/` | Pass |
| 3 | Type-hinted tool signatures driving generated schemas | Pass |
| 4 | Absolute-path client configs for Cursor + Claude Desktop | Pass |
| 5 | Capability surface documented; tools + resources + prompts since 2026-10-20 | Pass |
| 6 | Parameter descriptions: `Annotated[..., Field(description=...)]` on every tool/prompt parameter (docstring `Args:` alone does not populate SDK 2.x schemas — verified) | Pass (closed 2026-10-20; tested by `scripts/test_resources_prompts.py`) |
| 7 | Guide uses `async def` tools + `httpx2`; server uses sync tools + sync `httpx` | **Gap** — decide: migrate to async, or record a dated exception here |
| 8 | No explicit stderr `logging` configuration in server code (file history exists; library logs rely on defaults) | **Gap** — add `logging` setup writing to stderr |
| 9 | `ToolAnnotations` built with camelCase keys; accepted by `mcp-types` 2.3 via aliases | **Gap (minor)** — switch to snake_case field names |
| 10 | `pyproject.toml` description still says "Read-only MCP server" | **Gap (minor)** — update wording |

Note (2026-10-21): choice-list tools (`list_choice_lists`, `create_choice_list`, `delete_choice_list`, plus `choice_list_id` on `create_field`/`set_item_data`) follow the same audited patterns (items 1–6, 9); no new gaps introduced. Tool count 36.

## Koillection API facts (verified)

- Base: `http://192.168.86.31:3120`; OpenAPI 1.8.4 at `/api/docs.json`; human docs at `/api`.
- Auth: `POST /api/authentication_token` (username/password) → JWT; send `Authorization: Bearer <token>`; re-login on 401.
- Collections: field is `title`; subcollection = `parent` IRI. Items require `name` + `collection` IRI. Data (metadata) records require `type` + `label`, linked by `item` IRI.
- Content rules: JSON generally; uploads POST-only `multipart/form-data` (item main image field `file`; datum image field `fileImage` — verified 2026-10-20); PUT preferred over PATCH.
- Item reads do not embed `relatedItems` or tags; relations live at `GET /api/items/{id}/related_items` and are **not mirrored** — set both directions explicitly (verified 2026-10-20).
- Limits: no admin features, no sharing access — calls act as the logged-in user (`anmokhta`, decided 2026-10-20 as the MCP user). Checkbox values are `"0"`/`"1"`; `/api/collections/{id}/items` returns `[]` for deleted collections.
- Choice lists: `/api/choice_lists` (`name` + `choices[]`); a `choice-list` field/datum binds one static list via a `choiceList` IRI — no conditional logic. Datum values must be valid JSON array strings (verified 2026-10-21).

## Design decisions (settled)

1. Have-vs-want is a checkbox field on each item, not a wishlist (2026-10-18).
2. Setup and import are separate workflows; import-style tools read field definitions at run time and never hard-code field names (2026-10-18).
3. MCP runs as the `anmokhta` user; a dedicated user would see none of the existing data (2026-10-20).
4. Coin versions are separate items linked P↔D via Related Items; the 50 states + 2009 DC/Territories share one subcollection (`State & Territories Quarters`) and one unified program template, circulating P/D strikes only (2026-10-20).
5. One global `Coin Type` choice list (`Penny (Cent)`, `Nickel`, `Dime`, `Quarter`, `Half Dollar`, `Dollar`, `Other`) on every coin template, alongside free-text `Denomination` — Koillection choice lists are static per-field, with no country-conditional/cascading lists and no ancestry-based defaulting, so one global list is the approximation (2026-10-21). Choice-list datum values are stored as JSON array strings (e.g. `["Quarter"]`, verified 2026-10-21); a choice list cannot be deleted while item data references it.
6. `US Quarter` is the master template for all US quarter groups (30 fields, design block included); `State & Territories Quarters` (35 fields) is its specialization on the same ordered spine. On the quarter templates the duplicates were dropped — `Denomination` (= `Coin Type`; supersedes decision 5's coexistence for quarters only), `Series / Design` (= `Program`), `Release Year`, `Proof` (= `Finish`) — and `Jurisdiction` was unified into `State / Subject`; constants stay per-item. Item datum order is independent of template field order and must be re-positioned separately; image data re-positions via raw read-modify-write datum PUT, not `set_item_data` (2026-10-21).
7. Grading is choice-list based on every coin template: `Grade` = `1`–`8`, `8.5`, `9`, `9.5`, `10`; `Grading Service` = `PCGS`, `NGC`, `ANACS`, `Other`; `Condition` = the standard numismatic scale (`Poor` … `Proof`). An ungraded item stores the trio as empty selections (`[]`) (2026-10-21).

## Safety constraints

- Read before write; create → update → delete, deletes guarded last.
- Dry-run by default for all writes, bulk, and structural work; preview then explicit apply.
- Back up the Koillection DB before write/structural phases (`tertius:/home/anmokhta/docker/koillection/backups/`, latest 2026-10-20).
- Never expose the Docker socket to an MCP server container (root-equivalent).
- Never start the `plex` container if stopped; Andrew stops it on purpose.
- No credentials in chat, git, or MCP JSON. Koillection login only in `koillection-mcp/.env`.
- Ask before mutating anything on `tertius` outside the Koillection API (containers, compose, Portainer).

## Documentation conventions

- Decisions dated inline, absolute dates ("decided 2026-10-20").
- Verified and unverified facts kept separate; verify before promoting.
- Every planning doc ends with `## Sources`; add URLs with new claims.
- Update this audit and the Goal 1 findings when server behavior changes.

## Sources

- https://modelcontextprotocol.io/docs/2026-07-28/develop/build-server
- https://modelcontextprotocol.io/llms.txt
- https://koillection.github.io/
- https://github.com/koillection/koillection/wiki/API
- https://github.com/benjaminjonard/koillection
