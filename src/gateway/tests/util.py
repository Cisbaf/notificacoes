from datetime import timedelta

from django.utils import timezone

from gateway.evolution import OK, Resultado
from gateway.models import App, Mensagem, gerar_chave, hash_chave

NUMERO = "5521990729548"


def criar_app(nome="app1", **extra):
    chave = gerar_chave()
    campos = dict(nome=nome, chave_hash=hash_chave(chave), destino_livre=True)
    campos.update(extra)
    return App.objects.create(**campos), chave


def auth(chave):
    return {"HTTP_AUTHORIZATION": f"Bearer {chave}"}


def criar_mensagem(app, destino=NUMERO, texto="oi", **extra):
    agora = timezone.now()
    campos = dict(
        app=app, destino=destino, texto=texto,
        proxima_tentativa_em=agora - timedelta(seconds=1), expira_em=agora + timedelta(hours=1),
    )
    campos.update(extra)
    return Mensagem.objects.create(**campos)


class ClienteFalso:
    """Substitui o ClienteEvolution: devolve resultados combinados e guarda o que foi enviado."""

    def __init__(self, resultados=None, estado="open"):
        self.resultados = list(resultados or [])
        self.estado_atual = estado
        self.enviados = []

    def enviar_texto(self, numero, texto):
        self.enviados.append((numero, texto))
        return self.resultados.pop(0) if self.resultados else Resultado(OK, evolution_id="evo123")

    def estado(self):
        return self.estado_atual
