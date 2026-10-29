from datetime import timedelta

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from gateway import bloqueio
from gateway.models import EstadoWorker, Mensagem

from .util import NUMERO, auth, criar_app, criar_mensagem

GRUPO = "120363025246125486@g.us"


class ApiBase(TestCase):
    def setUp(self):
        bloqueio.resetar()
        self.c = APIClient()
        self.app, self.chave = criar_app()

    def enviar(self, corpo=None, chave=None, **extra):
        corpo = {"to": NUMERO, "text": "oi"} if corpo is None else corpo
        return self.c.post("/v1/messages", corpo, format="json", **auth(chave or self.chave), **extra)


class AutenticacaoTests(ApiBase):
    def test_sem_chave_401(self):
        r = self.c.post("/v1/messages", {"to": NUMERO, "text": "oi"}, format="json")
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.json()["error"]["code"], "nao_autenticado")

    def test_chave_errada_401(self):
        r = self.enviar(chave="ntf_errada")
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.json()["error"]["code"], "nao_autenticado")

    def test_esquema_errado_401(self):
        r = self.c.post("/v1/messages", {"to": NUMERO, "text": "oi"}, format="json",
                        HTTP_AUTHORIZATION=f"Basic {self.chave}")
        self.assertEqual(r.status_code, 401)

    def test_chave_valida_aceita(self):
        r = self.enviar()
        self.assertEqual(r.status_code, 202)
        self.assertEqual(r.json()["status"], "queued")
        self.assertEqual(Mensagem.objects.count(), 1)

    def test_app_desativado_403(self):
        self.app.ativo = False
        self.app.save()
        r = self.enviar()
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.json()["error"]["code"], "app_desativado")

    def test_ip_fora_da_allowlist_403(self):
        self.app.ips_permitidos = ["203.0.113.7"]
        self.app.save()
        r = self.enviar(REMOTE_ADDR="198.51.100.9")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.json()["error"]["code"], "ip_nao_permitido")
        self.assertEqual(Mensagem.objects.count(), 0)

    def test_ip_na_allowlist_aceita_ip_e_cidr(self):
        self.app.ips_permitidos = ["203.0.113.7", "198.51.100.0/24"]
        self.app.save()
        self.assertEqual(self.enviar(REMOTE_ADDR="203.0.113.7").status_code, 202)
        self.assertEqual(self.enviar(REMOTE_ADDR="198.51.100.200").status_code, 202)
        self.assertEqual(self.enviar(REMOTE_ADDR="198.51.101.1").status_code, 403)

    def test_x_forwarded_for_nao_engana_a_allowlist(self):
        self.app.ips_permitidos = ["203.0.113.7"]
        self.app.save()
        r = self.enviar(REMOTE_ADDR="198.51.100.9", HTTP_X_FORWARDED_FOR="203.0.113.7")
        self.assertEqual(r.status_code, 403)

    @override_settings(BLOQUEIO_FALHAS=3)
    def test_bloqueia_ip_apos_chaves_invalidas(self):
        for _ in range(3):
            self.assertEqual(self.enviar(chave="ntf_x", REMOTE_ADDR="198.51.100.9").status_code, 401)
        # Agora até a chave certa fica bloqueada, vinda desse IP.
        r = self.enviar(REMOTE_ADDR="198.51.100.9")
        self.assertEqual(r.status_code, 429)
        self.assertEqual(r.json()["error"]["code"], "limite_excedido")
        self.assertGreater(int(r["Retry-After"]), 0)
        # Outro IP não é afetado.
        self.assertEqual(self.enviar(REMOTE_ADDR="198.51.100.10").status_code, 202)

    @override_settings(BLOQUEIO_FALHAS=3)
    def test_chave_certa_nao_conta_como_falha(self):
        for _ in range(5):
            self.assertEqual(self.enviar(REMOTE_ADDR="198.51.100.9").status_code, 202)

    def test_chave_nao_fica_no_banco(self):
        self.assertNotIn(self.chave, str(list(self.app.__class__.objects.values())))


