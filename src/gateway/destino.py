"""Normalização, validação e mascaramento de destinos (número de celular ou grupo)."""
import re

_JID_GRUPO = re.compile(r"^\d+(-\d+)?@g\.us$")
_APELIDO = re.compile(r"^[A-Za-z0-9_.-]{1,40}$")
_SO_FORMATACAO = re.compile(r"^[+\d\s().-]+$")


class DestinoInvalido(ValueError):
    pass


def e_grupo(destino):
    return destino.endswith("@g.us")


def normalizar(bruto, apelidos=None):
    """Devolve o destino canônico: só dígitos com DDI, ou JID de grupo.

    Aceita número com formatação, JID de grupo (`...@g.us`) ou apelido de grupo do cadastro do app.
    Celular BR de 10/11 dígitos sem DDI ganha `55`.
    """
    if not isinstance(bruto, str) or not bruto.strip():
        raise DestinoInvalido("Destino ausente.")
    valor = bruto.strip()

    if "@" in valor:
        if _JID_GRUPO.match(valor):
            return valor
        raise DestinoInvalido("Só são aceitos grupos (...@g.us).")

    if not _SO_FORMATACAO.match(valor):
        # Não parece número: tenta como apelido de grupo.
        if _APELIDO.match(valor) and apelidos and valor in apelidos:
            return apelidos[valor]
        raise DestinoInvalido("Destino desconhecido.")

    digitos = re.sub(r"\D", "", valor)
    if len(digitos) == 11 and digitos[2] == "9" and digitos[0] != "0":
        digitos = "55" + digitos  # celular BR com DDD
    elif len(digitos) == 10 and digitos[0] != "0":
        digitos = "55" + digitos  # fixo BR com DDD (ou celular antigo)
    if not 11 <= len(digitos) <= 15:
        raise DestinoInvalido("Número inválido.")
    return digitos


def mascarar(destino):
    """Versão para log e exibição: nunca o número completo."""
    if not destino:
        return ""
    if e_grupo(destino):
        return "grupo:***" + destino.split("@")[0][-4:]
    if "*" in destino:
        return destino
    if len(destino) <= 6:
        return "*" * len(destino)
    return destino[:4] + "*" * (len(destino) - 6) + destino[-2:]
