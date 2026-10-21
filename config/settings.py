"""PawStay 宠物寄养平台 - Django 配置。

所有环境相关配置从项目根目录的 .env（或进程环境变量）读取，参见 .env.example。
"""

import os
import sys
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from django.utils.csp import CSP
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")


def env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def env_bool(name: str, default: bool = False) -> bool:
    value = env(name)
    return value.lower() in {"1", "true", "yes", "on"} if value else default


def env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in env(name, default).split(",") if item.strip()]


DEBUG = env_bool("DJANGO_DEBUG", False)

SECRET_KEY = env("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured("生产环境必须设置 DJANGO_SECRET_KEY")
    SECRET_KEY = "django-insecure-dev-only"

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")


INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "apps.stores",
    "apps.pets",
    "apps.rooms",
    "apps.bookings",
    "apps.care",
    "apps.hospitality",
    "apps.notifications",
    "apps.security",
    "apps.payments",
    "apps.web",
]

MIDDLEWARE = [
    "apps.web.middleware.HealthCheckMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.csp.ContentSecurityPolicyMiddleware",
    "apps.security.middleware.PermissionsPolicyMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

# 全站脚本均为同源静态文件（无内联脚本），可使用严格的脚本策略
SECURE_CSP = {
    "default-src": [CSP.SELF],
    "script-src": [CSP.SELF],
    "style-src": [CSP.SELF, CSP.UNSAFE_INLINE],
    "img-src": [CSP.SELF, "data:", "blob:"],
    "font-src": [CSP.SELF],
    "connect-src": [CSP.SELF],
    "worker-src": [CSP.SELF],
    "manifest-src": [CSP.SELF],
    "object-src": [CSP.NONE],
    "base-uri": [CSP.SELF],
    "form-action": [CSP.SELF],
    "frame-ancestors": [CSP.NONE],
}

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.web.context_processors.site",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.mysql",
        "NAME": env("MYSQL_DATABASE", "petowner"),
        "USER": env("MYSQL_USER", "root"),
        "PASSWORD": env("MYSQL_PASSWORD"),
        "HOST": env("MYSQL_HOST", "127.0.0.1"),
        "PORT": env("MYSQL_PORT", "3306"),
        "CONN_MAX_AGE": int(env("MYSQL_CONN_MAX_AGE", "60")),
        "OPTIONS": {
            "charset": "utf8mb4",
            "init_command": "SET sql_mode='STRICT_TRANS_TABLES'",
        },
        "TEST": {
            "NAME": env("MYSQL_TEST_DATABASE", "test_petowner"),
            "CHARSET": "utf8mb4",
            "COLLATION": "utf8mb4_unicode_ci",
        },
    }
}

# 数据库缓存可在多个 gunicorn 进程间共享（登录限流依赖），需执行 createcachetable
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": "django_cache",
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

if "test" in sys.argv[1:2]:
    PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]


AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "web:login"
LOGIN_REDIRECT_URL = "web:dashboard"
LOGOUT_REDIRECT_URL = "web:home"


LANGUAGE_CODE = "zh-hans"
TIME_ZONE = "Asia/Shanghai"
USE_I18N = True
USE_TZ = True


STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
# 测试运行器会把 DEBUG 改成 False，需固定为配置值，否则开发环境跑测试会扫描不存在的 staticfiles/
WHITENOISE_AUTOREFRESH = DEBUG

MEDIA_URL = "media/"
MEDIA_ROOT = Path(env("DJANGO_MEDIA_ROOT", str(BASE_DIR / "media")))

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        if DEBUG
        else "whitenoise.storage.CompressedManifestStaticFilesStorage"
    },
}

FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024


