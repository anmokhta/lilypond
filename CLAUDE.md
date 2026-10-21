# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repository is

A **planning repository** for a homelab MCP project, started 2026-10-18. Owner: Andrew. There is no source code, build system, test suite, or git repository here — only four Markdown planning docs. Do not invent build/lint/test commands; there are none yet.

The project's three goals, and the state of each, live in the docs. The working deliverable right now is the plan itself: keep the docs accurate as decisions are made.

## Document set

| File | Role |
|---|---|
| `homelab-mcp-summary.md` | The index. Goal statements, order of work, verified facts, homelab inventory, open decisions, sources. **Read this first.** |
| `goal-1-koillection-mcp.md` | Active goal: a Koillection MCP server (Track A) plus a side client with embedded AI (Track B). The only doc with a concrete phase plan and acceptance tests. |
| `goal-2-mcp-fleet-and-central-manager.md` | Explicitly a draft to be **rebuilt after Goal 1**. First-pass research agenda, not a design. |
| `goal-3-homelab-systems-wireframe.md` | Parked until Goals 1 and 2 work. Depends on the inventory Goal 2 produces. |

## Structural rules these docs follow

- **Goals are strictly sequenced.** Goal 1 → review → rebuild Goal 2's plan → Goal 2 → Goal 3. Don't plan or build Goal 2/3 work ahead of its dependency; Goal 2's plan is expected to change once Goal 1 is done.
- **Verified vs. unverified is tracked separately.** Each doc separates what has been confirmed from source from what still needs checking (Goal 1's "Not yet verified" list is the phase-0 gate). Preserve that split — when you confirm something, move it and cite the source. Never promote a guess.
- **Decisions are dated inline** (e.g. "clarified 2026-10-18", "decided 2026-10-18") rather than rewritten silently. Follow that convention; absolute dates, not relative.
- **Every doc ends with a `## Sources` list of URLs.** Add to it when you add a claim.
- Goal 1 also carries a "What Goal 1 must teach us for Goal 2" section — findings during Goal 1 belong there, since they are the input to the Goal 2 rebuild.

## Domain facts worth knowing before touching Goal 1

Koillection (self-hosted collection manager, Symfony/PHP on API Platform, running on the `tertius` Docker host):

- Auth is a JWT: `POST /api/authentication_token` with username/password, then `Authorization: Bearer <token>`. REST docs at `/api`.
- Relations are IRIs (`"template": "/api/templates/<uuid>"`). PATCH uses `application/merge-patch+json`; the maintainer recommends PUT over PATCH. Uploads are `multipart/form-data` and **POST only**.
- Known API limits: **no admin features, no sharing features**. Every call acts as whoever logged in — this is why Track B's multi-user story is an open question, and why user accounts likely can't be created via API.
- No built-in metadata download; scraping is still being built upstream.

Two design decisions already settled, which constrain any implementation:

1. **Have-vs-want is a checkbox field on the item**, not a wishlist. Each collection holds the full set; each item carries an owned flag.
2. **Setup and import are separate workflows with separate tools.** Import tools take the target collection as input, read its field definitions *at run time*, and never hard-code field names — Andrew decides which fields matter during Test 1, so no fixed schema can be assumed.

## Safety constraints that apply to any build work

These come from the homelab, not from general practice, and they are non-negotiable in the plans:

- **Read before write.** Ship read-only tools first; create, then update; delete tools last or never.
- **Dry-run by default for bulk and structural work** — preview, then explicit apply. Track B must preview and confirm before changing any listing.
- **Back up the Koillection database** before the first write phase and before each structural change (the upstream maintainer warns about this).
- **Never start a container that was stopped on purpose.** Andrew stops `plex` deliberately; the existing `check-plex-gpu.sh` already refuses to start a stopped container, and daemon MCPs must not fight it. A Plex restart can interrupt active streams, and `systemctl daemon-reload` is known to break GPU access in that container.
- **Docker socket access is root-equivalent on the host.** Treat it as the project's main risk; never expose the socket to an MCP server container.
- **No credentials in chat.** Koillection logins and other secrets live in env/secret files on `tertius` or a gateway secret store — not in conversation, and not in compose files in git.
- Directories created under `syn/` (Synology mounts) need PUID/PGID checked first.

## Hosts

`tertius` — main Docker host (Plex stack, `mediarr` stack, smart-home stack, Syncthing, Portainer, Koillection). `nasdaq` — Synology NAS, undocumented. An Ultra.cc seedbox slot, not Docker.
