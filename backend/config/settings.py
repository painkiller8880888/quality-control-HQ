import os
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from django.core.exceptions import ImproperlyConfigured


BASE_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BASE_DIR.parent

EXPLICIT_ENV_FILE = os.environ.get("DJANGO_ENV_FILE")
ENV_FILE = Path(EXPLICIT_ENV_FILE or str(REPO_DIR / ".env"))
if EXPLICIT_ENV_FILE and not ENV_FILE.is_file():
    raise ImproperlyConfigured(f"DJANGO_ENV_FILE does not exist: {ENV_FILE}")
if ENV_FILE.exists():
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def env_bool(name, default=False):
    raw = os.environ.get(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ImproperlyConfigured(f"{name} must be true or false.")


def env_list(name, default=()):
    raw = os.environ.get(name)
    if raw is None:
        return list(default)
    return [value.strip() for value in raw.split(",") if value.strip()]


APP_ENV = os.environ.get("APP_ENV", "development").strip().lower()
if APP_ENV not in {"development", "pseudoprod", "production"}:
    raise ImproperlyConfigured(
        "APP_ENV must be development, pseudoprod, or production."
    )

DEBUG = env_bool("DJANGO_DEBUG", APP_ENV == "development")
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "").strip()
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = "dev-only-quality-control-hq"
    else:
        raise ImproperlyConfigured("DJANGO_SECRET_KEY is required when DEBUG is false.")

ALLOWED_HOSTS = env_list(
    "DJANGO_ALLOWED_HOSTS",
    ("localhost", "127.0.0.1", "testserver") if DEBUG else (),
)
if not DEBUG and not ALLOWED_HOSTS:
    raise ImproperlyConfigured(
        "DJANGO_ALLOWED_HOSTS is required when DEBUG is false."
    )

APP_PUBLIC_URL = os.environ.get("APP_PUBLIC_URL", "").strip().rstrip("/")
if APP_PUBLIC_URL:
    public_url = urlparse(APP_PUBLIC_URL)
    if public_url.scheme not in {"http", "https"} or not public_url.hostname:
        raise ImproperlyConfigured("APP_PUBLIC_URL must be an explicit http(s) URL.")

APP_VERSION = os.environ.get("APP_VERSION", "development").strip()

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "quality",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
if not DEBUG:
    MIDDLEWARE.insert(1, "whitenoise.middleware.WhiteNoiseMiddleware")

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "HOST": os.environ.get("DB_HOST", "localhost"),
        "PORT": os.environ.get("DB_PORT", "5432"),
        "NAME": os.environ.get("DB_NAME", "quality_control_hq"),
        "USER": os.environ.get("DB_USER", "quality_app"),
        "PASSWORD": os.environ.get("DB_PASSWORD", os.environ.get("QUALITY_APP_PASS", "")),
    }
}

LANGUAGE_CODE = "ja"
TIME_ZONE = "Asia/Tokyo"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = Path(
    os.environ.get("STATIC_ROOT", str(REPO_DIR / "runtime" / "static"))
)
FRONTEND_DIST_DIR = Path(
    os.environ.get("FRONTEND_DIST_DIR", str(REPO_DIR / "backend" / "frontend_dist"))
)
STATICFILES_DIRS = [FRONTEND_DIST_DIR] if FRONTEND_DIST_DIR.exists() else []
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
    },
}
MEDIA_URL = "/media/"
MEDIA_ROOT = Path(os.environ.get("MEDIA_ROOT", str(REPO_DIR / "media")))
SERVE_MEDIA_FILES = env_bool("SERVE_MEDIA_FILES", DEBUG)

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTHENTICATION_BACKENDS = ["quality.authentication.LoginNameBackend"]

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "quality.authentication.ApiSessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
}

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = env_bool("SESSION_COOKIE_SECURE", not DEBUG)
CSRF_COOKIE_SECURE = env_bool("CSRF_COOKIE_SECURE", not DEBUG)

ALLOW_INSECURE_HTTP = env_bool("ALLOW_INSECURE_HTTP", False)
HTTP_RISK_ACCEPTANCE_ID = os.environ.get("HTTP_RISK_ACCEPTANCE_ID", "").strip()
HTTP_RISK_ACCEPTANCE_EXPIRES = os.environ.get(
    "HTTP_RISK_ACCEPTANCE_EXPIRES", ""
).strip()
if ALLOW_INSECURE_HTTP and APP_ENV != "pseudoprod":
    raise ImproperlyConfigured(
        "ALLOW_INSECURE_HTTP is restricted to the pseudoprod environment."
    )
if not DEBUG and (not SESSION_COOKIE_SECURE or not CSRF_COOKIE_SECURE):
    if not APP_PUBLIC_URL or urlparse(APP_PUBLIC_URL).scheme != "http":
        raise ImproperlyConfigured(
            "Insecure cookies require an explicit HTTP APP_PUBLIC_URL."
        )
    if not ALLOW_INSECURE_HTTP:
        raise ImproperlyConfigured(
            "Insecure HTTP cookies require ALLOW_INSECURE_HTTP=true."
        )
    if not HTTP_RISK_ACCEPTANCE_ID or not HTTP_RISK_ACCEPTANCE_EXPIRES:
        raise ImproperlyConfigured(
            "HTTP approval ID and expiry are required for insecure HTTP."
        )
    try:
        acceptance_expiry = date.fromisoformat(HTTP_RISK_ACCEPTANCE_EXPIRES)
    except ValueError as exc:
        raise ImproperlyConfigured(
            "HTTP_RISK_ACCEPTANCE_EXPIRES must use YYYY-MM-DD."
        ) from exc
    if acceptance_expiry < date.today():
        raise ImproperlyConfigured("The HTTP risk acceptance has expired.")

CSRF_TRUSTED_ORIGINS = (
    ["http://localhost:5173", "http://127.0.0.1:5173"] if DEBUG else []
)
for origin in env_list("CSRF_TRUSTED_ORIGINS"):
    origin = origin.rstrip("/")
    if not origin:
        continue
    if "*" in origin or not origin.startswith(("http://", "https://")):
        raise ImproperlyConfigured(
            "CSRF_TRUSTED_ORIGINS must contain explicit http(s) origins without wildcards."
        )
    if origin not in CSRF_TRUSTED_ORIGINS:
        CSRF_TRUSTED_ORIGINS.append(origin)

if not DEBUG and APP_PUBLIC_URL not in CSRF_TRUSTED_ORIGINS:
    raise ImproperlyConfigured(
        "CSRF_TRUSTED_ORIGINS must include APP_PUBLIC_URL when DEBUG is false."
    )

DAILY_REPORT_TEMPLATE = REPO_DIR / "excel" / "daily.xlsm"
DAILY_REPORT_OUTPUT_DIR = REPO_DIR / "reports"
PRESS_PLAN_DIR = r"\\192.168.1.210\@isk\★部門\④製造管理部\★製造\製造業務\巡回検査依頼表兼報告書"
TEST_INPUT_DIR = REPO_DIR / "temp"
