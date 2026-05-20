"""
Tests for authentication endpoints.

Covers: register, login, refresh, /me, duplicate email, wrong password.
"""

import pytest


@pytest.mark.asyncio
async def test_register_success(client):
    res = await client.post("/api/v1/auth/register", json={
        "email": "alice@nexus.ai",
        "password": "password123",
        "full_name": "Alice",
    })
    assert res.status_code == 201
    data = res.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_register_duplicate_email(client):
    payload = {"email": "bob@nexus.ai", "password": "password123", "full_name": "Bob"}
    await client.post("/api/v1/auth/register", json=payload)
    res = await client.post("/api/v1/auth/register", json=payload)
    assert res.status_code == 409
    assert "already registered" in res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_register_short_password(client):
    res = await client.post("/api/v1/auth/register", json={
        "email": "charlie@nexus.ai",
        "password": "short",
        "full_name": "Charlie",
    })
    assert res.status_code == 422  # Pydantic validation error


@pytest.mark.asyncio
async def test_login_success(client):
    await client.post("/api/v1/auth/register", json={
        "email": "dan@nexus.ai",
        "password": "password123",
        "full_name": "Dan",
    })
    res = await client.post("/api/v1/auth/login", json={
        "email": "dan@nexus.ai",
        "password": "password123",
    })
    assert res.status_code == 200
    assert "access_token" in res.json()


@pytest.mark.asyncio
async def test_login_wrong_password(client):
    await client.post("/api/v1/auth/register", json={
        "email": "eve@nexus.ai",
        "password": "correct_password",
        "full_name": "Eve",
    })
    res = await client.post("/api/v1/auth/login", json={
        "email": "eve@nexus.ai",
        "password": "wrong_password",
    })
    assert res.status_code == 401
    # Same message for wrong email AND wrong password (prevents enumeration)
    assert "invalid" in res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_login_unknown_email(client):
    res = await client.post("/api/v1/auth/login", json={
        "email": "nobody@nexus.ai",
        "password": "password123",
    })
    assert res.status_code == 401
    # Same error as wrong password — no user enumeration
    assert "invalid" in res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_get_me(auth_client):
    client, token = auth_client
    res = await client.get("/api/v1/auth/me")
    assert res.status_code == 200
    data = res.json()
    assert data["email"] == "test@nexus.ai"
    assert data["full_name"] == "Test User"
    assert "hashed_password" not in data  # never expose password hash


@pytest.mark.asyncio
async def test_get_me_no_token(client):
    res = await client.get("/api/v1/auth/me")
    assert res.status_code == 401  # no Authorization header → 401


@pytest.mark.asyncio
async def test_get_me_invalid_token(client):
    client.headers["Authorization"] = "Bearer totally.invalid.token"
    res = await client.get("/api/v1/auth/me")
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_refresh_token(auth_client):
    client, _ = auth_client
    # Get refresh token from login
    login = await client.post("/api/v1/auth/login", json={
        "email": "test@nexus.ai",
        "password": "testpass123",
    })
    refresh_token = login.json()["refresh_token"]

    res = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert res.status_code == 200
    assert "access_token" in res.json()
    assert "refresh_token" in res.json()  # rotated


@pytest.mark.asyncio
async def test_refresh_with_access_token_fails(auth_client):
    client, access_token = auth_client
    # Access token must not work as refresh token
    res = await client.post("/api/v1/auth/refresh", json={"refresh_token": access_token})
    assert res.status_code == 401
