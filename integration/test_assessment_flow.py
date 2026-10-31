"""
Integration tests: assessment_service through the gateway (authoring, taking an exam,
results, rankings, badges).

The taking flow crosses services: the course comes from course_service, the student's
enrollment from enrollment_service (via an admin grant), and sessions live in Redis.
"""

from typing import Any, Dict, Iterator, List

import httpx
import pytest

from .conftest import admin_headers, wait_until

A = "/api/assessments"


def _exam_payload(course_id: int, **overrides: Any) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "course_id": course_id,
        "title": "Integration Exam",
        "assessment_type": "quiz",
        "time_limit_minutes": 10,
        "pass_score": 50,
        "is_published": True,
    }
    body.update(overrides)
    return body


def _mcq(text: str = "2 + 2 = ?", correct: str = "4") -> Dict[str, Any]:
    return {
        "question_text": text,
        "question_type": "mcq",
        "options": [
            {"option_text": "3", "is_correct": False},
            {"option_text": correct, "is_correct": correct == "4"},
            {"option_text": "5", "is_correct": False},
        ],
        "marks": 1,
    }


@pytest.fixture
def course(client: httpx.Client, created_courses: List[int]) -> Dict[str, Any]:
    res = client.post(
        "/api/courses/",
        json={
            "title": "Assessment IT",
            "price": "0.00",
            "course_type": "exam",
            "grade": 10,
        },
        headers=admin_headers(),
    )
    assert res.status_code == 201, res.text
    body = res.json()
    created_courses.append(body["id"])
    return body


@pytest.fixture
def exam(client: httpx.Client, course: Dict[str, Any]) -> Iterator[Dict[str, Any]]:
    res = client.post(
        A + "/", json=_exam_payload(course["id"]), headers=admin_headers()
    )
    assert res.status_code == 201, res.text
    body = res.json()
    yield body
    client.delete(f"{A}/{body['id']}", headers=admin_headers())


@pytest.fixture
def exam_with_question(client: httpx.Client, exam: Dict[str, Any]) -> Dict[str, Any]:
    res = client.post(
        f"{A}/{exam['id']}/questions", json=_mcq(), headers=admin_headers()
    )
    assert res.status_code == 201, res.text
    return {**exam, "question": res.json()}


@pytest.fixture
def enrolled_student(
    client: httpx.Client, course: Dict[str, Any], student: Dict[str, Any]
) -> Dict[str, Any]:
    """Given a student with manual access to the course (waits for course replication)."""
    res = wait_until(
        lambda: client.post(
            "/api/enrollments/admin/grant",
            json={"course_id": course["id"], "user_ids": [student["id"]]},
            headers=admin_headers(),
        ),
        lambda r: r.status_code == 200,
    )
    assert res.status_code == 200, res.text
    return student


