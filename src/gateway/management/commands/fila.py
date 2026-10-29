from django.core.management.base import BaseCommand
from django.db.models import Count, Min
from django.utils import timezone

from gateway.models import EstadoWorker, Mensagem


class Command(BaseCommand):
    help = "Mostra o estado da fila agora."

    def handle(self, *args, **o):
        estado = EstadoWorker.objects.filter(pk=1).first()
        agora = timezone.now()
        if estado and estado.batimento_em:
            self.stdout.write(f"worker: batimento há {int((agora - estado.batimento_em).total_seconds())}s")
        else:
            self.stdout.write("worker: sem batimento")
        if estado and estado.whatsapp_em:
            self.stdout.write(
                f"whatsapp: {estado.whatsapp} (há {int((agora - estado.whatsapp_em).total_seconds())}s)"
            )
        abertas = (
            Mensagem.objects.filter(status__in=[Mensagem.QUEUED, Mensagem.SENDING])
            .values("app__nome", "status")
            .annotate(n=Count("id"), mais_antiga=Min("criado_em"))
            .order_by("app__nome", "status")
        )
        if not abertas:
            self.stdout.write("fila vazia")
        for linha in abertas:
            idade = int((agora - linha["mais_antiga"]).total_seconds())
            self.stdout.write(f"{linha['app__nome']}: {linha['n']} {linha['status']} (mais antiga há {idade}s)")
