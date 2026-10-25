"""
Integration tests: enrollment_service through the gateway (manual access grants,
class packages, own-enrollment views).

Courses reach enrollment_service as events from course_service, so admin grants wait
for the course to appear in its replica before asserting.
"""

import uuid
from typing import Any, Dict, Iterator, List

import httpx
import pytest

from .conftest import admin_headers, wait_until

E = "/api/enrollments"


@pytest.fixture
def course(client: httpx.Client, created_courses: List[int]) -> Dict[str, Any]:
    """Given a course that enrollment_service already knows about."""
    res = client.post(
        "/api/courses/",
        json={"title": "Enroll IT", "price": "0.00", "course_type": "video", "grade": 10},
        headers=admin_headers(),
    )
    assert res.status_code == 201, res.text
    body = res.json()
    created_courses.append(body["id"])
    probe = wait_until(
        lambda: client.get(
            f"{E}/admin/eligible", params={"course_id": body["id"]}, headers=admin_headers()
        ),
        lambda r: r.status_code != 404,
    )
    assert probe.status_code == 200, f"course never replicated: {probe.status_code} {probe.text}"
    return body


@pytest.fixture
def free_package(client: httpx.Client) -> Iterator[Dict[str, Any]]:
    res = client.post(
        f"{E}/admin/class-packages",
        json={"name": f"IT-{uuid.uuid4().hex[:8]}", "grade": 9, "price": 0},
        headers=admin_headers(),
    )
    assert res.status_code == 201, res.text
    body = res.json()
    yield body
    client.delete(f"{E}/admin/class-packages/{body['id']}", headers=admin_headers())


@pytest.fixture
def paid_package(client: httpx.Client) -> Iterator[Dict[str, Any]]:
    res = client.post(
        f"{E}/admin/class-packages",
        json={"name": f"IT-{uuid.uuid4().hex[:8]}", "grade": 9, "price": 5000},
        headers=admin_headers(),
    )
    assert res.status_code == 201, res.text
    body = res.json()
    yield body
    client.delete(f"{E}/admin/class-packages/{body['id']}", headers=admin_headers())