class ValidacaoTests(ApiBase):
    def test_json_invalido_400(self):
        r = self.c.post("/v1/messages", "{nao e json", content_type="application/json", **auth(self.chave))
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["error"]["code"], "payload_invalido")

    def test_corpo_nao_objeto_400(self):
        self.assertEqual(self.enviar(["a"]).status_code, 400)

    def test_text_obrigatorio(self):
        for corpo in [{"to": NUMERO}, {"to": NUMERO, "text": ""}, {"to": NUMERO, "text": "   "},
                      {"to": NUMERO, "text": 5}]:
            with self.subTest(corpo=corpo):
                r = self.enviar(corpo)
                self.assertEqual(r.status_code, 400)
                self.assertEqual(r.json()["error"]["code"], "payload_invalido")

    def test_text_maximo(self):
        self.assertEqual(self.enviar({"to": NUMERO, "text": "a" * 4000}).status_code, 202)
        self.assertEqual(self.enviar({"to": NUMERO, "text": "a" * 4001}).status_code, 400)

    def test_to_invalido_400(self):
        for to in [None, "", "abc", "123", "fulano@s.whatsapp.net"]:
            with self.subTest(to=to):
                r = self.enviar({"to": to, "text": "oi"})
                self.assertEqual(r.status_code, 400)
                self.assertEqual(r.json()["error"]["code"], "numero_invalido")

    def test_normaliza_celular_sem_ddi(self):
        self.enviar({"to": "21990729548", "text": "oi"})
        self.assertEqual(Mensagem.objects.get().destino, NUMERO)

    def test_expires_in(self):
        self.app.ttl_padrao, self.app.ttl_max = 600, 1200
        self.app.save()
        self.assertEqual(self.enviar({"to": NUMERO, "text": "a", "expires_in": 1201}).status_code, 400)
        self.assertEqual(self.enviar({"to": NUMERO, "text": "a", "expires_in": 0}).status_code, 400)
        self.assertEqual(self.enviar({"to": NUMERO, "text": "a", "expires_in": "10"}).status_code, 400)
        self.assertEqual(self.enviar({"to": NUMERO, "text": "a", "expires_in": 1200}).status_code, 202)
        self.assertEqual(self.enviar({"to": NUMERO, "text": "b"}).status_code, 202)
        m = Mensagem.objects.get(texto="b")
        self.assertAlmostEqual((m.expira_em - m.criado_em).total_seconds(), 600, delta=2)

    def test_ref_e_idempotency_key_limites(self):
        self.assertEqual(self.enviar({"to": NUMERO, "text": "a", "ref": "r" * 65}).status_code, 400)
        self.assertEqual(self.enviar({"to": NUMERO, "text": "a", "idempotency_key": "k" * 65}).status_code, 400)
        self.assertEqual(self.enviar({"to": NUMERO, "text": "a", "idempotency_key": "tem espaco"}).status_code, 400)

    @override_settings(MAX_BODY_BYTES=1000)
    def test_corpo_grande_413(self):
        r = self.enviar({"to": NUMERO, "text": "a" * 1500})
        self.assertEqual(r.status_code, 413)
        self.assertEqual(r.json()["error"]["code"], "corpo_grande")

    @override_settings(MAX_BODY_BYTES=1000)
    def test_corpo_grande_sem_chave_da_401_antes_de_ler(self):
        r = self.c.post("/v1/messages", {"to": NUMERO, "text": "a" * 1500}, format="json")
        self.assertEqual(r.status_code, 401)

    def test_rota_inexistente_e_metodo_errado(self):
        r = self.c.get("/nada")
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.json()["error"]["code"], "nao_encontrada")
        r = self.c.get("/v1/messages", **auth(self.chave))
        self.assertEqual(r.status_code, 405)


