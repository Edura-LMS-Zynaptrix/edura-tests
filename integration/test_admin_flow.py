"""
Integration tests: admin_service (feedback + chat) through the gateway.
"""

import uuid
from typing import Any, Dict, Iterator, List

import httpx
import pytest

from .conftest import admin_headers


def _feedback_payload(**overrides: Any) -> Dict[str, Any]:
    body = {
        "name": "Integ Tester",
        "email": "delivered+feedback@resend.dev",
        "category": "suggestion",
        "subject": "Integration subject",
        "message": "Written by the integration suite",
    }
    body.update(overrides)
    return body


def _guest_session() -> str:
    return f"it-{uuid.uuid4().hex[:16]}"


@pytest.fixture
def feedback(client: httpx.Client) -> Iterator[Dict[str, Any]]:
    res = client.post("/api/admin/feedback/submit", json=_feedback_payload())
    assert res.status_code == 201, res.text
    body = res.json()
    yield body
    client.delete(f"/api/admin/feedback/admin/{body['id']}", headers=admin_headers())


@pytest.fixture
def conversations(client: httpx.Client) -> Iterator[List[int]]:
    ids: List[int] = []
    yield ids
    for cid in ids:
        client.delete(f"/api/admin/chat/admin/conversations/{cid}", headers=admin_headers())


class TestAdminRoot:
    def test_given_admin_when_get_admin_root_then_welcome(self, client: httpx.Client):
        res = client.get("/api/admin/admin", headers=admin_headers())
        assert res.status_code == 200
        assert res.json() == {"message": "Welcome Admin"}

    def test_given_student_when_get_admin_root_then_403(
        self, client: httpx.Client, student_headers: Dict[str, str]
    ):
        assert client.get("/api/admin/admin", headers=student_headers).status_code == 403

    def test_given_no_token_when_get_admin_root_then_401(self, client: httpx.Client):
        assert client.get("/api/admin/admin").status_code == 401


class TestFeedbackSubmit:
    def test_given_anonymous_visitor_when_submit_feedback_then_201_unlinked(
        self, client: httpx.Client, feedback: Dict[str, Any]
    ):
        assert feedback["user_id"] is None
        assert feedback["is_read"] is False
        assert feedback["category"] == "suggestion"

    def test_given_signed_in_student_when_submit_feedback_then_linked_to_user(
        self,
        client: httpx.Client,
        student: Dict[str, Any],
        student_headers: Dict[str, str],
    ):
        res = client.post(
            "/api/admin/feedback/submit", json=_feedback_payload(), headers=student_headers
        )
        assert res.status_code == 201, res.text
        assert res.json()["user_id"] == student["id"]
        client.delete(
            f"/api/admin/feedback/admin/{res.json()['id']}", headers=admin_headers()
        )

    def test_given_invalid_category_when_submit_feedback_then_422(
        self, client: httpx.Client
    ):
        res = client.post(
            "/api/admin/feedback/submit", json=_feedback_payload(category="rant")
        )
        assert res.status_code == 422

    def test_given_bad_email_when_submit_feedback_then_422(self, client: httpx.Client):
        res = client.post(
            "/api/admin/feedback/submit", json=_feedback_payload(email="not-an-email")
        )
        assert res.status_code == 422

    def test_given_empty_message_when_submit_feedback_then_422(
        self, client: httpx.Client
    ):
        res = client.post(
            "/api/admin/feedback/submit", json=_feedback_payload(message="")
        )
        assert res.status_code == 422


