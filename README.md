# Gateway de notificações (WhatsApp)

Serviço único para qualquer app mandar notificação por WhatsApp. Só ele fala com o Evolution; os apps usam uma **chave própria** e nunca veem a chave da instância.

    app (interno ou externo) ──HTTP──▶ notificacoes-web ──fila MySQL──▶ notificacoes-worker ──▶ Evolution ──▶ WhatsApp

- `notificacoes-web`: Django + DRF, gunicorn (1 processo, 8 threads). Valida, grava na fila e responde.
- `notificacoes-worker`: tira da fila, envia em ritmo global (~1 mensagem a cada 2,5 s), faz retry e expira por TTL. Só ele recebe a chave do Evolution (`.env.worker`).
- Redes: `notificacoes_net` (apps internos), `cisbaf_network_apps` (MySQL), `evolution_internal` (worker ↔ Evolution).
- Base `notificacoes` no `mysql-container`, usuário próprio.

## Contrato v1

Todas as chamadas (menos `/healthz`) levam `Authorization: Bearer <chave-do-app>`. Corpo e resposta em JSON.

### `POST /v1/messages`

| campo | obrigatório | descrição |
|---|---|---|
| `to` | sim | Celular com DDI (`5521999990000`); celular BR de 10/11 dígitos sem DDI ganha `55`. Grupo: JID `...@g.us` ou apelido do cadastro do app. |
| `text` | sim | Até 4000 caracteres. |
| `idempotency_key` | não | Até 64 caracteres (`A-Z a-z 0-9 _ . : @ -`). Repetir a chave devolve a mensagem original. |
| `expires_in` | não | Segundos de validade na fila (inteiro, até o máximo do app). Passou disso sem enviar → `expired`. |
| `ref` | não | Até 64 caracteres, para você correlacionar. **Sem dado pessoal.** |

Resposta: **202** `{"id": "...", "status": "queued"}`. Repetição com a mesma `idempotency_key`: **200** com a mensagem original (não gasta limite).

### `GET /v1/messages/{id}`

Só mensagens do próprio app (de outro app: 404). Nunca devolve texto nem número.

    {"id","status","attempts","error_code","created_at","sent_at","expires_at"}

`status`: `queued` → `sending` → `sent` | `failed` | `expired`.
`error_code`: `whatsapp_offline`, `numero_invalido`, `falha_envio`, `expirada`.

`sent` significa que o Evolution aceitou a mensagem. Não é confirmação de leitura.

### `GET /v1/status`

`{"whatsapp": "open|close|connecting|unknown", "queued": N}` (`queued` = pendentes do próprio app).

### `GET /healthz`

Sem autenticação. `{"status":"ok"}` se o processo está vivo.

### Erros

`{"error": {"code": "...", "message": "..."}}`

| HTTP | `code` | quando |
|---|---|---|
| 400 | `payload_invalido` / `numero_invalido` | JSON ou campo inválido; destino que não vale |
| 401 | `nao_autenticado` | chave ausente ou errada |
| 403 | `destino_nao_permitido` / `ip_nao_permitido` / `app_desativado` | regra do cadastro do app |
| 404 | `nao_encontrada` | mensagem de outro app ou inexistente |
| 413 | `corpo_grande` | corpo acima de 64 KB |
| 429 | `limite_excedido` | cota do app ou IP bloqueado; leia `Retry-After` (segundos) |
| 5xx | `erro_interno` | tente de novo mais tarde |

## Como integrar um app

Variáveis padrão: `NOTIFY_URL` (vazio = envio desligado, sem erro) e `NOTIFY_API_KEY`.

Boas práticas:

- Envie **sem bloquear** a ação do usuário (timeout curto, 3 s conecta / 8 s lê) e nunca deixe falha de notificação derrubar o app.
- Use `idempotency_key` por evento (ex.: `chamado-123-aberto`) para que retry seu não duplique mensagem.
- Em 429, espere o `Retry-After`. Em 5xx e timeout, tente de novo com espera crescente.
- Não coloque dado pessoal sensível no texto nem na `ref`. Sem HTTPS, o conteúdo trafega em claro para apps fora da VPS.
- Guarde a chave só em variável de ambiente, nunca no git.

Shell:

    curl -sS -X POST "$NOTIFY_URL/v1/messages" \
      -H "Authorization: Bearer $NOTIFY_API_KEY" -H "Content-Type: application/json" \
      -d '{"to":"21999990000","text":"Backup concluído","idempotency_key":"backup-2026-10-29"}'

Python:

    import requests

    def notificar(para, texto, chave_evento=None):
        if not NOTIFY_URL:
            return
        try:
            requests.post(f"{NOTIFY_URL}/v1/messages", timeout=(3, 8),
                          headers={"Authorization": f"Bearer {NOTIFY_API_KEY}"},
                          json={"to": para, "text": texto, "idempotency_key": chave_evento})
        except requests.RequestException:
            pass  # notificação nunca derruba o app

