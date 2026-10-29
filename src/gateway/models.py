import hashlib
import secrets
import uuid

from django.db import models

PREFIXO_CHAVE = "ntf_"


def gerar_chave():
    """Chave nova de app. Só o hash vai para o banco; a chave aparece uma vez, na criação."""
    return PREFIXO_CHAVE + secrets.token_urlsafe(32)


def hash_chave(chave):
    return hashlib.sha256(chave.encode()).hexdigest()


class App(models.Model):
    nome = models.CharField(max_length=64, unique=True)
    chave_hash = models.CharField(max_length=64, unique=True)
    ativo = models.BooleanField(default=True)
    # App interno confiável (ex.: chamadosti): pode não ter IP fixo e pode ter destino livre.
    interno = models.BooleanField(default=False)
    destino_livre = models.BooleanField(default=False)
    destinos_permitidos = models.JSONField(default=list, blank=True)
    apelidos_grupo = models.JSONField(default=dict, blank=True)
    ips_permitidos = models.JSONField(default=list, blank=True)
    limite_minuto = models.PositiveIntegerField(default=30)
    limite_dia = models.PositiveIntegerField(default=500)
    ttl_padrao = models.PositiveIntegerField(default=3600)
    ttl_max = models.PositiveIntegerField(default=86400)
    criado_em = models.DateTimeField(auto_now_add=True)
    ultimo_uso_em = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.nome


class Mensagem(models.Model):
    QUEUED, SENDING, SENT, FAILED, EXPIRED = "queued", "sending", "sent", "failed", "expired"
    STATUS = [(s, s) for s in (QUEUED, SENDING, SENT, FAILED, EXPIRED)]
    FINAIS = (SENT, FAILED, EXPIRED)

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    app = models.ForeignKey(App, on_delete=models.CASCADE, related_name="mensagens")
    # Número completo (só dígitos) ou JID de grupo; vira versão mascarada após a retenção do texto.
    destino = models.CharField(max_length=64)
    texto = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=STATUS, default=QUEUED)
    tentativas = models.PositiveSmallIntegerField(default=0)
    proxima_tentativa_em = models.DateTimeField()
    expira_em = models.DateTimeField()
    idempotency_key = models.CharField(max_length=64, null=True, blank=True)
    codigo_erro = models.CharField(max_length=32, blank=True)
    evolution_id = models.CharField(max_length=64, blank=True)
    ref = models.CharField(max_length=64, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    travada_em = models.DateTimeField(null=True, blank=True)
    enviado_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["app", "idempotency_key"], name="idempotencia_por_app"),
        ]
        indexes = [
            models.Index(fields=["status", "proxima_tentativa_em"]),
            models.Index(fields=["app", "criado_em"]),
            models.Index(fields=["criado_em"]),
        ]


class EstadoWorker(models.Model):
    """Linha única (id=1): o worker publica aqui o estado do WhatsApp e o batimento; o web só lê."""

    id = models.PositiveSmallIntegerField(primary_key=True, default=1)
    whatsapp = models.CharField(max_length=16, default="unknown")
    whatsapp_em = models.DateTimeField(null=True, blank=True)
    batimento_em = models.DateTimeField(null=True, blank=True)