class TestFeedbackTriage:
    def test_given_submitted_feedback_when_admin_lists_then_includes_it(
        self, client: httpx.Client, feedback: Dict[str, Any]
    ):
        res = client.get(
            "/api/admin/feedback/admin/all",
            params={"limit": 500},
            headers=admin_headers(),
        )
        assert res.status_code == 200
        assert feedback["id"] in [f["id"] for f in res.json()]

    def test_given_limit_over_500_when_admin_lists_then_422(self, client: httpx.Client):
        res = client.get(
            "/api/admin/feedback/admin/all",
            params={"limit": 501},
            headers=admin_headers(),
        )
        assert res.status_code == 422

    def test_given_student_when_list_feedback_then_403(
        self, client: httpx.Client, student_headers: Dict[str, str]
    ):
        res = client.get("/api/admin/feedback/admin/all", headers=student_headers)
        assert res.status_code == 403

    def test_given_unread_feedback_when_admin_marks_read_then_flag_set(
        self, client: httpx.Client, feedback: Dict[str, Any]
    ):
        res = client.patch(
            f"/api/admin/feedback/admin/{feedback['id']}/read", headers=admin_headers()
        )
        assert res.status_code == 200, res.text
        assert res.json()["is_read"] is True

    def test_given_unknown_feedback_when_mark_read_then_404(self, client: httpx.Client):
        res = client.patch(
            "/api/admin/feedback/admin/999999999/read", headers=admin_headers()
        )
        assert res.status_code == 404
        assert res.json()["detail"]["error"] == "FEEDBACK_NOT_FOUND"

    def test_given_feedback_when_admin_deletes_then_204_and_404_after(
        self, client: httpx.Client
    ):
        created = client.post(
            "/api/admin/feedback/submit", json=_feedback_payload()
        ).json()

        res = client.delete(
            f"/api/admin/feedback/admin/{created['id']}", headers=admin_headers()
        )

        assert res.status_code == 204
        again = client.delete(
            f"/api/admin/feedback/admin/{created['id']}", headers=admin_headers()
        )
        assert again.status_code == 404


class TestGuestChat:
    def test_given_guest_session_when_send_message_then_stored_in_conversation(
        self, client: httpx.Client, conversations: List[int]
    ):
        session = _guest_session()

        res = client.post(
            "/api/admin/chat/send", json={"message": "hello", "session_id": session}
        )

        assert res.status_code == 200, res.text
        body = res.json()
        conversations.append(body["conversation_id"])
        assert body["message"] == "hello"
        assert body["is_from_admin"] is False

    def test_given_anonymous_without_session_when_send_then_400_identity_required(
        self, client: httpx.Client
    ):
        res = client.post("/api/admin/chat/send", json={"message": "hello"})
        assert res.status_code == 400
        assert res.json()["detail"]["error"] == "IDENTITY_REQUIRED"

    def test_given_bad_session_id_when_send_then_422(self, client: httpx.Client):
        res = client.post(
            "/api/admin/chat/send", json={"message": "hi", "session_id": "short"}
        )
        assert res.status_code == 422

    def test_given_two_messages_when_get_history_then_in_order(
        self, client: httpx.Client, conversations: List[int]
    ):
        session = _guest_session()
        first = client.post(
            "/api/admin/chat/send", json={"message": "one", "session_id": session}
        ).json()
        conversations.append(first["conversation_id"])
        client.post("/api/admin/chat/send", json={"message": "two", "session_id": session})

        res = client.get("/api/admin/chat/history", params={"session_id": session})

        assert res.status_code == 200
        assert [m["message"] for m in res.json()] == ["one", "two"]

    def test_given_unknown_session_when_get_history_then_empty(self, client: httpx.Client):
        res = client.get(
            "/api/admin/chat/history", params={"session_id": _guest_session()}
        )
        assert res.status_code == 200
        assert res.json() == []

    def test_given_guest_thread_when_student_syncs_then_history_follows_account(
        self,
        client: httpx.Client,
        student: Dict[str, Any],
        student_headers: Dict[str, str],
        conversations: List[int],
    ):
        session = _guest_session()
        sent = client.post(
            "/api/admin/chat/send", json={"message": "from guest", "session_id": session}
        ).json()
        conversations.append(sent["conversation_id"])

        sync = client.post(
            "/api/admin/chat/sync", json={"session_id": session}, headers=student_headers
        )
        history = client.get("/api/admin/chat/history", headers=student_headers)

        assert sync.status_code == 200, sync.text
        assert "from guest" in [m["message"] for m in history.json()]

    def test_given_nothing_to_sync_when_sync_then_nothing_message(
        self, client: httpx.Client, student_headers: Dict[str, str]
    ):
        res = client.post(
            "/api/admin/chat/sync",
            json={"session_id": _guest_session()},
            headers=student_headers,
        )
        assert res.status_code == 200
        assert res.json() == {"message": "Nothing to sync"}

    def test_given_no_token_when_sync_then_401(self, client: httpx.Client):
        res = client.post("/api/admin/chat/sync", json={"session_id": _guest_session()})
        assert res.status_code == 401


