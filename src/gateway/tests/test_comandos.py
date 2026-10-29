import re
from io import StringIO

from django.core.management import CommandError, call_command
from django.test import TestCase
from rest_framework.test import APIClient

from gateway import bloqueio
from gateway.models import App, hash_chave

from .util import NUMERO, auth, criar_app, criar_mensagem

GRUPO = "120363025246125486@g.us"


def rodar(*args, **kw):
    saida = StringIO()
    call_command(*args, stdout=saida, **kw)
    return saida.getvalue()


def extrair_chave(saida):
    return re.search(r"ntf_[A-Za-z0-9_-]+", saida).group(0)


class CriarAppTests(TestCase):
    def setUp(self):
        bloqueio.resetar()
        self.c = APIClient()

    def enviar(self, chave, **extra):
        return self.c.post("/v1/messages", {"to": NUMERO, "text": "oi"}, format="json", **auth(chave), **extra)

    def test_cria_interno_livre_e_chave_funciona(self):
        saida = rodar("criar_app", "chamadosti", "--interno", "--livre")
        chave = extrair_chave(saida)
        app = App.objects.get(nome="chamadosti")
        self.assertTrue(app.interno and app.destino_livre and app.ativo)
        self.assertEqual(app.chave_hash, hash_chave(chave))
        self.assertNotIn(chave, str(list(App.objects.values())))
        self.assertEqual(self.enviar(chave).status_code, 202)

    def test_chave_so_aparece_na_criacao(self):
        chave = extrair_chave(rodar("criar_app", "a", "--interno", "--livre"))
        for cmd in ("listar_apps", "fila", "estatisticas"):
            self.assertNotIn(chave, rodar(cmd))

    def test_externo_com_ip_e_destino(self):
        chave = extrair_chave(rodar("criar_app", "ext", "--ip", "203.0.113.0/24", "--destino", "21990729548"))
        app = App.objects.get(nome="ext")
        self.assertEqual(app.destinos_permitidos, [NUMERO])
        self.assertFalse(app.destino_livre)
        self.assertEqual(self.enviar(chave, REMOTE_ADDR="203.0.113.5").status_code, 202)
        self.assertEqual(self.enviar(chave, REMOTE_ADDR="198.51.100.5").status_code, 403)

    def test_grupo_por_apelido(self):
        chave = extrair_chave(rodar("criar_app", "ext", "--ip", "203.0.113.5", "--grupo", f"ti={GRUPO}"))
        app = App.objects.get(nome="ext")
        self.assertEqual(app.apelidos_grupo, {"ti": GRUPO})
        self.assertEqual(app.destinos_permitidos, [GRUPO])
        r = self.c.post("/v1/messages", {"to": "ti", "text": "oi"}, format="json", **auth(chave),
                        REMOTE_ADDR="203.0.113.5")
        self.assertEqual(r.status_code, 202)

    def test_externo_sem_ip_fica_com_limites_baixos(self):
        rodar("criar_app", "ext", "--destino", NUMERO)
        app = App.objects.get(nome="ext")
        self.assertLessEqual(app.limite_minuto, 10)
        self.assertLessEqual(app.limite_dia, 100)

    def test_recusas(self):
        casos = [
            ("sem destino nem livre", ["x", "--ip", "203.0.113.5"]),
            ("livre sem interno", ["x", "--livre"]),
            ("externo sem ip acima do teto", ["x", "--destino", NUMERO, "--limite-minuto", "50"]),
            ("ip invalido", ["x", "--ip", "999.1.1.1", "--destino", NUMERO]),
            ("destino invalido", ["x", "--ip", "203.0.113.5", "--destino", "abc"]),
            ("grupo invalido", ["x", "--ip", "203.0.113.5", "--grupo", "ti=naoegrupo"]),
            ("ttl maior que ttl-max", ["x", "--interno", "--livre", "--ttl", "5000", "--ttl-max", "100"]),
        ]
        for nome, args in casos:
            with self.subTest(nome), self.assertRaises(CommandError):
                rodar("criar_app", *args)
        self.assertEqual(App.objects.count(), 0)

    def test_nome_duplicado(self):
        rodar("criar_app", "a", "--interno", "--livre")
        with self.assertRaises(CommandError):
            rodar("criar_app", "a", "--interno", "--livre")


class RotacionarEDesativarTests(TestCase):
    def setUp(self):
        bloqueio.resetar()
        self.c = APIClient()
        self.app, self.chave = criar_app("a")

    def enviar(self, chave):
        return self.c.post("/v1/messages", {"to": NUMERO, "text": "oi"}, format="json", **auth(chave))

    def test_rotacionar_invalida_a_antiga(self):
        nova = extrair_chave(rodar("rotacionar_chave", "a"))
        self.assertNotEqual(nova, self.chave)
        self.assertEqual(self.enviar(self.chave).status_code, 401)
        self.assertEqual(self.enviar(nova).status_code, 202)

    def test_rotacionar_nao_afeta_outro_app(self):
        _, chave_b = criar_app("b")
        rodar("rotacionar_chave", "a")
        self.assertEqual(self.enviar(chave_b).status_code, 202)

    def test_desativar_e_reativar(self):
        rodar("desativar_app", "a")
        self.assertEqual(self.enviar(self.chave).status_code, 403)
        rodar("desativar_app", "a", "--reativar")
        self.assertEqual(self.enviar(self.chave).status_code, 202)

    def test_app_inexistente(self):
        for cmd in ("rotacionar_chave", "desativar_app"):
            with self.subTest(cmd), self.assertRaises(CommandError):
                rodar(cmd, "nao-existe")


class RelatoriosTests(TestCase):
    def test_fila_estatisticas_e_listar_funcionam(self):
        app, _ = criar_app("a")
        criar_mensagem(app)
        self.assertIn("a: 1 queued", rodar("fila"))
        self.assertIn("a: 1 queued", rodar("estatisticas"))
        listagem = rodar("listar_apps")
        self.assertIn("a [ativo]", listagem)
        self.assertNotIn(NUMERO, listagem)

    def test_fila_vazia(self):
        self.assertIn("fila vazia", rodar("fila"))

    def test_faxina_roda(self):
        self.assertIn("0 textos apagados", rodar("faxina"))
