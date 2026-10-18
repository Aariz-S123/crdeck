"""Network client behavior without any network: caching, tag encoding, retries, key hygiene."""

from __future__ import annotations

import json

import pytest

from crdeck.api import ApiClient, ApiError, encode_tag, safe_tag
from crdeck.config import Paths

KEY = "SECRET-TEST-KEY-123"
CFG = {
    "api": {"base_url": "https://example.invalid/v1", "key_env": "CR_API_KEY", "request_delay_s": 0.0,
            "max_retries": 2, "backoff_base_s": 0.0, "timeout_s": 1},
    "window": {"id": "test-window"},
}


class FakeResp:
    def __init__(self, status, body, headers=None):
        self.status_code = status
        self._body = body
        self.headers = headers or {}
        self.text = json.dumps(body)

    def json(self):
        return self._body


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, headers=None, params=None, timeout=None):
        self.calls.append({"url": url, "headers": headers, "params": params})
        return self.responses.pop(0)


def client(tmp_path, responses):
    paths = Paths(source="real", root=tmp_path)
    sess = FakeSession(responses)
    return ApiClient(paths=paths, cfg=CFG, session=sess, key=KEY, sleep=lambda s: None), sess


def test_tag_encoding():
    assert encode_tag("#2PP") == "%232PP"
    assert encode_tag("2pp") == "%232PP"
    assert safe_tag("#2pp") == "2PP"


def test_response_cached_and_never_refetched(tmp_path):
    c, sess = client(tmp_path, [FakeResp(200, [{"battleTime": "x"}])])
    r1 = c.battlelog("#ABC")
    assert not r1.from_cache and sess.calls[0]["url"].endswith("/players/%23ABC/battlelog")
    r2 = c.battlelog("#ABC")
    assert r2.from_cache and len(sess.calls) == 1
    saved = r1.path.read_text(encoding="utf-8")
    assert KEY not in saved and "Authorization" not in saved
    w = json.loads(saved)
    assert w["status"] == 200 and w["fetched_at"] and w["request"]["window_id"] == "test-window"
    assert r1.path == tmp_path / "raw" / "test-window" / "battlelog" / "ABC.json"


def test_retry_on_429_then_success(tmp_path):
    c, sess = client(tmp_path, [FakeResp(429, {}), FakeResp(503, {}), FakeResp(200, {"items": []})])
    r = c.cards()
    assert r.status == 200 and len(sess.calls) == 3


def test_gives_up_after_retries(tmp_path):
    c, _ = client(tmp_path, [FakeResp(429, {})] * 3)
    with pytest.raises(ApiError, match="429"):
        c.cards()
    assert not (tmp_path / "raw" / "test-window" / "cards" / "cards.json").exists()


def test_403_explains_ip_binding_without_leaking_key(tmp_path):
    c, _ = client(tmp_path, [FakeResp(403, {"reason": "accessDenied.invalidIp"})])
    with pytest.raises(ApiError) as e:
        c.cards()
    assert "IP" in str(e.value) and KEY not in str(e.value)


def test_404_cached(tmp_path):
    c, sess = client(tmp_path, [FakeResp(404, {"reason": "notFound"})])
    assert c.battlelog("#NOPE").status == 404
    assert c.battlelog("#NOPE").from_cache and len(sess.calls) == 1


def test_missing_key_is_clear(tmp_path, monkeypatch):
    monkeypatch.delenv("CR_API_KEY", raising=False)
    monkeypatch.setattr("crdeck.api.PROJECT_ROOT", tmp_path)  # no .env here
    c = ApiClient(paths=Paths(source="real", root=tmp_path), cfg=CFG, session=FakeSession([]), sleep=lambda s: None)
    with pytest.raises(ApiError, match="No API key"):
        c.cards()


def test_never_writes_into_synthetic_root(tmp_path):
    with pytest.raises(ApiError):
        ApiClient(paths=Paths(source="synthetic", root=tmp_path), cfg=CFG, key=KEY)