class TestManualAccess:
    def test_given_course_and_student_when_admin_grants_then_enrollment_active(
        self, client: httpx.Client, course: Dict[str, Any], student: Dict[str, Any]
    ):
        res = client.post(
            f"{E}/admin/grant",
            json={"course_id": course["id"], "user_ids": [student["id"]]},
            headers=admin_headers(),
        )

        assert res.status_code == 200, res.text
        assert res.json()["granted"] == 1
        lookup = client.get(
            E,
            params={"student_id": student["id"], "course_id": course["id"]},
            headers=admin_headers(),
        )
        assert lookup.status_code == 200
        assert lookup.json()["status"].upper() == "ACTIVE"

    def test_given_existing_grant_when_admin_grants_again_then_nothing_new_granted(
        self, client: httpx.Client, course: Dict[str, Any], student: Dict[str, Any]
    ):
        payload = {"course_id": course["id"], "user_ids": [student["id"]]}
        client.post(f"{E}/admin/grant", json=payload, headers=admin_headers())

        res = client.post(f"{E}/admin/grant", json=payload, headers=admin_headers())

        assert res.status_code == 200
        assert res.json()["granted"] == 0

    def test_given_granted_student_when_list_me_then_course_listed_with_access(
        self,
        client: httpx.Client,
        course: Dict[str, Any],
        student: Dict[str, Any],
        student_headers: Dict[str, str],
    ):
        client.post(
            f"{E}/admin/grant",
            json={"course_id": course["id"], "user_ids": [student["id"]]},
            headers=admin_headers(),
        )

        mine = client.get(f"{E}/me", params={"course_id": course["id"]}, headers=student_headers)
        access = client.get(
            f"{E}/me/access", params={"course_id": course["id"]}, headers=student_headers
        )

        assert mine.status_code == 200
        assert [e["course_id"] for e in mine.json()] == [course["id"]]
        assert access.status_code == 200
        assert access.json()["course"] is True

    def test_given_ungranted_student_when_get_access_then_no_course_access(
        self, client: httpx.Client, course: Dict[str, Any], student_headers: Dict[str, str]
    ):
        res = client.get(
            f"{E}/me/access", params={"course_id": course["id"]}, headers=student_headers
        )
        assert res.status_code == 200
        assert res.json()["course"] is False
        assert res.json()["lessons"] == []

    def test_given_granted_student_when_listed_enrolled_then_marked_manual(
        self, client: httpx.Client, course: Dict[str, Any], student: Dict[str, Any]
    ):
        client.post(
            f"{E}/admin/grant",
            json={"course_id": course["id"], "user_ids": [student["id"]]},
            headers=admin_headers(),
        )

        res = client.get(
            f"{E}/admin/enrolled", params={"course_id": course["id"]}, headers=admin_headers()
        )

        assert res.status_code == 200
        rows = [r for r in res.json() if r["user_id"] == str(student["id"])]
        assert rows and rows[0]["is_manual"] is True

    def test_given_granted_student_when_admin_revokes_then_enrollment_cancelled(
        self, client: httpx.Client, course: Dict[str, Any], student: Dict[str, Any]
    ):
        client.post(
            f"{E}/admin/grant",
            json={"course_id": course["id"], "user_ids": [student["id"]]},
            headers=admin_headers(),
        )

        res = client.delete(
            f"{E}/admin/revoke",
            params={"course_id": course["id"], "user_id": student["id"]},
            headers=admin_headers(),
        )

        assert res.status_code == 200, res.text
        lookup = client.get(
            E,
            params={"student_id": student["id"], "course_id": course["id"]},
            headers=admin_headers(),
        )
        assert lookup.json()["status"].upper() == "CANCELLED"

    def test_given_no_access_when_admin_revokes_then_404(
        self, client: httpx.Client, course: Dict[str, Any], student: Dict[str, Any]
    ):
        res = client.delete(
            f"{E}/admin/revoke",
            params={"course_id": course["id"], "user_id": student["id"]},
            headers=admin_headers(),
        )
        assert res.status_code == 404
        assert res.json()["detail"]["error"] == "ENROLLMENT_NOT_FOUND"

    def test_given_lesson_grant_when_revoked_then_removed(
        self, client: httpx.Client, course: Dict[str, Any], student: Dict[str, Any]
    ):
        client.post(
            f"{E}/admin/grant",
            json={"course_id": course["id"], "module_id": 4242, "user_ids": [student["id"]]},
            headers=admin_headers(),
        )

        res = client.delete(
            f"{E}/admin/revoke",
            params={"course_id": course["id"], "user_id": student["id"], "module_id": 4242},
            headers=admin_headers(),
        )
        again = client.delete(
            f"{E}/admin/revoke",
            params={"course_id": course["id"], "user_id": student["id"], "module_id": 4242},
            headers=admin_headers(),
        )

        assert res.status_code == 200
        assert again.status_code == 404
        assert again.json()["detail"]["error"] == "ACCESS_NOT_FOUND"

    def test_given_unknown_course_when_admin_grants_then_404(
        self, client: httpx.Client, student: Dict[str, Any]
    ):
        res = client.post(
            f"{E}/admin/grant",
            json={"course_id": 999999999, "user_ids": [student["id"]]},
            headers=admin_headers(),
        )
        assert res.status_code == 404
        assert res.json()["detail"]["error"] == "COURSE_NOT_FOUND"

    def test_given_empty_user_list_when_admin_grants_then_422(self, client: httpx.Client):
        res = client.post(
            f"{E}/admin/grant",
            json={"course_id": 1, "user_ids": []},
            headers=admin_headers(),
        )
        assert res.status_code == 422

    def test_given_student_when_grant_access_then_403(
        self, client: httpx.Client, student: Dict[str, Any], student_headers: Dict[str, str]
    ):
        res = client.post(
            f"{E}/admin/grant",
            json={"course_id": 1, "user_ids": [student["id"]]},
            headers=student_headers,
        )
        assert res.status_code == 403

    def test_given_unknown_course_when_admin_lists_eligible_then_404(
        self, client: httpx.Client
    ):
        res = client.get(
            f"{E}/admin/eligible", params={"course_id": 999999999}, headers=admin_headers()
        )
        assert res.status_code == 404