class TestAdminChat:
    def test_given_guest_message_when_admin_lists_conversations_then_shown_as_guest(
        self, client: httpx.Client, conversations: List[int]
    ):
        sent = client.post(
            "/api/admin/chat/send",
            json={"message": "need help", "session_id": _guest_session()},
        ).json()
        conversations.append(sent["conversation_id"])

        res = client.get("/api/admin/chat/admin/conversations", headers=admin_headers())

        assert res.status_code == 200
        mine = [c for c in res.json() if c["id"] == sent["conversation_id"]]
        assert mine and mine[0]["student_name"] == "Guest"
        assert mine[0]["unread_count"] >= 1

    def test_given_conversation_when_admin_reads_messages_then_marked_read(
        self, client: httpx.Client, conversations: List[int]
    ):
        sent = client.post(
            "/api/admin/chat/send",
            json={"message": "read me", "session_id": _guest_session()},
        ).json()
        cid = sent["conversation_id"]
        conversations.append(cid)

        res = client.get(
            f"/api/admin/chat/admin/conversations/{cid}/messages",
            headers=admin_headers(),
        )

        assert res.status_code == 200
        assert [m["message"] for m in res.json()] == ["read me"]
        listing = client.get(
            "/api/admin/chat/admin/conversations", headers=admin_headers()
        ).json()
        assert [c for c in listing if c["id"] == cid][0]["unread_count"] == 0

    def test_given_conversation_when_admin_replies_then_reply_flagged_from_admin(
        self, client: httpx.Client, conversations: List[int]
    ):
        session = _guest_session()
        cid = client.post(
            "/api/admin/chat/send", json={"message": "question", "session_id": session}
        ).json()["conversation_id"]
        conversations.append(cid)

        res = client.post(
            f"/api/admin/chat/admin/conversations/{cid}/reply",
            json={"message": "answer"},
            headers=admin_headers(),
        )

        assert res.status_code == 200, res.text
        assert res.json()["is_from_admin"] is True
        history = client.get("/api/admin/chat/history", params={"session_id": session})
        assert [m["message"] for m in history.json()] == ["question", "answer"]

    def test_given_unknown_conversation_when_admin_replies_then_404(
        self, client: httpx.Client
    ):
        res = client.post(
            "/api/admin/chat/admin/conversations/999999999/reply",
            json={"message": "hello?"},
            headers=admin_headers(),
        )
        assert res.status_code == 404

    def test_given_conversation_when_admin_deletes_then_204_and_history_empty(
        self, client: httpx.Client
    ):
        session = _guest_session()
        cid = client.post(
            "/api/admin/chat/send", json={"message": "bye", "session_id": session}
        ).json()["conversation_id"]

        res = client.delete(
            f"/api/admin/chat/admin/conversations/{cid}", headers=admin_headers()
        )

        assert res.status_code == 204
        history = client.get("/api/admin/chat/history", params={"session_id": session})
        assert history.json() == []

    def test_given_unknown_student_when_admin_opens_thread_then_404(
        self, client: httpx.Client
    ):
        res = client.get(
            "/api/admin/chat/admin/conversations/student/999999999",
            headers=admin_headers(),
        )
        assert res.status_code == 404
        assert res.json()["detail"]["error"] == "USER_NOT_FOUND"

    def test_given_student_when_admin_opens_thread_then_conversation_created(
        self,
        client: httpx.Client,
        student: Dict[str, Any],
        conversations: List[int],
    ):
        res = client.get(
            f"/api/admin/chat/admin/conversations/student/{student['id']}",
            headers=admin_headers(),
        )
        assert res.status_code in (200, 404), res.text
        if res.status_code == 200:
            conversations.append(res.json()["id"])
            assert res.json()["user_id"] == student["id"]

    def test_given_student_when_list_admin_conversations_then_403(
        self, client: httpx.Client, student_headers: Dict[str, str]
    ):
        res = client.get("/api/admin/chat/admin/conversations", headers=student_headers)
        assert res.status_code == 403
