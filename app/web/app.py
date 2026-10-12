"""Application factory."""

from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import datetime
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import __version__
from app.config import Settings, get_settings
from app.errors import ConfigError, StudyBuddyError
from app.llm.base import LLMProvider
from app.llm.factory import build_provider
from app.storage.db import init_db, make_engine, make_session_factory
from app.web import routes_decks, routes_pages, routes_study
from app.web.deps import WEB_DIR, render

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def create_app(settings: Settings | None = None, provider: LLMProvider | None = None,
               clock: Callable[[], datetime] | None = None) -> FastAPI:
    settings = settings or get_settings()
    engine = make_engine(settings.database_path)
    init_db(engine)

    provider_error: str | None = None
    if provider is None:
        try:
            provider = build_provider(settings)
        except ConfigError as exc:
            provider_error = str(exc)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        if provider is not None:
            await provider.aclose()
        engine.dispose()

    app = FastAPI(title="Study Buddy", version=__version__, lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings
    app.state.session_factory = make_session_factory(engine)
    app.state.provider = provider
    app.state.provider_error = provider_error
    app.state.clock = clock or datetime.now

    @app.middleware("http")
    async def same_origin_only(request: Request, call_next):
        """Refuse state-changing requests that come from another site.

        The app has no login, so a page on any other site open in the same browser could
        otherwise post to http://127.0.0.1:8000 and delete a deck.
        """
        if request.method in UNSAFE_METHODS:
            origin = request.headers.get("origin")
            fetch_site = request.headers.get("sec-fetch-site")
            cross_origin = origin is not None and urlparse(origin).netloc != request.headers.get("host")
            if cross_origin or fetch_site == "cross-site":
                return PlainTextResponse("Cross-site requests are not allowed.", status_code=403)
        return await call_next(request)

    @app.exception_handler(StudyBuddyError)
    async def study_buddy_error(request: Request, exc: StudyBuddyError):
        return render(request, "error.html", status_code=400, title="That did not work", message=str(exc))

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        title = "Not found" if exc.status_code == 404 else "Something went wrong"
        return render(request, "error.html", status_code=exc.status_code, title=title, message=str(exc.detail))

    app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")
    app.include_router(routes_pages.router)
    app.include_router(routes_decks.router)
    app.include_router(routes_study.router)
    return app
