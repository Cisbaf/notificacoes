import json

from django.conf import settings
from rest_framework.exceptions import ParseError
from rest_framework.parsers import JSONParser

from .errors import ErroGateway


class JSONLimitado(JSONParser):
    """JSON com teto de tamanho. O DRF não aplica DATA_UPLOAD_MAX_MEMORY_SIZE ao ler o stream."""

    def parse(self, stream, media_type=None, parser_context=None):
        limite = settings.MAX_BODY_BYTES
        dados = stream.read(limite + 1)
        if len(dados) > limite:
            raise ErroGateway(413, "corpo_grande", f"Corpo maior que {limite} bytes.")
        try:
            return json.loads(dados.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise ParseError("JSON inválido.")
