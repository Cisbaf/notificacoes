"""Worker: tira mensagens da fila (MySQL) e as envia ao Evolution, uma de cada vez, em ritmo global.

- Pausa quando o WhatsApp não está `open` (não gasta tentativas).
- Retry com backoff só para falha temporária; 400 do Evolution é definitivo.
- Mensagens vencem por TTL (`expired`); `sending` esquecida por queda do worker volta para a fila.
"""
import logging
import random
import threading
import time
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from . import destino as dest
from .evolution import OK, PERMANENTE, ClienteEvolution
from .models import EstadoWorker, Mensagem

log = logging.getLogger(__name__)

ESPERA_OFFLINE_S = 30


def expirar(agora):
    return Mensagem.objects.filter(status=Mensagem.QUEUED, expira_em__lte=agora).update(
        status=Mensagem.EXPIRED, codigo_erro="expirada"
    )


def recuperar_travadas(agora):
    limite = agora - timedelta(seconds=settings.WORKER_ENVIANDO_TRAVADA_S)
    return Mensagem.objects.filter(status=Mensagem.SENDING, travada_em__lt=limite).update(
        status=Mensagem.QUEUED, travada_em=None, proxima_tentativa_em=agora
    )


def reivindicar(agora):
    """Pega a próxima mensagem pronta e a marca `sending`. SKIP LOCKED permite mais de um worker."""
    with transaction.atomic():
        m = (
            Mensagem.objects.select_for_update(skip_locked=True)
            .filter(status=Mensagem.QUEUED, proxima_tentativa_em__lte=agora, expira_em__gt=agora)
            .order_by("proxima_tentativa_em", "criado_em")
            .first()
        )
        if m is None:
            return None
        m.status = Mensagem.SENDING
        m.tentativas += 1
        m.travada_em = agora
        m.save(update_fields=["status", "tentativas", "travada_em"])
        return m


def publicar_estado(whatsapp):
    EstadoWorker.objects.update_or_create(pk=1, defaults={"whatsapp": whatsapp, "whatsapp_em": timezone.now()})


def batimento():
    EstadoWorker.objects.update_or_create(pk=1, defaults={"batimento_em": timezone.now()})


def _espera_backoff(tentativas):
    return min(settings.WORKER_BACKOFF_BASE_S * 2 ** (tentativas - 1), settings.WORKER_BACKOFF_MAX_S)


def processar_uma(cliente, agora=None):
    """Envia uma mensagem da fila. Devolve 'enviada' | 'falhou' | 'adiada' | 'offline' | None (fila vazia)."""
    agora = agora or timezone.now()
    m = reivindicar(agora)
    if m is None:
        return None

    r = cliente.enviar_texto(m.destino, m.texto)
    m.travada_em = None

    if r.tipo == OK:
        m.status, m.enviado_em, m.evolution_id, m.codigo_erro = Mensagem.SENT, timezone.now(), r.evolution_id, ""
        resultado = "enviada"
        log.info("enviada id=%s app=%s para=%s", m.id, m.app_id, dest.mascarar(m.destino))
    elif r.tipo == PERMANENTE:
        m.status, m.codigo_erro = Mensagem.FAILED, r.codigo_erro
        resultado = "falhou"
        log.warning("falhou id=%s motivo=%s", m.id, r.codigo_erro)
    else:
        estado = cliente.estado()
        publicar_estado(estado)
        if estado != "open":
            # A sessão caiu: a falha não é culpa da mensagem, então não gasta tentativa.
            m.status, m.codigo_erro = Mensagem.QUEUED, "whatsapp_offline"
            m.tentativas -= 1
            m.proxima_tentativa_em = timezone.now() + timedelta(seconds=ESPERA_OFFLINE_S)
            resultado = "offline"
        elif m.tentativas >= settings.WORKER_MAX_TENTATIVAS:
            m.status, m.codigo_erro = Mensagem.FAILED, "falha_envio"
            resultado = "falhou"
            log.warning("esgotou tentativas id=%s", m.id)
        else:
            m.status, m.codigo_erro = Mensagem.QUEUED, r.codigo_erro or "falha_envio"
            m.proxima_tentativa_em = timezone.now() + timedelta(seconds=_espera_backoff(m.tentativas))
            resultado = "adiada"
    m.save(update_fields=[
        "status", "enviado_em", "evolution_id", "codigo_erro", "tentativas", "travada_em", "proxima_tentativa_em",
    ])
    return resultado


def faxina(agora=None, lote=500):
    """Retenção (LGPD): apaga o texto e mascara o destino cedo; remove a linha inteira mais tarde."""
    agora = agora or timezone.now()
    corte_texto = agora - timedelta(days=settings.RETENCAO_TEXTO_DIAS)
    corte_total = agora - timedelta(days=settings.RETENCAO_METADADOS_DIAS)

    limpas = 0
    pendentes = Mensagem.objects.filter(criado_em__lt=corte_texto, status__in=Mensagem.FINAIS).exclude(texto="")
    for m in pendentes[:lote]:
        m.texto = ""
        m.destino = dest.mascarar(m.destino)
        m.save(update_fields=["texto", "destino"])
        limpas += 1
    # Mensagem parada na fila por mais que a retenção do texto também não deve guardar o conteúdo.
    velhas = Mensagem.objects.filter(criado_em__lt=corte_texto, status=Mensagem.QUEUED)
    velhas.update(status=Mensagem.EXPIRED, codigo_erro="expirada")

    apagadas, _ = Mensagem.objects.filter(criado_em__lt=corte_total).delete()
    return limpas, apagadas


def rodar(cliente=None, parar=None):
    cliente = cliente or ClienteEvolution()
    parar = parar or threading.Event()
    ultimo_estado = ultimo_batimento = ultima_faxina = float("-inf")
    estado = "unknown"
    log.info("worker iniciado ritmo=%ss", settings.WORKER_RITMO_S)

    while not parar.is_set():
        mono = time.monotonic()
        agora = timezone.now()

        if mono - ultimo_batimento >= 15:
            batimento()
            ultimo_batimento = mono
        if mono - ultimo_estado >= settings.WORKER_ESTADO_A_CADA_S:
            estado = cliente.estado()
            publicar_estado(estado)
            ultimo_estado = mono
            log.info("whatsapp=%s", estado)
        if mono - ultima_faxina >= 3600:
            limpas, apagadas = faxina(agora)
            ultima_faxina = mono
            if limpas or apagadas:
                log.info("faxina: %s textos apagados, %s linhas removidas", limpas, apagadas)

        expirar(agora)
        recuperar_travadas(agora)

        if estado != "open":
            parar.wait(5)
            continue

        resultado = processar_uma(cliente, agora)
        if resultado is None:
            parar.wait(1)
            continue
        if resultado == "offline":
            estado = "unknown"
            ultimo_estado = float("-inf")
        # Ritmo global entre envios, com variação para não parecer robô.
        parar.wait(settings.WORKER_RITMO_S * random.uniform(0.8, 1.4))

    log.info("worker encerrado")
