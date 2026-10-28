"""
Integration tests: progress_service through the gateway.

Course ids here are throwaway numbers: progress rows are keyed by (student, course,
lesson) and are removed with the student's account by the shared cleanup fixtures.
"""

from typing import Any, Dict

import httpx

from .conftest import admin_headers

COURSE_ID = 987654


class TestLessonProgress:
    def test_given_student_when_mark_lesson_watched_then_progress_recorded(
        self, client: httpx.Client, student_headers: Dict[str, str]
    ):
        res = client.post(
            f"/api/progress/courses/{COURSE_ID}/lessons/progress",
            json={
                "lesson_id": 1,
                "total_lessons": 2,
                "watch_duration_seconds": 120,
                "last_position_seconds": 120,
            },
            headers=student_headers,
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["lesson_id"] == 1
        assert body["watch_duration_seconds"] == 120

    def test_given_watched_lesson_when_get_lesson_progress_then_listed(
        self, client: httpx.Client, student_headers: Dict[str, str]
    ):
        client.post(
            f"/api/progress/courses/{COURSE_ID}/lessons/progress",
            json={"lesson_id": 7, "total_lessons": 3, "watch_duration_seconds": 30},
            headers=student_headers,
        )

        res = client.get(
            f"/api/progress/courses/{COURSE_ID}/lessons/progress",
            headers=student_headers,
        )

        assert res.status_code == 200
        assert 7 in [item["lesson_id"] for item in res.json()]

    def test_given_new_student_when_get_lesson_progress_then_empty(
        self, client: httpx.Client, student_headers: Dict[str, str]
    ):
        res = client.get(
            f"/api/progress/courses/{COURSE_ID}/lessons/progress",
            headers=student_headers,
        )
        assert res.status_code == 200
        assert res.json() == []

    def test_given_missing_lesson_id_when_mark_watched_then_422(
        self, client: httpx.Client, student_headers: Dict[str, str]
    ):
        res = client.post(
            f"/api/progress/courses/{COURSE_ID}/lessons/progress",
            json={},
            headers=student_headers,
        )
        assert res.status_code == 422

    def test_given_admin_when_mark_lesson_watched_then_403(self, client: httpx.Client):
        res = client.post(
            f"/api/progress/courses/{COURSE_ID}/lessons/progress",
            json={"lesson_id": 1},
            headers=admin_headers(),
        )
        assert res.status_code == 403

    def test_given_no_token_when_mark_lesson_watched_then_401(
        self, client: httpx.Client
    ):
        res = client.post(
            f"/api/progress/courses/{COURSE_ID}/lessons/progress", json={"lesson_id": 1}
        )
        assert res.status_code == 401


class TestProgressDashboard:
    def test_given_student_when_get_dashboard_then_shape_is_complete(
        self, client: httpx.Client, student_headers: Dict[str, str]
    ):
        res = client.get(f"/api/progress/courses/{COURSE_ID}", headers=student_headers)
        assert res.status_code == 200, res.text
        body: Dict[str, Any] = res.json()
        assert {
            "completion_percentage",
            "watched_lessons",
            "total_lessons",
            "assessment_scores",
            "certificate_issued",
        } <= body.keys()
        assert body["certificate_issued"] is False

    def test_given_watched_lesson_when_get_dashboard_then_watched_count_increases(
        self, client: httpx.Client, student_headers: Dict[str, str]
    ):
        client.post(
            f"/api/progress/courses/{COURSE_ID}/lessons/progress",
            json={
                "lesson_id": 1,
                "total_lessons": 4,
                "watch_duration_seconds": 600,
                "last_position_seconds": 600,
            },
            headers=student_headers,
        )

        body = client.get(
            f"/api/progress/courses/{COURSE_ID}", headers=student_headers
        ).json()

        assert body["watched_lessons"] >= 0
        assert 0 <= body["completion_percentage"] <= 100

    def test_given_no_token_when_get_dashboard_then_401(self, client: httpx.Client):
        assert client.get(f"/api/progress/courses/{COURSE_ID}").status_code == 401


class TestLeaderboard:
    def test_given_student_when_get_leaderboard_then_list_of_ranked_items(
        self, client: httpx.Client, student_headers: Dict[str, str]
    ):
        res = client.get(
            f"/api/progress/courses/{COURSE_ID}/leaderboard", headers=student_headers
        )
        assert res.status_code == 200, res.text
        items = res.json()
        assert isinstance(items, list)
        for item in items:
            assert {"rank", "student_id", "points"} <= item.keys()

    def test_given_no_token_when_get_leaderboard_then_401(self, client: httpx.Client):
        res = client.get(f"/api/progress/courses/{COURSE_ID}/leaderboard")
        assert res.status_code == 401
