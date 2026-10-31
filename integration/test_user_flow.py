"""
Integration tests: user_service through the gateway (profiles, streams,
grade subjects, referrals, stats).

The profile is created by user_service from auth_service's registration event, so
tests that need it wait for it to appear instead of assuming it is there instantly.
"""

import uuid
from typing import Any, Dict, Iterator

import httpx
import pytest

from .conftest import admin_headers, wait_until


@pytest.fixture
def profile_ready(client: httpx.Client, student: Dict[str, Any]) -> Dict[str, Any]:
    """Given a student whose profile has reached user_service."""
    res = wait_until(
        lambda: client.get(f"/api/users/{student['id']}", headers=admin_headers()),
        lambda r: r.status_code == 200,
    )
    assert (
        res.status_code == 200
    ), f"profile never appeared: {res.status_code} {res.text}"
    return student


@pytest.fixture
def stream(client: httpx.Client) -> Iterator[Dict[str, Any]]:
    res = client.post(
        "/api/users/streams",
        json={
            "name": f"IT-{uuid.uuid4().hex[:8]}",
            "subjects": ["Physics", "Chemistry"],
        },
        headers=admin_headers(),
    )
    assert res.status_code == 201, res.text
    body = res.json()
    yield body
    client.delete(f"/api/users/streams/{body['id']}", headers=admin_headers())


@pytest.fixture
def grade_subject(client: httpx.Client) -> Iterator[Dict[str, Any]]:
    res = client.post(
        "/api/users/grade-subjects",
        json={"name": f"IT-{uuid.uuid4().hex[:8]}", "grade": 9},
        headers=admin_headers(),
    )
    assert res.status_code == 201, res.text
    body = res.json()
    yield body
    client.delete(f"/api/users/grade-subjects/{body['id']}", headers=admin_headers())


class TestProfileReadUpdate:
    def test_given_new_registration_when_event_processed_then_profile_exists(
        self, client: httpx.Client, profile_ready: Dict[str, Any]
    ):
        res = client.get(f"/api/users/{profile_ready['id']}", headers=admin_headers())
        assert res.status_code == 200
        body = res.json()
        assert body["first_name"] == "Integ"
        assert body["last_name"] == "Test"
        assert body["role"] == "student"

    def test_given_own_token_when_get_own_profile_then_200_with_email(
        self,
        client: httpx.Client,
        profile_ready: Dict[str, Any],
        student_headers: Dict[str, str],
    ):
        res = client.get(f"/api/users/{profile_ready['id']}", headers=student_headers)
        assert res.status_code == 200
        assert res.json()["email"] == profile_ready["email"]

    def test_given_student_when_get_other_profile_then_403(
        self, client: httpx.Client, profile_ready: Dict[str, Any], student_headers
    ):
        res = client.get(
            f"/api/users/{profile_ready['id'] + 1}", headers=student_headers
        )
        assert res.status_code == 403
        assert res.json()["detail"]["error"] == "INSUFFICIENT_PERMISSIONS"

    def test_given_unknown_id_when_admin_get_then_404(self, client: httpx.Client):
        res = client.get("/api/users/999999999", headers=admin_headers())
        assert res.status_code == 404
        assert res.json()["detail"]["error"] == "USER_NOT_FOUND"

    def test_given_own_token_when_update_profile_then_changes_persist(
        self,
        client: httpx.Client,
        profile_ready: Dict[str, Any],
        student_headers: Dict[str, str],
    ):
        uid = profile_ready["id"]

        res = client.put(
            f"/api/users/{uid}",
            json={"bio": "updated by integration test", "grade": 10},
            headers=student_headers,
        )

        assert res.status_code == 200, res.text
        again = client.get(f"/api/users/{uid}", headers=student_headers).json()
        assert again["bio"] == "updated by integration test"
        assert again["grade"] == 10

    def test_given_grade_out_of_range_when_update_then_422(
        self,
        client: httpx.Client,
        profile_ready: Dict[str, Any],
        student_headers: Dict[str, str],
    ):
        res = client.put(
            f"/api/users/{profile_ready['id']}",
            json={"grade": 3},
            headers=student_headers,
        )
        assert res.status_code == 422

    def test_given_student_when_update_other_profile_then_403(
        self, client: httpx.Client, profile_ready: Dict[str, Any], student_headers
    ):
        res = client.put(
            f"/api/users/{profile_ready['id'] + 1}",
            json={"bio": "nope"},
            headers=student_headers,
        )
        assert res.status_code == 403

    def test_given_no_token_when_get_profile_then_401(self, client: httpx.Client):
        assert client.get("/api/users/1").status_code == 401


