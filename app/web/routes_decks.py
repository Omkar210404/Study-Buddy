"""Decks, imported notes, card generation, card editing and export."""

from datetime import datetime
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app import services
from app.errors import ConfigError, LLMError, StudyBuddyError
from app.export.anki_csv import ExportCard, deck_to_anki_csv
from app.ingestion.extract import from_file, from_pasted
from app.scheduler.queue import build_queue
from app.storage.models import Card, Deck, GenerationRun, Source, Tag, card_tags
from app.web.deps import current_time, get_or_404, get_session, render

router = APIRouter()


def find_cards(session: Session, deck_id: int, q: str = "", tag: str = "", kind: str = "") -> list[Card]:
    query = select(Card).where(Card.deck_id == deck_id).order_by(Card.id)
    if q.strip():
        pattern = f"%{q.strip().lower()}%"
        query = query.where(or_(func.lower(Card.front).like(pattern), func.lower(Card.back).like(pattern),
                                func.lower(Card.supporting_quote).like(pattern)))
    if tag:
        query = query.where(Card.tags.any(Tag.name == tag))
    if kind:
        query = query.where(Card.kind == kind)
    return list(session.scalars(query))


def deck_tags(session: Session, deck_id: int) -> list[tuple[str, int]]:
    rows = session.execute(
        select(Tag.name, func.count()).join(card_tags, card_tags.c.tag_id == Tag.id)
        .join(Card, Card.id == card_tags.c.card_id).where(Card.deck_id == deck_id)
        .group_by(Tag.name).order_by(Tag.name)
    ).all()
    return [(name, count) for name, count in rows]


# --- decks ------------------------------------------------------------------------------------

@router.get("/decks")
def decks_page(request: Request, session: Session = Depends(get_session),
               now: datetime = Depends(current_time)):
    per_day = request.app.state.settings.new_cards_per_day
    decks = [(deck, len(deck.cards), len(build_queue(session, now.date(), per_day, deck.id)))
             for deck in session.scalars(select(Deck).order_by(Deck.name))]
    return render(request, "decks.html", active="decks", decks=decks)


@router.post("/decks")
def create_deck(name: str = Form(""), description: str = Form(""),
                session: Session = Depends(get_session), now: datetime = Depends(current_time)):
    deck = services.create_deck(session, name, description, now)
    session.commit()
    return RedirectResponse(f"/decks/{deck.id}", status_code=303)


@router.get("/decks/{deck_id}")
def deck_page(request: Request, deck_id: int, q: str = "", tag: str = "", kind: str = "",
              session: Session = Depends(get_session), now: datetime = Depends(current_time)):
    deck = get_or_404(session, Deck, deck_id)
    due = len(build_queue(session, now.date(), request.app.state.settings.new_cards_per_day, deck.id))
    return render(request, "deck.html", active="decks", deck=deck, due=due,
                  cards=find_cards(session, deck.id, q, tag, kind), tags=deck_tags(session, deck.id),
                  q=q, tag=tag, kind=kind)


@router.get("/decks/{deck_id}/cards")
def deck_cards(request: Request, deck_id: int, q: str = "", tag: str = "", kind: str = "",
               session: Session = Depends(get_session)):
    deck = get_or_404(session, Deck, deck_id)
    return render(request, "_card_list.html", deck=deck, cards=find_cards(session, deck.id, q, tag, kind),
                  q=q, tag=tag, kind=kind)


@router.post("/decks/{deck_id}/edit")
def edit_deck(deck_id: int, name: str = Form(""), description: str = Form(""),
              session: Session = Depends(get_session)):
    deck = get_or_404(session, Deck, deck_id)
    name = " ".join(name.split())
    if not name:
        raise StudyBuddyError("Give the deck a name.")
    deck.name, deck.description = name[:120], description.strip()
    session.commit()
    return RedirectResponse(f"/decks/{deck.id}", status_code=303)


@router.post("/decks/{deck_id}/delete")
def delete_deck(deck_id: int, session: Session = Depends(get_session)):
    session.delete(get_or_404(session, Deck, deck_id))
    session.commit()
    return RedirectResponse("/decks", status_code=303)


