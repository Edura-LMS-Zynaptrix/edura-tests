"""
Integration tests: course_service through the gateway (course CRUD + access rules).
"""

from typing import Any, Dict, List

import httpx

from .conftest import admin_headers


def _course_payload(title: str = "Integration Course") -> Dict[str, Any]:
    return {
        "title": title,
        "description": "created by the integration suite",
        "price": "1500.00",
        "course_type": "video",
        "grade": 10,
    }


def _create_course(
    client: httpx.Client, created: List[int], title: str
) -> Dict[str, Any]:
    res = client.post(
        "/api/courses/", json=_course_payload(title), headers=admin_headers()
    )
    assert res.status_code == 201, res.text
    body = res.json()
    created.append(body["id"])
    return body


class TestCourseLifecycle:
    def test_given_admin_when_create_course_then_201_draft(
        self, client: httpx.Client, created_courses: List[int]
    ):
        # Act
        res = client.post(
            "/api/courses/", json=_course_payload(), headers=admin_headers()
        )
        # Assert
        assert res.status_code == 201, res.text
        body = res.json()
        created_courses.append(body["id"])
        assert body["title"] == "Integration Course"
        assert str(body["status"]).lower() == "draft"

    def test_given_created_course_when_get_by_id_then_returns_it(
        self, client: httpx.Client, created_courses: List[int]
    ):
        course = _create_course(client, created_courses, "Get Me")

        res = client.get(f"/api/courses/{course['id']}", headers=admin_headers())

        assert res.status_code == 200
        assert res.json()["title"] == "Get Me"

    def test_given_created_course_when_update_then_changes_persist(
        self, client: httpx.Client, created_courses: List[int]
    ):
        course = _create_course(client, created_courses, "Before")

        res = client.put(
            f"/api/courses/{course['id']}",
            json={"title": "After"},
            headers=admin_headers(),
        )

        assert res.status_code == 200, res.text
        again = client.get(f"/api/courses/{course['id']}", headers=admin_headers())
        assert again.json()["title"] == "After"

    def test_given_created_course_when_delete_then_204_and_404_after(
        self, client: httpx.Client
    ):
        res = client.post(
            "/api/courses/", json=_course_payload("Doomed"), headers=admin_headers()
        )
        assert res.status_code == 201, res.text
        course_id = res.json()["id"]

        deleted = client.delete(f"/api/courses/{course_id}", headers=admin_headers())

        assert deleted.status_code == 204
        after = client.get(f"/api/courses/{course_id}", headers=admin_headers())
        assert after.status_code == 404

    def test_given_admin_when_list_courses_then_paginated_with_items(
        self, client: httpx.Client
    ):
        res = client.get(
            "/api/courses/", params={"page_size": 5}, headers=admin_headers()
        )
        assert res.status_code == 200
        data = res.json()
        assert "items" in data or isinstance(data, list)


class TestCourseValidationAndAccess:
    def test_given_invalid_course_type_when_create_then_422(self, client: httpx.Client):
        payload = _course_payload()
        payload["course_type"] = "podcast"
        res = client.post("/api/courses/", json=payload, headers=admin_headers())
        assert res.status_code == 422

    def test_given_grade_out_of_range_when_create_then_422(self, client: httpx.Client):
        payload = _course_payload()
        payload["grade"] = 4
        res = client.post("/api/courses/", json=payload, headers=admin_headers())
        assert res.status_code == 422

    def test_given_no_token_when_create_course_then_401(self, client: httpx.Client):
        assert client.post("/api/courses/", json=_course_payload()).status_code == 401

    def test_given_student_when_create_course_then_403(
        self, client: httpx.Client, student_headers: Dict[str, str]
    ):
        res = client.post(
            "/api/courses/", json=_course_payload(), headers=student_headers
        )
        assert res.status_code == 403

    def test_given_student_when_get_draft_course_then_not_visible(
        self,
        client: httpx.Client,
        created_courses: List[int],
        student_headers: Dict[str, str],
    ):
        course = _create_course(client, created_courses, "Hidden")

        res = client.get(f"/api/courses/{course['id']}", headers=student_headers)

        assert res.status_code in (403, 404)

    def test_given_unknown_id_when_get_course_then_404(self, client: httpx.Client):
        res = client.get("/api/courses/999999999", headers=admin_headers())
        assert res.status_code == 404
