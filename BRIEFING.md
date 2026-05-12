# Briefing — Meta Ads Automation Platform

## Contexto

Construir uma aplicação web que automatiza criação e gerenciamento de campanhas no Meta Ads (Facebook + Instagram) para múltiplos clientes de uma agência. Substitui trabalho manual no Ads Manager.

## Usuário-alvo

Gestor de tráfego que cuida de múltiplos clientes. Não é desenvolvedor — vai usar a aplicação pela interface web.

## Funcionalidades obrigatórias (MVP)

### 1. Criação de campanhas em massa
- Formulário web onde o usuário escolhe: cliente, objetivo, orçamento diário, públicos-alvo (3 a 5), criativos (3 a 10)
- Cria automaticamente: 1 campaign + N ad sets (um por público) + M ads (um por criativo × público)
- Tudo criado com status PAUSED para revisão manual antes de subir
- Naming convention: `{cliente}_{objetivo}_{mes}{ano}_{publico}_{criativo}`

### 2. Dois tipos de criativo suportados
- **Dark post**: criativo novo criado a partir de input (imagem/vídeo + copy + headline + CTA). Cria unpublished page post via `/{page_id}/feed` com `published: false`, pega o post_id retornado e usa no `object_story_id` do AdCreative
- **Post existente**: usuário cola um link de post já publicado (Facebook ou Instagram). Sistema extrai o post_id do link e usa direto no `object_story_id`

### 3. Regras de pausa/orçamento por cliente
- Cada cliente pode ter múltiplas regras configuráveis
- Tipos de regra:
  - Pausar campanhas em dias específicos (ex: sábado e domingo)
  - Reduzir orçamento em % em dias específicos
  - Reativar em dias específicos
- Cron interno (APScheduler) roda de hora em hora, lê as regras ativas e executa
- IMPORTANTE: trabalha com daily budget, não lifetime budget

### 4. Multi-cliente
- Cadastro de clientes com: nome, ad_account_id, page_id, instagram_actor_id (opcional), pixel_id (opcional), timezone, currency
- Cada cliente tem seu próprio System User Token? NÃO — usa um único token de System User da agência que tem acesso a todas as contas de anúncios dos clientes

### 5. Histórico e logs
- Toda criação de campanha registrada no banco
- Toda execução de regra registrada
- Página de histórico simples na interface

## Stack técnica

- **Linguagem**: Python 3.12+
- **Framework web**: FastAPI
- **Banco**: SQLite (suficiente pra essa escala)
- **ORM**: SQLModel (combina SQLAlchemy + Pydantic, integra bem com FastAPI)
- **Scheduler**: APScheduler (cron interno, sem precisar de cron do Linux)
- **SDK Meta**: `facebook-business` (SDK oficial Python)
- **Templates**: Jinja2 (renderização das páginas HTML)
- **Frontend**: HTML + HTMX (sem React, sem build step — mantém simples)
- **CSS**: Tailwind via CDN (sem build) ou Pico CSS (classless)
- **Deploy**: Railway (free tier inicialmente, depois Hobby $5/mês)
- **Versionamento**: Git + GitHub

## Estrutura de pastas sugerida

