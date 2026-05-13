# Meta Ads Automation

Aplicação web para automatizar criação e gerenciamento de campanhas
no Meta Ads (Facebook + Instagram) para múltiplos clientes de uma agência.

## Stack

- Python 3.12+
- FastAPI + SQLModel + SQLite (dev) / Postgres (produção)
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

Acesse http://localhost:8000 — o browser pede login HTTP Basic
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

### API JSON (HTTP Basic, exceto /health)
- `GET /health` (público) — usado pelo cron-job.org keep-alive
- `POST /api/test-token` — valida token e lista ad accounts
- `GET /api/clients/{id}/audiences` — lista custom audiences do cliente
- `POST /api/rules/{id}/execute-now` — força execução de uma regra

## Variáveis de ambiente

Veja `.env.example`. As chaves obrigatórias:

- `META_SYSTEM_USER_TOKEN` — token do System User da agência
- `META_API_VERSION` — default `v25.0`
- `AUTH_USERNAME`, `AUTH_PASSWORD` — credenciais HTTP Basic
- `SECRET_KEY` — usado pelo CSRF middleware. Gere com
  `python -c "import secrets; print(secrets.token_hex(32))"`
- `DATABASE_URL` — local: `sqlite:///./data/data.db`. Produção: URL Postgres do Neon
- `ENV` — `development` ou `production`

---

# Deploy 100% gratuito (Render + Neon + cron-job.org)

## Arquitetura

```
┌────────────────┐      ┌──────────────────────────┐      ┌──────────────┐
│ cron-job.org   │─GET─▶│  Render (web service)    │─SQL─▶│ Neon (PG)    │
│  ping /health  │      │  FastAPI + APScheduler   │      │  free 0.5GB  │
│  a cada 14 min │      │  free 750h/mês           │      └──────────────┘
└────────────────┘      └──────────┬───────────────┘
                                   │ HTTPS
                                   ▼
                          ┌────────────────────┐
                          │   Meta Marketing   │
                          │   API v25.0        │
                          └────────────────────┘
```

**Custo: $0/mês.** Os 3 serviços têm planos gratuitos suficientes pro escopo
desse app (1 agência, poucos clientes, dezenas de regras).

## Caveats (importantes de entender antes)

- Render free **dorme em 15min sem requests** → primeiro acesso depois leva
  ~30s. O cron-job.org pingando `/health` a cada 14min mantém acordado.
- Sem o keep-alive, o **APScheduler não dispara** quando o app está dormindo.
- Neon **suspende o Postgres** após inatividade (poucos minutos). Wake é
  ~500ms-1s na primeira query.
- **Disco grátis do Render é efêmero** — por isso usamos Postgres externo
  no Neon em vez do SQLite local.

