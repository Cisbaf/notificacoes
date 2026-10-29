from django.core.management.base import BaseCommand

from gateway import destino as dest
from gateway.models import App


class Command(BaseCommand):
    help = "Lista os apps cadastrados (sem chaves)."

    def handle(self, *args, **o):
        for a in App.objects.order_by("nome"):
            destinos = "livre" if a.destino_livre else ", ".join(dest.mascarar(d) for d in a.destinos_permitidos)
            self.stdout.write(
                f"{a.nome} [{'ativo' if a.ativo else 'DESATIVADO'}{', interno' if a.interno else ''}] "
                f"limites {a.limite_minuto}/min {a.limite_dia}/dia | ips: {', '.join(a.ips_permitidos) or 'qualquer'} "
                f"| destinos: {destinos} | último uso: {a.ultimo_uso_em or '-'}"
            )
