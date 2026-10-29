"""Cliente do Evolution. Só o worker usa; é o único que conhece a chave da instância.

Regras de log: nunca o corpo da resposta (pode trazer o número completo); no máximo o campo `error`.
"""
import logging
from dataclasses import dataclass

import requests
from django.conf import settings

log = logging.getLogger(__name__)

OK, PERMANENTE, TEMPORARIO = "ok", "permanente", "temporario"


@dataclass
class Resultado:
    tipo: str  # ok | permanente | temporario
    codigo_erro: str = ""
    evolution_id: str = ""


class ClienteEvolution:
    def __init__(self):
        self.base = settings.EVOLUTION_URL.rstrip("/")
        self.instancia = settings.EVOLUTION_INSTANCE
        self.cabecalhos = {"apikey": settings.EVOLUTION_API_KEY}

    def estado(self):
        """open | close | connecting | unknown (qualquer falha vira unknown)."""
        try:
            r = requests.get(
                f"{self.base}/instance/connectionState/{self.instancia}",
                headers=self.cabecalhos, timeout=(3, 8),
            )
            if r.status_code != 200:
                return "unknown"
            return str(r.json().get("instance", {}).get("state", "unknown"))
        except (requests.RequestException, ValueError):
            return "unknown"

    def enviar_texto(self, numero, texto):
        try:
            r = requests.post(
                f"{self.base}/message/sendText/{self.instancia}",
                json={"number": numero, "text": texto},
                headers=self.cabecalhos, timeout=settings.EVOLUTION_TIMEOUT,
            )
        except requests.RequestException as e:
            log.warning("falha de rede ao enviar (%s)", type(e).__name__)
            return Resultado(TEMPORARIO, "falha_envio")

        if r.status_code in (200, 201):
            try:
                evo_id = str(r.json().get("key", {}).get("id", ""))
            except ValueError:
                evo_id = ""
            return Resultado(OK, evolution_id=evo_id)

        if r.status_code == 400:
            # Número sem WhatsApp vem como {"message":[{"exists":false,...}]}; lido só em memória.
            invalido = '"exists":false' in r.text.replace(" ", "")
            log.warning("evolution recusou o envio (400) numero_invalido=%s", invalido)
            return Resultado(PERMANENTE, "numero_invalido" if invalido else "falha_envio")

        erro = ""
        try:
            e = r.json().get("error")
            erro = e if isinstance(e, str) else ""
        except ValueError:
            pass
        log.warning("evolution respondeu %s %s", r.status_code, erro[:80])
        return Resultado(TEMPORARIO, "falha_envio")
