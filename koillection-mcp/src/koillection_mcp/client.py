"""Read-only Koillection REST client (JWT auth)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv

# Package lives at .../koillection-mcp/src/koillection_mcp/; .env is at project root.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_ENV_FILE = _PROJECT_ROOT / ".env"


class KoillectionError(Exception):
    """Raised when the Koillection API returns an error or config is missing."""


class KoillectionClient:
    """Thin httpx wrapper: login, re-auth on 401, Hydra collection pagination."""

    def __init__(
        self,
        base_url: str | None = None,
        username: str | None = None,
        password: str | None = None,
    ) -> None:
        load_dotenv(_ENV_FILE)
        load_dotenv()  # also allow cwd / process env overrides
        self.base_url = (base_url or os.getenv("KOILLECTION_BASE_URL", "")).rstrip("/")
        self.username = username or os.getenv("KOILLECTION_USERNAME", "")
        self.password = password or os.getenv("KOILLECTION_PASSWORD", "")
        self._token: str | None = None
        self._client = httpx.Client(
            timeout=30.0,
            headers={"Accept": "application/ld+json"},
        )

    def close(self) -> None:
        self._client.close()

    def _require_config(self) -> None:
        missing = [
            name
            for name, value in (
                ("KOILLECTION_BASE_URL", self.base_url),
                ("KOILLECTION_USERNAME", self.username),
                ("KOILLECTION_PASSWORD", self.password),
            )
            if not value
        ]
        if missing:
            raise KoillectionError(
                "Missing config: "
                + ", ".join(missing)
                + ". Copy .env.example to .env and fill in values."
            )

    def login(self) -> str:
        self._require_config()
        response = self._client.post(
            f"{self.base_url}/api/authentication_token",
            json={"username": self.username, "password": self.password},
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )
        if response.status_code != 200:
            raise KoillectionError(
                f"Login failed ({response.status_code}): {response.text[:300]}"
            )
        data = response.json()
        token = data.get("token")
        if not token:
            raise KoillectionError("Login response missing token")
        self._token = token
        return token

    def _auth_headers(self) -> dict[str, str]:
        if not self._token:
            self.login()
        assert self._token is not None
        return {"Authorization": f"Bearer {self._token}"}

    def _normalize_path(self, path_or_iri: str) -> str:
        if path_or_iri.startswith("http"):
            parsed = urlparse(path_or_iri)
            return parsed.path + (f"?{parsed.query}" if parsed.query else "")
        return path_or_iri

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
        retry_auth: bool = True,
    ) -> Any:
        self._require_config()
        path = self._normalize_path(path)
        url = path if path.startswith("http") else f"{self.base_url}{path}"
        response = self._client.request(
            method,
            url,
            params=params,
            json=json_body,
            headers=self._auth_headers(),
        )
        if response.status_code == 401 and retry_auth:
            self.login()
            return self.request(method, path, params=params, json_body=json_body, retry_auth=False)
        if response.status_code >= 400:
            raise KoillectionError(
                f"{method} {path} failed ({response.status_code}): {response.text[:400]}"
            )
        if not response.content:
            return None
        return response.json()

    def get(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        return self.request("GET", path, params=params)

    def post(self, path: str, json_body: Any = None) -> Any:
        return self.request("POST", path, json_body=json_body)

    def put(self, path: str, json_body: Any = None) -> Any:
        return self.request("PUT", path, json_body=json_body)

    def delete(self, path: str) -> Any:
        return self.request("DELETE", path)

    def get_all_members(self, path: str, *, params: dict[str, Any] | None = None) -> list[Any]:
        """Follow Hydra pagination and return all member items."""
        members: list[Any] = []
        next_path: str | None = path
        query = dict(params or {})
        pages = 0
        while next_path and pages < 500:
            pages += 1
            data = self.get(next_path, params=query if pages == 1 else None)
            if isinstance(data, list):
                members.extend(data)
                break
            batch = data.get("hydra:member") or data.get("member") or []
            members.extend(batch)
            view = data.get("hydra:view") or data.get("view") or {}
            next_iri = view.get("hydra:next") or view.get("next")
            if not next_iri:
                break
            next_path = str(next_iri)
            query = {}
        return members

    def health(self) -> dict[str, Any]:
        """Check API docs endpoint (no auth) and whether credentials work."""
        if not self.base_url:
            return {
                "ok": False,
                "base_url": self.base_url,
                "docs_reachable": False,
                "error": "KOILLECTION_BASE_URL not set",
            }
        docs_ok = False
        version = None
        try:
            response = self._client.get(
                f"{self.base_url}/api/docs.json",
                headers={"Accept": "application/json"},
            )
            docs_ok = response.status_code == 200
            if docs_ok:
                version = response.json().get("info", {}).get("version")
        except Exception as exc:  # noqa: BLE001 — health payload
            return {
                "ok": False,
                "base_url": self.base_url,
                "docs_reachable": False,
                "error": str(exc),
            }
        auth_ok = False
        auth_error = None
        try:
            self._require_config()
            self.login()
            auth_ok = True
        except KoillectionError as exc:
            auth_error = str(exc)
        return {
            "ok": docs_ok and auth_ok,
            "base_url": self.base_url,
            "docs_reachable": docs_ok,
            "api_version": version,
            "authenticated": auth_ok,
            "auth_error": auth_error,
            "username_configured": bool(self.username),
        }

    def whoami(self) -> dict[str, Any]:
        users = self.get_all_members("/api/users")
        for user in users:
            if user.get("username") == self.username:
                return _compact_user(user)
        if len(users) == 1:
            return _compact_user(users[0])
        return {
            "username": self.username,
            "note": "Could not uniquely match /api/users; returning configured username",
            "users_visible": len(users),
        }


def _compact_user(user: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": user.get("id") or user.get("@id"),
        "username": user.get("username"),
        "email": user.get("email"),
        "visibility": user.get("visibility"),
    }


def dumps(data: Any) -> str:
    return json.dumps(data, indent=2, default=str)
