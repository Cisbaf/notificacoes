"""Bloqueio temporário de IP após chaves inválidas.

Contador em memória: vale porque o gunicorn roda 1 processo (várias threads). Reiniciar o container zera.
"""
import threading
import time

from django.conf import settings

_trava = threading.Lock()
_falhas = {}  # ip -> [instantes das falhas recentes]
_bloqueados = {}  # ip -> instante em que o bloqueio termina


def _agora():
    return time.monotonic()


def resetar():
    with _trava:
        _falhas.clear()
        _bloqueados.clear()


def segundos_bloqueado(ip):
    """0 se o IP pode seguir; senão, quanto falta para o bloqueio acabar."""
    with _trava:
        fim = _bloqueados.get(ip)
        if fim is None:
            return 0
        restante = fim - _agora()
        if restante <= 0:
            del _bloqueados[ip]
            return 0
        return int(restante) + 1


def registrar_falha(ip):
    agora = _agora()
    with _trava:
        janela = agora - settings.BLOQUEIO_JANELA_S
        recentes = [t for t in _falhas.get(ip, []) if t > janela]
        recentes.append(agora)
        if len(recentes) >= settings.BLOQUEIO_FALHAS:
            _bloqueados[ip] = agora + settings.BLOQUEIO_DURACAO_S
            recentes = []
        _falhas[ip] = recentes
        _podar(agora)


def _podar(agora):
    """Mantém a memória limitada mesmo sob varredura de muitos IPs."""
    if len(_falhas) > 5000:
        for ip in [i for i, ts in _falhas.items() if not ts or ts[-1] < agora - settings.BLOQUEIO_JANELA_S]:
            del _falhas[ip]
    if len(_bloqueados) > 5000:
        for ip in [i for i, fim in _bloqueados.items() if fim <= agora]:
            del _bloqueados[ip]