class TestAdminUserManagement:
    def test_given_admin_when_list_users_then_paginated(self, client: httpx.Client):
        res = client.get(
            "/api/users/", params={"page_size": 5}, headers=admin_headers()
        )
        assert res.status_code == 200
        body = res.json()
        assert body["page"] == 1
        assert body["page_size"] == 5
        assert isinstance(body["items"], list)
        assert body["total"] >= len(body["items"])

    def test_given_invalid_role_filter_when_list_then_422(self, client: httpx.Client):
        res = client.get(
            "/api/users/", params={"role": "wizard"}, headers=admin_headers()
        )
        assert res.status_code == 422

    def test_given_student_when_list_users_then_403(
        self, client: httpx.Client, student_headers: Dict[str, str]
    ):
        assert client.get("/api/users/", headers=student_headers).status_code == 403

    def test_given_new_student_when_search_by_name_then_found(
        self, client: httpx.Client, profile_ready: Dict[str, Any]
    ):
        res = client.get(
            "/api/users/",
            params={"search": "Integ", "role": "student", "page_size": 100},
            headers=admin_headers(),
        )
        assert res.status_code == 200
        ids = [u["id"] for u in res.json()["items"]]
        assert profile_ready["id"] in ids

    def test_given_admin_when_get_stats_then_counts_present(self, client: httpx.Client):
        res = client.get("/api/users/stats", headers=admin_headers())
        assert res.status_code == 200
        body = res.json()
        assert body["total_students"] >= 0
        assert {"total_teachers", "total_admins"} <= body.keys()

    def test_given_student_when_get_stats_then_403(
        self, client: httpx.Client, student_headers: Dict[str, str]
    ):
        assert (
            client.get("/api/users/stats", headers=student_headers).status_code == 403
        )

    def test_given_admin_when_change_role_then_profile_role_updates(
        self, client: httpx.Client, profile_ready: Dict[str, Any]
    ):
        uid = profile_ready["id"]

        res = client.put(
            f"/api/users/{uid}/role", json={"role": "teacher"}, headers=admin_headers()
        )

        assert res.status_code == 200, res.text
        assert res.json()["role"] == "teacher"

    def test_given_invalid_role_when_change_role_then_422(
        self, client: httpx.Client, profile_ready: Dict[str, Any]
    ):
        res = client.put(
            f"/api/users/{profile_ready['id']}/role",
            json={"role": "overlord"},
            headers=admin_headers(),
        )
        assert res.status_code == 422

    def test_given_student_when_change_role_then_403(
        self, client: httpx.Client, profile_ready: Dict[str, Any], student_headers
    ):
        res = client.put(
            f"/api/users/{profile_ready['id']}/role",
            json={"role": "admin"},
            headers=student_headers,
        )
        assert res.status_code == 403

    def test_given_admin_when_delete_profile_then_204_and_404_after(
        self, client: httpx.Client, profile_ready: Dict[str, Any]
    ):
        uid = profile_ready["id"]

        res = client.delete(f"/api/users/{uid}", headers=admin_headers())

        assert res.status_code == 204
        after = client.get(f"/api/users/{uid}", headers=admin_headers())
        assert after.status_code == 404

    def test_given_unknown_id_when_admin_delete_then_404(self, client: httpx.Client):
        res = client.delete("/api/users/999999999", headers=admin_headers())
        assert res.status_code == 404


