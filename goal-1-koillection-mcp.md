# Goal 1: Koillection MCP — Plan

Status: planning · Approach: iterate with Andrew until he is happy, then review before Goal 2

## Objective

Two tracks. Track A (primary): an MCP server that lets LLMs get data from and put data into Koillection, including helping set it up the way Andrew wants (collections, templates, fields, tags, visibility). Track B (secondary): a side client for Koillection with embedded AI that helps create new sections and categories and helps with bulk import. Track A comes first; the phases and tool list below are Track A.

## What we know (verified)

**API**

- Koillection is built on API Platform. Basic REST docs are served at `/api` on the Koillection instance.
- Auth: `POST /api/authentication_token` with `{"username", "password"}` returns a JWT. Every later request sends `Authorization: Bearer <token>`.
- Content types: most endpoints use `application/json`; file-upload POSTs use `multipart/form-data`; PATCH uses `application/merge-patch+json`. The maintainer recommends PUT over PATCH.
- Relations use IRIs. Example: a new Field points at its Template with `"template": "/api/templates/<uuid>"`.
- Data field values have type-specific formats (text, country as 2-letter code, date as `YYYY-MM-DD`, rating 1–10 in half-star steps, list as a JSON string, checkbox `0`/`1`). Image, sign, file and video fields are `null` at creation and filled by a separate upload call.
- **Known limits:** no admin features, no access to sharing features, uploads only on POST.

**Product model** (from the wiki): collections work like folders and contain items; items carry metadata; tags group items across collections; there are wishlists, loan tracking, templates, fields, visibility settings, scraping and metrics pages.

**Runtime on `tertius` (verified 2026-10-18 via SSH + laptop curl)**

- Image: `koillection/koillection:latest` (FrankenPHP labels show image created 2026-08-06). Companion DB: `postgres:16` as container `koillection-db`.
- Containers: `koillection` (healthy), `koillection-db`. Compose project name `koillection`; Portainer stack path was labeled `/data/compose/26/docker-compose.yml` (file not readable from SSH user without sudo).
- Host publish: `0.0.0.0:3120->80/tcp`. Laptop reaches `http://192.168.86.31:3120` and `http://tertius.local:3120` (`tertius.local` resolves to that IP).
- Docker network: `koillection_default`. Service DNS names `koillection` and `koillection-db` work for containers on that network. A future MCP container must join this network (or use the published host port) to reach the app by name.
- Volumes/binds: uploads → `/home/anmokhta/docker/koillection/uploads`; Postgres data → `/home/anmokhta/docker/koillection/db`.
- Env (non-secret): `DB_DRIVER=pdo_pgsql`, `DB_HOST=koillection-db`, `DB_PORT=5432`, `DB_NAME=koillection`, `DB_VERSION=16`, `APP_ENV=prod`, `HTTPS_ENABLED=0`, `FRANKENPHP_SERVER_NAME=:80`. CORS allowlist includes localhost, `192.168.86.31`, `tertius.local` (browser-only; server-side MCP clients are unaffected).
- **OpenAPI:** yes. `GET /api/docs.json` returns OpenAPI **3.1.0**, `info.version` **1.8.4**. Alternate: `GET /api/docs.jsonopenapi` with `Accept: application/vnd.openapi+json`. Hand-writing tools is fine for phase 1; codegen remains an option.
- Wiki API page still matches auth/IRI/upload rules; OpenAPI confirms endpoint set for 1.8.4.
- Unauthenticated `GET /api/collections` returns 401 JWT required. Auth username on this instance: `anmokhta` (from `koi_user`). App password is not stored in this repo — put it in local `.env` for the MCP.
- **Subcollections:** OpenAPI `Collection-collection.write` has `parent` as IRI (`iri-reference`). Also `GET /api/collections/{id}/children` and `.../parent`. Column `parent_id` exists in `koi_collection`. (Create not exercised yet — next plan.)
- Current collections (titles): CARDS, _WEBSITES, WATCHES, COINS, STAMPS, VINYL, PINS, and subcollection **50 State Quarters** (already has a parent). Field name in API is `title`, not `name`.
- **No Koillection DB backup found** under the data dir or common backup paths. Take a Postgres dump before any write phase.
- Item list API has no server-side search filter in OpenAPI (only `page`). Phase-1 `search_items` will filter client-side (and/or scope via `GET /api/collections/{id}/items`).

