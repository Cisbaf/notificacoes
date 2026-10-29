import hmac
import ipaddress
import logging
from datetime import timedelta

from django.utils import timezone
from rest_framework.authentication import BaseAuthentication

from . import bloqueio
from .errors import ErroGateway
from .models import App, hash_chave

log = logging.getLogger(__name__)


def ip_do_cliente(request):
    # Só REMOTE_ADDR: sem proxy na frente, X-Forwarded-For seria forjável pelo cliente.
    return request.META.get("REMOTE_ADDR", "")


def ip_permitido(ip, regras):
    if not regras:
        return True
    try:
        endereco = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for regra in regras:
        try:
            if endereco in ipaddress.ip_network(regra, strict=False):
                return True
        except ValueError:
            continue
    return False


class ChaveAppAuthentication(BaseAuthentication):
    """Authorization: Bearer <chave>. Devolve (App, None); falha com ErroGateway ou 401."""

    def authenticate_header(self, request):
        return "Bearer"

    def authenticate(self, request):
        ip = ip_do_cliente(request)
        espera = bloqueio.segundos_bloqueado(ip)
        if espera:
            raise ErroGateway(
                429, "limite_excedido", "Muitas tentativas inválidas. Tente mais tarde.",
                headers={"Retry-After": str(espera)},
            )

        cabecalho = request.META.get("HTTP_AUTHORIZATION", "")
        esquema, _, chave = cabecalho.partition(" ")
        chave = chave.strip()
        app = None
        if esquema.lower() == "bearer" and chave:
            app = App.objects.filter(chave_hash=hash_chave(chave)).first()
            # Defesa em profundidade: confirma em tempo constante o que o índice do banco achou.
            if app and not hmac.compare_digest(app.chave_hash, hash_chave(chave)):
                app = None
        if app is None:
            bloqueio.registrar_falha(ip)
            log.warning("chave inválida ip=%s", ip)
            raise ErroGateway(401, "nao_autenticado", "Chave ausente ou inválida.",
                              headers={"WWW-Authenticate": "Bearer"})

        if not app.ativo:
            raise ErroGateway(403, "app_desativado", "App desativado.")
        if not ip_permitido(ip, app.ips_permitidos):
            log.warning("ip fora da allowlist app=%s ip=%s", app.nome, ip)
            raise ErroGateway(403, "ip_nao_permitido", "IP de origem não permitido para este app.")

        agora = timezone.now()
        if app.ultimo_uso_em is None or agora - app.ultimo_uso_em > timedelta(seconds=60):
            App.objects.filter(pk=app.pk).update(ultimo_uso_em=agora)
        return (app, None)
