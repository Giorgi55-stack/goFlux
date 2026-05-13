# Meta Ads Automation

Aplicação web para automatizar criação e gerenciamento de campanhas
no Meta Ads (Facebook + Instagram) para múltiplos clientes de uma agência.

## Stack

- Python 3.12+
- FastAPI + SQLModel + SQLite
- APScheduler (cron interno, tick de hora em hora)
- facebook-business SDK 25.x (Meta Marketing API v25)
- Jinja2 + HTMX + Tailwind (via CDN, sem build step)
- starlette-csrf para CSRF nos forms HTML

## Setup local (Windows / PowerShell)

```powershell
# 1. Clonar e entrar
git clone <repo>
cd meta-ads-automation

# 2. Criar e ativar venv
python -m venv venv
.\venv\Scripts\Activate.ps1

# 3. Instalar dependências
pip install -r requirements.txt

# 4. Configurar variáveis de ambiente
copy .env.example .env
# Edite .env preenchendo META_SYSTEM_USER_TOKEN, AUTH_PASSWORD, SECRET_KEY

# 5. Rodar em dev
uvicorn app.main:app --reload
```

Acesse http://localhost:8000 — o browser vai pedir login HTTP Basic
(`AUTH_USERNAME` / `AUTH_PASSWORD` do `.env`).

## Rodando os testes

```powershell
.\venv\Scripts\python.exe -m pytest tests/ -v
```

## Endpoints

### Interface web (HTTP Basic)
- `GET /` — home com nav
- `GET /clients`, `GET /clients/new`, `POST /clients`
- `GET /campaigns/new`, `POST /campaigns`, `GET /campaigns/result/{id}`
- `GET /rules`, `GET /rules/new`, `POST /rules`
- `GET /history`

### API JSON (HTTP Basic)
- `GET /health` (público, sem auth)
- `POST /api/test-token` — valida token e lista ad accounts
- `GET /api/clients/{id}/audiences` — lista custom audiences do cliente
- `POST /api/rules/{id}/execute-now` — força execução de uma regra

## Variáveis de ambiente

Veja `.env.example`. As chaves obrigatórias:

- `META_SYSTEM_USER_TOKEN` — token do System User da agência com acesso
  aos ad accounts dos clientes
- `META_API_VERSION` — default `v25.0`
- `AUTH_USERNAME`, `AUTH_PASSWORD` — credenciais HTTP Basic da interface
- `SECRET_KEY` — usado pelo CSRF middleware. Gere com
  `python -c "import secrets; print(secrets.token_hex(32))"`
- `DATABASE_URL` — default `sqlite:///./data/data.db`
- `ENV` — `development` ou `production`

## Deploy no Railway

Railway com plano **Hobby ($5/mês)** — não use free tier (a aplicação
dorme por inatividade e o scheduler não dispara).

### Passos

1. **Crie um projeto no Railway** apontando para seu repo GitHub:
   - Railway detecta `requirements.txt` e `Procfile` automaticamente
   - Python é fixado em 3.12 via `.python-version`

2. **Adicione um Volume** (Settings → Volumes → New Volume):
   - **Mount path**: `/app/data`
   - Tamanho: 1 GB já basta pra um MVP

3. **Configure as variáveis de ambiente** (Variables tab):
   ```
   META_SYSTEM_USER_TOKEN=<seu token>
   META_API_VERSION=v25.0
   AUTH_USERNAME=<seu user>
   AUTH_PASSWORD=<senha forte>
   SECRET_KEY=<gere com secrets.token_hex(32)>
   DATABASE_URL=sqlite:////app/data/data.db
   ENV=production
   ```
   Note: 4 barras em `sqlite:////app/data/data.db` (caminho absoluto).

4. **Deploy**: Railway builda e sobe automaticamente. O Procfile
   já está configurado:
   ```
   web: uvicorn app.main:app --host 0.0.0.0 --port $PORT
   ```

5. **Acesse** a URL gerada pelo Railway. Vai pedir o HTTP Basic.

### Notas operacionais

- O `init_db()` cria as tabelas automaticamente no startup. Não precisa
  rodar migration.
- O scheduler do APScheduler roda em background. Com 1 worker (default
  do Railway), os jobs disparam exatamente uma vez por hora.
- Se você escalar para múltiplos workers, configure
  `WEB_CONCURRENCY=1` para manter só 1 instância do scheduler.
- O SQLite no Volume persiste entre restarts. Backup: copie
  `/app/data/data.db` manualmente quando precisar.

## Escopo completo

Veja [BRIEFING.md](BRIEFING.md).
