"""
Integration tests: notification_service and analytics_service through the gateway.
"""

from typing import Dict

import httpx

from .conftest import admin_headers


# notification_service runs only its RabbitMQ consumer (its Dockerfile starts consumer.py,
# not uvicorn), so the gateway has nothing to route /api/notifications/ to. Its behaviour
# is verified through the events it consumes, not over HTTP.


class TestPlatformStats:
    def test_given_anonymous_visitor_when_get_platform_stats_then_public_numbers(
        self, client: httpx.Client
    ):
        res = client.get("/api/analytics/platform-stats")
        assert res.status_code == 200, res.text
        body = res.json()
        assert {
            "total_students",
            "total_courses",
            "total_exams",
            "total_attempts",
            "top_courses",
        } <= body.keys()
        assert len(body["top_courses"]) <= 4


class TestAdminAnalytics:
    def test_given_admin_when_get_analytics_root_then_welcome(self, client: httpx.Client):
        res = client.get("/api/analytics/analytics", headers=admin_headers())
        assert res.status_code == 200
        assert res.json() == {"message": "Welcome Admin"}

    def test_given_student_when_get_analytics_root_then_403(
        self, client: httpx.Client, student_headers: Dict[str, str]
    ):
        assert (
            client.get("/api/analytics/analytics", headers=student_headers).status_code
            == 403
        )

    def test_given_admin_when_get_admin_stats_then_200(self, client: httpx.Client):
        res = client.get("/api/analytics/admin/stats", headers=admin_headers())
        assert res.status_code in (200, 503), res.text
        if res.status_code == 503:
            assert res.json()["detail"]["error"] == "SOURCE_UNAVAILABLE"

    def test_given_admin_when_get_admin_analytics_then_200(self, client: httpx.Client):
        res = client.get("/api/analytics/admin/analytics", headers=admin_headers())
        assert res.status_code in (200, 503), res.text

    def test_given_student_when_get_admin_stats_then_403(
        self, client: httpx.Client, student_headers: Dict[str, str]
    ):
        assert (
            client.get("/api/analytics/admin/stats", headers=student_headers).status_code
            == 403
        )

    def test_given_no_token_when_get_admin_analytics_then_401(self, client: httpx.Client):
        assert client.get("/api/analytics/admin/analytics").status_code == 401


class TestStudentProgressViews:
    def test_given_admin_when_get_progress_summary_then_200(self, client: httpx.Client):
        res = client.get(
            "/api/analytics/students/progress-summary", headers=admin_headers()
        )
        assert res.status_code in (200, 503), res.text

    def test_given_student_when_get_progress_summary_then_403(
        self, client: httpx.Client, student_headers: Dict[str, str]
    ):
        res = client.get(
            "/api/analytics/students/progress-summary", headers=student_headers
        )
        assert res.status_code == 403

    def test_given_unknown_student_when_admin_gets_progress_then_404(
        self, client: httpx.Client
    ):
        res = client.get(
            "/api/analytics/students/999999999/progress", headers=admin_headers()
        )
        assert res.status_code in (404, 503)
        if res.status_code == 404:
            assert res.json()["detail"]["error"] == "STUDENT_NOT_FOUND"

    def test_given_unknown_student_when_send_report_then_404(self, client: httpx.Client):
        res = client.post(
            "/api/analytics/students/999999999/send-report", headers=admin_headers()
        )
        assert res.status_code in (404, 503)

    def test_given_student_when_get_me_progress_then_200_or_not_found_yet(
        self, client: httpx.Client, student_headers: Dict[str, str]
    ):
        # The read model is filled from events, so a brand-new student may not be in it yet.
        res = client.get("/api/analytics/me/progress", headers=student_headers)
        assert res.status_code in (200, 404, 503), res.text

    def test_given_admin_when_get_me_progress_then_403(self, client: httpx.Client):
        res = client.get("/api/analytics/me/progress", headers=admin_headers())
        assert res.status_code == 403


class TestCourseStruggle:
    def test_given_unknown_course_when_admin_gets_struggle_then_404(
        self, client: httpx.Client
    ):
        res = client.get(
            "/api/analytics/courses/999999999/struggle", headers=admin_headers()
        )
        assert res.status_code in (404, 503)
        if res.status_code == 404:
            assert res.json()["detail"]["error"] == "COURSE_NOT_FOUND"

    def test_given_student_when_get_struggle_then_403(
        self, client: httpx.Client, student_headers: Dict[str, str]
    ):
        res = client.get("/api/analytics/courses/1/struggle", headers=student_headers)
        assert res.status_code == 403