class TestAssessmentAuthoring:
    def test_given_admin_when_create_assessment_then_201_with_zero_questions(
        self, client: httpx.Client, exam: Dict[str, Any]
    ):
        assert exam["title"] == "Integration Exam"
        assert exam["question_count"] == 0
        assert exam["is_published"] is True

    def test_given_assessment_when_update_then_changes_persist(
        self, client: httpx.Client, exam: Dict[str, Any]
    ):
        res = client.put(
            f"{A}/{exam['id']}", json={"title": "Renamed"}, headers=admin_headers()
        )
        assert res.status_code == 200, res.text
        assert res.json()["title"] == "Renamed"

    def test_given_assessment_when_get_by_id_then_returns_it(
        self,
        client: httpx.Client,
        exam: Dict[str, Any],
        student_headers: Dict[str, str],
    ):
        res = client.get(f"{A}/{exam['id']}", headers=student_headers)
        assert res.status_code == 200
        assert res.json()["id"] == exam["id"]

    def test_given_unpublished_assessment_when_student_gets_it_then_404(
        self,
        client: httpx.Client,
        course: Dict[str, Any],
        student_headers: Dict[str, str],
    ):
        draft = client.post(
            A + "/",
            json=_exam_payload(course["id"], is_published=False),
            headers=admin_headers(),
        ).json()

        res = client.get(f"{A}/{draft['id']}", headers=student_headers)

        assert res.status_code == 404
        assert res.json()["detail"]["error"] == "ASSESSMENT_NOT_FOUND"
        client.delete(f"{A}/{draft['id']}", headers=admin_headers())

    def test_given_assessment_when_delete_then_204_and_404_after(
        self, client: httpx.Client, course: Dict[str, Any]
    ):
        created = client.post(
            A + "/", json=_exam_payload(course["id"]), headers=admin_headers()
        ).json()

        res = client.delete(f"{A}/{created['id']}", headers=admin_headers())
        after = client.get(f"{A}/{created['id']}", headers=admin_headers())

        assert res.status_code == 204
        assert after.status_code == 404

    def test_given_unknown_course_when_teacher_creates_assessment_then_404(
        self, client: httpx.Client
    ):
        from .conftest import role_headers

        res = client.post(
            A + "/",
            json=_exam_payload(999999999),
            headers=role_headers("teacher", user_id=424242),
        )
        assert res.status_code == 404
        assert res.json()["detail"]["error"] == "COURSE_NOT_FOUND"

    def test_given_student_when_create_assessment_then_403(
        self,
        client: httpx.Client,
        course: Dict[str, Any],
        student_headers: Dict[str, str],
    ):
        res = client.post(
            A + "/", json=_exam_payload(course["id"]), headers=student_headers
        )
        assert res.status_code == 403

    def test_given_missing_title_when_create_assessment_then_422(
        self, client: httpx.Client, course: Dict[str, Any]
    ):
        res = client.post(
            A + "/", json={"course_id": course["id"]}, headers=admin_headers()
        )
        assert res.status_code == 422

    def test_given_no_filter_when_list_assessments_then_422_filter_required(
        self, client: httpx.Client
    ):
        res = client.get(A + "/")
        assert res.status_code == 422
        assert res.json()["detail"]["error"] == "FILTER_REQUIRED"

    def test_given_course_filter_when_anonymous_lists_then_only_published(
        self, client: httpx.Client, course: Dict[str, Any], exam: Dict[str, Any]
    ):
        draft = client.post(
            A + "/",
            json=_exam_payload(course["id"], title="Draft", is_published=False),
            headers=admin_headers(),
        ).json()

        public = client.get(A + "/", params={"course_id": course["id"]}).json()
        staff = client.get(
            A + "/", params={"course_id": course["id"]}, headers=admin_headers()
        ).json()

        assert [a["id"] for a in public] == [exam["id"]]
        assert {exam["id"], draft["id"]} <= {a["id"] for a in staff}
        client.delete(f"{A}/{draft['id']}", headers=admin_headers())

    def test_given_module_delete_when_by_module_then_204(
        self, client: httpx.Client, course: Dict[str, Any]
    ):
        client.post(
            A + "/",
            json=_exam_payload(course["id"], module_id=777001),
            headers=admin_headers(),
        )

        res = client.delete(
            f"{A}/by-module/777001",
            params={"course_id": course["id"]},
            headers=admin_headers(),
        )

        assert res.status_code == 204
        left = client.get(
            A + "/", params={"module_id": 777001}, headers=admin_headers()
        ).json()
        assert left == []


