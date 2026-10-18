"""The only network client (spec sections 4, 6).

- The key is read from the environment / .env and never printed, logged or saved.
- Every response is cached as one JSON file under data/raw/<window_id>/..., wrapped
  with request metadata (path, params, status, fetched_at) but no headers.
- A request whose cache file already exists for the window is never re-sent.
- Fixed delay between requests plus exponential backoff on 429 / 5xx.

Endpoint paths follow the pre-2026 public API docs and are UNVERIFIED for the
current API until docs/api-notes.md records observed calls.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

import requests

from .config import PROJECT_ROOT, Paths, collection_config


class ApiError(RuntimeError):
    """An API call failed. The message never contains the key."""


def encode_tag(tag: str) -> str:
    """'#ABC123' -> '%23ABC123' (spec section 6)."""
    tag = tag.strip().upper()
    if not tag.startswith("#"):
        tag = "#" + tag
    return quote(tag, safe="")


def safe_tag(tag: str) -> str:
    """Filesystem-safe tag: '#ABC123' -> 'ABC123'."""
    return tag.strip().upper().lstrip("#")


def load_key(key_env: str = "CR_API_KEY") -> str:
    key = os.environ.get(key_env)
    if not key:
        try:
            from dotenv import dotenv_values
            key = dotenv_values(PROJECT_ROOT / ".env").get(key_env)
        except ImportError:  # pragma: no cover
            key = None
    if not key:
        raise ApiError(
            f"No API key: set {key_env} in .env (see .env.example). "
            "Create one at developer.clashroyale.com for your current public IP."
        )
    return key


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class CachedResponse:
    path: Path
    from_cache: bool
    status: int
    body: Any


class ApiClient:
    def __init__(
        self,
        paths: Paths | None = None,
        cfg: dict | None = None,
        session: requests.Session | None = None,
        key: str | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.paths = paths or Paths.for_source("real")
        if self.paths.is_synthetic:
            raise ApiError("ApiClient never writes into the synthetic data root")
        full = cfg or collection_config()
        self.cfg = full["api"]
        self.window_id = str(full["window"]["id"])
        self.session = session or requests.Session()
        self._key = key
        self._key_env = self.cfg.get("key_env", "CR_API_KEY")
        self._sleep = sleep
        self._last = 0.0
        self.requests_sent = 0

    @property
    def window_dir(self) -> Path:
        return self.paths.raw / self.window_id

    def _headers(self) -> dict[str, str]:
        if self._key is None:
            self._key = load_key(self._key_env)
        return {"Authorization": f"Bearer {self._key}", "Accept": "application/json"}

    def _throttle(self) -> None:
        wait = float(self.cfg["request_delay_s"]) - (time.monotonic() - self._last)
        if wait > 0:
            self._sleep(wait)
        self._last = time.monotonic()

    def get(self, endpoint: str, cache_rel: str, params: dict | None = None) -> CachedResponse:
        """GET base_url + endpoint, cached at window_dir / cache_rel."""
        cache = self.window_dir / cache_rel
        if cache.exists():
            with cache.open(encoding="utf-8") as f:
                wrapped = json.load(f)
            return CachedResponse(cache, True, wrapped["status"], wrapped["body"])

        url = self.cfg["base_url"].rstrip("/") + endpoint
        retries = int(self.cfg["max_retries"])
        for attempt in range(retries + 1):
            self._throttle()
            try:
                resp = self.session.get(url, headers=self._headers(), params=params, timeout=self.cfg["timeout_s"])
            except requests.RequestException as e:
                if attempt == retries:
                    raise ApiError(f"network error on {endpoint}: {type(e).__name__}") from None
                self._sleep(float(self.cfg["backoff_base_s"]) * 2**attempt)
                continue
            self.requests_sent += 1
            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt == retries:
                    raise ApiError(f"{endpoint}: HTTP {resp.status_code} after {retries} retries")
                retry_after = resp.headers.get("Retry-After")
                delay = float(retry_after) if retry_after and retry_after.isdigit() else float(self.cfg["backoff_base_s"]) * 2**attempt
                self._sleep(delay)
                continue
            break

        try:
            body = resp.json()
        except ValueError:
            body = {"non_json_body": resp.text[:500]}
        if resp.status_code == 403:
            raise ApiError(
                f"{endpoint}: HTTP 403. The key is probably registered for a different IP "
                "(keys are IP-bound; campus Wi-Fi vs home differ). Response reason: "
                f"{body.get('reason') if isinstance(body, dict) else 'n/a'}"
            )
        if resp.status_code == 404:
            # Cache 404s too (e.g. a player with a private or missing log) so they aren't re-requested.
            pass
        elif resp.status_code != 200:
            raise ApiError(f"{endpoint}: HTTP {resp.status_code}")

        wrapped = {
            "request": {"endpoint": endpoint, "params": params or {}, "window_id": self.window_id},
            "status": resp.status_code,
            "fetched_at": utc_now(),
            "body": body,
        }
        cache.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(wrapped, f, ensure_ascii=False)
        tmp.replace(cache)
        return CachedResponse(cache, False, resp.status_code, body)

    # Endpoints -----------------------------------------------------------------

    def cards(self) -> CachedResponse:
        return self.get("/cards", "cards/cards.json")

    def pol_leaderboard(self, location_id: str = "global", season_id: str | None = None, limit: int = 1000) -> CachedResponse:
        if season_id:
            endpoint = f"/locations/{location_id}/pathoflegend/{season_id}/rankings/players"
            rel = f"leaderboard/{location_id}_{season_id}.json"
        else:
            endpoint = f"/locations/{location_id}/pathoflegend/players"
            rel = f"leaderboard/{location_id}.json"
        return self.get(endpoint, rel, params={"limit": limit})

    def battlelog(self, tag: str) -> CachedResponse:
        return self.get(f"/players/{encode_tag(tag)}/battlelog", f"battlelog/{safe_tag(tag)}.json")
