# Build from repo root:
#   docker build -f lilypond-sidecar/Dockerfile -t lilypond-sidecar:local .
FROM python:3.12-slim

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY koillection-mcp /app/koillection-mcp
COPY lilypond-sidecar /app/lilypond-sidecar

WORKDIR /app/lilypond-sidecar
RUN uv sync --frozen --no-dev

ENV HOST=0.0.0.0
ENV PORT=3121
ENV LILYPOND_SIDECAR_LOG_FILE=/var/log/lilypond-sidecar/calls.jsonl

RUN mkdir -p /var/log/lilypond-sidecar

EXPOSE 3121

# Do not mount the Docker socket. Secrets via env only.
CMD ["uv", "run", "lilypond-sidecar"]
