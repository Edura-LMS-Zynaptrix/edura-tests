"""
Integration tests: payment_service endpoints through the gateway.

The PayHere webhook -> enrollment -> content chain is covered by
test_payment_enrollment_flow.py; this file covers the rest of the service's surface.
"""

import hashlib
import os
import uuid
from typing import Any, Dict, Iterator

import httpx
import pytest

from .conftest import admin_headers

MERCHANT_ID = os.getenv("PAYHERE_MERCHANT_ID", "sandbox_merchant_12345")
MERCHANT_SECRET = os.getenv("PAYHERE_MERCHANT_SECRET", "sandbox_secret_abcdef")


def _signature(order_id: str, amount: str, currency: str, status_code: str) -> str:
    secret_hash = hashlib.md5(MERCHANT_SECRET.encode()).hexdigest().upper()
    raw = f"{MERCHANT_ID}{order_id}{amount}{currency}{status_code}{secret_hash}"
    return hashlib.md5(raw.encode()).hexdigest().upper()


def _webhook_form(order_id: str, status_code: str, signed: bool = True) -> Dict[str, str]:
    amount, currency = "1000.00", "LKR"
    return {
        "merchant_id": MERCHANT_ID,
        "order_id": order_id,
        "payhere_amount": amount,
        "payhere_currency": currency,
        "status_code": status_code,
        "md5sig": _signature(order_id, amount, currency, status_code)
        if signed
        else "0" * 32,
        "payment_id": f"PH-{uuid.uuid4().hex[:8]}",
    }


@pytest.fixture
def bank_account(client: httpx.Client) -> Iterator[Dict[str, Any]]:
    res = client.post(
        "/api/payments/admin/bank-accounts",
        json={
            "bank_name": "IT Bank",
            "account_number": f"{uuid.uuid4().int % 10**10:010d}",
            "account_name": "Integration Test",
            "branch": "Colombo",
            "order_number": 999,
        },
        headers=admin_headers(),
    )
    assert res.status_code == 201, res.text
    body = res.json()
    yield body
    client.delete(
        f"/api/payments/admin/bank-accounts/{body['id']}", headers=admin_headers()
    )


