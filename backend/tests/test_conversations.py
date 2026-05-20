"""Tests for conversation management endpoints."""

import pytest


@pytest.mark.asyncio
async def test_create_conversation(auth_client):
    client, _ = auth_client
    res = await client.post("/api/v1/conversations/", json={"title": "My first chat"})
    assert res.status_code == 201
    data = res.json()
    assert data["title"] == "My first chat"
    assert "conversation_id" in data
    assert data["message_count"] == 0


@pytest.mark.asyncio
async def test_list_conversations_empty(auth_client):
    client, _ = auth_client
    res = await client.get("/api/v1/conversations/")
    assert res.status_code == 200
    assert res.json() == []


@pytest.mark.asyncio
async def test_list_conversations_after_create(auth_client):
    client, _ = auth_client
    await client.post("/api/v1/conversations/", json={"title": "Chat A"})
    await client.post("/api/v1/conversations/", json={"title": "Chat B"})

    res = await client.get("/api/v1/conversations/")
    assert res.status_code == 200
    titles = [c["title"] for c in res.json()]
    assert "Chat A" in titles
    assert "Chat B" in titles


@pytest.mark.asyncio
async def test_get_conversation_detail(auth_client):
    client, _ = auth_client
    create = await client.post("/api/v1/conversations/", json={"title": "Detail test"})
    conv_id = create.json()["conversation_id"]

    res = await client.get(f"/api/v1/conversations/{conv_id}")
    assert res.status_code == 200
    assert res.json()["conversation_id"] == conv_id
    assert res.json()["messages"] == []


@pytest.mark.asyncio
async def test_get_other_users_conversation_returns_404(auth_client, client):
    user1, _ = auth_client
    create = await user1.post("/api/v1/conversations/", json={"title": "Private"})
    conv_id = create.json()["conversation_id"]

    # Register second user
    reg = await client.post("/api/v1/auth/register", json={
        "email": "u2@nexus.ai", "password": "password789", "full_name": "U2"
    })
    client.headers["Authorization"] = f"Bearer {reg.json()['access_token']}"

    res = await client.get(f"/api/v1/conversations/{conv_id}")
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_delete_conversation(auth_client):
    client, _ = auth_client
    create = await client.post("/api/v1/conversations/", json={"title": "To delete"})
    conv_id = create.json()["conversation_id"]

    res = await client.delete(f"/api/v1/conversations/{conv_id}")
    assert res.status_code == 204

    get = await client.get(f"/api/v1/conversations/{conv_id}")
    assert get.status_code == 404


@pytest.mark.asyncio
async def test_conversations_require_auth(client):
    res = await client.get("/api/v1/conversations/")
    assert res.status_code == 401