## Not yet verified (remaining)

- App login password works end-to-end from the MCP (depends on local `.env` — do not put credentials in chat or git).
- Whether checkbox owned-flag defaults and filter/sort behave as wanted in the UI (Test 1 follow-on).
- Exact Portainer compose file contents (needs sudo on `tertius`).

## Design principles

1. **Read before write.** Ship read-only tools first, then create, then update, then delete.
2. **Dry-run by default for bulk work.** Bulk imports and structure changes show a preview and require an explicit apply.
3. **Back up first.** The maintainer asks users to back up the database, so take a backup before the first write phase and before each structural change.
4. **No credentials in chat.** Store the Koillection login in a secret or env file on `tertius`, not in conversation.
5. **Dedicated user.** Consider a separate Koillection user for the MCP, since the API acts as whoever logs in. (Open question: does that fit how Andrew wants his collections organised?)
6. **No destructive tools until the end.** Delete tools are the last phase, if at all.

## Proposed tool surface (draft, to refine together)

| Group | Tools |
|---|---|
| Discovery | list collections, get collection, list templates, list fields, list tags, search items |
| Items | create item (with data fields), update item, add image, add tags |
| Structure | create collection, create template, create field, create tag, set visibility |
| Bulk | import items from CSV/JSON with a preview step |
| Safety | health check, whoami (which user the token belongs to) |

## Phases

| Phase | Goal | Done when |
|---|---|---|
| 0. Verify | Read the Docker, Configuration and `/api` pages; confirm version, DB and network; take a backup | Open questions above are answered |
| 1. Read-only | MCP can log in, refresh its token, and list/search everything | Claude can describe the current Koillection contents correctly |
| 2. Create | Add collections, templates, fields, tags and items | One real item added end to end, including an image |
| 3. Shape it | Work through Andrew's desired structure, collection by collection | Andrew signs off on the structure |
| 4. Bulk | CSV/JSON import with preview | A real batch imported and spot-checked |
| 5. Harden | Error messages, rate of calls, logging, update/delete if wanted | Andrew says it is good enough |

After phase 5, we hold a short review (see the last section).

## Acceptance tests (from Andrew, 2026-10-18)

**Test 1: the MCP (Track A).** Using only the MCP, Claude should:

