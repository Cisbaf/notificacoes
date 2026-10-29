from django.test import SimpleTestCase

from gateway.destino import DestinoInvalido, mascarar, normalizar


class NormalizarTests(SimpleTestCase):
    def test_celular_br_sem_ddi_ganha_55(self):
        self.assertEqual(normalizar("21990729548"), "5521990729548")
        self.assertEqual(normalizar("(21) 99072-9548"), "5521990729548")

    def test_fixo_br_de_10_digitos_ganha_55(self):
        self.assertEqual(normalizar("2133334444"), "552133334444")

    def test_com_ddi_fica_como_esta(self):
        self.assertEqual(normalizar("5521990729548"), "5521990729548")
        self.assertEqual(normalizar("+55 21 99072-9548"), "5521990729548")

    def test_numero_de_outro_pais_nao_e_confundido_com_br(self):
        # 11 dígitos, terceiro dígito não é 9: não é celular BR com DDD
        self.assertEqual(normalizar("14155551234"), "14155551234")

    def test_grupo_por_jid(self):
        self.assertEqual(normalizar("120363025246125486@g.us"), "120363025246125486@g.us")
        self.assertEqual(normalizar("5521999990000-1600000000@g.us"), "5521999990000-1600000000@g.us")

    def test_apelido_de_grupo(self):
        apelidos = {"ti": "120363025246125486@g.us"}
        self.assertEqual(normalizar("ti", apelidos), "120363025246125486@g.us")

    def test_invalidos(self):
        for bruto in [None, "", "   ", 123, "abc", "ti", "123", "12345678901234567890", "fulano@s.whatsapp.net",
                      "x@g.us", "0211234567"]:
            with self.subTest(bruto=bruto), self.assertRaises(DestinoInvalido):
                normalizar(bruto)

    def test_apelido_desconhecido(self):
        with self.assertRaises(DestinoInvalido):
            normalizar("ti", {"outro": "1@g.us"})


class MascararTests(SimpleTestCase):
    def test_numero(self):
        m = mascarar("5521990729548")
        self.assertEqual(m, "5521*******48")
        self.assertNotIn("990729", m)

    def test_grupo(self):
        self.assertEqual(mascarar("120363025246125486@g.us"), "grupo:***5486")

    def test_idempotente_e_vazio(self):
        self.assertEqual(mascarar(mascarar("5521990729548")), "5521*******48")
        self.assertEqual(mascarar(""), "")
