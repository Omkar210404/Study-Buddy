"""Shared fixtures. No test may use the internet: an autouse fixture makes any attempt fail."""

import socket
from datetime import datetime

import pytest

from app import services
from app.storage.db import init_db, make_engine, make_session_factory
from app.storage.models import Card

_LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost", "testserver", None, ""}


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    real_connect = socket.socket.connect
    real_getaddrinfo = socket.getaddrinfo

    def guarded_connect(self, address, *args):
        host = address[0] if isinstance(address, tuple) else address
        if host not in _LOCAL_HOSTS:
            raise RuntimeError(f"a test tried to reach the network: {address!r}")
        return real_connect(self, address, *args)

    def guarded_getaddrinfo(host, *args, **kwargs):
        if host not in _LOCAL_HOSTS:
            raise RuntimeError(f"a test tried to resolve a network host: {host!r}")
        return real_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket, "getaddrinfo", guarded_getaddrinfo)


NOW = datetime(2026, 10, 12, 9, 0)
TODAY = NOW.date()


@pytest.fixture
def session(tmp_path):
    engine = make_engine(tmp_path / "test.db")
    init_db(engine)
    with make_session_factory(engine)() as db:
        yield db
    engine.dispose()


@pytest.fixture
def sample_deck(session):
    """The bundled sample notes, imported and turned into offline cards."""
    deck = services.load_sample_deck(session, NOW)
    session.commit()
    return deck


def add_card(session, deck, front="What is a router?", back="A device", created=NOW, **fields):
    """A card with a real one-sentence passage, for tests that do not care about generation."""
    passage = f"{front} {back} is the answer given in these notes."
    card = Card(deck_id=deck.id, kind="definition", origin="offline", front=front, back=back,
                supporting_quote=passage, source_passage=passage, quote_start=0, quote_end=len(passage),
                due_date=created.date(), created_at=created, updated_at=created, **fields)
    session.add(card)
    session.flush()
    return card
