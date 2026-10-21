"""Structured JSONL call history for the Koillection MCP server.

One JSON object per line. Fields (schema version 1):
  version, ts, server, tool, category, args (redacted), dry_run,
  duration_ms, ok, error, summary

The future MCP manager reads this file; logging must never break a tool call.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
SERVER_NAME = "koillection"

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_LOG = _PROJECT_ROOT / "logs" / "calls.jsonl"

_SECRET_KEYS = {"password", "token", "authorization", "secret", "api_key", "apikey"}
_MAX_SUMMARY_ITEMS = 5


def get_log_path() -> Path:
    raw = os.getenv("KOILLECTION_MCP_LOG_FILE", "")
    return Path(raw).expanduser() if raw else _DEFAULT_LOG


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: ("***" if k.casefold() in _SECRET_KEYS else _redact(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_redact(v) for v in value[:20]]
    text = str(value) if not isinstance(value, (str, int, float, bool)) and value is not None else value
    if isinstance(text, str) and len(text) > 200:
        return text[:200] + "…"
    return text


def summarize_result(result: Any) -> dict[str, Any]:
    """Short, payload-free summary of a tool result for the history log."""
    parsed: Any = result
    if isinstance(result, str):
        try:
            parsed = json.loads(result)
        except (ValueError, TypeError):
            return {"text": result[:120]}
    if isinstance(parsed, list):
        return {"count": len(parsed)}
    if isinstance(parsed, dict):
        summary: dict[str, Any] = {}
        for key in ("dry_run", "applied", "action", "id", "title", "name", "ok", "authenticated", "matched", "scanned"):
            if key in parsed:
                summary[key] = parsed[key]
        for key, value in parsed.items():
            if isinstance(value, list):
                summary[f"{key}_count"] = len(value)
        if "collection" in parsed and isinstance(parsed["collection"], dict):
            summary["collection"] = parsed["collection"].get("title")
        if "item" in parsed and isinstance(parsed["item"], dict):
            summary["item"] = parsed["item"].get("name")
        if "result" in parsed and isinstance(parsed["result"], dict):
            inner = parsed["result"]
            for key in ("id", "title", "name", "label"):
                if key in inner:
                    summary[f"result_{key}"] = inner[key]
        if "error" in parsed:
            summary["error"] = parsed.get("message") or parsed.get("error")
        return summary
    return {"value": str(parsed)[:120]}


def record(
    *,
    tool: str,
    category: str,
    args: dict[str, Any],
    duration_ms: float,
    ok: bool,
    result: Any = None,
    error: str | None = None,
) -> None:
    entry = {
        "version": SCHEMA_VERSION,
        "ts": datetime.now(timezone.utc).isoformat(),
        "server": SERVER_NAME,
        "tool": tool,
        "category": category,
        "args": _redact(args),
        "dry_run": args.get("dry_run") if isinstance(args, dict) else None,
        "duration_ms": round(duration_ms, 1),
        "ok": ok,
        "error": error,
        "summary": summarize_result(result) if result is not None else None,
    }
    try:
        path = get_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, default=str) + "\n")
    except Exception:  # noqa: BLE001 — logging must never break a tool call
        pass


def read_history(limit: int = 50) -> list[dict[str, Any]]:
    path = get_log_path()
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    entries: list[dict[str, Any]] = []
    for line in lines[-max(1, min(limit, 500)):]:
        try:
            entries.append(json.loads(line))
        except ValueError:
            continue
    return entries
