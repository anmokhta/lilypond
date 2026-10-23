# Goal 1 — Track B: Lilypond sidecar (Compose) + optional later fork

Status: **B1 slice 0 in progress** (sidecar scaffold + Display-order helper shipped locally 2026-10-22; tertius Compose deploy pending Andrew’s approval) · Part of Goal 1 (secondary track) · Decided 2026-10-22 (revised later same day): **sidecar-first** — Compose service next to stock Koillection; **fork only later** if native group headings and/or a temporary list/grid toggle become worth the maintenance

Track A (MCP server) is the primary Goal 1 track — see [`goal-1-koillection-mcp.md`](goal-1-koillection-mcp.md). Track B is the friendlier interface for setup/import and related UX — delivered as a Docker Compose sidecar on `tertius`, leaving the stock `koillection/koillection` image untouched until a fork is clearly justified. Package: [`lilypond-sidecar/`](lilypond-sidecar/).

## Objective

| Phase | What | Touches stock Koillection image? |
|---|---|---|
| **B1 — Sidecar (default path)** | Compose service: AI Organizer, AI Importer, optional “set Display order” helper using stock API | No |
| **B2 — Fork (only if needed)** | Custom image: first-class `position`/`displayGroup`, temporary list/grid toggle, auto-update pipeline | Yes |

```text
[browser] → :3120  koillection          (stock image, unchanged)
         → :3121  lilypond-sidecar     ──HTTP──► koillection:80 (REST API)
                              └──► AI provider
```

Same Docker network (`koillection_default`). Prefer adding the sidecar to the existing Portainer Koillection stack (or a sibling compose that joins that network). Sidecar unhealthy must not take down Koillection.

## Why sidecar-first (decided 2026-10-22)

- Original Track B (2026-10-18) wanted AI help for setup and bulk import without living in MCP chat. That value is almost entirely **API-driven** — Track A already proved dry-run writes, field-defs-at-import, and the have-vs-want checkbox model.
- Stock Koillection has **no plugin system** (verified 2026-10-21). A fork is the only clean way to change collection page chrome (group headings, temporary list/grid toggle). AI does not need that.
- Stock already supports **custom child order** via a collection-level data field + parent `childrenDisplayConfiguration.sortingProperty` (no fork). First-class `position` / `displayGroup` are nice-to-haves.
- A Compose sidecar keeps upstream image updates independent, reuses Track A client/write-contract code, and matches how `tertius` already runs services.

Do not start Track B before Goal 1 Track A sign-off. Do not fold this into Goal 2/3. Do not start a Koillection fork until B2 is explicitly activated.

## Settled constraints (carry over from Track A)

1. Have-vs-want remains a checkbox field on each item, not a wishlist (2026-10-18).
2. Setup (organize) and import stay separate workflows; import reads field definitions at run time and never hard-codes field names (2026-10-18).
3. Dry-run / preview before every AI-proposed write; deletes last and guarded.
4. No credentials in chat, git, or image layers. Koillection login + AI provider keys only in Portainer/stack env (same pattern as `koillection-mcp/.env`).
5. Single-user homelab default: sidecar authenticates to the API as `anmokhta` (same as the MCP). Multi-user browser login through the sidecar is out of scope for v1.
6. Never expose the Docker socket to the sidecar (or any MCP container). No shared Postgres/uploads volumes with Koillection.

## Acceptance shape (from Goal 1 Test 2)

Via the sidecar UI, AI identifies which coins Andrew has and updates those listings from want → owned — with preview and confirmation before any write. Input method (typed list, photos, something else) is still open.

---

## Phase B1 — Compose sidecar

### Features in scope

| Feature | Behaviour |
|---|---|
| **AI Organizer** | Propose collection/subcollection structure, templates, fields → preview → apply only after explicit confirm |
| **AI Importer** | Target an existing collection; read field defs at run time; propose items (and later owned-flag flips) → preview → apply |
| **Display-order helper** | Optional: set a shared collection-level datum (e.g. `Display order`) on children and set the parent's `childrenDisplayConfiguration.sortingProperty` so stock grid/list sorts by it |

### Features deferred to B2 (need a fork)

- Native `position` / `displayGroup` columns and group section headings in Koillection's own grid/list.
- Temporary per-visit list/grid toggle that does not rewrite saved `displayMode`.

### Compose / runtime design

| Choice | Decision |
|---|---|
| Placement | Same Portainer stack as Koillection when practical; otherwise sibling compose on `koillection_default` |
| Reach Koillection | Service DNS (`http://koillection` or stack service name), not the LAN IP, for in-stack calls |
| Publish | Dedicated host port first (e.g. `3121`) for easy rollback; optional later path fronting (Caddy) under e.g. `/lilypond/…` |
| Volumes | Own volume for sidecar logs/history only |
| Health | Sidecar has its own healthcheck; Koillection must not `depends_on` the sidecar for readiness |
| Stack changes | Andrew approves any Portainer/compose mutation on `tertius` |

### Code relationship to Track A

Prefer **reusing** `koillection-mcp` client + dry-run write helpers (library import or shared package) so Organizer/Importer cannot drift from the MCP write contract. Do not require exposing MCP over the network for B1 — the sidecar calls Koillection's REST API the same way the MCP does.

