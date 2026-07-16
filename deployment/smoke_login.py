import argparse
import http.cookiejar
import json
import secrets
import sys
import urllib.request
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Run a real HTTP login smoke test.")
    parser.add_argument("--env-file", type=Path, required=True)
    args = parser.parse_args()

    repo_dir = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(repo_dir / "backend"))

    import os

    os.environ["DJANGO_ENV_FILE"] = str(args.env_file.resolve())
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

    import django

    django.setup()

    from django.conf import settings
    from quality.models import AuditLog, User, UserSetting

    stale_user_ids = list(
        User.objects.filter(login_name__startswith="smoke_").values_list("pk", flat=True)
    )
    if stale_user_ids:
        AuditLog.objects.filter(record_id__in=[str(pk) for pk in stale_user_ids]).delete()
        UserSetting.objects.filter(user_id__in=stale_user_ids).delete()
        User.objects.filter(pk__in=stale_user_ids).delete()

    login_name = f"smoke_{secrets.token_hex(6)}"
    password = secrets.token_urlsafe(32)
    user = User(login_name=login_name, display_name="Smoke Test", role=User.Role.ADMIN)
    user.set_password(password)
    user.save()
    UserSetting.objects.create(user=user)
    user_id = user.pk

    cookie_jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))
    base_url = settings.APP_PUBLIC_URL.rstrip("/")

    try:
        with opener.open(f"{base_url}/api/auth/session/", timeout=10) as response:
            session_before = json.load(response)
        if session_before != {"authenticated": False}:
            raise RuntimeError("Unexpected session state before login.")

        csrf_cookie = next(
            (cookie.value for cookie in cookie_jar if cookie.name == "csrftoken"),
            None,
        )
        if not csrf_cookie:
            raise RuntimeError("CSRF cookie was not issued.")

        payload = json.dumps(
            {"login_name": login_name, "password": password}
        ).encode("utf-8")
        login_request = urllib.request.Request(
            f"{base_url}/api/auth/login/",
            data=payload,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-CSRFToken": csrf_cookie,
                "Origin": base_url,
            },
        )
        with opener.open(login_request, timeout=10) as response:
            login_result = json.load(response)
        if login_result.get("user", {}).get("login_name") != login_name:
            raise RuntimeError("Login response did not contain the smoke-test user.")

        with opener.open(f"{base_url}/api/auth/session/", timeout=10) as response:
            session_after = json.load(response)
        if not session_after.get("authenticated"):
            raise RuntimeError("Authenticated session was not retained.")

        csrf_cookie = next(
            (cookie.value for cookie in cookie_jar if cookie.name == "csrftoken"),
            None,
        )
        if not csrf_cookie:
            raise RuntimeError("Rotated CSRF cookie was not retained after login.")

        logout_request = urllib.request.Request(
            f"{base_url}/api/auth/logout/",
            data=b"",
            method="POST",
            headers={"X-CSRFToken": csrf_cookie, "Origin": base_url},
        )
        with opener.open(logout_request, timeout=10) as response:
            if response.status != 204:
                raise RuntimeError("Logout did not return HTTP 204.")

        print("HTTP login, authenticated session, CSRF, and logout: OK")
    finally:
        AuditLog.objects.filter(record_id=str(user_id), operation__in=["login", "logout"]).delete()
        UserSetting.objects.filter(user_id=user_id).delete()
        User.objects.filter(pk=user_id).delete()


if __name__ == "__main__":
    main()