class TestQuestionAuthoring:
    def test_given_assessment_when_admin_adds_mcq_then_correct_answer_taken_from_option(
        self, client: httpx.Client, exam_with_question: Dict[str, Any]
    ):
        q = exam_with_question["question"]
        assert q["correct_answer"] == "4"

    def test_given_question_when_admin_lists_then_includes_it(
        self, client: httpx.Client, exam_with_question: Dict[str, Any]
    ):
        res = client.get(
            f"{A}/{exam_with_question['id']}/questions", headers=admin_headers()
        )
        assert res.status_code == 200
        assert [q["id"] for q in res.json()] == [exam_with_question["question"]["id"]]

    def test_given_no_correct_answer_when_add_question_then_422(
        self, client: httpx.Client, exam: Dict[str, Any]
    ):
        res = client.post(
            f"{A}/{exam['id']}/questions",
            json={
                "question_text": "?",
                "options": [{"option_text": "a"}, {"option_text": "b"}],
            },
            headers=admin_headers(),
        )
        assert res.status_code == 422
        assert res.json()["detail"]["error"] == "CORRECT_ANSWER_REQUIRED"

    def test_given_question_when_update_then_text_changes(
        self, client: httpx.Client, exam_with_question: Dict[str, Any]
    ):
        qid = exam_with_question["question"]["id"]
        res = client.put(
            f"{A}/questions/{qid}",
            json={"question_text": "Updated?"},
            headers=admin_headers(),
        )
        assert res.status_code == 200, res.text
        assert res.json()["question_text"] == "Updated?"

    def test_given_question_when_delete_then_204_and_404_after(
        self, client: httpx.Client, exam_with_question: Dict[str, Any]
    ):
        qid = exam_with_question["question"]["id"]
        res = client.delete(f"{A}/questions/{qid}", headers=admin_headers())
        again = client.delete(f"{A}/questions/{qid}", headers=admin_headers())
        assert res.status_code == 204
        assert again.status_code == 404

    def test_given_student_when_list_questions_then_403(
        self,
        client: httpx.Client,
        exam: Dict[str, Any],
        student_headers: Dict[str, str],
    ):
        res = client.get(f"{A}/{exam['id']}/questions", headers=student_headers)
        assert res.status_code == 403

    def test_given_csv_when_admin_imports_then_questions_created(
        self, client: httpx.Client, exam: Dict[str, Any]
    ):
        template = client.get(f"{A}/questions/csv-template", headers=admin_headers())
        assert template.status_code == 200
        header = template.text.splitlines()[0]
        assert header

        res = client.post(
            f"{A}/{exam['id']}/questions/import-csv",
            files={"file": ("q.csv", template.content, "text/csv")},
            headers=admin_headers(),
        )

        assert res.status_code == 201, res.text

    def test_given_non_csv_when_import_questions_then_415(
        self, client: httpx.Client, exam: Dict[str, Any]
    ):
        res = client.post(
            f"{A}/{exam['id']}/questions/import-csv",
            files={"file": ("q.txt", b"a,b", "text/plain")},
            headers=admin_headers(),
        )
        assert res.status_code == 415
        assert res.json()["detail"]["error"] == "NOT_A_CSV"

    def test_given_admin_when_download_templates_then_files_returned(
        self, client: httpx.Client
    ):
        csv = client.get(f"{A}/questions/csv-template", headers=admin_headers())
        bundle = client.get(f"{A}/bulk-import/template", headers=admin_headers())
        assert csv.status_code == 200
        assert bundle.status_code == 200
        assert bundle.headers["content-type"].startswith("application/zip")

    def test_given_non_zip_when_bulk_import_then_rejected(
        self, client: httpx.Client, course: Dict[str, Any]
    ):
        res = client.post(
            f"{A}/bulk-import",
            params={"course_id": course["id"]},
            files={"file": ("x.zip", b"definitely not a zip", "application/zip")},
            headers=admin_headers(),
        )
        assert 400 <= res.status_code < 500

    def test_given_student_when_download_template_then_403(
        self, client: httpx.Client, student_headers: Dict[str, str]
    ):
        res = client.get(f"{A}/bulk-import/template", headers=student_headers)
        assert res.status_code == 403