class TestStreams:
    def test_given_admin_when_create_stream_then_201(
        self, client: httpx.Client, stream: Dict[str, Any]
    ):
        assert stream["is_active"] is True
        assert stream["subjects"] == ["Physics", "Chemistry"]

    def test_given_created_stream_when_list_then_includes_it(
        self, client: httpx.Client, stream: Dict[str, Any]
    ):
        res = client.get("/api/users/streams")
        assert res.status_code == 200
        assert stream["id"] in [s["id"] for s in res.json()]

    def test_given_inactive_stream_when_list_active_only_then_hidden(
        self, client: httpx.Client, stream: Dict[str, Any]
    ):
        client.put(
            f"/api/users/streams/{stream['id']}",
            json={"is_active": False},
            headers=admin_headers(),
        )

        active = client.get("/api/users/streams").json()
        everything = client.get(
            "/api/users/streams", params={"active_only": "false"}
        ).json()

        assert stream["id"] not in [s["id"] for s in active]
        assert stream["id"] in [s["id"] for s in everything]

    def test_given_stream_when_update_then_changes_persist(
        self, client: httpx.Client, stream: Dict[str, Any]
    ):
        res = client.put(
            f"/api/users/streams/{stream['id']}",
            json={"description": "renamed"},
            headers=admin_headers(),
        )
        assert res.status_code == 200, res.text
        assert res.json()["description"] == "renamed"

    def test_given_unknown_stream_when_update_then_404(self, client: httpx.Client):
        res = client.put(
            "/api/users/streams/999999999", json={"name": "x"}, headers=admin_headers()
        )
        assert res.status_code == 404
        assert res.json()["detail"]["error"] == "STREAM_NOT_FOUND"

    def test_given_stream_when_delete_then_204_and_gone(self, client: httpx.Client):
        created = client.post(
            "/api/users/streams",
            json={"name": f"IT-{uuid.uuid4().hex[:8]}"},
            headers=admin_headers(),
        ).json()

        res = client.delete(
            f"/api/users/streams/{created['id']}", headers=admin_headers()
        )

        assert res.status_code == 204
        ids = [
            s["id"]
            for s in client.get(
                "/api/users/streams", params={"active_only": "false"}
            ).json()
        ]
        assert created["id"] not in ids

    def test_given_empty_name_when_create_stream_then_422(self, client: httpx.Client):
        res = client.post(
            "/api/users/streams", json={"name": ""}, headers=admin_headers()
        )
        assert res.status_code == 422

    def test_given_student_when_create_stream_then_403(
        self, client: httpx.Client, student_headers: Dict[str, str]
    ):
        res = client.post(
            "/api/users/streams", json={"name": "nope"}, headers=student_headers
        )
        assert res.status_code == 403


class TestGradeSubjects:
    def test_given_admin_when_create_grade_subject_then_201(
        self, client: httpx.Client, grade_subject: Dict[str, Any]
    ):
        assert grade_subject["grade"] == 9
        assert grade_subject["is_active"] is True

    def test_given_grade_subject_when_list_by_grade_then_includes_it(
        self, client: httpx.Client, grade_subject: Dict[str, Any]
    ):
        res = client.get("/api/users/grade-subjects", params={"grade": 9})
        assert res.status_code == 200
        assert grade_subject["id"] in [s["id"] for s in res.json()]

    def test_given_grade_subject_when_update_then_changes_persist(
        self, client: httpx.Client, grade_subject: Dict[str, Any]
    ):
        res = client.put(
            f"/api/users/grade-subjects/{grade_subject['id']}",
            json={"is_active": False},
            headers=admin_headers(),
        )
        assert res.status_code == 200, res.text
        assert res.json()["is_active"] is False

    def test_given_grade_above_11_when_create_then_422(self, client: httpx.Client):
        res = client.post(
            "/api/users/grade-subjects",
            json={"name": "Too High", "grade": 12},
            headers=admin_headers(),
        )
        assert res.status_code == 422

    def test_given_unknown_subject_when_delete_then_404(self, client: httpx.Client):
        res = client.delete(
            "/api/users/grade-subjects/999999999", headers=admin_headers()
        )
        assert res.status_code == 404
        assert res.json()["detail"]["error"] == "SUBJECT_NOT_FOUND"

    def test_given_grade_subject_when_delete_then_204(self, client: httpx.Client):
        created = client.post(
            "/api/users/grade-subjects",
            json={"name": f"IT-{uuid.uuid4().hex[:8]}", "grade": 8},
            headers=admin_headers(),
        ).json()
        res = client.delete(
            f"/api/users/grade-subjects/{created['id']}", headers=admin_headers()
        )
        assert res.status_code == 204