Sidecar keeps its own JSONL call/apply history (mirror Track A schema ideas: redacted args, dry_run, ok/error). Logging must never break an apply.

### B1 slices

| Slice | What | Status |
|---|---|---|
| **0** | Sidecar scaffold + Display-order helper (preview → apply; stock `Display order` datum + parent `sortingProperty`) | **Code + local smoke done 2026-10-22** (`uv run python scripts/smoke_display_order.py`). Tertius Portainer deploy **not** done — needs Andrew’s approval. |
| **1** | AI Importer (Test 2: owned-flag flips with preview) | Next after slice 0 deploy/use |
| **2** | AI Organizer | After Importer |
| **B2** | Optional Koillection fork (native groups / list-grid toggle) | Parked |

### Slice 0 findings (verified 2026-10-22)

- Collection-level data: `POST /api/data` with `"collection": "/api/collections/<uuid>"`, type `number`, label `Display order` works; list via `GET /api/collections/<uuid>/data`.
- Parent PUT with nested `childrenDisplayConfiguration` (`sortingProperty` = `Display order`, `sortingType` = `number`, ASC) works without sending nested `@id`.
- Package reuses `koillection-mcp` client via path dependency; JSONL history under `lilypond-sidecar/logs/` (or `LILYPOND_SIDECAR_LOG_FILE`).
- Compose example: [`lilypond-sidecar/docker-compose.example.yml`](lilypond-sidecar/docker-compose.example.yml) — external `koillection_default`, port 3121, logs volume only, **no Docker socket**.

### Research still open (for slice 1+)

- Open-ended vs domain-limited Organizer/Importer (cards / coins / comics); metadata sources and terms of use.
- AI provider, model, billing, rate limits; how keys are stored on `tertius`.
- Whether a reverse-proxy path + bookmark/link from Koillection is enough UX (userscript optional).

### B1 sequencing

1. ~~Scaffold `lilypond-sidecar/`; Display-order helper; local smoke~~ — done 2026-10-22.
2. Andrew approves Compose/Portainer add on `tertius`; deploy sidecar; optional apply Display order on `_Coins` after preview in the UI.
3. Slice 1: AI Importer (settle provider first); dry-run then sandbox apply.
4. Slice 2: AI Organizer.
5. Document rollback (stop/remove sidecar only); stock Koillection upgrades stay independent.

---

## Phase B2 — Custom Koillection image (optional, later)

Activate only if native group headings and/or a temporary list/grid toggle (or first-class `position`) are required enough to own a fork.

Feasibility already verified 2026-10-21 against upstream `benjaminjonard/koillection` branch `1.8` (instance 1.8.4): no plugins; children ordered by title; `DisplayConfiguration.displayMode` is persisted with no per-request override.

### Patch summary (if activated)

- Nullable `position` + `displayGroup` on `Collection`; additive migration; API serializer groups so Track A MCP can set them without MCP changes.
- Children precedence: `displayGroup` → `position` → configured `sortingProperty` → title; group headings in grid/list Twig.
- Temporary `childrenView` / `itemsView` query params + toggle buttons on `show.html.twig` — **no flush** of saved `displayMode`.
- Auto-update: poll upstream releases → rebase patch → build → test gate (incl. boot test on sanitised backup) → GHCR → LAN deployer on `tertius` (backup → pull → recreate → health → rollback on failure). Patch/minor auto; majors manual.
- Prerequisite ~~JWT Portainer pin~~ already **done 2026-10-22**.

Out of scope for B2 v1: drag-and-drop reordering; item grouping; MCP code changes beyond consuming new API fields.

B2 runbook and workflows would live under `koillection-custom/` when activated. Until then, do not create that tree.

### Risks if B2 is activated

- Recurring rebase/rebuild on every upstream release.
- Auto-rollback covers images, not destructive migrations — additive-only schema; majors need approval.
- Heavy upstream build (PHP + Node/yarn); Buildx cache helps.

---

## Sequencing relative to the rest of Goal 1

| Step | What |
|---|---|
| Track A complete + Goal 1 review signed off | Gate for starting B1 |
| AI research settled enough for a first Organizer/Importer slice | Before shipping B1 UI |
| B1 staging/smoke green on `tertius` | Before relying on it for real collections |
| Explicit decision that B2 is worth it | Before any Koillection fork or image swap |
| Goal 1 closed | Then rebuild Goal 2 plan (fleet/manager) |

Findings from Track B that feed Goal 2 (packaging, transport, secrets, what broke) go in [`goal-1-koillection-mcp.md`](goal-1-koillection-mcp.md)'s "What Goal 1 must teach us for Goal 2" section — same rule as Track A.

## Sources

- [`goal-1-koillection-mcp.md`](goal-1-koillection-mcp.md) — Track A plan, JWT durability (permanent fix 2026-10-22), tertius runtime facts
- https://github.com/benjaminjonard/koillection (branch `1.8`: Collection entity, DisplayConfiguration, ArraySorter, CollectionRepository, CollectionController, collection Twig, Dockerfile, entrypoint) — used for B2 feasibility and stock sort behaviour
- https://github.com/benjaminjonard/koillection/releases
- https://github.com/koillection/koillection/wiki/API
- Live instance OpenAPI: `http://192.168.86.31:3120/api/docs.json` (version 1.8.4, verified 2026-10-18)
- https://koillection.github.io/