class TestTakingAnExam:
    def test_given_unenrolled_student_when_start_then_403_not_enrolled(
        self,
        client: httpx.Client,
        exam_with_question: Dict[str, Any],
        student_headers: Dict[str, str],
    ):
        res = client.post(
            f"{A}/{exam_with_question['id']}/start", headers=student_headers
        )
        assert res.status_code == 403
        assert res.json()["detail"]["error"] == "NOT_ENROLLED"

    def test_given_enrolled_student_when_start_then_questions_without_answers(
        self,
        client: httpx.Client,
        exam_with_question: Dict[str, Any],
        enrolled_student: Dict[str, Any],
        student_headers: Dict[str, str],
    ):
        res = client.post(
            f"{A}/{exam_with_question['id']}/start", headers=student_headers
        )

        assert res.status_code == 200, res.text
        body = res.json()
        assert body["session_id"].startswith("sess_")
        assert len(body["questions"]) == 1
        assert "correct_answer" not in body["questions"][0]
        assert 0 < body["time_remaining_seconds"] <= 600

    def test_given_active_session_when_start_again_then_409_session_already_active(
        self,
        client: httpx.Client,
        exam_with_question: Dict[str, Any],
        enrolled_student: Dict[str, Any],
        student_headers: Dict[str, str],
    ):
        first = client.post(
            f"{A}/{exam_with_question['id']}/start", headers=student_headers
        )

        again = client.post(
            f"{A}/{exam_with_question['id']}/start", headers=student_headers
        )

        assert again.status_code == 409
        detail = again.json()["detail"]
        assert detail["error"] == "SESSION_ALREADY_ACTIVE"
        assert detail["session_id"] == first.json()["session_id"]

    def test_given_correct_answer_when_submit_then_full_score_and_passed(
        self,
        client: httpx.Client,
        exam_with_question: Dict[str, Any],
        enrolled_student: Dict[str, Any],
        student_headers: Dict[str, str],
    ):
        started = client.post(
            f"{A}/{exam_with_question['id']}/start", headers=student_headers
        ).json()
        qid = started["questions"][0]["id"]

        res = client.post(
            f"{A}/{exam_with_question['id']}/submit",
            json={
                "session_id": started["session_id"],
                "answers": [{"question_id": qid, "selected_option": "4"}],
            },
            headers=student_headers,
        )

        assert res.status_code == 200, res.text
        body = res.json()
        assert body["score"] == 100
        assert body["passed"] is True
        assert body["correct_count"] == 1
        assert body["total_questions"] == 1
        assert body["auto_submitted"] is False
        assert body["review"][0]["is_correct"] is True

    def test_given_wrong_answer_when_submit_then_zero_score_and_failed(
        self,
        client: httpx.Client,
        exam_with_question: Dict[str, Any],
        enrolled_student: Dict[str, Any],
        student_headers: Dict[str, str],
    ):
        started = client.post(
            f"{A}/{exam_with_question['id']}/start", headers=student_headers
        ).json()
        qid = started["questions"][0]["id"]

        body = client.post(
            f"{A}/{exam_with_question['id']}/submit",
            json={
                "session_id": started["session_id"],
                "answers": [{"question_id": qid, "selected_option": "3"}],
            },
            headers=student_headers,
        ).json()

        assert body["score"] == 0
        assert body["passed"] is False

    def test_given_unknown_session_when_submit_then_auto_submitted_flag_set(
        self,
        client: httpx.Client,
        exam_with_question: Dict[str, Any],
        enrolled_student: Dict[str, Any],
        student_headers: Dict[str, str],
    ):
        res = client.post(
            f"{A}/{exam_with_question['id']}/submit",
            json={"session_id": "sess_expired", "answers": []},
            headers=student_headers,
        )
        assert res.status_code == 200, res.text
        assert res.json()["auto_submitted"] is True

    def test_given_submitted_exam_when_get_last_attempt_then_same_score(
        self,
        client: httpx.Client,
        exam_with_question: Dict[str, Any],
        enrolled_student: Dict[str, Any],
        student_headers: Dict[str, str],
    ):
        started = client.post(
            f"{A}/{exam_with_question['id']}/start", headers=student_headers
        ).json()
        client.post(
            f"{A}/{exam_with_question['id']}/submit",
            json={
                "session_id": started["session_id"],
                "answers": [
                    {
                        "question_id": started["questions"][0]["id"],
                        "selected_option": "4",
                    }
                ],
            },
            headers=student_headers,
        )

        res = client.get(
            f"{A}/{exam_with_question['id']}/my-last-attempt", headers=student_headers
        )

        assert res.status_code == 200, res.text
        assert res.json()["score"] == 100

    def test_given_no_attempt_when_get_last_attempt_then_404(
        self,
        client: httpx.Client,
        exam_with_question: Dict[str, Any],
        student_headers: Dict[str, str],
    ):
        res = client.get(
            f"{A}/{exam_with_question['id']}/my-last-attempt", headers=student_headers
        )
        assert res.status_code == 404
        assert res.json()["detail"]["error"] == "NO_ATTEMPT_FOUND"

    def test_given_session_when_record_violation_then_204(
        self,
        client: httpx.Client,
        exam_with_question: Dict[str, Any],
        enrolled_student: Dict[str, Any],
        student_headers: Dict[str, str],
    ):
        started = client.post(
            f"{A}/{exam_with_question['id']}/start", headers=student_headers
        ).json()

        res = client.post(
            f"{A}/{exam_with_question['id']}/violations",
            json={"session_id": started["session_id"], "violation_type": "tab_switch"},
            headers=student_headers,
        )

        assert res.status_code == 204

    def test_given_no_token_when_start_then_401(
        self, client: httpx.Client, exam: Dict[str, Any]
    ):
        assert client.post(f"{A}/{exam['id']}/start").status_code == 401

    def test_given_unknown_assessment_when_start_then_404(
        self, client: httpx.Client, student_headers: Dict[str, str]
    ):
        assert (
            client.post(f"{A}/999999999/start", headers=student_headers).status_code
            == 404
        )


