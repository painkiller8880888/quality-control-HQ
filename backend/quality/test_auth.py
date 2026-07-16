import base64
import tempfile
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from PIL import Image as PillowImage

from .models import History, InspectionSession, InspectionTarget, Master, User


def make_user(login_name, role=User.Role.WORKER):
    user = User(login_name=login_name, display_name=login_name, role=role)
    user.set_password("test-password")
    user.save()
    return user


class AuthenticationTests(TestCase):
    def setUp(self):
        self.client = APIClient(enforce_csrf_checks=True)
        self.client.get("/api/auth/session/")
        self.csrf = self.client.cookies["csrftoken"].value

    def test_register_always_creates_worker_and_logs_in(self):
        response = self.client.post(
            "/api/auth/register/",
            {"login_name": "new-user", "password": "test-password", "role": "admin"},
            format="json",
            HTTP_X_CSRFTOKEN=self.csrf,
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(User.objects.get(login_name="new-user").role, User.Role.WORKER)
        self.assertTrue(self.client.get("/api/auth/session/").json()["authenticated"])
        settings_response = self.client.put(
            "/api/me/settings/",
            {"theme": "dark"},
            format="json",
            HTTP_X_CSRFTOKEN=self.client.cookies["csrftoken"].value,
        )
        self.assertEqual(settings_response.status_code, 200)
        self.assertTrue(settings_response.json()["browser_settings_imported"])
        self.assertEqual(settings_response.json()["theme"], "dark")
        self.assertNotIn("font_size", settings_response.json())

    def test_profile_updates_display_name_and_password_without_changing_login_name(self):
        user = make_user("profile-user")
        self.client.post(
            "/api/auth/login/",
            {"login_name": user.login_name, "password": "test-password"},
            format="json",
            HTTP_X_CSRFTOKEN=self.csrf,
        )
        response = self.client.patch(
            "/api/me/profile/",
            {
                "display_name": "表示名",
                "login_name": "ignored-name",
                "current_password": "test-password",
                "new_password": "new-password",
                "new_password_confirm": "new-password",
            },
            format="json",
            HTTP_X_CSRFTOKEN=self.client.cookies["csrftoken"].value,
        )
        self.assertEqual(response.status_code, 200)
        user.refresh_from_db()
        self.assertEqual(user.display_name, "表示名")
        self.assertEqual(user.login_name, "profile-user")
        self.assertTrue(user.check_password("new-password"))
        self.assertTrue(self.client.get("/api/auth/session/").json()["authenticated"])

    def test_profile_password_requires_all_three_fields(self):
        user = make_user("partial-password")
        self.client.force_authenticate(user)
        response = self.client.patch(
            "/api/me/profile/",
            {"new_password": "new-password"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_profile_rejects_wrong_current_password(self):
        user = make_user("wrong-current-password")
        self.client.force_authenticate(user)
        response = self.client.patch("/api/me/profile/", {"current_password": "wrong-password", "new_password": "new-password", "new_password_confirm": "new-password"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("current_password", response.json())

    def test_profile_rejects_password_confirmation_mismatch(self):
        user = make_user("password-mismatch")
        self.client.force_authenticate(user)
        response = self.client.patch("/api/me/profile/", {"current_password": "test-password", "new_password": "new-password", "new_password_confirm": "different-password"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("new_password_confirm", response.json())

    def test_profile_accepts_png_avatar_and_returns_authenticated_url(self):
        user = make_user("avatar-user")
        self.client.force_authenticate(user)
        png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")
        avatar = SimpleUploadedFile("avatar.png", png, content_type="image/png")
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            response = self.client.patch("/api/me/profile/", {"avatar": avatar}, format="multipart")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["user"]["avatar_url"].startswith("/api/me/avatar/?v="))

    def test_avatar_requires_authentication(self):
        self.assertEqual(APIClient().get("/api/me/avatar/").status_code, 401)

    def test_avatar_returns_404_when_not_registered_or_missing(self):
        user = make_user("avatar-missing")
        self.client.force_authenticate(user)
        self.assertEqual(self.client.get("/api/me/avatar/").status_code, 404)
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            user.avatar = "avatars/missing.png"
            user.save(update_fields=["avatar"])
            self.assertEqual(self.client.get("/api/me/avatar/").status_code, 404)

    def test_avatar_returns_image_with_private_headers(self):
        user = make_user("avatar-download")
        self.client.force_authenticate(user)
        png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            user.avatar.save("avatar.png", SimpleUploadedFile("avatar.png", png, content_type="image/png"))
            response = self.client.get("/api/me/avatar/")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(b"".join(response.streaming_content), png)
        self.assertEqual(response["Content-Type"], "image/png")
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response["Content-Disposition"], "inline")

    def test_avatar_storage_error_does_not_expose_path(self):
        user = make_user("avatar-storage-error")
        user.avatar = "avatars/avatar.webp"
        user.save(update_fields=["avatar"])
        self.client.force_authenticate(user)
        secret_path = r"\\internal-server\secret\avatars"
        with patch.object(user.avatar.storage, "open", side_effect=OSError(secret_path)):
            response = self.client.get("/api/me/avatar/")
        self.assertEqual(response.status_code, 503)
        self.assertNotIn(secret_path, response.content.decode())

    def test_replacing_avatar_deletes_old_file_after_commit(self):
        user = make_user("avatar-replace")
        self.client.force_authenticate(user)
        png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            first = SimpleUploadedFile("first.png", png, content_type="image/png")
            self.client.patch("/api/me/profile/", {"avatar": first}, format="multipart")
            user.refresh_from_db()
            old_name = user.avatar.name
            old_path = Path(media_root, old_name)
            self.assertTrue(old_path.exists())
            second = SimpleUploadedFile("second.png", png, content_type="image/png")
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.patch("/api/me/profile/", {"avatar": second}, format="multipart")
            self.assertEqual(response.status_code, 200)
            self.assertFalse(old_path.exists())

    def test_avatar_name_and_mime_are_normalized_from_image_data(self):
        user = make_user("avatar-format")
        self.client.force_authenticate(user)
        buffer = BytesIO()
        PillowImage.new("RGB", (1, 1), "white").save(buffer, format="JPEG")
        upload = SimpleUploadedFile("mismatched.png", buffer.getvalue(), content_type="image/png")
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            response = self.client.patch("/api/me/profile/", {"avatar": upload}, format="multipart")
            self.assertEqual(response.status_code, 200)
            user.refresh_from_db()
            self.assertTrue(user.avatar.name.endswith(".jpg"))
            image_response = self.client.get("/api/me/avatar/")
            self.assertEqual(image_response.status_code, 200)
            self.assertEqual(image_response["Content-Type"], "image/jpeg")
            b"".join(image_response.streaming_content)

    def test_profile_rejects_non_image_avatar(self):
        user = make_user("bad-avatar")
        self.client.force_authenticate(user)
        avatar = SimpleUploadedFile("avatar.txt", b"not an image", content_type="text/plain")
        response = self.client.patch("/api/me/profile/", {"avatar": avatar}, format="multipart")
        self.assertEqual(response.status_code, 400)

    def test_avatar_delete_failure_does_not_fail_profile_update(self):
        user = make_user("avatar-delete-failure")
        self.client.force_authenticate(user)
        png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            self.client.patch(
                "/api/me/profile/",
                {"avatar": SimpleUploadedFile("first.png", png, content_type="image/png")},
                format="multipart",
            )
            user.refresh_from_db()
            with patch.object(user.avatar.storage, "delete", side_effect=OSError("share unavailable")):
                with self.captureOnCommitCallbacks(execute=True):
                    response = self.client.patch(
                        "/api/me/profile/",
                        {"avatar": SimpleUploadedFile("second.png", png, content_type="image/png")},
                        format="multipart",
                    )
            self.assertEqual(response.status_code, 200)

    def test_login_requires_csrf(self):
        make_user("worker")
        no_csrf = APIClient(enforce_csrf_checks=True)
        response = no_csrf.post("/api/auth/login/", {"login_name": "worker", "password": "test-password"}, format="json")
        self.assertEqual(response.status_code, 403)

    def test_login_accepts_trusted_frontend_origin_with_csrf(self):
        make_user("trusted-worker")
        response = self.client.post(
            "/api/auth/login/",
            {"login_name": "trusted-worker", "password": "test-password"},
            format="json",
            HTTP_ORIGIN="http://localhost:5173",
            HTTP_X_CSRFTOKEN=self.csrf,
        )
        self.assertEqual(response.status_code, 200)

    def test_login_rejects_untrusted_origin_even_with_csrf(self):
        make_user("untrusted-worker")
        response = self.client.post(
            "/api/auth/login/",
            {"login_name": "untrusted-worker", "password": "test-password"},
            format="json",
            HTTP_ORIGIN="http://evil.example",
            HTTP_X_CSRFTOKEN=self.csrf,
        )
        self.assertEqual(response.status_code, 403)


class AuthorizationTests(TestCase):
    def setUp(self):
        self.worker = make_user("worker")
        self.other = make_user("other")
        self.admin = make_user("admin", User.Role.ADMIN)

    def test_business_api_requires_login(self):
        self.assertEqual(APIClient().get("/api/inspection-targets/?date=2026-07-13").status_code, 401)

    def test_worker_cannot_access_admin_setting(self):
        client = APIClient()
        client.force_authenticate(self.worker)
        self.assertEqual(client.get("/api/settings/").status_code, 403)
        self.assertEqual(client.post("/api/master/update/", {"force": False}, format="json").status_code, 403)
        self.assertEqual(client.post("/api/erp/automate/", {}, format="json").status_code, 403)

    def test_unchecking_history_soft_deletes_and_rechecking_revives(self):
        master = Master.objects.create(code="HIS0001", name="History")
        session = InspectionSession.objects.create(target_date="2026-07-13", owner_user=self.worker, created_by=self.worker, updated_by=self.worker)
        target = InspectionTarget.objects.create(session=session, master=master, raw_code=master.code, normalized_code=master.code, class_override=2, registration_route="ocr", created_by=self.worker, updated_by=self.worker)
        client = APIClient()
        client.force_authenticate(self.worker)
        payload = {"date": "2026-07-13", "target_id": target.id, "time": "A", "checked": True}
        self.assertEqual(client.patch("/api/history/", payload, format="json").status_code, 200)
        payload["checked"] = False
        client.patch("/api/history/", payload, format="json")
        history = History.objects.get(created_by=self.worker, master=master)
        self.assertIsNotNone(history.deleted_at)
        self.assertEqual(history.deleted_by, self.worker)
        payload["checked"] = True
        client.patch("/api/history/", payload, format="json")
        history.refresh_from_db()
        self.assertIsNone(history.deleted_at)
        self.assertIsNone(history.deleted_by)

    def test_dashboard_is_scoped_to_owner(self):
        master = Master.objects.create(code="OWN0001", name="Owned")
        own_session = InspectionSession.objects.create(target_date="2026-07-13", owner_user=self.worker, created_by=self.worker)
        other_session = InspectionSession.objects.create(target_date="2026-07-13", owner_user=self.other, created_by=self.other)
        InspectionTarget.objects.create(session=own_session, master=master, raw_code=master.code, normalized_code=master.code, created_by=self.worker)
        InspectionTarget.objects.create(session=other_session, master=master, raw_code=master.code, normalized_code=master.code, class_override=9, created_by=self.other)
        client = APIClient()
        client.force_authenticate(self.worker)
        response = client.get("/api/inspection-targets/?date=2026-07-13")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 1)

    def test_last_admin_cannot_be_demoted(self):
        client = APIClient()
        client.force_authenticate(self.admin)
        response = client.patch(f"/api/admin/users/{self.admin.pk}/", {"role": "worker"}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_admin_user_payload_does_not_use_current_user_avatar_endpoint(self):
        self.admin.avatar = "avatars/admin.png"
        self.admin.save(update_fields=["avatar"])
        client = APIClient()
        client.force_authenticate(self.admin)
        payload = client.get("/api/admin/users/").json()
        self.assertTrue(payload)
        self.assertTrue(all(item["avatar_url"] is None for item in payload))
