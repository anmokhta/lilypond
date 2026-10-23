# lilypond-sidecar (Goal 1 Track B)

Compose-friendly web sidecar beside stock Koillection. **Slice 0:** Display-order helper (preview → apply). AI Organizer/Importer are later slices. Full plan: [`../goal-1-track-b.md`](../goal-1-track-b.md).

```text
[browser] → :3121  lilypond-sidecar  ──REST──► Koillection API
```

## What slice 0 does

1. Lists top-level collections and their children.
2. Lets you assign a numeric **Display order** on each child (stored as a collection-level `/api/data` datum, type `number`).
3. Sets the parent’s `childrenDisplayConfiguration.sortingProperty` to `Display order` (ASC).
4. Always shows a dry-run preview; apply only after you type `apply`.

Stock Koillection’s grid/list then sorts children by that field. No fork, no Docker socket, no shared DB/uploads volumes.

## Local run

```bash
cd lilypond-sidecar
cp .env.example .env   # or reuse ../koillection-mcp/.env via dotenv fallback
# set KOILLECTION_PASSWORD
uv sync
uv run lilypond-sidecar          # http://127.0.0.1:3121
uv run python scripts/smoke_display_order.py
```

Env (same names as the MCP):

| Variable | Purpose |
|---|---|
| `KOILLECTION_BASE_URL` | e.g. `http://192.168.86.31:3120` locally; `http://koillection:80` in Compose |
| `KOILLECTION_USERNAME` | `anmokhta` |
| `KOILLECTION_PASSWORD` | from secrets — never commit |
| `LILYPOND_SIDECAR_LOG_FILE` | optional JSONL path (default `./logs/calls.jsonl`) |
| `HOST` / `PORT` | bind (default `0.0.0.0:3121`) |

## Compose / Portainer (tertius)

See [`docker-compose.example.yml`](docker-compose.example.yml). Summary:

- Join external network `koillection_default` (or add the service to the existing Koillection stack).
- Publish host port **3121**.
- Own volume for logs only.
- **Never** mount `/var/run/docker.sock`.
- Koillection must not `depends_on` this service for readiness.
- **Andrew must approve** any Portainer/stack change before deploy.

Build from repo root:

```bash
docker build -f lilypond-sidecar/Dockerfile -t lilypond-sidecar:local .
```

## Safety

- Dry-run preview before every apply.
- Secrets only in env / Portainer — not in the image or git.
- Stopping the sidecar leaves stock Koillection unaffected.

## Next

Slice 1: AI Importer (Test 2 — owned-flag flips with preview). Organizer after that. Custom Koillection fork (B2) remains parked.
