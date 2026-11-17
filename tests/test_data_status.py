"""web/data_status.json from the files the site already serves (crdeck.explore.data_status.from_site / refresh)."""

import json

from crdeck.explore import data_status


def test_refresh_reads_each_site_file_and_skips_missing_ones(tmp_path):
    (tmp_path / "models").mkdir()
    (tmp_path / "models" / "ranked.json").write_text(json.dumps({"meta": {"counts": {"last_battle": "2026-10-27 01:22:09+00:00"}}}), encoding="utf-8")
    (tmp_path / "modes.json").write_text(json.dumps({
        "default": "ranked", "log": {"export": {"exported_at": "2026-10-28T17:00:21Z"}},
        "modes": [{"slug": "ranked", "status": "exported", "file": "models/ranked.json",
                   "train_window": ["2026-09-01 14:58 UTC", "2026-10-23 03:31 UTC"], "test_window": ["2026-10-24 16:59 UTC", "2026-10-27 01:15 UTC"]}]}), encoding="utf-8")
    body = data_status.refresh(tmp_path)
    assert body == {"models": {"last_battle": "2026-10-27T01:22:09Z", "trained_from": "2026-09-01T14:58:00Z", "tested_to": "2026-10-27T01:15:00Z",
                               "exported": "2026-10-28T17:00:21Z", "written": "2026-10-28T17:00:21Z"}}
    (tmp_path / "future_meta.json").write_text(json.dumps({"written_at": "2026-11-12 08:43 UTC", "data": {"periods": [{"end": "2026-11-12 03:02:37+00:00"}]}}), encoding="utf-8")
    (tmp_path / "balance_watch.json").write_text(json.dumps({"cutoff": "2026-11-16T00:00:00Z", "generated_at": "2026-11-16T22:00:00Z", "status": "preview",
                                                             "window": {"start": "2026-11-02T00:00:00Z"}, "calendar": {"last_event": {"effective_date": "2026-10-19"}}}), encoding="utf-8")
    body = data_status.refresh(tmp_path)
    assert list(body) == ["models", "future_meta", "balance_watch"]
    assert body["future_meta"] == {"last_period_end": "2026-11-12T03:02:37Z", "periods": 1, "exported": "2026-11-12T08:43:00Z", "written": "2026-11-12T08:43:00Z"}
    assert body["balance_watch"]["cutoff"] == "2026-11-16T00:00:00Z" and body["balance_watch"]["last_update"] == "2026-10-19"
    assert data_status.read(tmp_path) == body


def test_iso_handles_every_time_format_the_site_uses():
    assert data_status._iso("2026-10-27 01:15 UTC") == "2026-10-27T01:15:00Z"
    assert data_status._iso("2026-10-27 01:22:09+00:00") == "2026-10-27T01:22:09Z"
    assert data_status._iso("2026-10-27T01:22:09Z") == "2026-10-27T01:22:09Z"
    assert data_status._iso(None) is None and data_status._iso("n/a") is None