if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", True)
    SESSION_COOKIE_SECURE = SECURE_SSL_REDIRECT
    CSRF_COOKIE_SECURE = SECURE_SSL_REDIRECT
    X_FRAME_OPTIONS = "DENY"
    SECURE_HSTS_SECONDS = int(env("DJANGO_HSTS_SECONDS", "0"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = SECURE_HSTS_SECONDS > 0
    SECURE_HSTS_PRELOAD = env_bool("DJANGO_HSTS_PRELOAD", SECURE_HSTS_SECONDS >= 31536000)
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = "same-origin"

SESSION_COOKIE_AGE = 60 * 60 * 24 * 14
# 部署在 Nginx 之后时由其写入 X-Real-IP，用于登录与短信的按 IP 限流
TRUST_X_REAL_IP = env_bool("DJANGO_TRUST_X_REAL_IP", False)


# 账号安全
SMS_BACKEND = env("SMS_BACKEND", "console")
SMS_ACCESS_KEY_ID = env("SMS_ACCESS_KEY_ID")
SMS_ACCESS_KEY_SECRET = env("SMS_ACCESS_KEY_SECRET")
SMS_SIGN_NAME = env("SMS_SIGN_NAME")
SMS_TEMPLATE_CODE = env("SMS_TEMPLATE_CODE")


LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"simple": {"format": "{asctime} {levelname} {name}: {message}", "style": "{"}},
    "filters": {"require_debug_false": {"()": "django.utils.log.RequireDebugFalse"}},
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "simple"},
        "mail_admins": {
            "level": "ERROR",
            "class": "django.utils.log.AdminEmailHandler",
            "filters": ["require_debug_false"],
        },
    },
    "root": {"handlers": ["console"], "level": env("DJANGO_LOG_LEVEL", "INFO")},
    "loggers": {
        "django": {"handlers": ["mail_admins"], "level": "INFO"},
        "apps": {"handlers": ["mail_admins"], "level": "INFO"},
    },
}

# 500 错误与业务异常（短信发送失败等）的告警邮件收件人，逗号分隔
ADMINS = [addr.strip() for addr in env("DJANGO_ADMINS").split(",") if addr.strip()]


_smtp_host = env("EMAIL_HOST")
_smtp_user = env("EMAIL_HOST_USER")
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL") or _smtp_user or "noreply@localhost"
SERVER_EMAIL = DEFAULT_FROM_EMAIL
MAILERS = {
    "default": (
        {
            "BACKEND": "django.core.mail.backends.smtp.EmailBackend",
            "OPTIONS": {
                "host": _smtp_host,
                "port": int(env("EMAIL_PORT", "465")),
                "username": _smtp_user,
                "password": env("EMAIL_HOST_PASSWORD"),
                "use_ssl": env_bool("EMAIL_USE_SSL", True),
                "timeout": 10,
            },
        }
        if _smtp_host
        else {"BACKEND": "django.core.mail.backends.console.EmailBackend"}
    ),
}


# 品牌与门店信息
SITE_NAME = env("SITE_NAME", "PawStay 宠物寄养")
SITE_SLOGAN = env("SITE_SLOGAN", "像家一样安心的宠物寄养")
SITE_PHONE = env("SITE_PHONE", "400-800-1234")
SITE_ADDRESS = env("SITE_ADDRESS", "上海市徐汇区宠爱路 88 号")
SITE_HOURS = env("SITE_HOURS", "每天 08:00 - 21:00")
SITE_ICP = env("SITE_ICP")

# 业务规则
MAX_BOARDING_DAYS = int(env("MAX_BOARDING_DAYS", "60"))
PAYMENT_SANDBOX = env_bool("PAYMENT_SANDBOX", True)
PAYMENT_TIMEOUT_MINUTES = int(env("PAYMENT_TIMEOUT_MINUTES", "30"))
LATE_CANCEL_NIGHTS = int(env("LATE_CANCEL_NIGHTS", "1"))
EARLY_CHECKOUT_REFUND = env_bool("EARLY_CHECKOUT_REFUND", True)

# 微信支付 Native（PAYMENT_SANDBOX=false 时必填）
WECHAT_APP_ID = env("WECHAT_APP_ID")
WECHAT_MCH_ID = env("WECHAT_MCH_ID")
WECHAT_API_KEY = env("WECHAT_API_KEY")
WECHAT_CERT_PATH = env("WECHAT_CERT_PATH")
WECHAT_KEY_PATH = env("WECHAT_KEY_PATH")  # 默认与证书同目录的 apiclient_key.pem

# 支付宝电脑网站支付（PAYMENT_SANDBOX=false 时必填）
ALIPAY_APP_ID = env("ALIPAY_APP_ID")
ALIPAY_PRIVATE_KEY = env("ALIPAY_PRIVATE_KEY")
ALIPAY_PUBLIC_KEY = env("ALIPAY_PUBLIC_KEY")

# 业务短信触达：逗号分隔事件 care / health；需另配 SMS_NOTIFY_TEMPLATE_CODE
SMS_NOTIFY_EVENTS = env_list("SMS_NOTIFY_EVENTS")
SMS_NOTIFY_TEMPLATE_CODE = env("SMS_NOTIFY_TEMPLATE_CODE")
