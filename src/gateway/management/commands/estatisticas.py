from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import Count
from django.utils import timezone

from gateway.models import Mensagem


class Command(BaseCommand):
    help = "Mensagens por app e status nas últimas N horas."

    def add_arguments(self, p):
        p.add_argument("--horas", type=int, default=24)

    def handle(self, *args, **o):
        desde = timezone.now() - timedelta(hours=o["horas"])
        linhas = (
            Mensagem.objects.filter(criado_em__gte=desde)
            .values("app__nome", "status", "codigo_erro")
            .annotate(n=Count("id"))
            .order_by("app__nome", "status", "codigo_erro")
        )
        self.stdout.write(f"Últimas {o['horas']}h:")
        if not linhas:
            self.stdout.write("  nenhuma mensagem")
        for l in linhas:
            motivo = f" ({l['codigo_erro']})" if l["codigo_erro"] else ""
            self.stdout.write(f"  {l['app__nome']}: {l['n']} {l['status']}{motivo}")
