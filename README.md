# Meta Ads Automation

Aplicação web para automatizar criação e gerenciamento de campanhas
no Meta Ads (Facebook + Instagram) para múltiplos clientes de uma agência.

## Stack

- Python 3.12+
- FastAPI + SQLModel + SQLite
- APScheduler (cron interno)
- facebook-business SDK
- Jinja2 + HTMX + Tailwind (via CDN)

## Setup local

```powershell
# 1. Crie e ative venv
python -m venv venv
.\venv\Scripts\Activate.ps1

# 2. Instale dependências
pip install -r requirements.txt

# 3. Configure variáveis de ambiente
copy .env.example .env
# Edite .env com suas credenciais

# 4. Rode em dev
uvicorn app.main:app --reload
```

Acesse http://localhost:8000

## Deploy

Railway, plano Hobby ($5/mês), com Volume montado em `/app/data` para
persistir o SQLite entre restarts.

## Escopo

Veja [BRIEFING.md](BRIEFING.md).
