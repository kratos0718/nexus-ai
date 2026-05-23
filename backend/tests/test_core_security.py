"""
Unit tests for app.core.security — JWT creation/decoding and password hashing.

These are pure Python tests (no HTTP client, no database).
"""


from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)

# ── Password hashing ──────────────────────────────────────────────────────────

def test_hash_password_returns_string():
    h = hash_password("mysecretpassword")
    assert isinstance(h, str)
    assert len(h) > 20


def test_hash_is_not_plaintext():
    h = hash_password("mysecretpassword")
    assert "mysecretpassword" not in h


def test_verify_correct_password():
    plain = "correctpassword"
    hashed = hash_password(plain)
    assert verify_password(plain, hashed) is True


def test_verify_wrong_password():
    hashed = hash_password("correctpassword")
    assert verify_password("wrongpassword", hashed) is False


def test_same_password_different_hashes():
    """bcrypt uses random salt — same password hashes differently each time."""
    h1 = hash_password("password")
    h2 = hash_password("password")
    assert h1 != h2  # different salts
    assert verify_password("password", h1) is True
    assert verify_password("password", h2) is True


# ── JWT access tokens ─────────────────────────────────────────────────────────

def test_create_access_token_returns_string():
    token = create_access_token(user_id=1, email="test@example.com")
    assert isinstance(token, str)
    assert len(token) > 20


def test_decode_valid_access_token():
    token = create_access_token(user_id=42, email="alice@example.com")
    payload = decode_token(token)

    assert payload is not None
    assert payload["sub"] == "42"
    assert payload["email"] == "alice@example.com"
    assert payload["type"] == "access"


def test_access_token_has_expiry():
    token = create_access_token(user_id=1, email="test@example.com")
    payload = decode_token(token)
    assert "exp" in payload


def test_decode_invalid_token_returns_none():
    assert decode_token("not.a.valid.token") is None


def test_decode_tampered_token_returns_none():
    token = create_access_token(user_id=1, email="test@example.com")
    tampered = token[:-5] + "XXXXX"
    assert decode_token(tampered) is None


def test_decode_empty_string_returns_none():
    assert decode_token("") is None


# ── JWT refresh tokens ────────────────────────────────────────────────────────

def test_create_refresh_token_returns_string():
    token = create_refresh_token(user_id=5)
    assert isinstance(token, str)


def test_decode_valid_refresh_token():
    token = create_refresh_token(user_id=99)
    payload = decode_token(token)

    assert payload is not None
    assert payload["sub"] == "99"
    assert payload["type"] == "refresh"


def test_access_and_refresh_tokens_are_different():
    access = create_access_token(user_id=1, email="test@example.com")
    refresh = create_refresh_token(user_id=1)
    assert access != refresh


def test_access_token_type_check():
    """Caller must verify token type to prevent refresh tokens being used as access."""
    refresh = create_refresh_token(user_id=1)
    payload = decode_token(refresh)
    # The type field distinguishes tokens — endpoint must check payload["type"] == "access"
    assert payload["type"] == "refresh"
    assert payload["type"] != "access"


# ── Expired token ─────────────────────────────────────────────────────────────

def test_expired_token_returns_none():
    """Simulate an expired token by back-dating the expiry."""
    from datetime import UTC, datetime, timedelta

    from jose import jwt

    from app.core.security import JWT_ALGORITHM, JWT_SECRET

    expired_payload = {
        "sub": "1",
        "email": "test@example.com",
        "type": "access",
        "exp": datetime.now(UTC) - timedelta(seconds=1),  # already expired
    }
    token = jwt.encode(expired_payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    assert decode_token(token) is None