class TestCheckout:
    def test_given_student_when_checkout_then_pending_order_with_hash(
        self, client: httpx.Client, student_headers: Dict[str, str]
    ):
        res = client.post(
            "/api/payments/checkout",
            json={"course_id": 1, "amount": 2500},
            headers=student_headers,
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["order_id"].startswith("ORD-")
        assert body["currency"] == "LKR"
        assert body["amount"] == 2500
        assert len(body["hash"]) == 32

    def test_given_checkout_when_list_own_payments_then_pending_payment_listed(
        self, client: httpx.Client, student_headers: Dict[str, str]
    ):
        client.post(
            "/api/payments/checkout",
            json={"course_id": 1, "amount": 100},
            headers=student_headers,
        )

        res = client.get("/api/payments/", headers=student_headers)

        assert res.status_code == 200
        payments = res.json()
        assert len(payments) == 1
        assert payments[0]["payment_status"].upper() == "PENDING"

    def test_given_no_token_when_checkout_then_401(self, client: httpx.Client):
        res = client.post("/api/payments/checkout", json={"course_id": 1})
        assert res.status_code == 401

    def test_given_missing_course_id_when_checkout_then_422(
        self, client: httpx.Client, student_headers: Dict[str, str]
    ):
        res = client.post("/api/payments/checkout", json={}, headers=student_headers)
        assert res.status_code == 422


class TestListPayments:
    def test_given_no_token_when_list_payments_then_401(self, client: httpx.Client):
        assert client.get("/api/payments/").status_code == 401

    def test_given_new_student_when_list_payments_then_empty(
        self, client: httpx.Client, student_headers: Dict[str, str]
    ):
        res = client.get("/api/payments/", headers=student_headers)
        assert res.status_code == 200
        assert res.json() == []

    def test_given_admin_when_list_payments_then_200(self, client: httpx.Client):
        res = client.get("/api/payments/", headers=admin_headers())
        assert res.status_code == 200
        assert isinstance(res.json(), list)


class TestWebhook:
    def test_given_failed_status_code_when_webhook_then_payment_marked_failed(
        self, client: httpx.Client, student_headers: Dict[str, str]
    ):
        order = client.post(
            "/api/payments/checkout",
            json={"course_id": 1, "amount": 1000},
            headers=student_headers,
        ).json()["order_id"]

        res = client.post("/api/payments/webhook", data=_webhook_form(order, "-2"))

        assert res.status_code == 200, res.text
        assert res.json()["status"] == "FAILED"
        payments = client.get("/api/payments/", headers=student_headers).json()
        assert payments[0]["payment_status"].upper() == "FAILED"

    def test_given_bad_signature_when_webhook_then_400_invalid_signature(
        self, client: httpx.Client
    ):
        form = _webhook_form("ORD-DOESNOTMATTER", "2", signed=False)
        res = client.post("/api/payments/webhook", data=form)
        assert res.status_code == 400
        assert res.json()["detail"]["error"] == "INVALID_SIGNATURE"

    def test_given_valid_signature_but_unknown_order_when_webhook_then_404(
        self, client: httpx.Client
    ):
        res = client.post(
            "/api/payments/webhook", data=_webhook_form("ORD-NOSUCHORDER", "2")
        )
        assert res.status_code == 404
        assert res.json()["detail"]["error"] == "PAYMENT_NOT_FOUND"


class TestFreeEnroll:
    def test_given_unknown_course_when_free_enroll_then_404(
        self, client: httpx.Client, student_headers: Dict[str, str]
    ):
        res = client.post(
            "/api/payments/free-enroll",
            json={"course_id": 999999999},
            headers=student_headers,
        )
        assert res.status_code == 404
        assert res.json()["detail"]["error"] == "COURSE_NOT_FOUND"

    def test_given_admin_token_when_free_enroll_then_403(self, client: httpx.Client):
        res = client.post(
            "/api/payments/free-enroll", json={"course_id": 1}, headers=admin_headers()
        )
        assert res.status_code == 403

    def test_given_no_token_when_free_enroll_then_401(self, client: httpx.Client):
        assert (
            client.post("/api/payments/free-enroll", json={"course_id": 1}).status_code
            == 401
        )


class TestReceipts:
    def test_given_disallowed_mime_when_upload_receipt_then_400_invalid_mime(
        self, client: httpx.Client, student_headers: Dict[str, str]
    ):
        res = client.post(
            "/api/payments/receipts",
            data={"course_id": "1", "amount": "1000"},
            files={"file": ("slip.txt", b"hello", "text/plain")},
            headers=student_headers,
        )
        assert res.status_code == 400
        assert res.json()["detail"]["error"] == "INVALID_MIME_TYPE"

    def test_given_file_over_2mb_when_upload_receipt_then_400_too_large(
        self, client: httpx.Client, student_headers: Dict[str, str]
    ):
        res = client.post(
            "/api/payments/receipts",
            data={"course_id": "1", "amount": "1000"},
            files={"file": ("slip.pdf", b"0" * (2 * 1024 * 1024 + 1), "application/pdf")},
            headers=student_headers,
        )
        assert res.status_code == 400
        assert res.json()["detail"]["error"] == "FILE_TOO_LARGE"

    def test_given_no_token_when_upload_receipt_then_401(self, client: httpx.Client):
        res = client.post(
            "/api/payments/receipts",
            data={"course_id": "1", "amount": "1000"},
            files={"file": ("slip.pdf", b"x", "application/pdf")},
        )
        assert res.status_code == 401

    def test_given_admin_when_list_receipts_then_200(self, client: httpx.Client):
        res = client.get("/api/payments/receipts", headers=admin_headers())
        assert res.status_code == 200
        assert isinstance(res.json(), list)

    def test_given_invalid_status_filter_when_list_receipts_then_422(
        self, client: httpx.Client
    ):
        res = client.get(
            "/api/payments/receipts",
            params={"status_filter": "bogus"},
            headers=admin_headers(),
        )
        assert res.status_code == 422

    def test_given_student_when_list_receipts_then_403(
        self, client: httpx.Client, student_headers: Dict[str, str]
    ):
        assert (
            client.get("/api/payments/receipts", headers=student_headers).status_code
            == 403
        )

    def test_given_unknown_receipt_when_verify_then_404(self, client: httpx.Client):
        res = client.put(
            "/api/payments/receipts/999999999/verify",
            json={"status": "verified"},
            headers=admin_headers(),
        )
        assert res.status_code == 404
        assert res.json()["detail"]["error"] == "RECEIPT_NOT_FOUND"

    def test_given_student_when_verify_receipt_then_403(
        self, client: httpx.Client, student_headers: Dict[str, str]
    ):
        res = client.put(
            "/api/payments/receipts/1/verify",
            json={"status": "verified"},
            headers=student_headers,
        )
        assert res.status_code == 403


class TestBankAccounts:
    def test_given_active_account_when_public_list_then_visible_without_token(
        self, client: httpx.Client, bank_account: Dict[str, Any]
    ):
        res = client.get("/api/payments/bank-accounts")
        assert res.status_code == 200
        assert bank_account["id"] in [a["id"] for a in res.json()]

    def test_given_inactive_account_when_public_list_then_hidden_but_admin_sees(
        self, client: httpx.Client, bank_account: Dict[str, Any]
    ):
        client.patch(
            f"/api/payments/admin/bank-accounts/{bank_account['id']}",
            json={"is_active": False},
            headers=admin_headers(),
        )

        public = client.get("/api/payments/bank-accounts").json()
        admin = client.get(
            "/api/payments/admin/bank-accounts", headers=admin_headers()
        ).json()

        assert bank_account["id"] not in [a["id"] for a in public]
        assert bank_account["id"] in [a["id"] for a in admin]

    def test_given_account_when_patch_then_changes_persist(
        self, client: httpx.Client, bank_account: Dict[str, Any]
    ):
        res = client.patch(
            f"/api/payments/admin/bank-accounts/{bank_account['id']}",
            json={"branch": "Kandy"},
            headers=admin_headers(),
        )
        assert res.status_code == 200, res.text
        assert res.json()["branch"] == "Kandy"

    def test_given_unknown_account_when_patch_then_404(self, client: httpx.Client):
        res = client.patch(
            "/api/payments/admin/bank-accounts/999999999",
            json={"branch": "x"},
            headers=admin_headers(),
        )
        assert res.status_code == 404
        assert res.json()["detail"]["error"] == "BANK_ACCOUNT_NOT_FOUND"

    def test_given_account_when_delete_then_204_and_gone(self, client: httpx.Client):
        created = client.post(
            "/api/payments/admin/bank-accounts",
            json={
                "bank_name": "Temp",
                "account_number": "1",
                "account_name": "Temp",
                "branch": "Temp",
            },
            headers=admin_headers(),
        ).json()

        res = client.delete(
            f"/api/payments/admin/bank-accounts/{created['id']}",
            headers=admin_headers(),
        )

        assert res.status_code == 204
        after = client.delete(
            f"/api/payments/admin/bank-accounts/{created['id']}",
            headers=admin_headers(),
        )
        assert after.status_code == 404

    def test_given_empty_bank_name_when_create_then_422(self, client: httpx.Client):
        res = client.post(
            "/api/payments/admin/bank-accounts",
            json={
                "bank_name": "",
                "account_number": "1",
                "account_name": "x",
                "branch": "x",
            },
            headers=admin_headers(),
        )
        assert res.status_code == 422

    def test_given_student_when_create_bank_account_then_403(
        self, client: httpx.Client, student_headers: Dict[str, str]
    ):
        res = client.post(
            "/api/payments/admin/bank-accounts",
            json={
                "bank_name": "x",
                "account_number": "1",
                "account_name": "x",
                "branch": "x",
            },
            headers=student_headers,
        )
        assert res.status_code == 403

    def test_given_student_when_list_admin_accounts_then_403(
        self, client: httpx.Client, student_headers: Dict[str, str]
    ):
        res = client.get("/api/payments/admin/bank-accounts", headers=student_headers)
        assert res.status_code == 403


class TestInternalEndpointsBlocked:
    def test_given_gateway_when_request_internal_admin_stats_then_blocked(
        self, client: httpx.Client
    ):
        res = client.get("/api/payments/internal/admin-stats", headers=admin_headers())
        assert res.status_code in (403, 404)