class DestinosTests(ApiBase):
    def test_destino_nao_permitido_403(self):
        self.app.destino_livre = False
        self.app.destinos_permitidos = ["5521999990000"]
        self.app.save()
        r = self.enviar()
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.json()["error"]["code"], "destino_nao_permitido")
        self.assertEqual(Mensagem.objects.count(), 0)

    def test_destino_permitido_e_normalizado_antes_de_comparar(self):
        self.app.destino_livre = False
        self.app.destinos_permitidos = [NUMERO]
        self.app.save()
        self.assertEqual(self.enviar({"to": "(21) 99072-9548", "text": "oi"}).status_code, 202)

    def test_apelido_de_grupo(self):
        self.app.destino_livre = False
        self.app.apelidos_grupo = {"ti": GRUPO}
        self.app.destinos_permitidos = [GRUPO]
        self.app.save()
        self.assertEqual(self.enviar({"to": "ti", "text": "oi"}).status_code, 202)
        self.assertEqual(Mensagem.objects.get().destino, GRUPO)
        self.assertEqual(self.enviar({"to": GRUPO, "text": "oi"}).status_code, 202)
        self.assertEqual(self.enviar({"to": "120363000000000000@g.us", "text": "oi"}).status_code, 403)

    def test_apelido_nao_vale_para_outro_app(self):
        outro, chave2 = criar_app("app2")
        self.app.apelidos_grupo = {"ti": GRUPO}
        self.app.save()
        r = self.enviar({"to": "ti", "text": "oi"}, chave=chave2)
        self.assertEqual(r.status_code, 400)


class IdempotenciaTests(ApiBase):
    def test_repeticao_devolve_original_com_200(self):
        corpo = {"to": NUMERO, "text": "oi", "idempotency_key": "evento-1"}
        r1 = self.enviar(corpo)
        r2 = self.enviar(corpo)
        self.assertEqual((r1.status_code, r2.status_code), (202, 200))
        self.assertEqual(r1.json()["id"], r2.json()["id"])
        self.assertEqual(Mensagem.objects.count(), 1)

    def test_repeticao_nao_gasta_limite(self):
        self.app.limite_minuto = 1
        self.app.save()
        corpo = {"to": NUMERO, "text": "oi", "idempotency_key": "evento-1"}
        self.assertEqual(self.enviar(corpo).status_code, 202)
        self.assertEqual(self.enviar(corpo).status_code, 200)

    def test_mesma_chave_em_apps_diferentes_sao_independentes(self):
        _, chave2 = criar_app("app2")
        corpo = {"to": NUMERO, "text": "oi", "idempotency_key": "evento-1"}
        self.assertEqual(self.enviar(corpo).status_code, 202)
        self.assertEqual(self.enviar(corpo, chave=chave2).status_code, 202)
        self.assertEqual(Mensagem.objects.count(), 2)

    def test_sem_chave_nao_deduplica(self):
        self.enviar()
        self.enviar()
        self.assertEqual(Mensagem.objects.count(), 2)


class LimitesTests(ApiBase):
    def test_limite_por_minuto(self):
        self.app.limite_minuto = 2
        self.app.save()
        self.assertEqual(self.enviar().status_code, 202)
        self.assertEqual(self.enviar().status_code, 202)
        r = self.enviar()
        self.assertEqual(r.status_code, 429)
        self.assertEqual(r.json()["error"]["code"], "limite_excedido")
        self.assertTrue(1 <= int(r["Retry-After"]) <= 61)
        self.assertEqual(Mensagem.objects.count(), 2)

    def test_limite_por_dia(self):
        self.app.limite_dia = 1
        self.app.save()
        self.assertEqual(self.enviar().status_code, 202)
        Mensagem.objects.update(criado_em=timezone.now() - timedelta(hours=1))
        r = self.enviar()
        self.assertEqual(r.status_code, 429)
        self.assertGreater(int(r["Retry-After"]), 60)

    def test_limite_e_por_app(self):
        _, chave2 = criar_app("app2")
        self.app.limite_minuto = 1
        self.app.save()
        self.enviar()
        self.assertEqual(self.enviar().status_code, 429)
        self.assertEqual(self.enviar(chave=chave2).status_code, 202)

    def test_cota_zero_bloqueia(self):
        self.app.limite_minuto = 0
        self.app.save()
        self.assertEqual(self.enviar().status_code, 429)

    def test_mensagem_antiga_sai_da_janela(self):
        self.app.limite_minuto = 1
        self.app.save()
        self.enviar()
        Mensagem.objects.update(criado_em=timezone.now() - timedelta(seconds=61))
        self.assertEqual(self.enviar().status_code, 202)


