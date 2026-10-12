"""Today, progress, privacy, the sample-deck loader and the health check."""

from datetime import datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app import services
from app.storage.stats import progress
from app.web.deps import current_time, get_session, render

router = APIRouter()


@router.get("/")
def today_page(request: Request, session: Session = Depends(get_session),
               now: datetime = Depends(current_time)):
    data = progress(session, now.date(), request.app.state.settings.new_cards_per_day)
    return render(request, "today.html", active="today", progress=data)


@router.get("/progress")
def progress_page(request: Request, session: Session = Depends(get_session),
                  now: datetime = Depends(current_time)):
    data = progress(session, now.date(), request.app.state.settings.new_cards_per_day)
    labelled = {index for index, day in enumerate(data.days)
                if day.count and (day.count == data.busiest_day or index == len(data.days) - 1)}
    return render(request, "progress.html", active="progress", progress=data, labelled=labelled)


@router.get("/privacy")
def privacy_page(request: Request):
    return render(request, "privacy.html", active="privacy")


@router.post("/demo/load-sample")
def load_sample(session: Session = Depends(get_session), now: datetime = Depends(current_time)):
    deck = services.load_sample_deck(session, now)
    session.commit()
    return RedirectResponse(f"/decks/{deck.id}", status_code=303)


@router.get("/health")
def health():
    return {"status": "ok"}
