import ipaddress

from django.core.management.base import BaseCommand, CommandError

from gateway import destino as dest
from gateway.models import App, gerar_chave, hash_chave

# Sem IP fixo a chave é a única defesa: teto baixo e destinos fechados.
TETO_SEM_IP = (10, 100)


def avisar_chave(stdout, nome, chave):
    stdout.write(f"\nApp: {nome}\nChave (aparece só agora, guarde em lugar seguro):\n\n  {chave}\n")


class Command(BaseCommand):
    help = "Cadastra um app e imprime a chave uma única vez."

    def add_arguments(self, p):
        p.add_argument("nome")
        p.add_argument("--interno", action="store_true", help="App interno confiável (pode não ter IP fixo).")
        p.add_argument("--livre", action="store_true", help="Destino livre (só com --interno).")
        p.add_argument("--ip", action="append", default=[], help="IP ou CIDR permitido (repita para vários).")
        p.add_argument("--destino", action="append", default=[], help="Número permitido (repita).")
        p.add_argument("--grupo", action="append", default=[], help="apelido=JID@g.us permitido (repita).")
        p.add_argument("--limite-minuto", type=int)
        p.add_argument("--limite-dia", type=int)
        p.add_argument("--ttl", type=int, default=3600, help="TTL padrão em segundos.")
        p.add_argument("--ttl-max", type=int, default=86400)

    def handle(self, *args, **o):
        nome = o["nome"].strip()
        if not nome or App.objects.filter(nome=nome).exists():
            raise CommandError("Nome vazio ou já existente.")
        if o["livre"] and not o["interno"]:
            raise CommandError("Destino livre só para app --interno.")

        ips = []
        for valor in o["ip"]:
            try:
                ipaddress.ip_network(valor, strict=False)
            except ValueError:
                raise CommandError(f"IP/CIDR inválido: {valor}")
            ips.append(valor)

        apelidos, permitidos = {}, []
        for item in o["grupo"]:
            apelido, _, jid = item.partition("=")
            if not apelido or not dest.e_grupo(jid):
                raise CommandError(f"--grupo deve ser apelido=JID@g.us (recebi: {item})")
            apelidos[apelido] = dest.normalizar(jid)
            permitidos.append(apelidos[apelido])
        for numero in o["destino"]:
            try:
                permitidos.append(dest.normalizar(numero))
            except dest.DestinoInvalido as e:
                raise CommandError(f"Destino inválido ({e})")

        if not o["livre"] and not permitidos:
            raise CommandError("Informe --destino/--grupo, ou --livre num app --interno.")
        if not o["interno"] and not ips:
            if o["limite_minuto"] is None:
                o["limite_minuto"] = TETO_SEM_IP[0] // 2
            if o["limite_dia"] is None:
                o["limite_dia"] = TETO_SEM_IP[1] // 2
            if o["limite_minuto"] > TETO_SEM_IP[0] or o["limite_dia"] > TETO_SEM_IP[1]:
                raise CommandError(
                    f"App externo sem IP fixo: limite máximo {TETO_SEM_IP[0]}/min e {TETO_SEM_IP[1]}/dia."
                )
        if o["ttl"] > o["ttl_max"]:
            raise CommandError("--ttl não pode passar de --ttl-max.")

        chave = gerar_chave()
        App.objects.create(
            nome=nome, chave_hash=hash_chave(chave), interno=o["interno"], destino_livre=o["livre"],
            destinos_permitidos=sorted(set(permitidos)), apelidos_grupo=apelidos, ips_permitidos=ips,
            limite_minuto=o["limite_minuto"] if o["limite_minuto"] is not None else (30 if o["interno"] else 20),
            limite_dia=o["limite_dia"] if o["limite_dia"] is not None else (500 if o["interno"] else 300),
            ttl_padrao=o["ttl"], ttl_max=o["ttl_max"],
        )
        avisar_chave(self.stdout, nome, chave)
        if not o["interno"] and not ips:
            self.stdout.write(self.style.WARNING("\nAtenção: sem IP fixo, a chave é a única defesa."))
