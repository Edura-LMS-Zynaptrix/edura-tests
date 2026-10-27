#!/usr/bin/env python3
"""
E2E Critical Path Smoke Test for EDURA Platform (DDP-#24)
Covers: student register → email verification → login → course list → checkout → webhook →
active enrollment → lesson stream → assessment start → progress view.
Target: Staging API (STAGING_API_URL, default: http://localhost)

The script runs against the live gateway with a fresh test account and removes what it
created afterwards (AC2). It needs the staging SECRET_KEY (to sign the email-verification
link and the cleanup admin token, exactly as auth_service does) and the PayHere merchant
credentials (to sign the mock webhook).
"""

import hashlib
import os
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Optional, Tuple

import httpx
import jwt

# ---------------------------------------------------------------------------
# Configuration & Environment Variables
# ---------------------------------------------------------------------------
def _require_env(name: str) -> str:
    """Return a required environment variable or fail with a clear message."""
    value = os.getenv(name)
    if not value:
        raise RuntimeError(
            f"{name} is not set. Copy .env.example to .env and fill it in "
            "(CI supplies it from GitHub Secrets)."
        )
    return value


BASE_URL = os.getenv("STAGING_API_URL", "http://localhost").rstrip("/")
PAYHERE_MERCHANT_ID = os.getenv("PAYHERE_MERCHANT_ID", "sandbox_merchant_12345")
PAYHERE_MERCHANT_SECRET = _require_env("PAYHERE_MERCHANT_SECRET")
JWT_SECRET_KEY = _require_env("SECRET_KEY")
JWT_ALGORITHM = "HS256"
# Resend's test inbox: accepts any "+label", delivers nothing and never bounces,
# so the verification email auth_service sends on sign-up doesn't hurt the sender domain.
SMOKE_EMAIL_DOMAIN = os.getenv("SMOKE_EMAIL_DOMAIN", "resend.dev")
SMOKE_EMAIL_USER = os.getenv("SMOKE_EMAIL_USER", "delivered")
# Any valid-looking ID: content_service only builds the embed URL from it.
SMOKE_YOUTUBE_VIDEO_ID = os.getenv("SMOKE_YOUTUBE_VIDEO_ID", "M7lc1UVf-VE")
REQUEST_TIMEOUT = 30.0
# Enrollment and access reach other services through RabbitMQ events, so the
# steps that depend on them retry for a while instead of failing on the first try.
EVENT_WAIT_SECONDS = int(os.getenv("SMOKE_EVENT_WAIT_SECONDS", "30"))

# ANSI Color Codes for Clear Reporting
GREEN = "\033[92m"
RED = "\033[91m"
CYAN = "\033[96m"
YELLOW = "\033[93m"
BOLD = "\033[1m"
RESET = "\033[0m"


def print_step_header(step_num: int, title: str):
    print(f"\n{CYAN}{BOLD}[STEP {step_num}/10] {title}{RESET}")


def print_step_success(step_num: int, message: str):
    print(f"  {GREEN}✔ Step {step_num} Passed:{RESET} {message}")


def print_step_failure(step_num: int, title: str, status_code: int, response_body: str):
    print(f"\n{RED}{BOLD}❌ [FAILURE] Step {step_num} Failed: {title}{RESET}")
    print(f"  {RED}HTTP Status:{RESET} {status_code}")
    print(f"  {RED}Response Body:{RESET}\n{response_body}\n")


def generate_admin_token() -> str:
    """An admin access token signed like auth_service's, for the cleanup calls."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": "0",
        "email": "smoke-test@edura.lk",
        "role": "ADMIN",
        "iat": now,
        "exp": now + timedelta(minutes=15),
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def generate_email_verification_token(user_id: int, email: str) -> str:
    """The same signed token auth_service puts in the verification email link."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "purpose": "email_verification",
        "email": email,
        "iat": now,
        "exp": now + timedelta(minutes=15),
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def calculate_payhere_signature(
    merchant_id: str,
    order_id: str,
    amount: str,
    currency: str,
    status_code: str,
    secret: str,
) -> str:
    """Calculates PayHere MD5 HMAC signature for webhook verification."""
    secret_hash = hashlib.md5(secret.encode("utf-8")).hexdigest().upper()
    raw = f"{merchant_id}{order_id}{amount}{currency}{status_code}{secret_hash}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest().upper()


