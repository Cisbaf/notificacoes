from datetime import timedelta

from django.test import TestCase, override_settings
from django.utils import timezone

from gateway import worker
from gateway.evolution import PERMANENTE, TEMPORARIO, Resultado
from gateway.models import EstadoWorker, Mensagem

from .util import NUMERO, ClienteFalso, criar_app, criar_mensagem


class Parada:
    """Event falso: o loop do worker roda N vezes e para; registra as esperas pedidas."""

    def __init__(self, voltas):
        self.voltas = voltas
        self.esperas = []

    def is_set(self):
        return len(self.esperas) >= self.voltas

    def wait(self, segundos):
        self.esperas.append(segundos)


class ProcessarUmaTests(TestCase):
    def setUp(self):
        self.app, _ = criar_app()

    def test_fila_vazia(self):
        self.assertIsNone(worker.processar_uma(ClienteFalso()))

    def test_envio_ok(self):
        m = criar_mensagem(self.app, texto="ola")
        cliente = ClienteFalso()
        self.assertEqual(worker.processar_uma(cliente), "enviada")
        self.assertEqual(cliente.enviados, [(NUMERO, "ola")])
        m.refresh_from_db()
        self.assertEqual((m.status, m.tentativas, m.evolution_id, m.codigo_erro), ("sent", 1, "evo123", ""))
        self.assertIsNotNone(m.enviado_em)
        self.assertIsNone(m.travada_em)

    def test_numero_invalido_e_definitivo(self):
        m = criar_mensagem(self.app)
        cliente = ClienteFalso([Resultado(PERMANENTE, "numero_invalido")])
        self.assertEqual(worker.processar_uma(cliente), "falhou")
        m.refresh_from_db()
        self.assertEqual((m.status, m.codigo_erro, m.tentativas), ("failed", "numero_invalido", 1))
        self.assertIsNone(worker.processar_uma(cliente))  # sem retry

    def test_falha_temporaria_volta_para_fila_com_backoff(self):
        m = criar_mensagem(self.app)
        cliente = ClienteFalso([Resultado(TEMPORARIO, "falha_envio")])
        self.assertEqual(worker.processar_uma(cliente), "adiada")
        m.refresh_from_db()
        self.assertEqual((m.status, m.tentativas, m.codigo_erro), ("queued", 1, "falha_envio"))
        self.assertGreater(m.proxima_tentativa_em, timezone.now() + timedelta(seconds=20))
        # Ainda não é hora: não reenvia.
        self.assertIsNone(worker.processar_uma(cliente))

    @override_settings(WORKER_BACKOFF_BASE_S=30, WORKER_BACKOFF_MAX_S=100)
    def test_backoff_dobra_e_tem_teto(self):
        self.assertEqual([worker._espera_backoff(n) for n in (1, 2, 3, 4, 5)], [30, 60, 100, 100, 100])

    @override_settings(WORKER_MAX_TENTATIVAS=2)
    def test_esgota_tentativas(self):
        m = criar_mensagem(self.app)
        cliente = ClienteFalso([Resultado(TEMPORARIO, "falha_envio")] * 2)
        self.assertEqual(worker.processar_uma(cliente), "adiada")
        Mensagem.objects.update(proxima_tentativa_em=timezone.now() - timedelta(seconds=1))
        self.assertEqual(worker.processar_uma(cliente), "falhou")
        m.refresh_from_db()
        self.assertEqual((m.status, m.codigo_erro, m.tentativas), ("failed", "falha_envio", 2))

    def test_sessao_caida_nao_gasta_tentativa(self):
        m = criar_mensagem(self.app)
        cliente = ClienteFalso([Resultado(TEMPORARIO, "falha_envio")], estado="close")
        self.assertEqual(worker.processar_uma(cliente), "offline")
        m.refresh_from_db()
        self.assertEqual((m.status, m.tentativas, m.codigo_erro), ("queued", 0, "whatsapp_offline"))
        self.assertEqual(EstadoWorker.objects.get(pk=1).whatsapp, "close")

    def test_envia_na_ordem_de_chegada(self):
        agora = timezone.now()
        a = criar_mensagem(self.app, texto="primeira", proxima_tentativa_em=agora - timedelta(seconds=10))
        b = criar_mensagem(self.app, texto="segunda", proxima_tentativa_em=agora - timedelta(seconds=5))
        cliente = ClienteFalso()
        worker.processar_uma(cliente)
        worker.processar_uma(cliente)
        self.assertEqual([t for _, t in cliente.enviados], ["primeira", "segunda"])

    def test_nao_pega_mensagem_expirada_nem_futura(self):
        agora = timezone.now()
        criar_mensagem(self.app, expira_em=agora - timedelta(seconds=1))
        criar_mensagem(self.app, proxima_tentativa_em=agora + timedelta(minutes=5))
        self.assertIsNone(worker.processar_uma(ClienteFalso()))

    def test_reivindicar_nao_entrega_a_mesma_mensagem_duas_vezes(self):
        criar_mensagem(self.app, texto="a")
        criar_mensagem(self.app, texto="b")
        agora = timezone.now()
        primeira, segunda = worker.reivindicar(agora), worker.reivindicar(agora)
        self.assertNotEqual(primeira.id, segunda.id)
        self.assertEqual({primeira.status, segunda.status}, {"sending"})
        self.assertIsNone(worker.reivindicar(agora))

    def test_log_nao_traz_numero_completo_nem_texto(self):
        criar_mensagem(self.app, texto="texto-secreto")
        criar_mensagem(self.app, texto="texto-secreto")
        cliente = ClienteFalso([Resultado(PERMANENTE, "numero_invalido")])
        with self.assertLogs("gateway", level="INFO") as logs:
            worker.processar_uma(cliente)
            worker.processar_uma(cliente)
        saida = "\n".join(logs.output)
        self.assertNotIn(NUMERO, saida)
        self.assertNotIn("990729548", saida)
        self.assertNotIn("texto-secreto", saida)


