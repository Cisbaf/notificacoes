import signal
import threading

from django.core.management.base import BaseCommand

from gateway import worker


class Command(BaseCommand):
    help = "Roda o worker de envio (fila -> Evolution)."

    def handle(self, *args, **o):
        parar = threading.Event()
        for sinal in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sinal, lambda *_: parar.set())
        worker.rodar(parar=parar)