```
meta-ads-automation/
├── app/
│   ├── __init__.py
│   ├── main.py                    # FastAPI app + rotas
│   ├── config.py                  # Pydantic settings (lê .env)
│   ├── database.py                # SQLModel engine + session
│   ├── models/
│   │   ├── __init__.py
│   │   ├── client.py              # Cliente
│   │   ├── campaign.py            # Campaign histórico
│   │   ├── rule.py                # Regras de pausa/orçamento
│   │   └── execution_log.py       # Logs de execução de regras
│   ├── services/
│   │   ├── __init__.py
│   │   ├── meta_api.py            # Wrapper do facebook-business SDK
│   │   ├── campaign_builder.py    # Lógica de criar campaign+adset+ad
│   │   ├── dark_post.py           # Cria unpublished page post
│   │   ├── link_parser.py         # Extrai post_id de URL FB/IG
│   │   └── rule_executor.py       # Executa as regras agendadas
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── clients.py             # CRUD clientes
│   │   ├── campaigns.py           # Criar campanhas
│   │   ├── rules.py               # CRUD regras
│   │   └── history.py             # Histórico
│   ├── scheduler.py               # APScheduler setup
│   └── templates/                 # Jinja2 templates HTML
│       ├── base.html
│       ├── index.html             # Home/dashboard
│       ├── clients.html
│       ├── new_campaign.html
│       ├── rules.html
│       └── history.html
├── tests/
│   └── test_meta_api.py
├── .env.example
├── .gitignore
├── requirements.txt
├── README.md
└── Procfile                       # Pra deploy no Railway
```

## Variáveis de ambiente (.env.example)

```
META_APP_ID=
META_APP_SECRET=
META_SYSTEM_USER_TOKEN=
META_API_VERSION=v25.0
DATABASE_URL=sqlite:///./data.db
SECRET_KEY=mude-isso-em-producao
ENV=development
```

## Endpoints HTTP (rotas FastAPI)

### Públicas (interface web)
- `GET /` — Dashboard com resumo (campanhas ativas por cliente, próximas regras a executar)
- `GET /clients` — Lista clientes
- `GET /clients/new` — Formulário novo cliente
- `POST /clients` — Criar cliente
- `GET /campaigns/new` — Formulário criação de campanha
- `POST /campaigns` — Cria campanhas no Meta (retorna status)
- `GET /rules` — Lista regras
- `GET /rules/new` — Formulário nova regra
- `POST /rules` — Criar regra
- `GET /history` — Histórico de criações e execuções

### API (JSON)
- `POST /api/test-token` — Valida o System User Token e lista ad accounts acessíveis
- `GET /api/clients/{client_id}/audiences` — Lista custom audiences do cliente (busca na Meta)
- `POST /api/rules/{rule_id}/execute-now` — Executa regra manualmente

## Schema do banco

### Client
- id (PK)
- name
- ad_account_id (formato `act_XXXXXX`)
- page_id
- instagram_actor_id (nullable)
- pixel_id (nullable)
- timezone (default 'America/Sao_Paulo')
- currency (default 'BRL')
- created_at, updated_at

### Campaign (histórico do que foi criado)
- id (PK)
- client_id (FK)
- meta_campaign_id (ID retornado pela Meta)
- name
- objective
- daily_budget
- status (paused/active/archived)
- created_by_app (bool, marca campanhas criadas pela aplicação)
- ad_set_ids (JSON array)
- ad_ids (JSON array)
- created_at

### Rule
- id (PK)
- client_id (FK, nullable — null significa "todos os clientes")
- name
- type (pause | resume | adjust_budget)
- trigger_type (day_of_week | specific_date | metric)
- trigger_config (JSON — depende do tipo, ex: `{"days": ["sat", "sun"]}` ou `{"metric": "cpa", "operator": ">", "value": 50}`)
- action_config (JSON — ex: `{"action": "pause"}` ou `{"action": "set_budget_pct", "value": 50}`)
- target_scope (all_campaigns | created_by_app_only | specific_campaigns)
- target_campaign_ids (JSON array, nullable)
- execution_time (string HH:MM, hora do dia que executa)
- active (bool)
- created_at, updated_at

### ExecutionLog
- id (PK)
- rule_id (FK, nullable — null se foi criação manual)
- campaign_id (FK, nullable)
- action (string descritivo)
- result (success | error | partial)
- details (JSON com mais info)
- executed_at

## Fluxo de criação de campanha (detalhado)

