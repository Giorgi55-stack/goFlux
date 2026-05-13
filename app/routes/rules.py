import re
from html import escape
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.auth import CurrentUser
from app.database import get_session
from app.models import Client, Rule, RuleType, TargetScope, TriggerType
from app.services import rule_executor

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

WEEKDAY_OPTIONS: list[tuple[str, str]] = [
    ("mon", "Seg"),
    ("tue", "Ter"),
    ("wed", "Qua"),
    ("thu", "Qui"),
    ("fri", "Sex"),
    ("sat", "Sáb"),
    ("sun", "Dom"),
]

TYPE_LABELS = {
    RuleType.pause: "Pausar",
    RuleType.resume: "Reativar",
    RuleType.adjust_budget: "Ajustar orçamento",
}

SCOPE_LABELS = {
    TargetScope.all_campaigns: "Todas as campanhas",
    TargetScope.created_by_app_only: "Só criadas pelo app",
    TargetScope.specific_campaigns: "Campanhas específicas",
}


def _errors_html(errors: list[str]) -> str:
    items = "".join(f"<div>• {escape(e)}</div>" for e in errors)
    return (
        '<div class="bg-red-50 border border-red-200 text-red-800 '
        f'px-4 py-2 rounded text-sm space-y-1">{items}</div>'
    )


@router.get("/rules", response_class=HTMLResponse)
def list_rules(
    request: Request,
    user: CurrentUser,
    session: Annotated[Session, Depends(get_session)],
):
    rules = list(
        session.exec(select(Rule).order_by(Rule.created_at.desc()))  # type: ignore[attr-defined]
    )
    clients = {c.id: c for c in session.exec(select(Client)).all()}
    return templates.TemplateResponse(
        request,
        "rules_list.html",
        {
            "rules": rules,
            "clients": clients,
            "type_labels": TYPE_LABELS,
            "scope_labels": SCOPE_LABELS,
        },
    )


@router.get("/rules/new", response_class=HTMLResponse)
def new_rule_form(
    request: Request,
    user: CurrentUser,
    session: Annotated[Session, Depends(get_session)],
):
    clients = session.exec(select(Client).order_by(Client.name)).all()
    return templates.TemplateResponse(
        request,
        "rules_new.html",
        {"clients": clients, "weekday_options": WEEKDAY_OPTIONS},
    )


@router.post("/rules")
async def create_rule(
    request: Request,
    user: CurrentUser,
    session: Annotated[Session, Depends(get_session)],
):
    form = await request.form()
    errors: list[str] = []

    name = str(form.get("name", "")).strip()
    if not name:
        errors.append("Nome é obrigatório")

    raw_client = str(form.get("client_id", "")).strip()
    client_id: Optional[int] = None
    if raw_client:
        try:
            client_id = int(raw_client)
            if not session.get(Client, client_id):
                errors.append("Cliente não encontrado")
        except ValueError:
            errors.append("Cliente inválido")

    try:
        rule_type = RuleType(str(form.get("type", "")).strip())
    except ValueError:
        errors.append("Tipo de regra inválido")
        rule_type = RuleType.pause

    try:
        trigger_type = TriggerType(str(form.get("trigger_type", "")).strip())
    except ValueError:
        errors.append("Tipo de trigger inválido")
        trigger_type = TriggerType.day_of_week

    trigger_config: dict[str, Any] = {}
    if trigger_type == TriggerType.day_of_week:
        days = form.getlist("days")
        valid = {k for k, _ in WEEKDAY_OPTIONS}
        clean = [str(d) for d in days if str(d) in valid]
        if not clean:
            errors.append("Selecione pelo menos 1 dia da semana")
        trigger_config["days"] = clean
    else:
        date_str = str(form.get("specific_date", "")).strip()
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
            errors.append("Data inválida (use YYYY-MM-DD)")
        trigger_config["date"] = date_str

    action_config: dict[str, Any] = {}
    if rule_type == RuleType.adjust_budget:
        kind = str(form.get("budget_value_kind", "")).strip()
        try:
            value = float(
                str(form.get("budget_value", "0")).replace(",", ".")
            )
        except ValueError:
            errors.append("Valor do orçamento inválido")
            value = 0.0
        if value <= 0:
            errors.append("Valor do orçamento deve ser maior que zero")
        if kind == "cents":
            action_config["value_cents"] = int(value)
        elif kind == "percent":
            action_config["value_pct"] = value
        else:
            errors.append("Modo de ajuste de orçamento inválido")

    execution_time = str(form.get("execution_time", "")).strip()
    if not re.match(r"^\d{2}:\d{2}$", execution_time):
        errors.append("Horário inválido (use HH:MM)")

    try:
        target_scope = TargetScope(
            str(form.get("target_scope", "")).strip()
        )
    except ValueError:
        errors.append("Escopo inválido")
        target_scope = TargetScope.created_by_app_only

    target_campaign_ids: Optional[list[str]] = None
    if target_scope == TargetScope.specific_campaigns:
        raw = str(form.get("target_campaign_ids", "")).strip()
        ids = [s.strip() for s in re.split(r"[,\s\n]+", raw) if s.strip()]
        if not ids:
            errors.append(
                "Informe ao menos 1 meta_campaign_id para escopo específico"
            )
        target_campaign_ids = ids

    active = form.get("active") in ("on", "true", "1")

    if errors:
        return HTMLResponse(_errors_html(errors), status_code=400)

    rule = Rule(
        client_id=client_id,
        name=name,
        type=rule_type,
        trigger_type=trigger_type,
        trigger_config=trigger_config,
        action_config=action_config,
        target_scope=target_scope,
        target_campaign_ids=target_campaign_ids,
        execution_time=execution_time,
        active=active,
    )
    session.add(rule)
    session.commit()

    return Response(status_code=204, headers={"HX-Redirect": "/rules"})


@router.post("/api/rules/{rule_id}/execute-now")
def execute_rule_now(
    rule_id: int,
    request: Request,
    user: CurrentUser,
    session: Annotated[Session, Depends(get_session)],
):
    rule = session.get(Rule, rule_id)
    if not rule:
        return JSONResponse({"error": "rule not found"}, status_code=404)

    logs = rule_executor.execute_rule(session, rule, force=True)
    n_errors = sum(1 for log in logs if log.result.value == "error")
    summary = {
        "ok": True,
        "rule_id": rule.id,
        "rule_name": rule.name,
        "logs": len(logs),
        "errors": n_errors,
    }

    if request.headers.get("HX-Request"):
        css = "text-green-600" if n_errors == 0 else "text-red-600"
        msg = f"✓ {len(logs)} log(s), {n_errors} erro(s)"
        return HTMLResponse(
            f'<span class="{css} text-xs ml-2">{msg}</span>'
        )
    return summary