class ConsultaTests(ApiBase):
    def test_consulta_propria_sem_texto_nem_numero(self):
        m = criar_mensagem(self.app, texto="segredo-no-texto")
        r = self.c.get(f"/v1/messages/{m.id}", **auth(self.chave))
        self.assertEqual(r.status_code, 200)
        corpo = r.content.decode()
        self.assertEqual(r.json()["status"], "queued")
        self.assertNotIn("segredo-no-texto", corpo)
        self.assertNotIn(NUMERO, corpo)
        self.assertNotIn("990729548", corpo)

    def test_mensagem_de_outro_app_da_404(self):
        outro, chave2 = criar_app("app2")
        m = criar_mensagem(outro)
        self.assertEqual(self.c.get(f"/v1/messages/{m.id}", **auth(self.chave)).status_code, 404)
        self.assertEqual(self.c.get(f"/v1/messages/{m.id}", **auth(chave2)).status_code, 200)

    def test_consulta_exige_chave(self):
        m = criar_mensagem(self.app)
        self.assertEqual(self.c.get(f"/v1/messages/{m.id}").status_code, 401)

    def test_codigo_de_erro_aparece(self):
        m = criar_mensagem(self.app, status=Mensagem.FAILED, codigo_erro="numero_invalido")
        r = self.c.get(f"/v1/messages/{m.id}", **auth(self.chave))
        self.assertEqual(r.json()["error_code"], "numero_invalido")


class StatusTests(ApiBase):
    def test_status_sem_worker_e_unknown(self):
        r = self.c.get("/v1/status", **auth(self.chave))
        self.assertEqual(r.json(), {"whatsapp": "unknown", "queued": 0})

    def test_status_com_estado_recente(self):
        EstadoWorker.objects.create(pk=1, whatsapp="open", whatsapp_em=timezone.now())
        criar_mensagem(self.app)
        criar_mensagem(self.app, status=Mensagem.SENT)
        r = self.c.get("/v1/status", **auth(self.chave))
        self.assertEqual(r.json(), {"whatsapp": "open", "queued": 1})

    def test_status_velho_vira_unknown(self):
        EstadoWorker.objects.create(pk=1, whatsapp="open", whatsapp_em=timezone.now() - timedelta(minutes=10))
        self.assertEqual(self.c.get("/v1/status", **auth(self.chave)).json()["whatsapp"], "unknown")

    def test_fila_conta_so_o_proprio_app(self):
        outro, _ = criar_app("app2")
        criar_mensagem(outro)
        self.assertEqual(self.c.get("/v1/status", **auth(self.chave)).json()["queued"], 0)

    def test_status_exige_chave(self):
        self.assertEqual(self.c.get("/v1/status").status_code, 401)

    def test_healthz_sem_auth(self):
        r = self.c.get("/healthz")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"status": "ok"})


class LogTests(ApiBase):
    def test_log_nao_traz_numero_completo(self):
        with self.assertLogs("gateway", level="INFO") as logs:
            self.enviar()
        saida = "\n".join(logs.output)
        self.assertIn("mensagem aceita", saida)
        self.assertNotIn(NUMERO, saida)
        self.assertNotIn("990729548", saida)