1. Usuário acessa `/campaigns/new`
2. Seleciona cliente (dropdown carregado do banco)
3. Escolhe objetivo (mapping de objetivos da Meta v25: OUTCOME_LEADS, OUTCOME_TRAFFIC, OUTCOME_ENGAGEMENT, OUTCOME_SALES, OUTCOME_AWARENESS)
4. Define orçamento diário (CBO no nível da campaign)
5. Adiciona públicos (1 a 5) — pode ser:
   - Custom audience ID (busca os disponíveis via API)
   - Lookalike audience ID
   - Targeting básico (idade, gênero, localização, interesses)
6. Adiciona criativos (3 a 10) — para cada um:
   - Tipo: dark_post ou link_existente
   - Se dark_post: upload de imagem/vídeo + primary_text + headline + description + cta_type + link
   - Se link_existente: cola URL → backend extrai post_id
7. Submete o formulário
8. Backend:
   - Cria 1 Campaign (status PAUSED)
   - Para cada público: cria 1 AdSet (status PAUSED) ligado à campaign
   - Para cada criativo:
     - Se dark_post: cria unpublished page post, pega post_id
     - Se link_existente: usa post_id já extraído
     - Cria AdCreative com object_story_id = post_id
     - Para cada AdSet (público): cria 1 Ad com esse criativo (status PAUSED)
9. Salva tudo no banco (tabela Campaign)
10. Mostra resultado: "Criadas 1 campanha + N adsets + M ads. Todos pausados. Revisa no Ads Manager: [link]"

## Tratamento de erros importantes

- Token expirado/inválido → mostra erro claro com link pra atualizar
- Ad account sem permissão → erro específico
- Custom audience inválida → erro específico
- Rate limit da Meta → backoff exponencial automático
- Imagem/vídeo inválido → validação antes de subir

## Segurança

- System User Token nunca exposto no frontend
- Autenticação simples na interface web (HTTP Basic Auth ou senha única no .env é suficiente — é ferramenta interna)
- HTTPS obrigatório em produção (Railway dá automaticamente)
- CSRF protection nos forms

## Versão inicial vs versão futura

### MVP (essa primeira versão)
- CRUD de clientes
- Criação de campanha com dark post + post existente
- Regras simples por dia da semana (pausar/reativar)
- Histórico básico
- Deploy no Railway

### Futuro (depois do MVP funcionar)
- Regras baseadas em métricas (CPA, ROAS, CTR)
- Notificações via WhatsApp quando regras executam
- Dashboard com gráficos de performance
- Bulk edit de campanhas existentes
- Geração de criativos com IA (DALL-E ou similar)
- Integração com Notion pra puxar criativos de um database

## Como começar (ordem sugerida pro Claude Code)

1. Setup do projeto: estrutura de pastas, requirements.txt, .env.example, .gitignore, README inicial
2. Configuração básica: config.py com Pydantic Settings, database.py com engine SQLModel
3. Models: criar todas as classes (Client, Campaign, Rule, ExecutionLog)
4. Endpoint de health check + endpoint de teste de token (pra validar acesso à Meta)
5. CRUD de clientes (rotas + templates HTML)
6. Wrapper do Meta API (services/meta_api.py)
7. Campaign builder (services/campaign_builder.py)
8. Rota de criação de campanha + template
9. Regras + scheduler
10. Deploy Railway

## Referências oficiais

- Meta Marketing API v25: https://developers.facebook.com/docs/marketing-apis/
- Python SDK: https://github.com/facebook/facebook-python-business-sdk
- FastAPI: https://fastapi.tiangolo.com
- SQLModel: https://sqlmodel.tiangolo.com
- APScheduler: https://apscheduler.readthedocs.io

## Decisão sobre interface

Interface deve ser simples e funcional, não bonita. HTMX permite interatividade (validação em tempo real, atualização parcial da página) sem precisar escrever JavaScript. Tailwind via CDN dá estilo decente sem build step.

Não usar React/Vue/Next nesse momento — overkill pro escopo. Se um dia precisar evoluir, refatora.