Node (18+):

    async function notificar(to, text, idempotencyKey) {
      if (!process.env.NOTIFY_URL) return;
      try {
        await fetch(`${process.env.NOTIFY_URL}/v1/messages`, {
          method: "POST",
          headers: { Authorization: `Bearer ${process.env.NOTIFY_API_KEY}`, "Content-Type": "application/json" },
          body: JSON.stringify({ to, text, idempotency_key: idempotencyKey }),
          signal: AbortSignal.timeout(8000),
        });
      } catch (e) { /* notificação nunca derruba o app */ }
    }

PHP:

    function notificar($para, $texto, $chaveEvento = null) {
        $url = getenv('NOTIFY_URL');
        if (!$url) return;
        $ch = curl_init("$url/v1/messages");
        curl_setopt_array($ch, [
            CURLOPT_POST => true, CURLOPT_RETURNTRANSFER => true,
            CURLOPT_CONNECTTIMEOUT => 3, CURLOPT_TIMEOUT => 8,
            CURLOPT_HTTPHEADER => ['Authorization: Bearer ' . getenv('NOTIFY_API_KEY'), 'Content-Type: application/json'],
            CURLOPT_POSTFIELDS => json_encode(['to' => $para, 'text' => $texto, 'idempotency_key' => $chaveEvento]),
        ]);
        curl_exec($ch);
        curl_close($ch);
    }

## Administração (só linha de comando)

Sem painel web. Dentro do container:

    docker exec notificacoes-web python manage.py criar_app NOME [opções]
    docker exec notificacoes-web python manage.py rotacionar_chave NOME
    docker exec notificacoes-web python manage.py desativar_app NOME [--reativar]
    docker exec notificacoes-web python manage.py listar_apps
    docker exec notificacoes-web python manage.py fila
    docker exec notificacoes-web python manage.py estatisticas [--horas 24]
    docker exec notificacoes-web python manage.py faxina

`criar_app` imprime a chave **uma única vez** (no banco fica só o hash SHA-256). Entregue por canal seguro.

Regras de cadastro:

- App **interno** (`--interno`): pode não ter IP fixo; pode ter `--livre` (qualquer destino). Ex.: `criar_app chamadosti --interno --livre`.
- App **externo** com IP fixo: `--ip 203.0.113.5` (ou CIDR, repetível) e destinos fechados: `--destino 21999990000`, `--grupo apelido=JID@g.us`.
- App externo **sem IP fixo**: só com destinos fechados e limites baixos (máx. 10/min e 100/dia). A chave é a única defesa.
- Limites: `--limite-minuto`, `--limite-dia`; validade na fila: `--ttl`, `--ttl-max`.

## Operação

- Subir/atualizar: `./deployment.sh` (build, `up -d`; o web aplica migrações antes de aceitar tráfego e o worker só sobe depois dele saudável).
- Testes (usam o MySQL real, base `test_notificacoes`): `docker compose run --rm --no-deps notificacoes-web python manage.py test gateway --noinput`
- Saúde: `docker ps` mostra `healthy`; `manage.py fila` mostra batimento do worker, estado do WhatsApp e fila.
- Se o WhatsApp cair (`close`), o worker pausa sem gastar tentativas; as mensagens vencem pelo TTL (`expired`). Não há alerta automático: reconectar por QR no Evolution (ver `/home/daniel/servers/evolution/README.md`).
- Retenção: texto apagado e número mascarado após 7 dias; linhas removidas após 90 (`RETENCAO_*`). O worker faz isso de hora em hora.
- Backup: o `backup-v2` já cobre a base `notificacoes` (dump de todas as bases) e esta pasta (`servers/`).
- Variáveis ajustáveis: ver `.env.example`.

## Segurança

- Chave por app, só o hash no banco; comparação em tempo constante; rotação e desativação por app.
- Allowlist de IP por app aplicada no gateway (usa só o IP da conexão; `X-Forwarded-For` é ignorado). O Docker ignora o UFW em portas publicadas, por isso a regra está aqui.
- Destinos permitidos por app; limites por minuto/dia e ritmo global no worker.
- Bloqueio temporário de IP após 10 chaves inválidas em 10 min (contador em memória; zera ao reiniciar).
- Logs com número mascarado; corpo de erro do Evolution nunca é logado.
- Sem HTTPS (decisão do projeto): quem estiver no caminho vê chave, números e texto de apps externos. Mitigação: firewall do provedor só para os IPs dos apps e nenhum dado sensível no texto.

## Fora do v1

Mídia, mensagens recebidas, webhooks de status, painel web.