class ManutencaoTests(TestCase):
    def setUp(self):
        self.app, _ = criar_app()

    def test_expira_so_o_que_venceu(self):
        agora = timezone.now()
        vencida = criar_mensagem(self.app, expira_em=agora - timedelta(seconds=1))
        valida = criar_mensagem(self.app)
        self.assertEqual(worker.expirar(agora), 1)
        vencida.refresh_from_db()
        valida.refresh_from_db()
        self.assertEqual((vencida.status, vencida.codigo_erro), ("expired", "expirada"))
        self.assertEqual(valida.status, "queued")

    @override_settings(WORKER_ENVIANDO_TRAVADA_S=300)
    def test_sending_esquecida_volta_para_fila(self):
        agora = timezone.now()
        presa = criar_mensagem(self.app, status=Mensagem.SENDING, travada_em=agora - timedelta(minutes=10))
        em_curso = criar_mensagem(self.app, status=Mensagem.SENDING, travada_em=agora - timedelta(seconds=30))
        self.assertEqual(worker.recuperar_travadas(agora), 1)
        presa.refresh_from_db()
        em_curso.refresh_from_db()
        self.assertEqual(presa.status, "queued")
        self.assertEqual(em_curso.status, "sending")

    def test_faxina_apaga_texto_e_mascara_destino_apos_7_dias(self):
        velha = criar_mensagem(self.app, status=Mensagem.SENT, texto="conteudo")
        nova = criar_mensagem(self.app, status=Mensagem.SENT, texto="recente")
        Mensagem.objects.filter(pk=velha.pk).update(criado_em=timezone.now() - timedelta(days=8))
        self.assertEqual(worker.faxina(), (1, 0))
        velha.refresh_from_db()
        nova.refresh_from_db()
        self.assertEqual(velha.texto, "")
        self.assertNotIn("990729548", velha.destino)
        self.assertEqual(velha.status, "sent")
        self.assertEqual((nova.texto, nova.destino), ("recente", NUMERO))

    def test_faxina_remove_linhas_apos_90_dias(self):
        m = criar_mensagem(self.app, status=Mensagem.SENT)
        Mensagem.objects.filter(pk=m.pk).update(criado_em=timezone.now() - timedelta(days=91))
        worker.faxina()
        self.assertEqual(Mensagem.objects.count(), 0)

    def test_faxina_nao_guarda_texto_de_mensagem_presa_na_fila(self):
        m = criar_mensagem(self.app, status=Mensagem.QUEUED)
        Mensagem.objects.filter(pk=m.pk).update(criado_em=timezone.now() - timedelta(days=8))
        worker.faxina()
        m.refresh_from_db()
        self.assertEqual(m.status, "expired")


class LoopTests(TestCase):
    def setUp(self):
        self.app, _ = criar_app()

    def test_pausa_quando_whatsapp_nao_esta_open(self):
        m = criar_mensagem(self.app)
        cliente = ClienteFalso(estado="close")
        worker.rodar(cliente, Parada(voltas=3))
        self.assertEqual(cliente.enviados, [])
        m.refresh_from_db()
        self.assertEqual((m.status, m.tentativas), ("queued", 0))
        self.assertEqual(EstadoWorker.objects.get(pk=1).whatsapp, "close")

    @override_settings(WORKER_RITMO_S=2.5)
    def test_envia_tudo_com_ritmo_global(self):
        for i in range(3):
            criar_mensagem(self.app, texto=f"m{i}")
        cliente = ClienteFalso()
        parada = Parada(voltas=5)
        worker.rodar(cliente, parada)
        self.assertEqual(len(cliente.enviados), 3)
        self.assertEqual(Mensagem.objects.filter(status="sent").count(), 3)
        # Cada envio é seguido de uma espera de 0,8x a 1,4x o ritmo.
        esperas_de_envio = parada.esperas[:3]
        for e in esperas_de_envio:
            self.assertTrue(2.0 <= e <= 3.5, e)

    def test_publica_estado_e_batimento(self):
        worker.rodar(ClienteFalso(estado="open"), Parada(voltas=1))
        estado = EstadoWorker.objects.get(pk=1)
        self.assertEqual(estado.whatsapp, "open")
        self.assertIsNotNone(estado.batimento_em)

    def test_expira_mensagem_durante_o_loop(self):
        m = criar_mensagem(self.app, expira_em=timezone.now() - timedelta(seconds=1))
        cliente = ClienteFalso()
        worker.rodar(cliente, Parada(voltas=2))
        m.refresh_from_db()
        self.assertEqual(m.status, "expired")
        self.assertEqual(cliente.enviados, [])