class TestGetEnrollment:
    def test_given_student_when_look_up_other_student_then_403(
        self, client: httpx.Client, student: Dict[str, Any], student_headers: Dict[str, str]
    ):
        res = client.get(
            E,
            params={"student_id": student["id"] + 1, "course_id": 1},
            headers=student_headers,
        )
        assert res.status_code == 403

    def test_given_no_enrollment_when_look_up_then_404(
        self, client: httpx.Client, student: Dict[str, Any], student_headers: Dict[str, str]
    ):
        res = client.get(
            E,
            params={"student_id": student["id"], "course_id": 999999999},
            headers=student_headers,
        )
        assert res.status_code == 404

    def test_given_no_token_when_look_up_then_401(self, client: httpx.Client):
        res = client.get(E, params={"student_id": 1, "course_id": 1})
        assert res.status_code == 401

    def test_given_missing_params_when_look_up_then_422(
        self, client: httpx.Client, student_headers: Dict[str, str]
    ):
        assert client.get(E, headers=student_headers).status_code == 422

    def test_given_new_student_when_list_me_then_empty(
        self, client: httpx.Client, student_headers: Dict[str, str]
    ):
        res = client.get(f"{E}/me", headers=student_headers)
        assert res.status_code == 200
        assert res.json() == []

    def test_given_no_token_when_list_me_then_401(self, client: httpx.Client):
        assert client.get(f"{E}/me").status_code == 401


class TestClassPackagesAdmin:
    def test_given_admin_when_create_package_then_201_and_listed(
        self, client: httpx.Client, free_package: Dict[str, Any]
    ):
        assert free_package["is_active"] is True
        res = client.get(f"{E}/admin/class-packages", headers=admin_headers())
        assert res.status_code == 200
        assert free_package["id"] in [p["id"] for p in res.json()]

    def test_given_packages_when_filter_by_grade_then_only_that_grade(
        self, client: httpx.Client, free_package: Dict[str, Any]
    ):
        res = client.get(
            f"{E}/admin/class-packages", params={"grade": 9}, headers=admin_headers()
        )
        assert res.status_code == 200
        assert {p["grade"] for p in res.json()} == {9}

    def test_given_package_when_patch_then_changes_persist(
        self, client: httpx.Client, free_package: Dict[str, Any]
    ):
        res = client.patch(
            f"{E}/admin/class-packages/{free_package['id']}",
            json={"description": "patched"},
            headers=admin_headers(),
        )
        assert res.status_code == 200, res.text
        assert res.json()["description"] == "patched"

    def test_given_unknown_package_when_patch_then_404(self, client: httpx.Client):
        res = client.patch(
            f"{E}/admin/class-packages/999999999",
            json={"description": "x"},
            headers=admin_headers(),
        )
        assert res.status_code == 404
        assert res.json()["detail"]["error"] == "PACKAGE_NOT_FOUND"

    def test_given_package_when_delete_then_gone(self, client: httpx.Client):
        created = client.post(
            f"{E}/admin/class-packages",
            json={"name": f"IT-{uuid.uuid4().hex[:8]}", "grade": 8},
            headers=admin_headers(),
        ).json()

        res = client.delete(
            f"{E}/admin/class-packages/{created['id']}", headers=admin_headers()
        )
        again = client.delete(
            f"{E}/admin/class-packages/{created['id']}", headers=admin_headers()
        )

        assert res.status_code == 200
        assert again.status_code == 404

    def test_given_grade_out_of_range_when_create_package_then_422(
        self, client: httpx.Client
    ):
        res = client.post(
            f"{E}/admin/class-packages",
            json={"name": "bad", "grade": 4},
            headers=admin_headers(),
        )
        assert res.status_code == 422

    def test_given_negative_price_when_create_package_then_422(self, client: httpx.Client):
        res = client.post(
            f"{E}/admin/class-packages",
            json={"name": "bad", "grade": 8, "price": -1},
            headers=admin_headers(),
        )
        assert res.status_code == 422

    def test_given_student_when_create_package_then_403(
        self, client: httpx.Client, student_headers: Dict[str, str]
    ):
        res = client.post(
            f"{E}/admin/class-packages",
            json={"name": "nope", "grade": 8},
            headers=student_headers,
        )
        assert res.status_code == 403

    def test_given_admin_when_auto_generate_then_returns_created_summary(
        self, client: httpx.Client
    ):
        res = client.post(f"{E}/admin/class-packages/auto-generate", headers=admin_headers())
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["count"] == len(body["created"])

    def test_given_auto_generate_run_twice_then_second_run_creates_nothing(
        self, client: httpx.Client
    ):
        client.post(f"{E}/admin/class-packages/auto-generate", headers=admin_headers())
        res = client.post(f"{E}/admin/class-packages/auto-generate", headers=admin_headers())
        assert res.json()["count"] == 0


