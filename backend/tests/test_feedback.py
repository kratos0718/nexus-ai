"""
Tests for the feedback (RLHF thumbs up/down) endpoints.

Covers: submit positive/negative, stats calculation, JSONL export, auth enforcement.
"""

import json
import pytest


SAMPLE_FEEDBACK = {
    "question": "What is the refund policy?",
    "answer": "Refunds are accepted within 30 days of purchase.",
    "rating": 1,
    "retrieval_mode": "standard",
}


@pytest.mark.asyncio
async def test_submit_positive_feedback(auth_client):
    client, _ = auth_client
    res = await client.post("/api/v1/feedback/", json=SAMPLE_FEEDBACK)
    assert res.status_code == 201
    data = res.json()
    assert data["rating"] == 1
    assert "id" in data
    assert "created_at" in data


@pytest.mark.asyncio
async def test_submit_negative_feedback(auth_client):
    client, _ = auth_client
    payload = {**SAMPLE_FEEDBACK, "rating": -1}
    res = await client.post("/api/v1/feedback/", json=payload)
    assert res.status_code == 201
    assert res.json()["rating"] == -1


@pytest.mark.asyncio
async def test_feedback_with_comment(auth_client):
    client, _ = auth_client
    res = await client.post("/api/v1/feedback/", json={
        **SAMPLE_FEEDBACK,
        "comment": "The answer was missing details about international orders.",
    })
    assert res.status_code == 201


@pytest.mark.asyncio
async def test_stats_empty(auth_client):
    client, _ = auth_client
    res = await client.get("/api/v1/feedback/stats")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 0
    assert data["positive"] == 0
    assert data["negative"] == 0
    assert data["positive_rate"] == 0.0


@pytest.mark.asyncio
async def test_stats_after_feedback(auth_client):
    client, _ = auth_client
    await client.post("/api/v1/feedback/", json={**SAMPLE_FEEDBACK, "rating": 1})
    await client.post("/api/v1/feedback/", json={**SAMPLE_FEEDBACK, "rating": 1})
    await client.post("/api/v1/feedback/", json={**SAMPLE_FEEDBACK, "rating": -1})

    res = await client.get("/api/v1/feedback/stats")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 3
    assert data["positive"] == 2
    assert data["negative"] == 1
    assert data["positive_rate"] == pytest.approx(66.7, abs=0.1)


@pytest.mark.asyncio
async def test_export_feedback_returns_jsonl(auth_client):
    client, _ = auth_client
    await client.post("/api/v1/feedback/", json=SAMPLE_FEEDBACK)

    res = await client.get("/api/v1/feedback/export")
    assert res.status_code == 200
    assert "ndjson" in res.headers.get("content-type", "")

    lines = [l for l in res.text.strip().split("\n") if l]
    assert len(lines) == 1

    record = json.loads(lines[0])
    assert "messages" in record
    assert len(record["messages"]) == 2
    assert record["messages"][0]["role"] == "user"
    assert record["messages"][1]["role"] == "assistant"
    assert record["rating"] == 1


@pytest.mark.asyncio
async def test_export_multiple_records(auth_client):
    client, _ = auth_client
    await client.post("/api/v1/feedback/", json={**SAMPLE_FEEDBACK, "rating": 1})
    await client.post("/api/v1/feedback/", json={**SAMPLE_FEEDBACK, "rating": -1})

    res = await client.get("/api/v1/feedback/export")
    lines = [l for l in res.text.strip().split("\n") if l]
    assert len(lines) == 2
    ratings = [json.loads(l)["rating"] for l in lines]
    assert set(ratings) == {1, -1}


@pytest.mark.asyncio
async def test_feedback_requires_auth(client):
    res = await client.post("/api/v1/feedback/", json=SAMPLE_FEEDBACK)
    assert res.status_code == 401

    res = await client.get("/api/v1/feedback/stats")
    assert res.status_code == 401

    res = await client.get("/api/v1/feedback/export")
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_invalid_rating_rejected(auth_client):
    client, _ = auth_client
    res = await client.post("/api/v1/feedback/", json={
        **SAMPLE_FEEDBACK,
        "rating": 2,  # only 1 and -1 are valid
    })
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_feedback_stats_scoped_to_user(auth_client, client):
    """User A's feedback does not appear in User B's stats."""
    user_a, _ = auth_client
    await user_a.post("/api/v1/feedback/", json=SAMPLE_FEEDBACK)

    reg = await client.post("/api/v1/auth/register", json={
        "email": "userb_fb@nexus.ai",
        "password": "password123",
        "full_name": "User B",
    })
    client.headers["Authorization"] = f"Bearer {reg.json()['access_token']}"

    res = await client.get("/api/v1/feedback/stats")
    assert res.status_code == 200
    assert res.json()["total"] == 0  # B sees only their own feedback
