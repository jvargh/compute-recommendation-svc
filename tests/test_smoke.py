import json
import sys
from unittest.mock import MagicMock

import httpx
import pytest

import smoke


def test_smoke_requires_explicit_live_opt_in(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["smoke.py"])
    with pytest.raises(SystemExit) as exc:
        smoke.main()
    assert exc.value.code == 2


@pytest.mark.parametrize("status,expected_posts,exit_code", [(200, 2, 0), (429, 1, 1)])
def test_smoke_cache_check_and_no_retry_on_failure(
    monkeypatch, tmp_path, status, expected_posts, exit_code,
):
    output = tmp_path / "evidence.json"
    monkeypatch.setattr(sys, "argv", [
        "smoke.py", "--live", "--api-version", "2026-09-05-preview",
        "--resource-group", "existing-rg", "--output", str(output),
    ])
    client = MagicMock()
    client.__enter__.return_value = client
    client.get.return_value = httpx.Response(200, json={"properties": {"state": "Registered"}})
    if status == 200:
        client.post.side_effect = [
            httpx.Response(200, json={"placementScores": []}, headers={"x-poc-cache": cache})
            for cache in ("MISS", "HIT", "MISS", "HIT")
        ]
    else:
        client.post.return_value = httpx.Response(
            status, json={"error": {"code": "ThrottleLimitReached"}},
        )
    monkeypatch.setattr(smoke, "TestClient", lambda app: client)
    assert smoke.main() == exit_code
    assert client.post.call_count == expected_posts * (2 if status == 200 else 1)
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["apiVersion"] == "2026-09-05-preview"
    assert report["checks"][2]["cache"] == ("HIT" if status == 200 else None)
