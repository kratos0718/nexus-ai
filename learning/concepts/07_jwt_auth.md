# Concept 7 — JWT Authentication Deep Dive

## What Is a JWT?

JSON Web Token — a compact, self-contained token for transmitting claims between parties.

```
Header.Payload.Signature
```

Each part is base64url-encoded (URL-safe, no `+`, `/`, `=`).

### Header
```json
{
  "alg": "HS256",   // HMAC-SHA256 — symmetric key algorithm
  "typ": "JWT"
}
```

### Payload (Claims)
```json
{
  "sub": "42",                    // subject — who the token is about
  "email": "user@example.com",   // custom claim
  "type": "access",              // custom: distinguish access vs refresh
  "iat": 1700000000,             // issued at (Unix timestamp)
  "exp": 1700001800              // expires at (30 min later)
}
```

Standard claims (defined by RFC 7519): `sub`, `iss`, `aud`, `exp`, `nbf`, `iat`, `jti`.
Custom claims: anything you add (prefix with your domain to avoid conflicts in prod).

### Signature
```
HMAC-SHA256(
    base64url(header) + "." + base64url(payload),
    secret_key
)
```

If you change even one character in the payload, the signature becomes invalid.

---

## HS256 vs RS256

| | HS256 | RS256 |
|--|--|--|
| Algorithm | HMAC-SHA256 | RSA with SHA-256 |
| Key type | Single shared secret | Private key (sign) + Public key (verify) |
| Who can verify | Anyone with the secret | Anyone with the public key |
| Use case | Monolith / single service | Microservices, third-party verification |
| Security | Secret must be kept private | Public key can be shared safely |

**When to use RS256:** Multiple services need to verify tokens (e.g., auth service signs, API gateway verifies, individual services verify — public key is distributed freely).

We use HS256 because we have one service with one secret.

---

## Access Token vs Refresh Token

```
                    ┌──────────────────────────────────────────┐
                    │              Token Lifecycle              │
                    └──────────────────────────────────────────┘

Login ──────────────► Server issues:
                         Access Token (30 min, type="access")
                         Refresh Token (7 days, type="refresh")

Every API call ──────► Client sends: Authorization: Bearer <access_token>
                        Server verifies signature + expiry + type="access"

Access expires ──────► Client sends: POST /auth/refresh {refresh_token: ...}
                        Server verifies type="refresh" + expiry
                        Issues NEW access token + rotates refresh token

Refresh expires ──────► User must log in again
```

### Token Rotation

Each `/auth/refresh` call returns a NEW refresh token and invalidates conceptually the old one.
This makes stolen refresh tokens a 1-use weapon — the legitimate user's next refresh call will use the new token and the attacker's copy becomes irrelevant.

(True revocation requires a token blacklist in Redis — we skip that for now.)

---

## The FastAPI Dependency Graph

```python
# dependencies.py

from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

bearer_scheme = HTTPBearer()

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    ...
```

```
Request arrives at protected endpoint
       ↓
FastAPI sees Depends(get_current_user)
       ↓
FastAPI sees get_current_user needs Depends(bearer_scheme) and Depends(get_db)
       ↓
HTTPBearer extracts "Authorization: Bearer <token>" header
       (raises 403 automatically if header missing)
       ↓
get_db creates DB session
       ↓
get_current_user runs: verifies token, loads user
       ↓
If valid: injects User object into endpoint function
If invalid: raises HTTPException(401) — endpoint never runs
```

Dependency graph is a DAG — FastAPI resolves dependencies in order, caches shared dependencies within one request (get_db is called once even if multiple dependencies need it).

---

## Security Checklist

### What We Do Right
- [x] bcrypt with cost factor 12 (slow hashing)
- [x] Same error for wrong email AND wrong password (prevents user enumeration)
- [x] Short-lived access tokens (30 min)
- [x] Refresh token rotation
- [x] Token type checking (`payload["type"] == "access"`)
- [x] `is_active` flag check (can disable accounts without deleting)
- [x] JWT_SECRET from environment variable (never hardcoded in prod)

### What Production Would Add
- [ ] Refresh token blacklist in Redis (true revocation)
- [ ] Rate limiting on `/auth/login` (prevent brute force)
- [ ] HTTPS only (tokens in transit are plaintext without TLS)
- [ ] `Secure` + `HttpOnly` cookies instead of localStorage (prevents XSS token theft)
- [ ] Token binding (bind token to device fingerprint)

---

## Common JWT Mistakes

### 1. Algorithm Confusion ("alg: none" attack)
```python
# VULNERABLE:
jwt.decode(token, secret)  # no algorithms parameter

# An attacker can send: {"alg": "none"} → signature is skipped!

# SAFE:
jwt.decode(token, secret, algorithms=["HS256"])  # explicitly whitelist
```

### 2. Storing JWT in localStorage
```javascript
// VULNERABLE — XSS can steal it
localStorage.setItem("token", jwt)

// SAFER — HttpOnly cookie can't be accessed by JavaScript
// Set-Cookie: token=...; HttpOnly; Secure; SameSite=Strict
```

### 3. Not Verifying Token Type
```python
# Without this check, a refresh token works as an access token
if payload.get("type") != "access":
    raise HTTPException(401, "Wrong token type")
```

### 4. Long-Lived Access Tokens
```python
# BAD — 30 day access token
ACCESS_TOKEN_EXPIRE_MINUTES = 43200

# GOOD — 30 minute access token
ACCESS_TOKEN_EXPIRE_MINUTES = 30
```

If an access token is stolen, short expiry limits the damage window.

---

## Interview Questions on JWT

**Q: Where should you store JWTs on the frontend?**
A: HttpOnly cookies (prevents XSS theft) with SameSite=Strict (prevents CSRF). localStorage is convenient but vulnerable to XSS.

**Q: How do you invalidate a JWT before it expires?**
A: JWTs are stateless — you can't "un-issue" one. Options: (1) Redis blacklist of invalidated JTIs (JWT IDs), (2) short expiry windows, (3) secret key rotation (invalidates ALL tokens — nuclear option).

**Q: What does "sub" mean in a JWT?**
A: "Subject" — standardized RFC 7519 claim identifying who the token is about. Typically the user's ID. Must be a string per spec.

**Q: What's the difference between authentication and authorization?**
A: Authentication = "who are you?" (login, JWT verification). Authorization = "what can you do?" (role checks, permission checks after knowing identity).
