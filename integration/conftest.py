"""
Shared fixtures for the integration suite (development guideline 6.3.2).

Tests call real HTTP endpoints on the gateway at STAGING_API_URL. There is no mock
fallback: if the gateway is unreachable the tests are skipped, never silently faked.
Every account/course a test creates is removed afterwards through the admin API.
"""

import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterator, List

import httpx
import jwt
import pytest

BASE_URL = os.getenv("STAGING_API_URL", "http://localhost").rstrip("/")
# No default: the signing key of the system under test must be supplied (see .env.example).
JWT_SECRET_KEY = os.getenv("SECRET_KEY", "")
JWT_ALGORITHM = "HS256"
# Resend's test inbox accepts any "+label", delivers nothing and never bounces.
EMAIL_DOMAIN = os.getenv("SMOKE_EMAIL_DOMAIN", "resend.dev")
EMAIL_USER = os.getenv("SMOKE_EMAIL_USER", "delivered")
TEST_PASSWORD = "IntegTest123!"
REQUEST_TIMEOUT = 30.0
EVENT_WAIT_SECONDS = int(os.getenv("SMOKE_EVENT_WAIT_SECONDS", "30"))
# The gateway rate-limits each IP to 100 requests a minute, so requests are spaced out.
REQUEST_INTERVAL_SECONDS = float(os.getenv("INTEGRATION_REQUEST_INTERVAL", "0.65"))
# Tokens are issued slightly in the past so a clock that runs a little ahead of the
# server's does not make the server reject them as "not yet valid".
TOKEN_BACKDATE = timedelta(seconds=60)


def _signed(payload: Dict[str, Any]) -> str:
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def admin_headers() -> Dict[str, str]:
    """An admin access token signed like auth_service's, for setup/cleanup calls."""
    now = datetime.now(timezone.utc)
    token = _signed(
        {
            "sub": "0",
            "email": "integration-test@edura.lk",
            "role": "ADMIN",
            "iat": now - TOKEN_BACKDATE,
            "exp": now + timedelta(minutes=15),
        }
    )
    return {"Authorization": f"Bearer {token}"}


def role_headers(role: str, user_id: int = 0) -> Dict[str, str]:
    """A signed access token for an arbitrary role (e.g. notification_manager)."""
    now = datetime.now(timezone.utc)
    token = _signed(
        {
            "sub": str(user_id),
            "email": f"{role}-integration@edura.lk",
            "role": role,
            "iat": now - TOKEN_BACKDATE,
            "exp": now + timedelta(minutes=15),
        }
    )
    return {"Authorization": f"Bearer {token}"}


def email_verification_token(user_id: int, email: str) -> str:
    """The same signed token auth_service puts in the verification email link."""
    now = datetime.now(timezone.utc)
    return _signed(
        {
            "sub": str(user_id),
            "purpose": "email_verification",
            "email": email,
            "iat": now - TOKEN_BACKDATE,
            "exp": now + timedelta(minutes=15),
        }
    )


def unique_email(label: str = "integ") -> str:
    return (
        f"{EMAIL_USER}+{label}{int(time.time())}{uuid.uuid4().hex[:6]}@{EMAIL_DOMAIN}"
    )


def wait_until(fetch, done, seconds: int = EVENT_WAIT_SECONDS) -> httpx.Response:
    """Repeats a request once a second until done(response) or the time runs out."""
    deadline = time.monotonic() + seconds
    res = fetch()
    while not done(res) and time.monotonic() < deadline:
        time.sleep(1)
        res = fetch()
    return res


@pytest.fixture(scope="session")
def client() -> Iterator[httpx.Client]:
    if not JWT_SECRET_KEY:
        pytest.skip("SECRET_KEY is not set; see .env.example")
    with httpx.Client(
        base_url=BASE_URL, timeout=REQUEST_TIMEOUT, follow_redirects=True
    ) as c:
        send = c.send
        last_sent = [0.0]

        def paced_send(*args, **kwargs):
            wait = REQUEST_INTERVAL_SECONDS - (time.monotonic() - last_sent[0])
            if wait > 0:
                time.sleep(wait)
            last_sent[0] = time.monotonic()
            return send(*args, **kwargs)

        c.send = paced_send
        try:
            health = c.get("/api/auth/health", timeout=3.0)
        except httpx.HTTPError as exc:
            pytest.skip(f"Gateway {BASE_URL} unreachable: {exc}")
        if health.status_code != 200:
            pytest.skip(f"Gateway {BASE_URL} unhealthy: HTTP {health.status_code}")
        yield c


@pytest.fixture
def created_users(client: httpx.Client) -> Iterator[List[int]]:
    """Collects user ids a test registers; removes profile + login afterwards."""
    ids: List[int] = []
    yield ids
    for uid in ids:
        for path in (f"/api/users/{uid}", f"/api/auth/users/{uid}"):
            try:
                client.delete(path, headers=admin_headers())
            except httpx.HTTPError:
                pass


@pytest.fixture
def created_courses(client: httpx.Client) -> Iterator[List[int]]:
    ids: List[int] = []
    yield ids
    for cid in ids:
        try:
            client.delete(f"/api/courses/{cid}", headers=admin_headers())
        except httpx.HTTPError:
            pass


@pytest.fixture
def student(client: httpx.Client, created_users: List[int]) -> Dict[str, Any]:
    """Given a registered, email-verified student account."""
    email = unique_email("stu")
    res = client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": TEST_PASSWORD,
            "role": "student",
            "profile": {"first_name": "Integ", "last_name": "Test"},
        },
    )
    assert res.status_code in (200, 201), res.text
    user_id = res.json()["id"]
    created_users.append(user_id)
    verify = client.post(
        "/api/auth/verify-email",
        json={"token": email_verification_token(user_id, email)},
    )
    assert verify.status_code == 200, verify.text
    return {"id": user_id, "email": email, "password": TEST_PASSWORD}


@pytest.fixture
def student_headers(client: httpx.Client, student: Dict[str, Any]) -> Dict[str, str]:
    res = client.post(
        "/api/auth/login",
        json={"email": student["email"], "password": student["password"]},
    )
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}
