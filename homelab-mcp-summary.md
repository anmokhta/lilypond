# Homelab MCP Project — Summary

Started 2026-10-18 · Owner: Andrew · Status: planning, nothing built yet

## The three goals

1. **Koillection MCP.** Primary: an MCP server so LLMs can get data from and put data into Koillection, including helping set it up the way Andrew wants. Secondary: a side client for Koillection with embedded AI that creates sections and handles bulk import. Built iteratively until Andrew is happy.
2. **MCP fleet + one control point.** Eventually an MCP for every Docker container on the homelab, plus an MCP for each system's Docker daemon, with one place to manage all of them.
3. **Systems wireframe.** A map of every system and application in the homelab. Done after goals 1 and 2 are working, and possibly also written down in Koillection as text.

## Order of work

| Step | What | Depends on |
|---|---|---|
| 1 | Goal 1, iterated until Andrew is satisfied | Koillection running on `tertius` (it is) |
| 2 | Review: what Goal 1 taught us, then rebuild the Goal 2 plan and deep research | Step 1 |
| 3 | Goal 2, built in stages | Step 2 |
| 4 | Goal 3, using the inventory Goal 2 produces | Step 3 |

Goal 2 is deliberately planned only at a high level for now. Its plan is expected to change after Goal 1.

## What is verified so far

From Koillection's own docs:

- It is a self-hosted collection manager built on API Platform (Symfony/PHP), with a REST API, multi-user support, tags, wishlists and loan tracking.
- Supports MySQL, PostgreSQL and MariaDB.
- The API has basic docs at `/api`. Auth is a JWT: `POST /api/authentication_token` with username and password, then `Authorization: Bearer <token>`.
- Known API limits: no admin features, no access to sharing features, uploads only on POST.
- Koillection has no built-in metadata download; metadata is added by hand, and scraping is still being built.
- The maintainer warns to back up the database before updates.

From MCP tooling research:

- **Docker MCP Gateway** (MIT, Docker CLI plugin) puts many MCP servers behind one client connection, runs catalog servers in isolated containers, and has profiles, secrets and per-client allowlists.
- **MetaMCP** (open source) aggregates many STDIO/HTTP MCP servers into one endpoint, with namespaces, API-key auth, middleware and a built-in inspector.
- Several community **Docker MCP servers** exist. At least two support remote daemons (via SSH or `DOCKER_HOST`). Their docs warn that the Docker socket is effectively root on the host.

## Known homelab inventory (from existing notes)

- **`tertius`**: main Docker host. Runs the Plex stack (Plex, Tautulli), the `mediarr` stack (Prowlarr, Radarr, Sonarr, Seerr, Requestrr, FlareSolverr), the smart-home stack (Home Assistant, Mosquitto, Zigbee2MQTT, govee2mqtt), Syncthing, Portainer, and now Koillection.
- **`nasdaq`**: Synology NAS.
- **Ultra.cc seedbox**: hosted slot (rTorrent now, qBittorrent planned).

## Open decisions

1. What does "set up the way I want" mean for Koillection? See the Goal 1 doc.
2. Where will Claude connect from (desktop, Claude Code, or claude.ai), and can it reach the homelab? This decides how MCPs are exposed. See Goal 2.
3. Which gateway: Docker MCP Gateway, MetaMCP, or something else. Decide in the Goal 2 rebuild.

## Companion docs

- Goal 1: Koillection MCP — Plan
- Goal 2: MCP Fleet and Central Manager — Plan
- Goal 3: Homelab Systems Wireframe — Plan

## Goal 1 secondary track (clarified 2026-10-18)

After the MCP works: a side client (app or alternate page) for Koillection with embedded AI that helps create new sections and categories and helps with mass or bulk import. Open research question: fully open-ended, or limited to cards, coins or comics. Details are in the Goal 1 doc, under Track B.

## Sources

- https://koillection.github.io/
- https://github.com/koillection/koillection/wiki/API
- https://github.com/koillection/koillection/wiki
- https://www.docker.com/blog/docker-mcp-gateway-secure-infrastructure-for-agentic-ai/
- https://pkg.go.dev/github.com/docker/mcp-gateway
- https://www.sourcepulse.org/projects/2387288 (MetaMCP)
- https://hub.docker.com/r/gavinlucas/docker-mcp-server
- https://github.com/ResearchComputer/mcp-server-docker
