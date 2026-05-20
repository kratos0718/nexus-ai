"""
Tests for document management endpoints.

The RAG pipeline (embedding, ChromaDB) is mocked so tests run
fast without GPU/model downloads.
"""

import io
import pytest
from unittest.mock import patch, AsyncMock


def _mock_pipeline_result(chunks=5):
    return {"document_id": "test-doc-id", "chunks_indexed": chunks}


@pytest.mark.asyncio
async def test_list_documents_empty(auth_client):
    client, _ = auth_client
    res = await client.get("/api/v1/documents/")
    assert res.status_code == 200
    assert res.json()["total"] == 0
    assert res.json()["documents"] == []


@pytest.mark.asyncio
async def test_upload_document_success(auth_client):
    client, _ = auth_client

    with patch("app.services.rag_service.RAGService.index_file_background", new_callable=AsyncMock):
        res = await client.post(
            "/api/v1/documents/upload",
            files={"file": ("policy.txt", io.BytesIO(b"vacation policy content"), "text/plain")},
        )

    assert res.status_code == 202
    data = res.json()
    assert data["filename"] == "policy.txt"
    assert data["status"] == "pending"
    assert "document_id" in data


@pytest.mark.asyncio
async def test_upload_disallowed_extension(auth_client):
    client, _ = auth_client
    res = await client.post(
        "/api/v1/documents/upload",
        files={"file": ("script.py", io.BytesIO(b"print('hi')"), "text/plain")},
    )
    assert res.status_code == 400
    assert "not supported" in res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_upload_requires_auth(client):
    res = await client.post(
        "/api/v1/documents/upload",
        files={"file": ("doc.txt", io.BytesIO(b"content"), "text/plain")},
    )
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_list_documents_after_upload(auth_client):
    client, _ = auth_client

    with patch("app.services.rag_service.RAGService.index_file_background", new_callable=AsyncMock):
        await client.post(
            "/api/v1/documents/upload",
            files={"file": ("doc.txt", io.BytesIO(b"content"), "text/plain")},
        )

    res = await client.get("/api/v1/documents/")
    assert res.status_code == 200
    assert res.json()["total"] == 1
    assert res.json()["documents"][0]["filename"] == "doc.txt"


@pytest.mark.asyncio
async def test_get_document_status(auth_client):
    client, _ = auth_client

    with patch("app.services.rag_service.RAGService.index_file_background", new_callable=AsyncMock):
        upload = await client.post(
            "/api/v1/documents/upload",
            files={"file": ("report.txt", io.BytesIO(b"content"), "text/plain")},
        )
    doc_id = upload.json()["document_id"]

    res = await client.get(f"/api/v1/documents/{doc_id}/status")
    assert res.status_code == 200
    assert res.json()["document_id"] == doc_id


@pytest.mark.asyncio
async def test_get_other_users_document_returns_404(auth_client, client, db_session):
    """Users cannot see each other's documents — isolation test."""
    user1_client, _ = auth_client

    # User 1 uploads a document
    with patch("app.services.rag_service.RAGService.index_file_background", new_callable=AsyncMock):
        upload = await user1_client.post(
            "/api/v1/documents/upload",
            files={"file": ("secret.txt", io.BytesIO(b"secret"), "text/plain")},
        )
    doc_id = upload.json()["document_id"]

    # User 2 registers and tries to access user 1's document
    reg2 = await client.post("/api/v1/auth/register", json={
        "email": "user2@nexus.ai",
        "password": "password456",
        "full_name": "User Two",
    })
    client.headers["Authorization"] = f"Bearer {reg2.json()['access_token']}"
    res = await client.get(f"/api/v1/documents/{doc_id}/status")
    assert res.status_code == 404  # not 403 — don't reveal document exists


@pytest.mark.asyncio
async def test_delete_document(auth_client):
    client, _ = auth_client

    with patch("app.services.rag_service.RAGService.index_file_background", new_callable=AsyncMock):
        upload = await client.post(
            "/api/v1/documents/upload",
            files={"file": ("todelete.txt", io.BytesIO(b"content"), "text/plain")},
        )
    doc_id = upload.json()["document_id"]

    with patch("app.services.rag_service.RAGService.delete_document", new_callable=AsyncMock) as mock_del:
        mock_del.return_value = True
        res = await client.delete(f"/api/v1/documents/{doc_id}")
        assert res.status_code == 204
        mock_del.assert_called_once()
        call_kwargs = mock_del.call_args
        assert doc_id in call_kwargs.args or call_kwargs.kwargs.get("document_id") == doc_id
