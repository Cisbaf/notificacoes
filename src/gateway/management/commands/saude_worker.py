import sys
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from gateway.models import EstadoWorker


class Command(BaseCommand):
    help = "Healthcheck do worker: sai com 1 se o batimento tem mais de 120s."

    def handle(self, *args, **o):
        estado = EstadoWorker.objects.filter(pk=1).first()
        if not estado or not estado.batimento_em or timezone.now() - estado.batimento_em > timedelta(seconds=120):
            sys.exit(1)
