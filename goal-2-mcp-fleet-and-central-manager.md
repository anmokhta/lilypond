# Goal 2: MCP Fleet and Central Manager — Plan

Status: **draft, to be rebuilt after Goal 1** · This is a first-pass plan and a research agenda, not a final design.

## Objective

1. An MCP for each Docker container worth controlling.
2. An MCP for each system's Docker daemon (at minimum `tertius`).
3. One place to see, enable, disable and secure all of those MCPs.

## Three layers

| Layer | What it is | Examples from the homelab |
|---|---|---|
| A. App MCPs | One MCP per application, using that app's own API | Koillection (Goal 1), Radarr, Sonarr, Prowlarr, Seerr, Home Assistant, Plex/Tautulli |
| B. Daemon MCPs | One MCP per Docker daemon, managing containers, images, networks, volumes | `tertius` Docker; possibly `nasdaq` if it runs Docker (unverified) |
| C. Gateway / manager | One endpoint and one admin place in front of A and B | Candidates below |

## Inventory seed (from existing notes)

| Host | Stack | Containers |
|---|---|---|
| `tertius` | Plex (Portainer stack 7) | `plex`, `tautulli` |
| `tertius` | `mediarr` | `flaresolverr`, `prowlarr`, `radarr`, `sonarr`, `seerr`, `requestrr` |
| `tertius` | smart home | Home Assistant, Mosquitto, Zigbee2MQTT, govee2mqtt |
| `tertius` | other | Syncthing, Portainer, Koillection (new) |
| `nasdaq` | unknown | not documented |
| Ultra.cc seedbox | not Docker | rTorrent now; qBittorrent, qbit_manage planned |

For each container, the Goal 2 research must answer: does it have an API, does a maintained MCP already exist, or do we build one?

## Layer C candidates (researched at a surface level)

**Docker MCP Gateway** (Docker, MIT)

- Docker CLI plugin that puts many MCP servers behind one client connection.
- Runs catalog servers in isolated containers; has catalogs, profiles, secrets, OAuth and per-client server/tool allowlists.
- Can serve over a network transport: `docker mcp gateway run --port 8080 --transport streaming`.
- Its own docs advise never exposing the Docker socket to an MCP server container.
- Unknown: how well it handles custom (non-catalog) servers, and whether it fits a headless Linux host and Portainer-managed setups.

**MetaMCP** (open source, self-hosted)

- Aggregates STDIO and HTTP MCP servers into one endpoint, with namespaces to group tool sets, API-key and OIDC auth, middleware for rate limiting and observability, and a built-in inspector.
- Unknown: current version and maintenance state, resource use, and how it handles many servers.

**Others** to survey: Portkey MCP gateway and McpMesh were mentioned in a comparison article; not evaluated.

## Layer B candidates

- `mcp-server-docker` (ckreiling): manages containers, images, volumes; can connect to a remote daemon over SSH; refuses `--privileged` and capability options.
- `gavinlucas/docker-mcp-server`: manages many Docker object types, can manage multiple daemons, retargetable via `DOCKER_HOST`.
- `@swartdraak/docker-mcp-server`: remote hosts over TCP, HTTP/HTTPS or SSH tunnel.
- All three warn, in one form or another, that Docker access is root-equivalent on the host. Treat this as the main risk in the project.

## Safety rules to carry over from the homelab

- **Never start a container that was stopped on purpose.** Andrew stops `plex` deliberately and often; the existing `check-plex-gpu.sh` already refuses to start a stopped container. Daemon MCPs need the same rule: read-only by default, restart/start/stop only with explicit confirmation.
- **Plex GPU:** a restart can interrupt active streams, and a systemd `daemon-reload` is known to break GPU access in the Plex container. Any daemon MCP that touches Plex must not fight the existing self-heal script.
- **Synology ownership:** anything that creates directories under `syn/` needs the right PUID/PGID checked first.
- **Least privilege per client.** Use the gateway's allowlists so a given client only sees the servers it needs.
- **Secrets** live in the gateway's secret store or env files, not in chat or compose files in git.

## Open questions (decide after Goal 1)

1. Where does Claude connect from, and can it reach `tertius`? Local clients and a cloud-hosted client have different network needs; this decides whether the gateway must be reachable from outside the LAN and, if so, how to authenticate it.
2. One gateway for everything, or one per host?
3. Do app MCPs run as containers in the same stacks as the apps, or in a dedicated `mcp` stack?
4. How do we manage MCPs as code (compose file in git, Portainer stack, or the gateway's own config)?
5. Which containers deserve an MCP at all? Not everything needs one.
6. Monitoring: should the gateway's health feed Healthchecks.io like the other checks?

## Proposed phases (provisional)

| Phase | Output |
|---|---|
| 0. Rebuild | Review Goal 1 lessons; redo this research in depth; pick the gateway |
| 1. Gateway up | Gateway running on `tertius` with the Koillection MCP behind it; one client connected |
| 2. Daemon MCP, read-only | List containers, logs and stats on `tertius`; no write actions |
| 3. First app MCPs | The highest-value apps (likely the Arr stack and Home Assistant); verify each app's API and any existing MCP first |
| 4. Controlled writes | Start/stop/restart with confirmation and a protected-container list |
| 5. Other hosts | `nasdaq` and any others |
| 6. Management view | One place to see every MCP, its health, and which clients can use it |

## Research agenda for the rebuild

- Read the Docker MCP Gateway and MetaMCP docs end to end; try both with one test server.
- Check each homelab app for an official or maintained community MCP.
- Check how a gateway authenticates remote clients.
- Check the security guidance for exposing a Docker daemon to an MCP.
- Size the work from how long the Koillection MCP took.

## Sources

- https://www.docker.com/blog/docker-mcp-gateway-secure-infrastructure-for-agentic-ai/
- https://pkg.go.dev/github.com/docker/mcp-gateway
- https://www.anavem.com/mcp/docker-mcp-gateway
- https://www.sourcepulse.org/projects/2387288 (MetaMCP)
- https://www.morphllm.com/mcp-gateway (gateway comparison)
- https://github.com/ResearchComputer/mcp-server-docker
- https://hub.docker.com/r/gavinlucas/docker-mcp-server
- https://mcp.directory/servers/docker-mcp-server (@swartdraak)
