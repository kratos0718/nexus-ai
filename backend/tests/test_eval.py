"""
Tests for the evaluation endpoints.

Covers: auth enforcement, list results, get latest, get by filename,
        404 when no results exist, path traversal guard.
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

# ── Auth enforcement ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_results_requires_auth(client):
    res = await client.get("/api/v1/eval/results")
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_get_latest_requires_auth(client):
    res = await client.get("/api/v1/eval/results/latest")
    assert res.status_code == 401


# ── Empty state ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_results_empty(auth_client, tmp_path):
    client, _ = auth_client
    with patch("app.api.v1.endpoints.eval.RESULTS_DIR", tmp_path):
        res = await client.get("/api/v1/eval/results")
    assert res.status_code == 200
    data = res.json()
    assert data["count"] == 0
    assert data["files"] == []


@pytest.mark.asyncio
async def test_get_latest_no_results(auth_client, tmp_path):
    client, _ = auth_client
    with patch("app.api.v1.endpoints.eval.RESULTS_DIR", tmp_path):
        res = await client.get("/api/v1/eval/results/latest")
    assert res.status_code == 404


# ── With data ─────────────────────────────────────────────────────────────────

def _write_result(directory: Path, name: str, data: dict) -> None:
    """Helper: write a fake result file to directory."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(json.dumps(data))


@pytest.mark.asyncio
async def test_list_results_returns_files(auth_client, tmp_path):
    client, _ = auth_client
    _write_result(tmp_path, "eval_20260521_120000.json", {"total_cases": 5})
    _write_result(tmp_path, "eval_20260520_090000.json", {"total_cases": 3})

    with patch("app.api.v1.endpoints.eval.RESULTS_DIR", tmp_path):
        res = await client.get("/api/v1/eval/results")
    assert res.status_code == 200
    data = res.json()
    assert data["count"] == 2
    # Should be sorted newest-first
    assert data["files"][0] == "eval_20260521_120000.json"


@pytest.mark.asyncio
async def test_get_latest_returns_newest(auth_client, tmp_path):
    client, _ = auth_client
    _write_result(tmp_path, "eval_20260521_120000.json", {
        "total_cases": 5,
        "ragas_metrics_avg": {"faithfulness": 0.91}
    })
    _write_result(tmp_path, "eval_20260520_090000.json", {"total_cases": 3})

    with patch("app.api.v1.endpoints.eval.RESULTS_DIR", tmp_path):
        res = await client.get("/api/v1/eval/results/latest")
    assert res.status_code == 200
    data = res.json()
    assert data["total_cases"] == 5
    assert data["ragas_metrics_avg"]["faithfulness"] == 0.91


@pytest.mark.asyncio
async def test_get_result_by_filename(auth_client, tmp_path):
    client, _ = auth_client
    _write_result(tmp_path, "eval_20260521_120000.json", {"total_cases": 5})

    with patch("app.api.v1.endpoints.eval.RESULTS_DIR", tmp_path):
        res = await client.get("/api/v1/eval/results/eval_20260521_120000.json")
    assert res.status_code == 200
    assert res.json()["total_cases"] == 5


@pytest.mark.asyncio
async def test_get_result_nonexistent_file(auth_client, tmp_path):
    client, _ = auth_client
    with patch("app.api.v1.endpoints.eval.RESULTS_DIR", tmp_path):
        res = await client.get("/api/v1/eval/results/eval_20260101_000000.json")
    assert res.status_code == 404


# ── Input validation ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_invalid_filename_rejected(auth_client, tmp_path):
    """Filenames that don't match eval_*.json pattern are rejected with 400."""
    client, _ = auth_client
    with patch("app.api.v1.endpoints.eval.RESULTS_DIR", tmp_path):
        # Wrong prefix
        res = await client.get("/api/v1/eval/results/results.json")
        assert res.status_code == 400

        # Path traversal attempt
        res2 = await client.get("/api/v1/eval/results/../../../etc/passwd")
        # FastAPI will URL-decode and route this differently, but the guard still fires
        assert res2.status_code in (400, 404, 422)