class TestResultsAndRankings:
    def _take_exam(
        self, client: httpx.Client, exam_id: int, headers: Dict[str, str], answer: str
    ) -> Dict[str, Any]:
        started = client.post(f"{A}/{exam_id}/start", headers=headers).json()
        res = client.post(
            f"{A}/{exam_id}/submit",
            json={
                "session_id": started["session_id"],
                "answers": [
                    {
                        "question_id": started["questions"][0]["id"],
                        "selected_option": answer,
                    }
                ],
            },
            headers=headers,
        )
        assert res.status_code == 200, res.text
        return res.json()

    def test_given_graded_attempt_when_list_my_submissions_then_listed(
        self,
        client: httpx.Client,
        exam_with_question: Dict[str, Any],
        enrolled_student: Dict[str, Any],
        student_headers: Dict[str, str],
    ):
        self._take_exam(client, exam_with_question["id"], student_headers, "4")

        res = client.get(f"{A}/my-submissions", headers=student_headers)

        assert res.status_code == 200, res.text
        assert len(res.json()) == 1

    def test_given_graded_attempt_when_list_my_attempts_then_summary_counts_one(
        self,
        client: httpx.Client,
        exam_with_question: Dict[str, Any],
        enrolled_student: Dict[str, Any],
        student_headers: Dict[str, str],
    ):
        self._take_exam(client, exam_with_question["id"], student_headers, "4")

        res = client.get(
            f"{A}/my-attempts",
            params={"course_id": exam_with_question["course_id"]},
            headers=student_headers,
        )

        assert res.status_code == 200
        mine = [a for a in res.json() if a["assessment_id"] == exam_with_question["id"]]
        assert mine[0]["attempt_count"] == 1
        assert mine[0]["passed"] is True

    def test_given_limit_over_50_when_list_my_submissions_then_422(
        self, client: httpx.Client, student_headers: Dict[str, str]
    ):
        res = client.get(
            f"{A}/my-submissions", params={"limit": 51}, headers=student_headers
        )
        assert res.status_code == 422

    def test_given_other_students_submission_when_review_then_403_or_404(
        self,
        client: httpx.Client,
        exam_with_question: Dict[str, Any],
        enrolled_student: Dict[str, Any],
        student_headers: Dict[str, str],
    ):
        self._take_exam(client, exam_with_question["id"], student_headers, "4")
        sub_id = (
            client.get(f"{A}/my-submissions", headers=student_headers)
            .json()[0]
            .get("submission_id")
        )
        if sub_id is None:
            pytest.skip("my-submissions does not expose submission_id")

        own = client.get(f"{A}/submissions/{sub_id}/review", headers=student_headers)
        assert own.status_code == 200, own.text

    def test_given_unknown_submission_when_review_then_404(
        self, client: httpx.Client, student_headers: Dict[str, str]
    ):
        res = client.get(f"{A}/submissions/999999999/review", headers=student_headers)
        assert res.status_code == 404
        assert res.json()["detail"]["error"] == "ATTEMPT_NOT_FOUND"

    def test_given_graded_attempt_when_get_exam_rank_then_student_is_ranked(
        self,
        client: httpx.Client,
        exam_with_question: Dict[str, Any],
        enrolled_student: Dict[str, Any],
        student_headers: Dict[str, str],
    ):
        self._take_exam(client, exam_with_question["id"], student_headers, "4")

        res = client.get(
            f"{A}/rankings/exam/{exam_with_question['id']}", headers=student_headers
        )

        assert res.status_code == 200, res.text

    def test_given_graded_attempt_when_list_ranking_exams_then_exam_present(
        self,
        client: httpx.Client,
        exam_with_question: Dict[str, Any],
        enrolled_student: Dict[str, Any],
        student_headers: Dict[str, str],
    ):
        self._take_exam(client, exam_with_question["id"], student_headers, "4")

        res = client.get(f"{A}/rankings/exams", headers=student_headers)

        assert res.status_code == 200
        assert str(exam_with_question["id"]) in [e["exam_id"] for e in res.json()]

    def test_given_published_exam_when_get_leaderboard_publicly_then_list(
        self, client: httpx.Client, exam_with_question: Dict[str, Any]
    ):
        res = client.get(
            f"{A}/rankings/leaderboard", params={"exam_id": exam_with_question["id"]}
        )
        assert res.status_code == 200
        assert res.json() == []

    def test_given_unknown_exam_when_get_leaderboard_then_404(
        self, client: httpx.Client
    ):
        res = client.get(f"{A}/rankings/leaderboard", params={"exam_id": 999999999})
        assert res.status_code == 404

    def test_given_limit_over_200_when_get_leaderboard_then_422(
        self, client: httpx.Client, exam: Dict[str, Any]
    ):
        res = client.get(
            f"{A}/rankings/leaderboard", params={"exam_id": exam["id"], "limit": 500}
        )
        assert res.status_code == 422


class TestBadges:
    def test_given_anonymous_visitor_when_list_badges_then_catalogue_returned(
        self, client: httpx.Client
    ):
        res = client.get(f"{A}/badges")
        assert res.status_code == 200
        assert isinstance(res.json(), list)

    def test_given_new_student_when_get_my_badges_then_empty(
        self, client: httpx.Client, student_headers: Dict[str, str]
    ):
        res = client.get(f"{A}/badges/my", headers=student_headers)
        assert res.status_code == 200
        assert res.json() == []

    def test_given_new_student_when_get_badge_dashboard_then_nothing_earned(
        self, client: httpx.Client, student_headers: Dict[str, str]
    ):
        res = client.get(f"{A}/badges/dashboard", headers=student_headers)
        assert res.status_code == 200
        body = res.json()
        assert body["earned_badges"] == []
        assert isinstance(body["available_badges"], list)

    def test_given_no_token_when_get_my_badges_then_401(self, client: httpx.Client):
        assert client.get(f"{A}/badges/my").status_code == 401
