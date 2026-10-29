import logging

from django.core.exceptions import PermissionDenied
from django.http import Http404, JsonResponse
from rest_framework import exceptions
from rest_framework.response import Response

log = logging.getLogger(__name__)


class ErroGateway(Exception):
    """Erro de negócio com status HTTP e código estável (contrato do README)."""

    def __init__(self, status, codigo, mensagem, headers=None):
        super().__init__(mensagem)
        self.status = status
        self.codigo = codigo
        self.mensagem = mensagem
        self.headers = headers or {}


def corpo_erro(codigo, mensagem):
    return {"error": {"code": codigo, "message": mensagem}}


def tratar_excecao(exc, context):
    if isinstance(exc, ErroGateway):
        return Response(corpo_erro(exc.codigo, exc.mensagem), status=exc.status, headers=exc.headers)
    if isinstance(exc, (exceptions.NotAuthenticated, exceptions.AuthenticationFailed)):
        return Response(
            corpo_erro("nao_autenticado", "Chave ausente ou inválida."),
            status=401,
            headers={"WWW-Authenticate": "Bearer"},
        )
    if isinstance(exc, exceptions.ParseError):
        return Response(corpo_erro("payload_invalido", "JSON inválido."), status=400)
    if isinstance(exc, exceptions.UnsupportedMediaType):
        return Response(corpo_erro("payload_invalido", "Use Content-Type: application/json."), status=415)
    if isinstance(exc, (Http404, exceptions.NotFound)):
        return Response(corpo_erro("nao_encontrada", "Não encontrada."), status=404)
    if isinstance(exc, exceptions.MethodNotAllowed):
        return Response(corpo_erro("metodo_invalido", "Método não permitido."), status=405)
    if isinstance(exc, PermissionDenied):
        return Response(corpo_erro("nao_autenticado", "Acesso negado."), status=403)
    # Qualquer outra coisa: erro nosso. Nunca devolver detalhe interno.
    log.exception("erro inesperado na API")
    return Response(corpo_erro("erro_interno", "Erro interno."), status=500)


def nao_encontrada(request, exception=None):
    return JsonResponse(corpo_erro("nao_encontrada", "Não encontrada."), status=404)


def erro_interno(request):
    return JsonResponse(corpo_erro("erro_interno", "Erro interno."), status=500)