1. View the existing "Coins" collection and list its subcollections.
2. Create a new subcollection called "50 State Quarters".
3. Create the fields and attributes for it, including a yes/no field for whether Andrew has collected each coin. (Koillection's API supports a checkbox field type.)
4. Populate one entry per state with its data.
5. Leave Andrew able to use Koillection to track what he has and what he still needs.

**Test 2: the embedded AI client (Track B).** Andrew wants to test the AI identifying which coins he has and updating those listings from "want to own" to owned.

**Open items these tests raise:**

- The state data (which fields, which values) must be sourced and checked, not written from memory. Andrew to decide which fields matter.
- Whether the API can create a subcollection directly (a parent reference by IRI is the likely way, but this is unverified). Check in phase 0.
- How "have" versus "want" is modelled: decided 2026-10-18. Each collection holds the full set, and each item carries a yes/no owned flag (a checkbox field); wishlists are not used for this. Still to check: that the flag can default to not owned, and that Koillection can filter or sort by it.
- Test 2 input: how does the AI learn which coins Andrew has (photos, a typed list, something else)? Coin identification from images has not been researched.
- Test 2 should show a preview and ask for confirmation before changing any listing.
- Test 2 depends on the data model chosen in Test 1, so settle that first.

## Design implication: setup and import are separate (2026-10-18)

Andrew will decide which fields to track during Test 1, not up front. So neither the MCP nor the embedded AI can assume a fixed set of fields. Both must also let Andrew set up collections for users and import items into them as two separate steps.

**Two separate workflows, separate tools**

1. **Setup:** create a collection, its template and its fields (including the owned flag). Shows a preview of the structure before anything is created.
2. **Import:** add items to an existing collection. Reads that collection's field definitions at run time, checks each item against them, shows a preview, then writes. Because it reads fields at run time, the same tools work for any collection.

**What this means for the build**

- Import tools take the target collection as input and never hard-code field names.
- Setup and import can each be called alone, in either order, and re-run later (for example, new items added to an old collection).
- Re-running an import should not create duplicates. How to match existing items (by name, by a key field) is undecided.
- Track B follows the same split: the AI proposes a structure, Andrew approves it, setup runs; separately, the AI proposes items, Andrew reviews, import runs.
- The fields Andrew keeps after Test 1 get saved as a reusable template, which becomes the starting point for Track B's suggestions.

**"For users" raises an access question.** Koillection's API wiki says the API has no admin features and no access to other users' content, so every call acts as whoever logged in. Likely consequences, not yet verified: the side client must log in as each user, and user accounts cannot be created through the API. Open questions: how users sign in to the Track B client, and where their tokens are stored.

## Questions for Andrew (start here)

1. Which collections do you want in Koillection first, and roughly how many items each?
2. For each: what fields matter (condition, purchase price, location, serial number, etc.)? Do you want shared templates across collections?
3. Do you want wishlists and loans used?
4. Single user, or will others (family, arcade staff) log in?
5. Where should items' source data come from: typing, spreadsheets, photos, existing lists?
6. Which client will you use this MCP from (Claude desktop, Claude Code, claude.ai)? This affects how the MCP is hosted.

## Build choices (decided 2026-10-18 for first slice)

- **Language/SDK:** Python + official `mcp` SDK + `uv`.
- **Transport (now):** local stdio for Cursor (Claude Desktop same command next).
- **Hosting (now):** process on the laptop; reaches Koillection at `http://192.168.86.31:3120` (or `tertius.local`). HTTP container on `tertius` deferred for ChatGPT / Goal 2.
- **Generate vs hand-write tools:** OpenAPI is available (1.8.4); phase 1 hand-writes read-only tools against known paths.

## What Goal 1 must teach us for Goal 2

Record these as we go; they feed the Goal 2 rebuild:

- Which packaging worked (container image, env/secret handling, restart policy).
- Which transport the client could actually use, and what had to be exposed.
- How token/credential refresh was handled.
- Which tools were used constantly and which never.
- What went wrong, and which safety guards earned their keep.
- How long one MCP took to build, to size the work for dozens of them.

**CRUD phase findings (2026-10-20):**

- CRUD shipped for collections/subcollections, items, item data, templates, fields, tags (28 tools total). All writes `dry_run=true` by default; deletes need exact confirm title/name; collection delete preview counts the cascade recursively. Sandbox lifecycle test (`koillection-mcp/scripts/test_crud_sandbox.py`) passes 35/35 and is self-cleaning.
- API quirks learned: updates must be PUT read-modify-write to avoid clobbering; item metadata is one `POST /api/data` per field (no nested create); `GET /api/collections/{id}/items` returns `[]` (not 404) for a deleted collection; checkbox datum values round-trip as strings `"0"`/`"1"`.
- **Manager-ready conventions (for the future MCP manager / Goal 2):** (1) tool manifest = the MCP protocol `tools/list` response — no registry file; (2) every tool carries a category prefix (`[read]`/`[create]`/`[update]`/`[delete]`) plus MCP annotations (`read_only_hint`, `destructive_hint`); (3) call history = one JSONL file per server (schema v1: ts, server, tool, category, redacted args, dry_run, duration, ok/error, payload-free summary), readable via the server's `get_call_history` tool or directly from disk; (4) stdio servers have no discoverable endpoint — a Mac manager must spawn them from config (like Cursor does) or read their log files; an HTTP transport later would make discovery/health checks much easier. No Mac app work in this phase.
- Safety guards that earned their keep: dry-run previews caught nothing destructive in sandbox, but the confirm-title delete + cascade count preview is the guard that matters for real collections; DB backup before writes (see JWT note) is in place.
- **Capabilities expanded (2026-10-20):** server now exposes all three MCP capability types. Every tool parameter got real schema descriptions (`Annotated[..., Field(description=...)]` — verified that docstring `Args:` alone does not populate SDK 2.x schemas). Added 6 read-only resources (`koillection://...`) and 4 prompts (`setup_collection`, `populate_from_list`, `review_collection`, `have_vs_want_summary`); verified by `scripts/test_resources_prompts.py` (24 checks) with smoke + CRUD sandbox regressions green.

**Findings so far (2026-10-18, phase 0–1 scaffolding):**

- **Packaging:** Python + `uv` + official `mcp` 2.x (`MCPServer`, not FastMCP) works as a local package under `koillection-mcp/`. Entry point `uv run koillection-mcp`. No container yet.
- **Transport:** stdio is enough for Cursor and Claude Desktop. Both configs use `uv --directory <path> run koillection-mcp`. Secrets stay in `koillection-mcp/.env` (gitignored), loaded via `python-dotenv` from the project root — not in MCP JSON.
- **Auth:** JWT via `POST /api/authentication_token`; client re-logins on 401. No `/api/me`; `whoami` matches `/api/users` by username. App password is separate from the Postgres `DB_PASSWORD` (reusing DB password failed).
- **JWT key incident (found/fixed 2026-10-19):** API login returned 500 `JWTEncodeFailureException` after correct credentials. Cause: container restart 2026-09-20 regenerated `.env.local` with a new random `JWT_PASSPHRASE`, but entrypoint's `lexik:jwt:generate-keypair --skip-if-exists` kept the Aug 24 private key encrypted with the lost original passphrase. Web (session) login unaffected. Fix applied: old keys backed up to `/home/anmokhta/docker/koillection/jwt-backup-20261019/` on `tertius`, then `lexik:jwt:generate-keypair --overwrite`. Smoke test passes (`authenticated: true`).
- **JWT durability (2026-10-20):** DB backup taken before write phase: `/home/anmokhta/docker/koillection/backups/koillection-20261020-032623.sql` (89K). Entrypoint deletes `.env.local` on every start, so the passphrase must come from container env or a persisted file. Interim fix applied in-container: entrypoint patched (original at `docker/entrypoint.sh.bak-20261020` in the container) to reuse `/app/.jwt-passphrase`; verified by `docker restart koillection` — API auth still 200 afterward. **Permanent fix still pending Andrew:** set `JWT_PASSPHRASE` in the Portainer stack env (same value as in the container's `.env.local`); the in-container patch survives restarts but not a stack recreate/image update.
- **MCP user (decided 2026-10-20):** keep `anmokhta`. A dedicated MCP user cannot access existing collections via the API (no admin/sharing), so it would be an empty silo.
- **Reachability:** laptop → `http://192.168.86.31:3120` (and `tertius.local`) works on the LAN. Homelab gateway MCP in Cursor was down during this work; not required for Koillection stdio.
- **OpenAPI:** available (`/api/docs.json`, version 1.8.4). Hand-written tools were faster for the first eight read tools; codegen still optional later.
- **Safety:** no write tools shipped. Phase-0 found **no Koillection DB backup** — still required before any write phase.
- **macOS note:** `mcp install` rewrites Claude Desktop `mcpServers`; prefer editing JSON to match Cursor’s `uv --directory` form so secrets are not embedded in the config file.
- **Time so far:** phase 0 verify + phase 1 scaffold/read-only tools in one session; authenticated end-to-end smoke still needs `KOILLECTION_PASSWORD` in local `.env`.

## Track B (secondary): side client with embedded AI

Added and clarified 2026-10-18 as the secondary track of Goal 1, started after the MCP works. Andrew wants an app or alternate page for Koillection with embedded AI that helps create new sections and categories and helps with mass or bulk import.

This builds directly on Goal 1: phases 3 (shape the structure) and 4 (bulk import with preview) are the same capabilities, offered through a friendlier interface instead of a chat.

**Research question to settle first:** should it be completely open-ended, or limited to specific domains such as trading cards, coins or comics? The trade-off, to be researched:

- *Open-ended:* works for any collection, but the AI must infer templates and fields from scratch and has no trusted metadata source.
- *Domain-limited:* can use domain-specific fields and external metadata sources for each domain, but each domain is separate work. Koillection itself has no built-in metadata download, so domain data would have to come from outside.

**Other things to research later** (none looked into yet):

- Which metadata sources exist for cards, coins and comics, and their terms of use.
- Whether it should be a separate web app that calls Koillection's REST API, or something closer to Koillection itself (Koillection's own scraping feature is still being built).
- How the AI is embedded and how its calls are paid for and secured.
- Preview-and-approve flow for every AI-proposed change, since the AI would be writing to a real collection.
- Whether the Goal 1 MCP can be reused as this app's tool layer.

## Sources

- https://github.com/koillection/koillection/wiki/API
- https://github.com/koillection/koillection/wiki
- https://github.com/koillection/koillection/wiki/Configuration
- https://github.com/benjaminjonard/koillection (README: backup warning, scraping, no built-in metadata download)
- Live instance OpenAPI: `http://192.168.86.31:3120/api/docs.json` (version 1.8.4, verified 2026-10-18)