class TestSubjectsForGrade:
    def test_given_grade_9_subject_when_get_subjects_then_name_listed(
        self, client: httpx.Client, grade_subject: Dict[str, Any]
    ):
        res = client.get("/api/users/subjects", params={"grade": 9})
        assert res.status_code == 200
        assert grade_subject["name"] in res.json()

    def test_given_grade_12_with_stream_when_get_subjects_then_stream_subjects(
        self, client: httpx.Client, stream: Dict[str, Any]
    ):
        res = client.get(
            "/api/users/subjects", params={"grade": 12, "stream_id": stream["id"]}
        )
        assert res.status_code == 200
        assert res.json() == ["Physics", "Chemistry"]

    def test_given_grade_12_without_stream_when_get_subjects_then_empty(
        self, client: httpx.Client
    ):
        res = client.get("/api/users/subjects", params={"grade": 12})
        assert res.status_code == 200
        assert res.json() == []

    def test_given_grade_out_of_range_when_get_subjects_then_422(
        self, client: httpx.Client
    ):
        assert client.get("/api/users/subjects", params={"grade": 2}).status_code == 422


class TestReferrals:
    def test_given_student_with_profile_when_get_summary_then_has_code(
        self,
        client: httpx.Client,
        profile_ready: Dict[str, Any],
        student_headers: Dict[str, str],
    ):
        res = client.get("/api/users/referral/summary", headers=student_headers)
        assert res.status_code == 200, res.text
        assert res.json()

    def test_given_student_with_profile_when_get_events_then_list(
        self,
        client: httpx.Client,
        profile_ready: Dict[str, Any],
        student_headers: Dict[str, str],
    ):
        res = client.get(
            "/api/users/referral/events", params={"limit": 10}, headers=student_headers
        )
        assert res.status_code == 200, res.text
        assert isinstance(res.json(), (list, dict))

    def test_given_limit_over_200_when_get_events_then_422(
        self, client: httpx.Client, student_headers: Dict[str, str]
    ):
        res = client.get(
            "/api/users/referral/events", params={"limit": 500}, headers=student_headers
        )
        assert res.status_code == 422

    def test_given_unknown_code_when_apply_referral_then_rejected(
        self,
        client: httpx.Client,
        profile_ready: Dict[str, Any],
        student_headers: Dict[str, str],
    ):
        res = client.post(
            "/api/users/referral/apply",
            json={"referral_code": "NOSUCHCODE"},
            headers=student_headers,
        )
        assert 400 <= res.status_code < 500

    def test_given_admin_token_when_apply_referral_then_403(self, client: httpx.Client):
        res = client.post(
            "/api/users/referral/apply",
            json={"referral_code": "ANY"},
            headers=admin_headers(),
        )
        assert res.status_code == 403

    def test_given_no_token_when_get_summary_then_401(self, client: httpx.Client):
        assert client.get("/api/users/referral/summary").status_code == 401


class TestOwnProfileCreation:
    def test_given_no_token_when_create_own_profile_then_401(
        self, client: httpx.Client
    ):
        res = client.post("/api/users/", json={"first_name": "A", "last_name": "B"})
        assert res.status_code == 401

    def test_given_existing_profile_when_create_own_profile_then_conflict(
        self,
        client: httpx.Client,
        profile_ready: Dict[str, Any],
        student_headers: Dict[str, str],
    ):
        res = client.post(
            "/api/users/",
            json={"first_name": "Again", "last_name": "Dup"},
            headers=student_headers,
        )
        assert res.status_code == 409
        assert res.json()["detail"]["error"] == "PROFILE_EXISTS"
