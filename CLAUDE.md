# CLAUDE.md

Guidance for Claude Code in this repo. Shared, tool-agnostic guidance lives in [`AGENTS.md`](AGENTS.md) — read it too; where the two overlap, `AGENTS.md` is canonical.

## What this repository is

**lilypond**: tools for [Koillection](https://koillection.github.io/), Andrew's self-hosted collection manager on `tertius`. Started 2026-10-18. This is Goal 1 of a three-goal homelab MCP project (Goal 1 → review → Goal 2 fleet/manager → Goal 3 wireframe; goals are strictly sequenced).

Current state (2026-10-20): a working Python MCP server in [`koillection-mcp/`](koillection-mcp/) — 28 tools: read-only discovery plus CRUD for collections/subcollections, items, item data, templates, fields, and tags. All writes are dry-run by default; every call is logged to a JSONL history. Next up: populating real collections. Track B (side client with embedded AI) has not started.

## Read in this order

1. [`AGENTS.md`](AGENTS.md) — project + MCP engineering standard (canonical)
2. [`goal-1-koillection-mcp.md`](goal-1-koillection-mcp.md) — active plan, phases, acceptance tests, findings
3. [`koillection-mcp/README.md`](koillection-mcp/README.md) — tool table, dry-run contract, client wiring

## Claude-specific working rules

- **Decisions are dated inline** ("decided 2026-10-20"), never silently rewritten.
- **Verified vs. unverified is tracked separately** in the goal docs. When you verify something, move it to the verified section with the date and source. Never promote a guess.
- **Every planning doc ends with `## Sources`.** Add the URL when you add a claim.
- **No credentials in chat, ever.** The Koillection password lives only in `koillection-mcp/.env` (gitignored). Server-side changes on `tertius` (Docker, Portainer, systemd) are Andrew's to approve — ask first; recent exception history is documented in the Goal 1 doc, not to be repeated casually.
- When behavior changes, update the `AGENTS.md` compliance audit and the Goal 1 doc's findings section in the same change.

## MCP standards (summary — full checklist in AGENTS.md)

Following [Build an MCP server (2026-07-28)](https://modelcontextprotocol.io/docs/2026-07-28/develop/build-server):

- This server exposes all three MCP capability types: **Tools** (read + CRUD), read-only **Resources** (`koillection://...`), and workflow **Prompts**. New capabilities still need a plan, not ad-hoc additions.
- Python MCP SDK 2.x, `MCPServer` from `mcp.server.mcpserver`; tool schemas come from **type hints + docstrings**, so every tool needs an `Args:` section.
- **STDIO servers must never write to stdout** (it corrupts JSON-RPC). No `print()` in server code; diagnostics go to stderr or files.
- Transports: stdio now (Cursor, Claude Desktop); streamable HTTP is a later plan (ChatGPT / manager).
- Tool contract here: snake_case names, `[read]`/`[create]`/`[update]`/`[delete]` category prefixes, MCP annotations, `dry_run=true` default on every write, exact-name confirmation on deletes.

## Koillection essentials

- JWT auth: `POST /api/authentication_token` → `Authorization: Bearer <token>`; client re-logs in on 401. REST docs and OpenAPI (1.8.4) at `/api` and `/api/docs.json` on `http://192.168.86.31:3120`.
- Relations are IRIs; updates are PUT (read-modify-write), not PATCH; uploads are POST-only multipart (no upload tools yet).
- **No admin or sharing API** — every call acts as the logged-in user (`anmokhta`); a different login sees different data.
- Settled design: have-vs-want is an item checkbox field; setup and import are separate workflows, and import-style tools must read field definitions at run time, never hard-code field names.

## Safety (non-negotiable)

- Read before write; create → update → delete. Deletes last and always guarded.
- Dry-run/preview before any apply, including bulk and structural work. Never apply a write without showing the preview and getting explicit confirmation.
- Back up the Koillection Postgres DB before structural/write phases (latest: `/home/anmokhta/docker/koillection/backups/koillection-20261020-032623.sql`).
- Never expose the Docker socket to an MCP container. Never start the `plex` container (Andrew stops it deliberately). Secrets only in `.env` files, never in MCP JSON or git.

## Commands

```bash
cd koillection-mcp
uv sync
uv run koillection-mcp                        # stdio server (Cursor/Claude spawn this)
uv run python scripts/smoke_readonly.py       # read-only smoke against tertius
uv run python scripts/test_crud_sandbox.py    # full CRUD lifecycle, self-cleaning
```

## Sources

- https://modelcontextprotocol.io/docs/2026-07-28/develop/build-server
- https://modelcontextprotocol.io/llms.txt
- https://koillection.github.io/
- https://github.com/koillection/koillection/wiki/API
- https://github.com/benjaminjonard/koillection
