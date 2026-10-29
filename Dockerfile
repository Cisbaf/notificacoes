FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# mysqlclient precisa compilar contra a libmysqlclient
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc pkg-config default-libmysqlclient-dev && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY src/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src .

RUN useradd --system --uid 1000 --create-home app
USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3)"

# 1 processo com várias threads: o bloqueio de IP por chave inválida vive em memória e precisa ser único.
# Aplica migrações pendentes antes de subir (o worker só inicia depois que este container está healthy).
CMD ["sh", "-c", "python manage.py migrate --noinput && exec gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 1 --threads 8 --worker-class gthread --timeout 30 --graceful-timeout 20 --limit-request-line 4094 --limit-request-fields 50 --access-logfile -"]