## Pré-requisitos
- Conta GitHub (https://github.com)
- 3 emails (ou reutilizar o mesmo nos 3 cadastros)

---

## Etapa 1 — Subir código para o GitHub

A maneira mais rápida no Windows é com **GitHub CLI**:

```powershell
# 1.1 Instalar gh
winget install GitHub.cli

# Feche e reabra o PowerShell pro PATH atualizar

# 1.2 Logar (abre o browser, OAuth)
gh auth login
# Escolha: GitHub.com  →  HTTPS  →  Login with a web browser
# Cole o código que aparece no terminal na página que abriu

# 1.3 Criar repo PRIVADO e dar push (rode dentro da pasta do projeto)
cd C:\Users\gomak\dev\meta-ads-automation
gh repo create meta-ads-automation --private --source=. --push
```

Vai retornar uma URL tipo `https://github.com/seu-user/meta-ads-automation`.
Guarde — vamos usar nas próximas etapas.

> **Importante:** repo **privado**. O `.env` está gitignored e não vai pro repo,
> mas mesmo assim manter o código privado é boa prática.

---

## Etapa 2 — Banco de dados (Neon)

### 2.1 — Criar conta
1. Abra https://console.neon.tech/signup
2. Clique **Continue with GitHub** (reutiliza login)
3. Aceite os termos

### 2.2 — Criar projeto
1. Vai abrir o wizard "Create a project"
2. Preencha:
   - **Project name**: `meta-ads-automation`
   - **Postgres version**: 16 (default)
   - **Region**: `AWS São Paulo (sa-east-1)` (mais próximo do Brasil)
3. Clique **Create project**

### 2.3 — Copiar connection string
1. Depois que o projeto criar, abre direto a tela "Connection Details"
2. Vai aparecer uma URL tipo:
   ```
   postgresql://username:password@ep-cool-name-12345.sa-east-1.aws.neon.tech/neondb?sslmode=require
   ```
3. **Copie ela inteira** — vai ser o `DATABASE_URL` no Render
4. Em "Connection pooling", deixe **OFF** (mais simples; ligue depois se precisar)

> Se aparecer `postgres://` em vez de `postgresql://`, tudo bem — nosso
> `database.py` corrige o prefixo automaticamente.

---

## Etapa 3 — Web app (Render)

### 3.1 — Criar conta
1. Abra https://dashboard.render.com/register
2. Clique **GitHub** (reutiliza login)
3. Aceite os permissionamentos do GitHub

### 3.2 — Criar Web Service
1. No dashboard, clique **+ New** (canto sup. dir.) → **Web Service**
2. **Connect a repository**:
   - Se o repo não aparecer, clique **Configure GitHub App** e dê acesso ao repo `meta-ads-automation`
   - Volte e selecione o repo

### 3.3 — Configurar o serviço
Preencha:
- **Name**: `meta-ads-automation` (ou outro; vai virar parte da URL)
- **Region**: `Oregon` ou `Frankfurt` (Render free não tem São Paulo; Oregon é o mais próximo da costa oeste americana)
- **Branch**: `main`
- **Runtime**: `Python 3` (auto-detectado)
- **Build Command**: `pip install -r requirements.txt`
- **Start Command**: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- **Instance Type**: **Free**

### 3.4 — Configurar variáveis de ambiente
Role para baixo, clique **Advanced**, depois **Add Environment Variable**.
Adicione **uma por uma**:

| Key | Value |
|---|---|
| `ENV` | `production` |
| `META_API_VERSION` | `v25.0` |
| `META_SYSTEM_USER_TOKEN` | seu token Meta (o atual) |
| `AUTH_USERNAME` | `admin` (ou outro) |
| `AUTH_PASSWORD` | senha forte (rotacione a `##Lazarus##293329!`) |
| `SECRET_KEY` | rode local: `python -c "import secrets; print(secrets.token_hex(32))"` e cole o output |
| `DATABASE_URL` | a connection string do Neon (etapa 2.3) |

### 3.5 — Configurar Health Check
Ainda em Advanced:
- **Health Check Path**: `/health`

### 3.6 — Deploy
Clique **Create Web Service** no fim da página.

Render vai começar o build (3-5 min). Acompanhe na aba **Logs**. Quando aparecer
`Uvicorn running on http://0.0.0.0:10000` o app está no ar.

A URL pública aparece no topo da página, algo tipo:
```
https://meta-ads-automation.onrender.com
```

Guarde essa URL.

---

## Etapa 4 — Keep-alive (cron-job.org)

Sem isso, o Render free dorme depois de 15min e o scheduler de regras não roda.

### 4.1 — Criar conta
1. Abra https://cron-job.org/en/signup/
2. Cadastre com email (sem GitHub aqui)
3. Confirme o email

### 4.2 — Criar o cronjob
1. No dashboard, clique **CREATE CRONJOB** (botão verde)
2. Preencha:
   - **Title**: `Keep-alive Meta Ads`
   - **URL**: `https://meta-ads-automation.onrender.com/health` (sua URL do Render + `/health`)
   - **Schedule**: clique em **Every** e configure:
     - **Every**: `14` minutes
   - **Notifications**: pode deixar tudo desligado (vai pingar a cada 14min, você não quer email a cada vez)
3. Clique **Create**

### 4.3 — Testar
Clique no cronjob criado e depois **Test run** — deve dar status 200 OK.

> **Por que 14 minutos e não 15?** Render dorme depois de 15min exatos. Um
> ping a cada 14min garante margem.

---

## Etapa 5 — Verificar tudo no ar

1. Abra a URL Render no browser
2. O browser pede login → use `AUTH_USERNAME` / `AUTH_PASSWORD` que você definiu
3. Vai abrir a home "Bem-vindo"
4. Vá em **Clientes → + Novo cliente** e cadastre o `[GMK] Testes Agenxs`:
   - Nome: `[GMK] Testes Agenxs`
   - Ad Account ID: `act_1372136953974164`
   - Page ID: pegue no Business Manager
5. Vá em **Nova campanha**, preencha 1 público e 1 criativo com URL de post existente
6. Submete e verifique que aparece em **Histórico**
7. Abre o link **Ads Manager** que aparece no resultado e confirma que a campanha foi criada lá (status PAUSED — não vai gastar dinheiro)

## Atualizando depois do primeiro deploy

Qualquer push no `main` do GitHub dispara um redeploy automático no Render:

```powershell
git add .
git commit -m "feat: ..."
git push
```

Render builda e troca o serviço sem downtime (free tier tem um pequeno gap).

## Backup do banco

```powershell
# Snapshot via psql (precisa instalar PostgreSQL client local; opcional)
# Ou: no painel Neon, "Backups" → criar branch a partir de um point-in-time
```

Neon mantém branches/snapshots por 7 dias no free tier.

---

# Alternativa paga ($5/mês): Railway Hobby

Se quiser uma stack mais simples (SQLite com Volume, sem orquestrar 3 serviços),
Railway Hobby plan é $5/mês. Mantém quase tudo igual mas substitui Render+Neon+cron
por 1 só serviço. Posso escrever esse guia também se mudar de ideia.

## Escopo completo

Veja [BRIEFING.md](BRIEFING.md).
