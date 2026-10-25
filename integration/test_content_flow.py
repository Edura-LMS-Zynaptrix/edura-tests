"""
Integration tests: content_service through the gateway.

Uploads that would reach Cloudinary are only exercised on their rejection paths
(auth, MIME type, forbidden prefix), so the suite leaves no assets behind.
"""

from typing import Dict

import httpx

from .conftest import admin_headers

PDF_BYTES = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"


class TestSignedUrl:
    def test_given_admin_when_request_signed_url_then_returns_url_and_expiry(
        self, client: httpx.Client
    ):
        res = client.post(
            "/api/content/signed-url",
            json={"public_id": "edura/content/sample", "course_id": 1},
            headers=admin_headers(),
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["signed_url"].startswith("http")
        assert body["expires_at"] > 0

    def test_given_unenrolled_student_when_request_signed_url_then_403_not_enrolled(
        self, client: httpx.Client, student_headers: Dict[str, str]
    ):
        res = client.post(
            "/api/content/signed-url",
            json={"public_id": "edura/content/sample", "course_id": 999999999},
            headers=student_headers,
        )
        assert res.status_code == 403
        assert res.json()["detail"]["error"] == "NOT_ENROLLED"

    def test_given_no_token_when_request_signed_url_then_401(self, client: httpx.Client):
        res = client.post(
            "/api/content/signed-url", json={"public_id": "x", "course_id": 1}
        )
        assert res.status_code == 401

    def test_given_missing_course_id_when_request_signed_url_then_422(
        self, client: httpx.Client
    ):
        res = client.post(
            "/api/content/signed-url",
            json={"public_id": "x"},
            headers=admin_headers(),
        )
        assert res.status_code == 422


class TestLessonStream:
    def test_given_admin_when_stream_lesson_then_embed_url_built_from_video_id(
        self, client: httpx.Client
    ):
        res = client.get(
            "/api/content/lessons/1/stream",
            params={"youtube_video_id": "M7lc1UVf-VE"},
            headers=admin_headers(),
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert "M7lc1UVf-VE" in body["embed_url"]
        assert body["embed_url"].startswith("https://www.youtube-nocookie.com/embed/")

    def test_given_student_without_course_id_when_stream_then_422(
        self, client: httpx.Client, student_headers: Dict[str, str]
    ):
        res = client.get(
            "/api/content/lessons/1/stream",
            params={"youtube_video_id": "M7lc1UVf-VE"},
            headers=student_headers,
        )
        assert res.status_code == 422
        assert res.json()["detail"]["error"] == "COURSE_ID_REQUIRED"

    def test_given_unenrolled_student_when_stream_then_403(
        self, client: httpx.Client, student_headers: Dict[str, str]
    ):
        res = client.get(
            "/api/content/lessons/1/stream",
            params={"youtube_video_id": "M7lc1UVf-VE", "course_id": 999999999},
            headers=student_headers,
        )
        assert res.status_code == 403
        assert res.json()["detail"]["error"] == "NOT_ENROLLED"

    def test_given_missing_video_id_when_stream_then_422(self, client: httpx.Client):
        res = client.get("/api/content/lessons/1/stream", headers=admin_headers())
        assert res.status_code == 422


class TestUploadRejections:
    def test_given_no_token_when_upload_then_401(self, client: httpx.Client):
        res = client.post(
            "/api/content/upload",
            files={"file": ("a.pdf", PDF_BYTES, "application/pdf")},
        )
        assert res.status_code == 401

    def test_given_student_when_upload_then_403(
        self, client: httpx.Client, student_headers: Dict[str, str]
    ):
        res = client.post(
            "/api/content/upload",
            files={"file": ("a.pdf", PDF_BYTES, "application/pdf")},
            headers=student_headers,
        )
        assert res.status_code == 403

    def test_given_disallowed_mime_when_upload_then_415(self, client: httpx.Client):
        res = client.post(
            "/api/content/upload",
            files={"file": ("a.txt", b"hello", "text/plain")},
            headers=admin_headers(),
        )
        assert res.status_code == 415
        assert res.json()["detail"]["error"] == "UNSUPPORTED_MEDIA_TYPE"

    def test_given_pdf_declared_but_text_content_when_upload_then_415(
        self, client: httpx.Client
    ):
        res = client.post(
            "/api/content/upload",
            files={"file": ("fake.pdf", b"just some text", "application/pdf")},
            headers=admin_headers(),
        )
        assert res.status_code == 415

    def test_given_disallowed_mime_when_upload_material_then_415(
        self, client: httpx.Client
    ):
        res = client.post(
            "/api/content/upload-material",
            files={"file": ("a.exe", b"MZ", "application/octet-stream")},
            headers=admin_headers(),
        )
        assert res.status_code == 415

    def test_given_student_when_upload_material_then_403(
        self, client: httpx.Client, student_headers: Dict[str, str]
    ):
        res = client.post(
            "/api/content/upload-material",
            files={"file": ("a.pdf", PDF_BYTES, "application/pdf")},
            headers=student_headers,
        )
        assert res.status_code == 403


class TestAvatarUpload:
    def test_given_no_token_when_upload_avatar_then_401(self, client: httpx.Client):
        res = client.post(
            "/api/content/avatar",
            files={"file": ("a.png", b"x", "image/png")},
        )
        assert res.status_code == 401

    def test_given_pdf_when_upload_avatar_then_415(
        self, client: httpx.Client, student_headers: Dict[str, str]
    ):
        res = client.post(
            "/api/content/avatar",
            files={"file": ("a.pdf", PDF_BYTES, "application/pdf")},
            headers=student_headers,
        )
        assert res.status_code == 415

    def test_given_png_declared_but_not_an_image_when_upload_avatar_then_415(
        self, client: httpx.Client, student_headers: Dict[str, str]
    ):
        res = client.post(
            "/api/content/avatar",
            files={"file": ("a.png", b"not really a png", "image/png")},
            headers=student_headers,
        )
        assert res.status_code == 415


class TestDeleteAsset:
    def test_given_foreign_public_id_when_delete_asset_then_403_not_deletable(
        self, client: httpx.Client
    ):
        res = client.delete(
            "/api/content/assets",
            params={"public_id": "somewhere/else/file"},
            headers=admin_headers(),
        )
        assert res.status_code == 403
        assert res.json()["detail"]["error"] == "ASSET_NOT_DELETABLE"

    def test_given_path_traversal_when_delete_asset_then_403(
        self, client: httpx.Client
    ):
        res = client.delete(
            "/api/content/assets",
            params={"public_id": "edura/uploads/../../secret"},
            headers=admin_headers(),
        )
        assert res.status_code == 403

    def test_given_student_when_delete_asset_then_403(
        self, client: httpx.Client, student_headers: Dict[str, str]
    ):
        res = client.delete(
            "/api/content/assets",
            params={"public_id": "edura/content/x"},
            headers=student_headers,
        )
        assert res.status_code == 403

    def test_given_missing_public_id_when_delete_asset_then_422(
        self, client: httpx.Client
    ):
        res = client.delete("/api/content/assets", headers=admin_headers())
        assert res.status_code == 422
