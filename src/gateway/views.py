import logging
import re
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError
from django.http import JsonResponse
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from . import destino as dest
from .errors import ErroGateway
from .models import EstadoWorker, Mensagem

log = logging.getLogger(__name__)

_CHAVE_IDEMP = re.compile(r"^[A-Za-z0-9_.:@-]+$")


def healthz(request):
    return JsonResponse({"status": "ok"})


def _texto(corpo, campo, obrigatorio=False, maximo=None):
    valor = corpo.get(campo)
    if valor is None:
        if obrigatorio:
            raise ErroGateway(400, "payload_invalido", f"Campo '{campo}' é obrigatório.")
        return ""
    if not isinstance(valor, str):
        raise ErroGateway(400, "payload_invalido", f"Campo '{campo}' deve ser texto.")
    if obrigatorio and not valor.strip():
        raise ErroGateway(400, "payload_invalido", f"Campo '{campo}' é obrigatório.")
    if maximo and len(valor) > maximo:
        raise ErroGateway(400, "payload_invalido", f"Campo '{campo}' passa de {maximo} caracteres.")
    return valor


def _limite(app, janela, maximo):
    """429 se o app já enviou `maximo` mensagens nos últimos `janela` segundos."""
    if maximo == 0:
        raise ErroGateway(429, "limite_excedido", "Este app não tem cota de envio.",
                          headers={"Retry-After": str(janela)})
    desde = timezone.now() - timedelta(seconds=janela)
    recentes = Mensagem.objects.filter(app=app, criado_em__gte=desde)
    if recentes.count() >= maximo:
        # A mais antiga que ainda conta sai da janela em:
        mais_antiga = recentes.order_by("-criado_em").values_list("criado_em", flat=True)[maximo - 1]
        espera = max(1, int((mais_antiga + timedelta(seconds=janela) - timezone.now()).total_seconds()) + 1)
        raise ErroGateway(429, "limite_excedido", "Limite de envios excedido.",
                          headers={"Retry-After": str(espera)})


def _resumo(m):
    return {
        "id": str(m.id),
        "status": m.status,
        "attempts": m.tentativas,
        "error_code": m.codigo_erro or None,
        "created_at": m.criado_em.isoformat(),
        "sent_at": m.enviado_em.isoformat() if m.enviado_em else None,
        "expires_at": m.expira_em.isoformat(),
    }


class Mensagens(APIView):
    def post(self, request):
        app = request.user
        corpo = request.data
        if not isinstance(corpo, dict):
            raise ErroGateway(400, "payload_invalido", "O corpo deve ser um objeto JSON.")

        texto = _texto(corpo, "text", obrigatorio=True, maximo=settings.TEXTO_MAX)
        chave = _texto(corpo, "idempotency_key", maximo=settings.IDEMPOTENCY_KEY_MAX) or None
        ref = _texto(corpo, "ref", maximo=settings.REF_MAX)
        if chave and not _CHAVE_IDEMP.match(chave):
            raise ErroGateway(400, "payload_invalido", "idempotency_key com caracteres inválidos.")

        expires_in = corpo.get("expires_in", app.ttl_padrao)
        if isinstance(expires_in, bool) or not isinstance(expires_in, int) or expires_in <= 0:
            raise ErroGateway(400, "payload_invalido", "expires_in deve ser inteiro positivo (segundos).")
        if expires_in > app.ttl_max:
            raise ErroGateway(400, "payload_invalido", f"expires_in máximo deste app: {app.ttl_max}s.")

        # Repetição com a mesma chave devolve a original, sem gastar limite nem validar de novo.
        if chave:
            existente = Mensagem.objects.filter(app=app, idempotency_key=chave).first()
            if existente:
                return Response(_resumo(existente), status=200)

        try:
            para = dest.normalizar(corpo.get("to"), app.apelidos_grupo)
        except dest.DestinoInvalido as e:
            raise ErroGateway(400, "numero_invalido", str(e))
        if not app.destino_livre and para not in app.destinos_permitidos:
            raise ErroGateway(403, "destino_nao_permitido", "Destino não permitido para este app.")

        _limite(app, 60, app.limite_minuto)
        _limite(app, 86400, app.limite_dia)

        agora = timezone.now()
        try:
            m = Mensagem.objects.create(
                app=app, destino=para, texto=texto, idempotency_key=chave, ref=ref,
                proxima_tentativa_em=agora, expira_em=agora + timedelta(seconds=expires_in),
            )
        except IntegrityError:
            # Duas requisições simultâneas com a mesma chave: a outra venceu.
            existente = Mensagem.objects.filter(app=app, idempotency_key=chave).first()
            if existente:
                return Response(_resumo(existente), status=200)
            raise
        log.info("mensagem aceita id=%s app=%s para=%s", m.id, app.nome, dest.mascarar(para))
        return Response({"id": str(m.id), "status": m.status}, status=202)


class MensagemDetalhe(APIView):
    def get(self, request, pk):
        # Só mensagens do próprio app; de outro app responde como inexistente.
        m = Mensagem.objects.filter(app=request.user, pk=pk).first()
        if m is None:
            raise ErroGateway(404, "nao_encontrada", "Mensagem não encontrada.")
        return Response(_resumo(m))


class Status(APIView):
    def get(self, request):
        estado = EstadoWorker.objects.filter(pk=1).first()
        whatsapp = "unknown"
        if estado and estado.whatsapp_em:
            idade = (timezone.now() - estado.whatsapp_em).total_seconds()
            if idade <= settings.STATUS_VALIDADE_S:
                whatsapp = estado.whatsapp
        fila = Mensagem.objects.filter(app=request.user, status=Mensagem.QUEUED).count()
        return Response({"whatsapp": whatsapp, "queued": fila})
