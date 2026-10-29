from django.core.management.base import BaseCommand, CommandError

from gateway.models import App


class Command(BaseCommand):
    help = "Desativa (ou reativa) um app. Mensagens já na fila continuam saindo."

    def add_arguments(self, p):
        p.add_argument("nome")
        p.add_argument("--reativar", action="store_true")

    def handle(self, *args, **o):
        app = App.objects.filter(nome=o["nome"]).first()
        if app is None:
            raise CommandError("App não encontrado.")
        app.ativo = o["reativar"]
        app.save(update_fields=["ativo"])
        self.stdout.write(f"{app.nome}: {'ativo' if app.ativo else 'desativado'}")
