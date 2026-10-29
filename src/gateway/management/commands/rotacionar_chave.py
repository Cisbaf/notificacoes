from django.core.management.base import BaseCommand, CommandError

from gateway.models import App, gerar_chave, hash_chave

from .criar_app import avisar_chave


class Command(BaseCommand):
    help = "Gera chave nova para um app; a antiga deixa de valer na hora."

    def add_arguments(self, p):
        p.add_argument("nome")

    def handle(self, *args, **o):
        app = App.objects.filter(nome=o["nome"]).first()
        if app is None:
            raise CommandError("App não encontrado.")
        chave = gerar_chave()
        app.chave_hash = hash_chave(chave)
        app.save(update_fields=["chave_hash"])
        avisar_chave(self.stdout, app.nome, chave)
