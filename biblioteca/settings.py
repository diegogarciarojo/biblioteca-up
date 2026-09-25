import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
DEBUG = os.getenv("DJANGO_DEBUG", "0") == "1"
USE_HTTPS = os.getenv("DJANGO_USE_HTTPS", "1") == "1"
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "")
if not SECRET_KEY and not DEBUG:
    raise RuntimeError("Configura DJANGO_SECRET_KEY en .env antes de iniciar.")
if not SECRET_KEY:
    SECRET_KEY = "development-only-insecure-key"

ALLOWED_HOSTS = [host.strip() for host in os.getenv(
    "DJANGO_ALLOWED_HOSTS", "biblioteca.dns.army,localhost,127.0.0.1"
).split(",") if host.strip()]
CSRF_TRUSTED_ORIGINS = [origin.strip() for origin in os.getenv(
    "DJANGO_CSRF_TRUSTED_ORIGINS", "https://biblioteca.dns.army"
).split(",") if origin.strip()]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "catalog.apps.CatalogConfig",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "biblioteca.urls"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "templates"],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.debug",
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
    ]},
}]
WSGI_APPLICATION = "biblioteca.wsgi.application"

DATA_DIR = Path(os.getenv("BIBLIOTECA_DATA_DIR", str(BASE_DIR / "data")))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DATABASES = {"default": {
    "ENGINE": "django.db.backends.sqlite3",
    "NAME": DATA_DIR / "db.sqlite3",
    "OPTIONS": {"timeout": 30},
}}
MEDIA_ROOT = DATA_DIR / "media"
MEDIA_ROOT.mkdir(parents=True, exist_ok=True)
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": (
        "django.contrib.staticfiles.storage.StaticFilesStorage" if DEBUG
        else "whitenoise.storage.CompressedManifestStaticFilesStorage"
    )},
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
LANGUAGE_CODE = "es-mx"
TIME_ZONE = "America/Mexico_City"
USE_I18N = True
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LOGIN_URL = "/login"

MAX_PDF_MB = int(os.getenv("MAX_PDF_MB", "1024"))
FILE_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 3 * 1024 * 1024
FILE_UPLOAD_PERMISSIONS = 0o600
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = USE_HTTPS and not DEBUG
SESSION_COOKIE_SECURE = USE_HTTPS and not DEBUG
CSRF_COOKIE_SECURE = USE_HTTPS and not DEBUG
SESSION_COOKIE_HTTPONLY = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
SECURE_HSTS_SECONDS = 3600 if USE_HTTPS and not DEBUG else 0