def retry_until(
    attempt: Callable[[], httpx.Response],
    done: Callable[[httpx.Response], bool],
    seconds: int = EVENT_WAIT_SECONDS,
) -> httpx.Response:
    """Repeats a request (once a second) until done(response) or the time runs out."""
    deadline = time.monotonic() + seconds
    res = attempt()
    while not done(res) and time.monotonic() < deadline:
        time.sleep(1)
        res = attempt()
    return res


def started(assessment: Dict[str, Any]) -> bool:
    start = assessment.get("scheduled_start")
    if not start:
        return True
    try:
        return datetime.fromisoformat(start.replace("Z", "+00:00")) <= datetime.now(timezone.utc)
    except ValueError:
        return False


def pick_course_and_assessment(
    client: httpx.Client, headers: Dict[str, str]
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]], str]:
    """
    A published course the critical path can walk end to end: paid (so the PayHere
    checkout → webhook → enrollment path is exercised) with a published assessment
    that has already opened. Falls back to any published course with such an assessment.
    """
    res = client.get(f"{BASE_URL}/api/courses/", params={"page_size": 100}, headers=headers)
    if res.status_code != 200:
        return None, None, f"GET /api/courses/ returned {res.status_code}: {res.text}"
    data = res.json()
    courses = data.get("items", []) if isinstance(data, dict) else data
    if not courses:
        return None, None, "No published courses on this environment"

    def price(c: Dict[str, Any]) -> float:
        try:
            return float(c.get("price") or 0)
        except (TypeError, ValueError):
            return 0.0

    # Paid courses first, then the rest; checked in order until one has a usable exam.
    for course in sorted(courses, key=lambda c: price(c) <= 0):
        res = client.get(
            f"{BASE_URL}/api/assessments/", params={"course_id": course["id"]}, headers=headers
        )
        if res.status_code != 200:
            continue
        usable = [a for a in res.json() if a.get("is_published", True) and started(a)]
        if usable:
            return course, usable[0], ""
    return None, None, (
        f"None of the {len(courses)} published courses has a published assessment that "
        "has already started; publish one on this environment"
    )


# ---------------------------------------------------------------------------
# Cleanup Function (AC2)
# ---------------------------------------------------------------------------
def run_cleanup(
    client: httpx.Client,
    student_id: Optional[int],
    order_id: Optional[str],
    course_id: Optional[int],
):
    """
    Removes the test data (enrollment, profile, account) through the admin API.
    Guaranteed to run in the finally block (pass or fail).
    """
    print(f"\n{YELLOW}{BOLD}--- Running AC2 Test Cleanup ---{RESET}")
    admin_headers = {"Authorization": f"Bearer {generate_admin_token()}"}

    def call(label: str, method: str, path: str, **kwargs):
        try:
            resp = client.request(
                method, f"{BASE_URL}{path}", headers=admin_headers, timeout=REQUEST_TIMEOUT, **kwargs
            )
            print(f"  {label}: HTTP {resp.status_code}")
        except Exception as e:
            print(f"  {YELLOW}Warning: {label} failed: {e}{RESET}")

    # 1. Enrollment: revoked (kept as a CANCELLED record, as the admin UI does).
    if student_id and course_id:
        call(
            f"Revoke enrollment (student_id={student_id}, course_id={course_id})",
            "DELETE",
            "/api/enrollments/admin/revoke",
            params={"user_id": student_id, "course_id": course_id},
        )

    # 2. Payment: payment_service has no delete endpoint; the record stays as an audit trail.
    if order_id:
        print(f"  Payment {order_id}: kept (payment_service exposes no delete endpoint)")

    # 3. Profile in user_service, then the login in auth_service.
    if student_id:
        call(f"Delete user profile (student_id={student_id})", "DELETE", f"/api/users/{student_id}")
        call(f"Delete auth user (student_id={student_id})", "DELETE", f"/api/auth/users/{student_id}")

    print(f"{YELLOW}--- Cleanup Complete ---{RESET}\n")


