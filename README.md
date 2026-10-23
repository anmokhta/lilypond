# lilypond

Tools and extensions for [Koillection](https://koillection.github.io/) — a self-hosted collection manager.

lilypond is two tracks:

| Track | What | Status |
|---|---|---|
| **A — MCP server** | Let LLMs read from and write to Koillection: collections, templates, fields, tags, items, setup | Primary — build first |
| **B — Sidecar (+ optional fork)** | Compose sidecar for AI Organizer/Importer on stock Koillection; fork later only if native groups/list-grid toggle are needed | Slice 0 (Display-order helper) in [`lilypond-sidecar/`](lilypond-sidecar/); plan in [`goal-1-track-b.md`](goal-1-track-b.md) |

**Status (2026-10-20):** Track A phases 1–2 done in [`koillection-mcp/`](koillection-mcp/) — read tools plus CRUD (dry-run by default) for collections/subcollections, items, item data, templates, fields, tags, with JSONL call history. Run `uv run python scripts/test_crud_sandbox.py` for the self-cleaning CRUD lifecycle test. Next: populate real collections; bulk import/scrapers and the MCP manager app are later plans.

## Why "lilypond"

Koillection is the pond. lilypond is the tooling that grows around it — MCP tools for agents, and later an AI-assisted client for setup and bulk work.

## Settled design decisions

1. **Have vs want** is a checkbox field on each item, not a wishlist. Each collection holds the full set; each item has an owned flag.
2. **Setup and import are separate workflows** with separate tools. Import takes a target collection, reads field definitions at run time, and never hard-codes field names.

## Safety rules

- Read-only tools first; create; then update; delete last or never
- Dry-run by default for bulk and structural work — preview, then explicit apply
- Back up the Koillection database before the first write phase and before each structural change
- No credentials in the repo or in chat — login lives in env/secrets on the host
- Do not expose the Docker socket to an MCP server container

## Koillection API (verified)

- REST docs at `/api`
- Auth: `POST /api/authentication_token` with username/password → JWT → `Authorization: Bearer <token>`
- Relations are IRIs (e.g. `"template": "/api/templates/<uuid>"`)
- Prefer PUT over PATCH; uploads are `multipart/form-data` and **POST only**
- **Limits:** no admin features, no sharing features — every call acts as whoever logged in
- No built-in metadata download; scraping is still being built upstream

## Roadmap (Track A)

| Phase | Goal | Done when |
|---|---|---|
| 0. Verify | Confirm Docker config, DB, network, OpenAPI, version; take a backup | Phase-0 open questions answered |
| 1. Read-only | Login, token refresh, list/search | An agent describes current contents correctly |
| 2. Create | Collections, templates, fields, tags, items (incl. image) | One real item end to end |
| 3. Shape it | Desired structure, collection by collection | Owner sign-off |
| 4. Bulk | CSV/JSON import with preview | Real batch imported and spot-checked |
| 5. Harden | Errors, rate limits, logging, update/delete if wanted | Good enough to use day to day |

## Acceptance tests

**Test 1 (Track A):** Using only the MCP, an agent should view the existing Coins collection, create a "50 State Quarters" subcollection with fields (including owned yes/no), populate one entry per state, and leave the owner able to track have vs need in Koillection.

**Test 2 (Track B):** Via the sidecar, AI identifies which coins are owned and updates listings from want → owned — with preview and confirmation before any write.

Details and open items: [`goal-1-koillection-mcp.md`](goal-1-koillection-mcp.md).

## Proposed MCP tools (draft)

| Group | Tools |
|---|---|
| Discovery | list/get collections, list templates/fields/tags, search items |
| Items | create/update item, add image, add tags |
| Structure | create collection/template/field/tag, set visibility |
| Bulk | import from CSV/JSON with preview |
| Safety | health check, whoami |

## Docs in this repo

| File | Role |
|---|---|
| [`goal-1-koillection-mcp.md`](goal-1-koillection-mcp.md) | **Active Track A plan** — phases, tools, acceptance tests, findings |
| [`goal-1-track-b.md`](goal-1-track-b.md) | **Track B plan** — Compose sidecar (AI Organizer/Importer) + optional later fork |
| [`lilypond-sidecar/README.md`](lilypond-sidecar/README.md) | Track B sidecar — slice 0 Display-order helper; Compose/Portainer notes |
| [`homelab-mcp-summary.md`](homelab-mcp-summary.md) | Broader homelab MCP context (fleet, wireframe) — out of scope for lilypond proper |
| [`goal-2-mcp-fleet-and-central-manager.md`](goal-2-mcp-fleet-and-central-manager.md) | Draft notes for a later fleet project |
| [`goal-3-homelab-systems-wireframe.md`](goal-3-homelab-systems-wireframe.md) | Parked systems map |
| [`CLAUDE.md`](CLAUDE.md) | Guidance for AI assistants working in this repo |

## Phase 0 status

Verified on `tertius` (2026-10-18): image `koillection/koillection` + `postgres:16`, port `3120`, network `koillection_default`, OpenAPI 1.8.4 at `/api/docs.json`, laptop can reach the API. **Still open:** app password in local `.env` for authenticated smoke; take a DB backup before any write phase. Details in [`goal-1-koillection-mcp.md`](goal-1-koillection-mcp.md).

## Sources

- https://koillection.github.io/
- https://github.com/koillection/koillection/wiki/API
- https://github.com/koillection/koillection/wiki
- https://github.com/benjaminjonard/koillection
