"""
Tests for the system prompts (personas) CRUD endpoints.

Covers: create, list, get, update, delete, auth enforcement, ownership isolation.
"""

import pytest

VALID_PROMPT = {
    "name": "Legal expert",
    "description": "Answers using legal terminology",
    "content": "You are a legal analyst. Cite clause numbers when possible.",
}


@pytest.mark.asyncio
async def test_create_prompt(auth_client):
    client, _ = auth_client
    res = await client.post("/api/v1/system-prompts/", json=VALID_PROMPT)
    assert res.status_code == 201
    data = res.json()
    assert data["name"] == "Legal expert"
    assert data["content"] == VALID_PROMPT["content"]
    assert "id" in data
    assert "created_at" in data


@pytest.mark.asyncio
async def test_list_prompts_empty(auth_client):
    client, _ = auth_client
    res = await client.get("/api/v1/system-prompts/")
    assert res.status_code == 200
    assert res.json() == []


@pytest.mark.asyncio
async def test_list_prompts_after_create(auth_client):
    client, _ = auth_client
    await client.post("/api/v1/system-prompts/", json=VALID_PROMPT)
    await client.post("/api/v1/system-prompts/", json={
        "name": "Tutor",
        "content": "You are a patient teacher.",
    })
    res = await client.get("/api/v1/system-prompts/")
    assert res.status_code == 200
    names = [p["name"] for p in res.json()]
    assert "Legal expert" in names
    assert "Tutor" in names


@pytest.mark.asyncio
async def test_get_prompt_by_id(auth_client):
    client, _ = auth_client
    create = await client.post("/api/v1/system-prompts/", json=VALID_PROMPT)
    prompt_id = create.json()["id"]

    res = await client.get(f"/api/v1/system-prompts/{prompt_id}")
    assert res.status_code == 200
    assert res.json()["id"] == prompt_id


@pytest.mark.asyncio
async def test_get_nonexistent_prompt_returns_404(auth_client):
    client, _ = auth_client
    res = await client.get("/api/v1/system-prompts/99999")
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_update_prompt(auth_client):
    client, _ = auth_client
    create = await client.post("/api/v1/system-prompts/", json=VALID_PROMPT)
    prompt_id = create.json()["id"]

    res = await client.put(f"/api/v1/system-prompts/{prompt_id}", json={"name": "Updated"})
    assert res.status_code == 200
    assert res.json()["name"] == "Updated"
    # Unchanged fields preserved
    assert res.json()["content"] == VALID_PROMPT["content"]


@pytest.mark.asyncio
async def test_delete_prompt(auth_client):
    client, _ = auth_client
    create = await client.post("/api/v1/system-prompts/", json=VALID_PROMPT)
    prompt_id = create.json()["id"]

    res = await client.delete(f"/api/v1/system-prompts/{prompt_id}")
    assert res.status_code == 204

    get = await client.get(f"/api/v1/system-prompts/{prompt_id}")
    assert get.status_code == 404


@pytest.mark.asyncio
async def test_delete_nonexistent_prompt_returns_404(auth_client):
    client, _ = auth_client
    res = await client.delete("/api/v1/system-prompts/99999")
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_prompt_requires_auth(client):
    res = await client.get("/api/v1/system-prompts/")
    assert res.status_code == 401

    res = await client.post("/api/v1/system-prompts/", json=VALID_PROMPT)
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_prompt_ownership_isolation(auth_client, client):
    """User A cannot read or modify User B's prompts — returns 404."""
    user_a, _ = auth_client
    create = await user_a.post("/api/v1/system-prompts/", json=VALID_PROMPT)
    prompt_id = create.json()["id"]

    # Register User B
    reg = await client.post("/api/v1/auth/register", json={
        "email": "userb@nexus.ai",
        "password": "password999",
        "full_name": "User B",
    })
    client.headers["Authorization"] = f"Bearer {reg.json()['access_token']}"

    assert (await client.get(f"/api/v1/system-prompts/{prompt_id}")).status_code == 404
    assert (await client.put(f"/api/v1/system-prompts/{prompt_id}", json={"name": "Hacked"})).status_code == 404
    assert (await client.delete(f"/api/v1/system-prompts/{prompt_id}")).status_code == 404


@pytest.mark.asyncio
async def test_create_prompt_without_description(auth_client):
    client, _ = auth_client
    res = await client.post("/api/v1/system-prompts/", json={
        "name": "Minimal",
        "content": "Be brief.",
    })
    assert res.status_code == 201
    assert res.json()["description"] is None


@pytest.mark.asyncio
async def test_create_prompt_missing_content_fails(auth_client):
    client, _ = auth_client
    res = await client.post("/api/v1/system-prompts/", json={"name": "No content"})
    assert res.status_code == 422  # Pydantic validation