class TestClassPackagesStudent:
    def test_given_anonymous_visitor_when_list_packages_then_active_ones_visible(
        self, client: httpx.Client, free_package: Dict[str, Any]
    ):
        res = client.get(f"{E}/class-packages", params={"grade": 9})
        assert res.status_code == 200
        assert free_package["id"] in [p["id"] for p in res.json()]

    def test_given_free_package_when_student_enrolls_then_active_enrollment(
        self,
        client: httpx.Client,
        free_package: Dict[str, Any],
        student_headers: Dict[str, str],
    ):
        res = client.post(
            f"{E}/class-packages/{free_package['id']}/enroll-free", headers=student_headers
        )

        assert res.status_code == 200, res.text
        assert res.json()["status"] == "active"
        mine = client.get(f"{E}/my-class-enrollments", headers=student_headers).json()
        assert free_package["id"] in [m["class_package_id"] for m in mine]

    def test_given_already_enrolled_when_enroll_free_again_then_400(
        self,
        client: httpx.Client,
        free_package: Dict[str, Any],
        student_headers: Dict[str, str],
    ):
        client.post(
            f"{E}/class-packages/{free_package['id']}/enroll-free", headers=student_headers
        )
        res = client.post(
            f"{E}/class-packages/{free_package['id']}/enroll-free", headers=student_headers
        )
        assert res.status_code == 400
        assert res.json()["detail"]["error"] == "ALREADY_ENROLLED"

    def test_given_paid_package_when_enroll_free_then_400_payment_required(
        self,
        client: httpx.Client,
        paid_package: Dict[str, Any],
        student_headers: Dict[str, str],
    ):
        res = client.post(
            f"{E}/class-packages/{paid_package['id']}/enroll-free", headers=student_headers
        )
        assert res.status_code == 400
        assert res.json()["detail"]["error"] == "PAYMENT_REQUIRED"

    def test_given_unknown_package_when_enroll_free_then_404(
        self, client: httpx.Client, student_headers: Dict[str, str]
    ):
        res = client.post(
            f"{E}/class-packages/999999999/enroll-free", headers=student_headers
        )
        assert res.status_code == 404

    def test_given_admin_token_when_enroll_free_then_403(
        self, client: httpx.Client, free_package: Dict[str, Any]
    ):
        res = client.post(
            f"{E}/class-packages/{free_package['id']}/enroll-free", headers=admin_headers()
        )
        assert res.status_code == 403

    def test_given_new_student_when_list_my_class_enrollments_then_empty(
        self, client: httpx.Client, student_headers: Dict[str, str]
    ):
        res = client.get(f"{E}/my-class-enrollments", headers=student_headers)
        assert res.status_code == 200
        assert res.json() == []


class TestClassEnrollmentsAdmin:
    def test_given_admin_grants_package_then_listed_and_revocable(
        self,
        client: httpx.Client,
        free_package: Dict[str, Any],
        student: Dict[str, Any],
    ):
        grant = client.post(
            f"{E}/admin/class-enrollments",
            json={"user_id": student["id"], "class_package_id": int(free_package["id"])},
            headers=admin_headers(),
        )
        assert grant.status_code == 201, grant.text
        enrollment_id = grant.json()["id"]

        listed = client.get(
            f"{E}/admin/class-enrollments",
            params={"user_id": student["id"]},
            headers=admin_headers(),
        )
        revoked = client.delete(
            f"{E}/admin/class-enrollments/{enrollment_id}", headers=admin_headers()
        )
        again = client.delete(
            f"{E}/admin/class-enrollments/{enrollment_id}", headers=admin_headers()
        )

        assert enrollment_id in [e["id"] for e in listed.json()]
        assert revoked.status_code == 200
        assert again.status_code == 404
        assert again.json()["detail"]["error"] == "CLASS_ENROLLMENT_NOT_FOUND"

    def test_given_unknown_package_when_admin_grants_then_404(
        self, client: httpx.Client, student: Dict[str, Any]
    ):
        res = client.post(
            f"{E}/admin/class-enrollments",
            json={"user_id": student["id"], "class_package_id": 999999999},
            headers=admin_headers(),
        )
        assert res.status_code == 404

    def test_given_student_when_list_class_enrollments_then_403(
        self, client: httpx.Client, student_headers: Dict[str, str]
    ):
        res = client.get(f"{E}/admin/class-enrollments", headers=student_headers)
        assert res.status_code == 403
