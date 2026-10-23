"""Append-only JSONL history for sidecar actions. Must never break a request."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
SERVER_NAME = "lilypond-sidecar"

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_LOG = _PROJECT_ROOT / "logs" / "calls.jsonl"
_SECRET_KEYS = {"password", "token", "authorization", "secret", "api_key", "apikey"}


def get_log_path() -> Path:
    raw = os.getenv("LILYPOND_SIDECAR_LOG_FILE", "")
    return Path(raw).expanduser() if raw else _DEFAULT_LOG


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: ("***" if k.casefold() in _SECRET_KEYS else _redact(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_redact(v) for v in value[:40]]
    if isinstance(value, str) and len(value) > 200:
        return value[:200] + "…"
    return value


def record(
    *,
    action: str,
    category: str,
    args: dict[str, Any] | None = None,
    dry_run: bool | None = None,
    ok: bool = True,
    error: str | None = None,
    summary: dict[str, Any] | None = None,
    duration_ms: float | None = None,
) -> None:
    try:
        path = get_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        row = {
            "version": SCHEMA_VERSION,
            "ts": datetime.now(timezone.utc).isoformat(),
            "server": SERVER_NAME,
            "action": action,
            "category": category,
            "args": _redact(args or {}),
            "dry_run": dry_run,
            "duration_ms": duration_ms,
            "ok": ok,
            "error": error,
            "summary": summary or {},
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, default=str) + "\n")
    except Exception:  # noqa: BLE001 — history must never break callers
        pass


class timed:
    """Context manager that yields elapsed ms via .ms after exit."""

    def __init__(self) -> None:
        self.ms: float = 0.0
        self._start = 0.0

    def __enter__(self) -> timed:
        self._start = time.perf_counter()
        return self

    def __exit__(self, *args: object) -> None:
        self.ms = round((time.perf_counter() - self._start) * 1000, 2)
