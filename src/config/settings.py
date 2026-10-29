import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _int(nome, padrao):
    return int(os.getenv(nome, padrao))


SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]
DEBUG = os.getenv("DJANGO_DEBUG", "0") == "1"
# Acesso por IP, sem DNS: o Host chega como o IP; a proteção é a chave + allowlist, não o Host.
ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    "rest_framework",
    "gateway",
]

# Sem sessão, CSRF, admin nem estáticos: é só uma API com chave no cabeçalho.
MIDDLEWARE = []
APPEND_SLASH = False

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

if os.getenv("MYSQL_HOST"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.mysql",
            "NAME": os.environ["MYSQL_DATABASE"],
            "USER": os.environ["MYSQL_USER"],
            "PASSWORD": os.environ["MYSQL_PASSWORD"],
            "HOST": os.environ["MYSQL_HOST"],
            "PORT": os.getenv("MYSQL_PORT", "3306"),
            "CONN_MAX_AGE": 60,
            "OPTIONS": {"charset": "utf8mb4"},
        }
    }
else:
    # Só para rodar os testes rápido fora do Docker.
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": os.getenv("SQLITE_PATH", BASE_DIR / "db.sqlite3"),
        }
    }

LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Sao_Paulo"
USE_TZ = True

# Corpo máximo aceito em POST /v1/messages (o parser também aplica este limite).
MAX_BODY_BYTES = 64 * 1024

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["gateway.auth.ChaveAppAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": [],
    "DEFAULT_PARSER_CLASSES": ["gateway.parsers.JSONLimitado"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "UNAUTHENTICATED_USER": None,
    "EXCEPTION_HANDLER": "gateway.errors.tratar_excecao",
}

# Limites de aplicação.
TEXTO_MAX = 4000
IDEMPOTENCY_KEY_MAX = 64
REF_MAX = 64

# Bloqueio temporário de IP após chaves inválidas (contador em memória; o gunicorn roda 1 processo).
BLOQUEIO_FALHAS = _int("BLOQUEIO_FALHAS", 10)
BLOQUEIO_JANELA_S = _int("BLOQUEIO_JANELA_S", 600)
BLOQUEIO_DURACAO_S = _int("BLOQUEIO_DURACAO_S", 900)

# Worker.
WORKER_RITMO_S = float(os.getenv("WORKER_RITMO_S", "2.5"))
WORKER_MAX_TENTATIVAS = _int("WORKER_MAX_TENTATIVAS", 5)
WORKER_BACKOFF_BASE_S = _int("WORKER_BACKOFF_BASE_S", 30)
WORKER_BACKOFF_MAX_S = _int("WORKER_BACKOFF_MAX_S", 900)
WORKER_ESTADO_A_CADA_S = _int("WORKER_ESTADO_A_CADA_S", 30)
WORKER_ENVIANDO_TRAVADA_S = _int("WORKER_ENVIANDO_TRAVADA_S", 300)
# Quanto tempo o estado do WhatsApp gravado pelo worker vale para /v1/status.
STATUS_VALIDADE_S = _int("STATUS_VALIDADE_S", 90)

EVOLUTION_URL = os.getenv("EVOLUTION_URL", "http://evolution-api:8080")
EVOLUTION_INSTANCE = os.getenv("EVOLUTION_INSTANCE", "notificacoes")
EVOLUTION_API_KEY = os.getenv("EVOLUTION_API_KEY", "")
EVOLUTION_TIMEOUT = (3, 20)

# Retenção (LGPD): texto e destino completo somem cedo; metadados ficam mais.
RETENCAO_TEXTO_DIAS = _int("RETENCAO_TEXTO_DIAS", 7)
RETENCAO_METADADOS_DIAS = _int("RETENCAO_METADADOS_DIAS", 90)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"padrao": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "padrao"}},
    "root": {"handlers": ["console"], "level": os.getenv("LOG_LEVEL", "INFO")},
}
