import tempfile
import os
import subprocess
import sys
from pathlib import Path

from django.test import SimpleTestCase, override_settings


class FrontendDeliveryTests(SimpleTestCase):
    def test_version_endpoint_reports_environment_and_version(self):
        with override_settings(APP_ENV="pseudoprod", APP_VERSION="test-build"):
            response = self.client.get("/api/system/version/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"environment": "pseudoprod", "version": "test-build"},
        )

    def test_root_serves_built_frontend_without_cache(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            index_path = Path(temp_dir) / "index.html"
            index_path.write_text("<!doctype html><title>built</title>", encoding="utf-8")
            with override_settings(FRONTEND_DIST_DIR=Path(temp_dir)):
                response = self.client.get("/")
                body = b"".join(response.streaming_content)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertIn(b"<title>built</title>", body)

    def test_api_404_does_not_fall_back_to_frontend(self):
        response = self.client.get("/api/not-a-real-endpoint/")

        self.assertEqual(response.status_code, 404)


class EnvironmentSafetyTests(SimpleTestCase):
    def import_settings(self, overrides):
        with tempfile.TemporaryDirectory() as temp_dir:
            env_file = Path(temp_dir) / "settings.env"
            env_file.write_text("", encoding="utf-8")
            environment = os.environ.copy()
            for name in (
                "APP_ENV",
                "APP_PUBLIC_URL",
                "DJANGO_DEBUG",
                "DJANGO_SECRET_KEY",
                "DJANGO_ALLOWED_HOSTS",
                "CSRF_TRUSTED_ORIGINS",
                "SESSION_COOKIE_SECURE",
                "CSRF_COOKIE_SECURE",
                "ALLOW_INSECURE_HTTP",
                "HTTP_RISK_ACCEPTANCE_ID",
                "HTTP_RISK_ACCEPTANCE_EXPIRES",
            ):
                environment.pop(name, None)
            environment["DJANGO_ENV_FILE"] = str(env_file)
            environment.update(overrides)
            return subprocess.run(
                [sys.executable, "-c", "import config.settings"],
                cwd=Path(__file__).resolve().parent.parent,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )

    def test_pseudoprod_http_requires_approval(self):
        result = self.import_settings(
            {
                "APP_ENV": "pseudoprod",
                "APP_PUBLIC_URL": "http://localhost:8080",
                "DJANGO_DEBUG": "false",
                "DJANGO_SECRET_KEY": "test-secret",
                "DJANGO_ALLOWED_HOSTS": "localhost",
                "CSRF_TRUSTED_ORIGINS": "http://localhost:8080",
                "SESSION_COOKIE_SECURE": "false",
                "CSRF_COOKIE_SECURE": "false",
            }
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ALLOW_INSECURE_HTTP", result.stderr)

    def test_approved_pseudoprod_http_is_valid(self):
        result = self.import_settings(
            {
                "APP_ENV": "pseudoprod",
                "APP_PUBLIC_URL": "http://localhost:8080",
                "DJANGO_DEBUG": "false",
                "DJANGO_SECRET_KEY": "test-secret",
                "DJANGO_ALLOWED_HOSTS": "localhost",
                "CSRF_TRUSTED_ORIGINS": "http://localhost:8080",
                "SESSION_COOKIE_SECURE": "false",
                "CSRF_COOKIE_SECURE": "false",
                "ALLOW_INSECURE_HTTP": "true",
                "HTTP_RISK_ACCEPTANCE_ID": "test-approval",
                "HTTP_RISK_ACCEPTANCE_EXPIRES": "2099-12-31",
            }
        )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_production_cannot_reuse_insecure_http_exception(self):
        result = self.import_settings(
            {
                "APP_ENV": "production",
                "APP_PUBLIC_URL": "http://localhost:8080",
                "DJANGO_DEBUG": "false",
                "DJANGO_SECRET_KEY": "test-secret",
                "DJANGO_ALLOWED_HOSTS": "localhost",
                "CSRF_TRUSTED_ORIGINS": "http://localhost:8080",
                "SESSION_COOKIE_SECURE": "false",
                "CSRF_COOKIE_SECURE": "false",
                "ALLOW_INSECURE_HTTP": "true",
                "HTTP_RISK_ACCEPTANCE_ID": "test-approval",
                "HTTP_RISK_ACCEPTANCE_EXPIRES": "2099-12-31",
            }
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("restricted to the pseudoprod", result.stderr)
