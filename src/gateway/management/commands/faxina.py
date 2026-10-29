from django.core.management.base import BaseCommand

from gateway import worker


class Command(BaseCommand):
    help = "Aplica a retenção agora (o worker já faz isso de hora em hora)."

    def handle(self, *args, **o):
        limpas, apagadas = worker.faxina()
        self.stdout.write(f"{limpas} textos apagados, {apagadas} linhas removidas")
