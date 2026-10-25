"""
Integration tests: auth_service through the gateway (session management).

Each test follows Arrange-Act-Assert with Given-When-Then names.
"""

from typing import Any, Dict, List

import httpx

from .conftest import (
    TEST_PASSWORD,
    admin_headers,
    email_verification_token,
    unique_email,
)


def _fresh_session(client: httpx.Client) -> httpx.Client:
    """A client with its own cookie jar, so refresh cookies don't leak between tests."""
    return httpx.Client(base_url=str(client.base_url), timeout=30.0)


class TestRegister:
    def test_given_new_email_when_register_then_returns_unverified_student(
        self, client: httpx.Client, created_users: List[int]
    ):
        # Arrange
        email = unique_email("reg")
        # Act
        res = client.post(
            "/api/auth/register",
            json={"email": email, "password": TEST_PASSWORD, "role": "student"},
        )
        # Assert
        assert res.status_code == 200, res.text
        body = res.json()
        created_users.append(body["id"])
        assert body["email"] == email
        assert body["role"] == "student"
        assert body["is_email_verified"] is False

    def test_given_existing_email_when_register_then_400_email_exists(
        self, client: httpx.Client, student: Dict[str, Any]
    ):
        res = client.post(
            "/api/auth/register",
            json={"email": student["email"], "password": TEST_PASSWORD},
        )
        assert res.status_code == 400
        assert res.json()["detail"]["error"] == "EMAIL_EXISTS"

    def test_given_admin_role_when_register_then_downgraded_to_student(
        self, client: httpx.Client, created_users: List[int]
    ):
        res = client.post(
            "/api/auth/register",
            json={
                "email": unique_email("adm"),
                "password": TEST_PASSWORD,
                "role": "admin",
            },
        )
        assert res.status_code == 200, res.text
        created_users.append(res.json()["id"])
        assert res.json()["role"] == "student"

    def test_given_weak_password_when_register_then_422(self, client: httpx.Client):
        res = client.post(
            "/api/auth/register",
            json={"email": unique_email("weak"), "password": "abc"},
        )
        assert res.status_code == 422


class TestVerifyEmail:
    def test_given_valid_token_when_verify_then_account_is_verified(
        self, client: httpx.Client, student_headers: Dict[str, str]
    ):
        # `student` already verified the account through /verify-email.
        res = client.get("/api/auth/me", headers=student_headers)
        assert res.status_code == 200, res.text
        assert res.json()["is_email_verified"] is True

    def test_given_garbage_token_when_verify_then_400(self, client: httpx.Client):
        res = client.post("/api/auth/verify-email", json={"token": "not-a-token"})
        assert res.status_code == 400
        assert res.json()["detail"]["error"] == "INVALID_VERIFICATION_TOKEN"

    def test_given_token_for_other_email_when_verify_then_400(
        self, client: httpx.Client, student: Dict[str, Any]
    ):
        token = email_verification_token(student["id"], "someone-else@example.com")
        res = client.post("/api/auth/verify-email", json={"token": token})
        assert res.status_code == 400


class TestLogin:
    def test_given_valid_credentials_when_login_then_returns_bearer_token(
        self, client: httpx.Client, student: Dict[str, Any]
    ):
        res = client.post(
            "/api/auth/login",
            json={"email": student["email"], "password": student["password"]},
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["access_token"]
        assert body["token_type"].lower() == "bearer"

    def test_given_wrong_password_when_login_then_401(
        self, client: httpx.Client, student: Dict[str, Any]
    ):
        res = client.post(
            "/api/auth/login",
            json={"email": student["email"], "password": "WrongPass999!"},
        )
        assert res.status_code == 401
        assert res.json()["detail"]["error"] == "INVALID_CREDENTIALS"

    def test_given_unknown_email_when_login_then_401(self, client: httpx.Client):
        res = client.post(
            "/api/auth/login",
            json={"email": unique_email("ghost"), "password": TEST_PASSWORD},
        )
        assert res.status_code == 401


class TestMeAndProtectedRoutes:
    def test_given_valid_token_when_get_me_then_returns_own_account(
        self,
        client: httpx.Client,
        student: Dict[str, Any],
        student_headers: Dict[str, str],
    ):
        res = client.get("/api/auth/me", headers=student_headers)
        assert res.status_code == 200
        assert res.json()["id"] == student["id"]
        assert res.json()["email"] == student["email"]

    def test_given_no_token_when_get_me_then_401(self, client: httpx.Client):
        assert client.get("/api/auth/me").status_code == 401

    def test_given_student_token_when_delete_user_then_403(
        self,
        client: httpx.Client,
        student: Dict[str, Any],
        student_headers: Dict[str, str],
    ):
        res = client.delete(f"/api/auth/users/{student['id']}", headers=student_headers)
        assert res.status_code == 403


class TestRefreshAndLogout:
    def test_given_valid_refresh_token_when_refresh_then_new_access_token(
        self, client: httpx.Client, student: Dict[str, Any]
    ):
        # Arrange: login stores the refresh cookie in this session's cookie jar
        with _fresh_session(client) as session:
            login = session.post(
                "/api/auth/login",
                json={"email": student["email"], "password": student["password"]},
            )
            assert login.status_code == 200, login.text
            # Act
            res = session.post("/api/auth/refresh", json={})
        # Assert
        assert res.status_code == 200, res.text
        assert res.json()["access_token"]

    def test_given_no_refresh_token_when_refresh_then_401_missing(
        self, client: httpx.Client
    ):
        with _fresh_session(client) as session:
            res = session.post("/api/auth/refresh", json={})
        assert res.status_code == 401
        assert res.json()["detail"]["error"] == "MISSING_REFRESH_TOKEN"

    def test_given_logged_in_session_when_logout_then_refresh_is_rejected(
        self, client: httpx.Client, student: Dict[str, Any]
    ):
        # Arrange
        with _fresh_session(client) as session:
            login = session.post(
                "/api/auth/login",
                json={"email": student["email"], "password": student["password"]},
            )
            assert login.status_code == 200, login.text
            token = session.cookies.get("refresh_token")
            assert token, "login should set the refresh_token cookie"
            # Act
            out = session.post("/api/auth/logout")
        # Assert: the revoked token no longer refreshes
        assert out.status_code == 200
        with _fresh_session(client) as other:
            res = other.post("/api/auth/refresh", json={"refresh_token": token})
        assert res.status_code == 401


class TestAdminUserManagement:
    def test_given_admin_when_delete_user_then_204_and_login_fails(
        self, client: httpx.Client, student: Dict[str, Any]
    ):
        res = client.delete(f"/api/auth/users/{student['id']}", headers=admin_headers())
        assert res.status_code == 204
        login = client.post(
            "/api/auth/login",
            json={"email": student["email"], "password": student["password"]},
        )
        assert login.status_code == 401

    def test_given_unknown_id_when_admin_delete_then_404(self, client: httpx.Client):
        res = client.delete("/api/auth/users/999999999", headers=admin_headers())
        assert res.status_code == 404