# ---------------------------------------------------------------------------
# Main Critical Path Execution (AC1 & AC3)
# ---------------------------------------------------------------------------
def run_critical_path() -> bool:
    print(f"\n{BOLD}═══════════════════════════════════════════════════════════════════{RESET}")
    print(f"{BOLD}   EDURA E2E Smoke Test — Critical Path (DDP-#24){RESET}")
    print(f"   Target URL: {CYAN}{BASE_URL}{RESET}")
    print(f"{BOLD}═══════════════════════════════════════════════════════════════════{RESET}")

    unique_suffix = f"{int(time.time())}{uuid.uuid4().hex[:6]}"
    test_email = f"{SMOKE_EMAIL_USER}+smoke{unique_suffix}@{SMOKE_EMAIL_DOMAIN}"
    test_password = "SmokePassword123!"

    student_id: Optional[int] = None
    course_id: Optional[int] = None
    order_id: Optional[str] = None
    res: Optional[httpx.Response] = None

    client = httpx.Client(timeout=REQUEST_TIMEOUT, follow_redirects=True)

    try:
        # -------------------------------------------------------------------
        # Step 1: POST /api/auth/register → 200 (account created, unverified)
        # -------------------------------------------------------------------
        step = 1
        title = "POST /api/auth/register (New test student account)"
        print_step_header(step, title)
        reg_payload = {
            "email": test_email,
            "password": test_password,
            "role": "student",
            "profile": {"first_name": "Smoke", "last_name": "Test"},
        }
        res = client.post(f"{BASE_URL}/api/auth/register", json=reg_payload)
        if res.status_code not in (200, 201):
            print_step_failure(step, title, res.status_code, res.text)
            return False

        reg_data = res.json()
        student_id = reg_data.get("id")
        if not student_id:
            print_step_failure(step, title, res.status_code, "Response missing 'id' field")
            return False
        print_step_success(step, f"Registered student ID={student_id}, email={test_email}")

        # -------------------------------------------------------------------
        # Step 2: POST /api/auth/verify-email → 200 (the emailed verification link)
        # -------------------------------------------------------------------
        step = 2
        title = "POST /api/auth/verify-email (Verify student email)"
        print_step_header(step, title)
        token = generate_email_verification_token(student_id, test_email)
        res = client.post(f"{BASE_URL}/api/auth/verify-email", json={"token": token})
        if res.status_code != 200:
            print_step_failure(step, title, res.status_code, res.text)
            return False
        print_step_success(step, "Email verified with the signed verification link")

        # -------------------------------------------------------------------
        # Step 3: POST /api/auth/login → 200
        # -------------------------------------------------------------------
        step = 3
        title = "POST /api/auth/login (Authenticate student & obtain JWT)"
        print_step_header(step, title)
        login_payload = {
            "email": test_email,
            "password": test_password,
        }
        res = client.post(f"{BASE_URL}/api/auth/login", json=login_payload)
        if res.status_code != 200:
            print_step_failure(step, title, res.status_code, res.text)
            return False

        login_data = res.json()
        access_token = login_data.get("access_token")
        if not access_token:
            print_step_failure(step, title, res.status_code, "Response missing 'access_token'")
            return False
        auth_headers = {"Authorization": f"Bearer {access_token}"}
        print_step_success(step, f"Access token received ({login_data.get('token_type', 'Bearer')})")

        # -------------------------------------------------------------------
        # Step 4: GET /api/courses → 200, a PUBLISHED course with an open assessment
        # -------------------------------------------------------------------
        step = 4
        title = "GET /api/courses (List published courses)"
        print_step_header(step, title)
        course, assessment, why_not = pick_course_and_assessment(client, auth_headers)
        if not course or not assessment:
            print_step_failure(step, title, 200, why_not)
            return False

        course_id = course["id"]
        assessment_id = assessment["id"]
        try:
            checkout_amount = float(course.get("price") or 0)
        except (TypeError, ValueError):
            checkout_amount = 0.0
        if checkout_amount <= 0:
            checkout_amount = 1000.00
        print_step_success(
            step,
            f"Found course ID={course_id} '{course.get('title', 'Untitled')}' "
            f"[Status: {course.get('status', '')}, price {checkout_amount:.2f}] "
            f"with assessment ID={assessment_id}",
        )

        # -------------------------------------------------------------------
        # Step 5: POST /api/payments/checkout → 200, redirect_url returned
        # -------------------------------------------------------------------
        step = 5
        title = "POST /api/payments/checkout (Initialize PayHere checkout)"
        print_step_header(step, title)
        checkout_payload = {
            "course_id": course_id,
            "amount": checkout_amount,
        }
        res = client.post(
            f"{BASE_URL}/api/payments/checkout",
            json=checkout_payload,
            headers=auth_headers,
        )
        if res.status_code != 200:
            print_step_failure(step, title, res.status_code, res.text)
            return False

        checkout_data = res.json()
        order_id = checkout_data.get("order_id")
        redirect_url = checkout_data.get("redirect_url")
        checkout_amount = float(checkout_data.get("amount", checkout_amount))
        checkout_currency = checkout_data.get("currency", "LKR")

        if not order_id or not redirect_url:
            print_step_failure(step, title, res.status_code, "Missing 'order_id' or 'redirect_url'")
            return False
        print_step_success(step, f"Checkout initialized. Order={order_id}, Redirect={redirect_url}")

        # -------------------------------------------------------------------
        # Step 6: POST /api/payments/webhook with valid HMAC → 200
        # -------------------------------------------------------------------
        step = 6
        title = "POST /api/payments/webhook (Mock PayHere server-to-server webhook)"
        print_step_header(step, title)
        formatted_amount = f"{checkout_amount:.2f}"
        status_code_str = "2"  # PayHere Success status code
        actual_merchant_id = str(checkout_data.get("merchant_id") or PAYHERE_MERCHANT_ID)

        md5sig = calculate_payhere_signature(
            merchant_id=actual_merchant_id,
            order_id=order_id,
            amount=formatted_amount,
            currency=checkout_currency,
            status_code=status_code_str,
            secret=PAYHERE_MERCHANT_SECRET,
        )

        webhook_data = {
            "merchant_id": actual_merchant_id,
            "order_id": order_id,
            "payhere_amount": formatted_amount,
            "payhere_currency": checkout_currency,
            "status_code": status_code_str,
            "md5sig": md5sig,
            "payment_id": f"PAY-{uuid.uuid4().hex[:8].upper()}",
        }

        res = client.post(
            f"{BASE_URL}/api/payments/webhook",
            data=webhook_data,
        )
        if res.status_code != 200 or res.json().get("status") != "SUCCESS":
            print_step_failure(step, title, res.status_code, res.text)
            return False
        print_step_success(step, f"Webhook accepted with valid HMAC MD5 signature: {res.json()}")

        # -------------------------------------------------------------------
        # Step 7: GET /api/enrollments/me → 200, enrollment ACTIVE
        # -------------------------------------------------------------------
        step = 7
        title = "GET /api/enrollments/me (Verify active enrollment granted via event)"
        print_step_header(step, title)

        def active_enrollment(r: httpx.Response) -> Optional[Dict[str, Any]]:
            if r.status_code != 200:
                return None
            for e in r.json():
                if e.get("course_id") == course_id and e.get("status") == "ACTIVE" and not e.get("module_id"):
                    return e
            return None

        res = retry_until(
            lambda: client.get(
                f"{BASE_URL}/api/enrollments/me", params={"course_id": course_id}, headers=auth_headers
            ),
            lambda r: active_enrollment(r) is not None,
        )
        enrollment = active_enrollment(res)
        if not enrollment:
            print_step_failure(
                step,
                title,
                res.status_code,
                f"No ACTIVE enrollment for course {course_id} after {EVENT_WAIT_SECONDS}s: {res.text}",
            )
            return False
        print_step_success(
            step,
            f"Enrollment verified ACTIVE: ID={enrollment.get('enrollment_id')}, "
            f"Expires={enrollment.get('expires_at')}",
        )

        # -------------------------------------------------------------------
        # Step 8: GET /api/content/lessons/{id}/stream → 200, embed_url returned
        # -------------------------------------------------------------------
        lesson_id = assessment.get("lesson_id") or assessment.get("module_id") or 1
        step = 8
        title = f"GET /api/content/lessons/{lesson_id}/stream (Stream authorized lesson content)"
        print_step_header(step, title)
        res = retry_until(
            lambda: client.get(
                f"{BASE_URL}/api/content/lessons/{lesson_id}/stream",
                params={"course_id": course_id, "youtube_video_id": SMOKE_YOUTUBE_VIDEO_ID},
                headers=auth_headers,
            ),
            lambda r: r.status_code != 403,  # access reaches content_service by event
        )
        if res.status_code != 200:
            print_step_failure(step, title, res.status_code, res.text)
            return False

        embed_url = res.json().get("embed_url")
        if not embed_url:
            print_step_failure(step, title, res.status_code, "Response missing 'embed_url'")
            return False
        print_step_success(step, f"Stream embed_url returned: {embed_url}")

        # -------------------------------------------------------------------
        # Step 9: POST /api/assessments/{id}/start → 200, session created
        # -------------------------------------------------------------------
        step = 9
        title = f"POST /api/assessments/{assessment_id}/start (Start assessment session)"
        print_step_header(step, title)
        res = retry_until(
            lambda: client.post(f"{BASE_URL}/api/assessments/{assessment_id}/start", headers=auth_headers),
            lambda r: r.status_code != 403,  # access reaches assessment_service by event
        )
        if res.status_code != 200:
            print_step_failure(step, title, res.status_code, res.text)
            return False

        session_data = res.json()
        session_id = session_data.get("session_id")
        if not session_id:
            print_step_failure(step, title, res.status_code, "Response missing 'session_id'")
            return False
        print_step_success(
            step,
            f"Assessment session created: session_id={session_id}, "
            f"time_remaining={session_data.get('time_remaining_seconds')}s",
        )

        # -------------------------------------------------------------------
        # Step 10: GET /api/progress/courses/{id} → 200, completion_percentage returned
        # -------------------------------------------------------------------
        step = 10
        title = f"GET /api/progress/courses/{course_id} (Verify learner progress dashboard)"
        print_step_header(step, title)
        res = client.get(
            f"{BASE_URL}/api/progress/courses/{course_id}",
            headers=auth_headers,
        )
        if res.status_code != 200:
            print_step_failure(step, title, res.status_code, res.text)
            return False

        progress_data = res.json()
        if "completion_percentage" not in progress_data:
            print_step_failure(step, title, res.status_code, "Response missing 'completion_percentage'")
            return False
        print_step_success(
            step,
            f"Progress dashboard returned: completion={progress_data.get('completion_percentage')}%, "
            f"lessons={progress_data.get('watched_lessons')}/{progress_data.get('total_lessons')}",
        )

        # -------------------------------------------------------------------
        # All Steps Completed Successfully
        # -------------------------------------------------------------------
        print(f"\n{GREEN}{BOLD}═══════════════════════════════════════════════════════════════════{RESET}")
        print(f"{GREEN}{BOLD}   🎉 ALL 10 CRITICAL PATH STEPS PASSED SUCCESSFULLY! (AC1){RESET}")
        print(f"{GREEN}{BOLD}═══════════════════════════════════════════════════════════════════{RESET}\n")
        return True

    except Exception as exc:
        print(f"\n{RED}{BOLD}❌ Unexpected Exception occurred during critical path run:{RESET} {exc}")
        import traceback

        traceback.print_exc()
        return False

    finally:
        # AC2: Cleanup function deletes test data
        run_cleanup(client, student_id, order_id, course_id)
        client.close()


def test_critical_path():
    """Pytest hook for running critical path test suite."""
    success = run_critical_path()
    assert success is True, "Critical path smoke test failed"


if __name__ == "__main__":
    success = run_critical_path()
    sys.exit(0 if success else 1)
