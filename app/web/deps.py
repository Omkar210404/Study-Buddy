"""Shared pieces for the routes: database session, clock, templates, small formatters."""

from collections.abc import Iterator
from datetime import date, datetime
from pathlib import Path
from typing import TypeVar

from fastapi import HTTPException, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.grounding import REASONS
from app.text import strip_markers

WEB_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=WEB_DIR / "templates")

T = TypeVar("T")


def interval_text(days: int) -> str:
    if days <= 0:
        return "today"
    if days == 1:
        return "1 day"
    if days < 60:
        return f"{days} days"
    return f"{days / 30:.1f} months"


def due_text(due: date, today: date) -> str:
    delta = (due - today).days
    if delta <= 0:
        return "due today"
    return "due tomorrow" if delta == 1 else f"due in {delta} days"


def plural(count: int, word: str, many: str | None = None) -> str:
    return f"{count} {word if count == 1 else (many or word + 's')}"


templates.env.filters["plain"] = strip_markers
templates.env.filters["interval"] = interval_text
templates.env.globals["plural"] = plural
templates.env.globals["due_text"] = due_text
templates.env.globals["reasons"] = REASONS


def get_session(request: Request) -> Iterator[Session]:
    """One session per request. Routes that change data commit before they build the response."""
    with request.app.state.session_factory() as session:
        yield session


def current_time(request: Request) -> datetime:
    return request.app.state.clock()


def get_or_404(session: Session, model: type[T], item_id: int) -> T:
    item = session.get(model, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="That page does not exist.")
    return item


def render(request: Request, name: str, status_code: int = 200, **context):
    state = request.app.state
    context.setdefault("active", "")
    context.update(settings=state.settings, provider=state.provider, provider_error=state.provider_error,
                   today=state.clock().date())
    return templates.TemplateResponse(request, name, context, status_code=status_code)