@router.get("/decks/{deck_id}/export.csv")
def export_deck(deck_id: int, session: Session = Depends(get_session)):
    deck = get_or_404(session, Deck, deck_id)
    cards = [ExportCard(card.front, card.back, card.supporting_quote, tuple(card.tag_names))
             for card in deck.cards]
    filename = quote("-".join(deck.name.lower().split()) or "deck") + "-anki.csv"
    return Response(deck_to_anki_csv(deck.name, cards), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"})


# --- notes ------------------------------------------------------------------------------------

@router.get("/decks/{deck_id}/import")
def import_page(request: Request, deck_id: int, session: Session = Depends(get_session)):
    return render(request, "import.html", active="decks", deck=get_or_404(session, Deck, deck_id),
                  error=None, title="", text="")


@router.post("/decks/{deck_id}/sources")
async def import_notes(request: Request, deck_id: int, title: str = Form(""), text: str = Form(""),
                       file: UploadFile | None = File(None), session: Session = Depends(get_session),
                       now: datetime = Depends(current_time)):
    deck = get_or_404(session, Deck, deck_id)
    max_bytes = request.app.state.settings.max_upload_mb * 1024 * 1024
    try:
        if file is not None and file.filename:
            data = await file.read(max_bytes + 1)
            extracted = from_file(file.filename, data, max_bytes)
            filename = file.filename
        else:
            extracted, filename = from_pasted(text), None
        source = services.import_source(session, deck, extracted, title, filename, now)
    except StudyBuddyError as exc:
        session.rollback()
        return render(request, "import.html", status_code=400, active="decks", deck=deck,
                      error=str(exc), title=title, text=text)
    session.commit()
    return RedirectResponse(f"/sources/{source.id}", status_code=303)


@router.get("/sources/{source_id}")
def source_page(request: Request, source_id: int, session: Session = Depends(get_session)):
    source = get_or_404(session, Source, source_id)
    runs = list(session.scalars(select(GenerationRun).where(GenerationRun.source_id == source.id)
                                .order_by(GenerationRun.id.desc())))
    return render(request, "source.html", active="decks", source=source, deck=source.deck, runs=runs,
                  error=None)


@router.post("/sources/{source_id}/delete")
def delete_source(source_id: int, session: Session = Depends(get_session)):
    source = get_or_404(session, Source, source_id)
    deck_id = source.deck_id
    session.delete(source)
    session.commit()
    return RedirectResponse(f"/decks/{deck_id}", status_code=303)


@router.post("/sources/{source_id}/generate")
async def generate(request: Request, source_id: int, mode: str = Form("offline"),
                   session: Session = Depends(get_session), now: datetime = Depends(current_time)):
    source = get_or_404(session, Source, source_id)
    state = request.app.state
    try:
        if mode == "llm":
            if state.provider is None:
                raise ConfigError(state.provider_error or "LLM mode is off. Set LLM_PROVIDER to turn it on.")
            run = await services.generate_llm_cards(session, source, state.provider, state.settings, now)
        else:
            run = services.generate_offline_cards(session, source, now)
    except (ConfigError, LLMError) as exc:
        session.rollback()
        return render(request, "source.html", status_code=400, active="decks", source=source,
                      deck=source.deck, runs=[], error=f"No cards were generated. {exc}")
    session.commit()
    return RedirectResponse(f"/runs/{run.id}", status_code=303)


@router.get("/runs/{run_id}")
def run_page(request: Request, run_id: int, session: Session = Depends(get_session)):
    run = get_or_404(session, GenerationRun, run_id)
    return render(request, "run.html", active="decks", run=run, deck=get_or_404(session, Deck, run.deck_id))


# --- cards ------------------------------------------------------------------------------------

@router.get("/cards/{card_id}")
def card_item(request: Request, card_id: int, session: Session = Depends(get_session)):
    return render(request, "_card_item.html", card=get_or_404(session, Card, card_id))


@router.get("/cards/{card_id}/edit")
def card_edit_form(request: Request, card_id: int, session: Session = Depends(get_session)):
    card = get_or_404(session, Card, card_id)
    return render(request, "_card_edit.html", card=card, error=None, front=card.front, back=card.back,
                  quote=card.supporting_quote, tags=", ".join(card.tag_names))


@router.put("/cards/{card_id}")
def card_update(request: Request, card_id: int, front: str = Form(""), back: str = Form(""),
                quote: str = Form(""), tags: str = Form(""), session: Session = Depends(get_session),
                now: datetime = Depends(current_time)):
    card = get_or_404(session, Card, card_id)
    try:
        services.update_card(session, card, front, back, quote, tags, now)
    except services.CardEditError as exc:
        session.rollback()
        # 200 on purpose: HTMX only swaps successful responses, and the form must come back.
        return render(request, "_card_edit.html", card=card, error=str(exc),
                      front=front, back=back, quote=quote, tags=tags)
    session.commit()
    return render(request, "_card_item.html", card=card)


@router.delete("/cards/{card_id}")
def card_delete(card_id: int, session: Session = Depends(get_session)):
    session.delete(get_or_404(session, Card, card_id))
    session.commit()
    return HTMLResponse("")
