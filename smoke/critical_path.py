#!/usr/bin/env python3
"""
E2E Critical Path Smoke Test for EDURA Platform (DDP-#24)
Covers: student register → OTP verify → login → course list → checkout → webhook → active enrollment → lesson stream → assessment start → progress view.
Target: Staging API (STAGING_API_URL, default: http://localhost)
"""

import hashlib
import os
import sys
import time
import uuid
from typing import Any, Dict, Optional

import httpx
import jwt

# ---------------------------------------------------------------------------
# Configuration & Environment Variables
# ---------------------------------------------------------------------------
BASE_URL = os.getenv("STAGING_API_URL", "http://localhost").rstrip("/")
PAYHERE_MERCHANT_ID = os.getenv("PAYHERE_MERCHANT_ID", "sandbox_merchant_12345")
PAYHERE_MERCHANT_SECRET = os.getenv("PAYHERE_MERCHANT_SECRET", "sandbox_secret_abcdef")
SMOKE_TEST_OTP = os.getenv("SMOKE_TEST_OTP", "123456")
JWT_SECRET_KEY = os.getenv("SECRET_KEY", "edura_super_secret_jwt_key_2026_dev")
JWT_ALGORITHM = "HS256"
REQUEST_TIMEOUT = 30.0

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
    """Generates an administrative JWT token for cleanup actions."""
    payload = {
        "sub": "1",
        "email": "admin@edura.lk",
        "role": "admin",
        "exp": int(time.time()) + 3600,
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
    Cleans up all test data (account, enrollments, payments) created during the test.
    Guaranteed to run in finally block (pass or fail).
    """
    print(f"\n{YELLOW}{BOLD}--- Running AC2 Test Cleanup ---{RESET}")
    admin_token = generate_admin_token()
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    # 1. Delete test enrollment records
    if student_id:
        try:
            resp = client.delete(
                f"{BASE_URL}/api/enrollments/",
                params={"student_id": student_id, "course_id": course_id} if course_id else {"student_id": student_id},
                headers=admin_headers,
                timeout=REQUEST_TIMEOUT,
            )
            print(f"  Cleanup enrollments (student_id={student_id}): HTTP {resp.status_code}")
        except Exception as e:
            print(f"  {YELLOW}Warning: Error deleting test enrollments: {e}{RESET}")

    # 2. Delete test payment records
    if student_id or order_id:
        try:
            params: Dict[str, Any] = {}
            if student_id:
                params["student_id"] = student_id
            if order_id:
                params["order_id"] = order_id
            resp = client.delete(
                f"{BASE_URL}/api/payments/",
                params=params,
                headers=admin_headers,
                timeout=REQUEST_TIMEOUT,
            )
            print(f"  Cleanup payments (student_id={student_id}, order_id={order_id}): HTTP {resp.status_code}")
        except Exception as e:
            print(f"  {YELLOW}Warning: Error deleting test payments: {e}{RESET}")

    # 3. Delete user profile from user_service
    if student_id:
        try:
            resp = client.delete(
                f"{BASE_URL}/api/users/{student_id}",
                headers=admin_headers,
                timeout=REQUEST_TIMEOUT,
            )
            print(f"  Cleanup user profile (student_id={student_id}): HTTP {resp.status_code}")
        except Exception as e:
            print(f"  {YELLOW}Warning: Error deleting user profile: {e}{RESET}")

    # 4. Delete user account from auth_service
    if student_id:
        try:
            resp = client.delete(
                f"{BASE_URL}/api/auth/users/{student_id}",
                headers=admin_headers,
                timeout=REQUEST_TIMEOUT,
            )
            print(f"  Cleanup auth user (student_id={student_id}): HTTP {resp.status_code}")
        except Exception as e:
            print(f"  {YELLOW}Warning: Error deleting auth user: {e}{RESET}")

    print(f"{YELLOW}--- Cleanup Complete ---{RESET}\n")


# ---------------------------------------------------------------------------
# Main Critical Path Execution (AC1 & AC3)
# ---------------------------------------------------------------------------
def run_critical_path() -> bool:
    print(f"\n{BOLD}═══════════════════════════════════════════════════════════════════{RESET}")
    print(f"{BOLD}   EDURA E2E Smoke Test — Critical Path (DDP-#24){RESET}")
    print(f"   Target URL: {CYAN}{BASE_URL}{RESET}")
    print(f"{BOLD}═══════════════════════════════════════════════════════════════════{RESET}")

    unique_suffix = f"{int(time.time())}_{uuid.uuid4().hex[:6]}"
    test_email = f"smoke_student_{unique_suffix}@example.com"
    test_password = "SmokePassword123!"

    student_id: Optional[int] = None
    access_token: Optional[str] = None
    course_id: Optional[int] = None
    lesson_id: int = 1
    assessment_id: int = 1
    order_id: Optional[str] = None
    checkout_amount: float = 1000.00
    checkout_currency: str = "LKR"

    client = httpx.Client(timeout=REQUEST_TIMEOUT, follow_redirects=True)

    try:
        # -------------------------------------------------------------------
        # Step 1: POST /api/auth/register → 201
        # -------------------------------------------------------------------
        step = 1
        title = "POST /api/auth/register (New test student account)"
        print_step_header(step, title)
        reg_payload = {
            "email": test_email,
            "password": test_password,
            "role": "student",
        }
        res = client.post(f"{BASE_URL}/api/auth/register", json=reg_payload)
        if res.status_code != 201:
            print_step_failure(step, title, res.status_code, res.text)
            return False

        reg_data = res.json()
        student_id = reg_data.get("id")
        if not student_id:
            print_step_failure(step, title, res.status_code, "Response missing 'id' field")
            return False
        print_step_success(step, f"Registered student ID={student_id}, email={test_email}")

        # -------------------------------------------------------------------
        # Step 2: POST /api/auth/otp/verify → 200
        # -------------------------------------------------------------------
        step = 2
        title = "POST /api/auth/otp/verify (Verify student email OTP)"
        print_step_header(step, title)
        otp_payload = {
            "user_id": student_id,
            "code": SMOKE_TEST_OTP,
            "purpose": "email_verify",
        }
        res = client.post(f"{BASE_URL}/api/auth/otp/verify", json=otp_payload)
        if res.status_code != 200:
            print_step_failure(step, title, res.status_code, res.text)
            return False
        print_step_success(step, "OTP verified successfully")

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
        # Step 4: GET /api/courses → 200, at least one PUBLISHED course
        # -------------------------------------------------------------------
        step = 4
        title = "GET /api/courses (List published courses)"
        print_step_header(step, title)
        res = client.get(f"{BASE_URL}/api/courses/", headers=auth_headers)
        if res.status_code != 200:
            print_step_failure(step, title, res.status_code, res.text)
            return False

        courses_data = res.json()
        items = courses_data.get("items", []) if isinstance(courses_data, dict) else courses_data
        if not items:
            print_step_failure(step, title, res.status_code, "No courses found; expected at least one PUBLISHED course")
            return False

        first_course = items[0]
        course_id = first_course.get("id")
        course_title = first_course.get("title", "Untitled")
        course_status = first_course.get("status", "")
        checkout_amount = float(first_course.get("price", 1000.00))
        if checkout_amount <= 0:
            checkout_amount = 1000.00

        print_step_success(step, f"Found course ID={course_id} '{course_title}' [Status: {course_status}]")

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
        if res.status_code != 200:
            print_step_failure(step, title, res.status_code, res.text)
            return False
        print_step_success(step, f"Webhook accepted with valid HMAC MD5 signature: {res.json()}")

        # -------------------------------------------------------------------
        # Step 7: GET /api/enrollments → 200, status ACTIVE
        # -------------------------------------------------------------------
        step = 7
        title = "GET /api/enrollments (Verify active enrollment granted via event)"
        print_step_header(step, title)

        # Allow up to 10 seconds for asynchronous RabbitMQ event processing
        enrollment_verified = False
        max_attempts = 10
        enrollment_resp_data = None

        for attempt in range(1, max_attempts + 1):
            time.sleep(1)
            res = client.get(
                f"{BASE_URL}/api/enrollments/",
                params={"student_id": student_id, "course_id": course_id},
                headers=auth_headers,
            )
            if res.status_code == 200:
                enrollment_resp_data = res.json()
                if enrollment_resp_data.get("status") == "ACTIVE":
                    enrollment_verified = True
                    break

        if not enrollment_verified:
            err_msg = res.text if res is not None else "Timeout waiting for enrollment activation"
            status_c = res.status_code if res is not None else 408
            print_step_failure(step, title, status_c, f"Enrollment status not ACTIVE: {err_msg}")
            return False

        print_step_success(
            step,
            f"Enrollment verified ACTIVE: ID={enrollment_resp_data.get('enrollment_id')}, "
            f"Expires={enrollment_resp_data.get('expires_at')}",
        )

        # -------------------------------------------------------------------
        # Step 8: GET /api/content/lessons/{id}/stream → 200, embed_url returned
        # -------------------------------------------------------------------
        step = 8
        title = f"GET /api/content/lessons/{lesson_id}/stream (Stream authorized lesson content)"
        print_step_header(step, title)
        res = client.get(
            f"{BASE_URL}/api/content/lessons/{lesson_id}/stream",
            params={"course_id": course_id, "youtube_video_id": "dQw4w9WgXcQ"},
            headers=auth_headers,
        )
        if res.status_code != 200:
            print_step_failure(step, title, res.status_code, res.text)
            return False

        stream_data = res.json()
        embed_url = stream_data.get("embed_url")
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
        res = client.post(
            f"{BASE_URL}/api/assessments/{assessment_id}/start",
            headers=auth_headers,
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
