"""FastAPI gateway: create interviews, accept one WebSocket per interview, serve the client."""

from __future__ import annotations

import contextlib
import time
from collections import defaultdict, deque
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

import structlog
from fastapi import FastAPI, HTTPException, Request, WebSocket
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from starlette.types import Scope
from ulid import ULID

from acme_agent.bootstrap import AppContainer
from acme_agent.storage.json_repo import validate_conversation_id
from acme_agent.storage.repository import InvalidConversationIdError
from acme_agent.web.frames import FrameTooLargeError
from acme_agent.web.protocol import CLOSE_DUPLICATE, CLOSE_POLICY, CLOSE_TOO_BIG
from acme_agent.web.session import InterviewSession

STATIC_DIR = Path(__file__).parent / "static"
RATE_LIMIT_PER_MINUTE = 5
RATE_WINDOW_SECONDS = 60.0
ISSUED_TTL_SECONDS = 600.0
ISSUED_CAP = 1000

log = structlog.get_logger(__name__)


class InterviewRunner(Protocol):
    """What the gateway needs from a session: run until the interview or socket ends."""

    async def run(self) -> None: ...


class SessionFactory(Protocol):
    """Builds the runner for one accepted socket (seam for `InterviewSession`)."""

    def __call__(
        self, ws: WebSocket, conversation_id: str, container: AppContainer
    ) -> InterviewRunner: ...


class SlidingWindowLimiter:
    """In-memory per-key sliding window; not shared across processes (PoC)."""

    def __init__(
        self,
        limit: int = RATE_LIMIT_PER_MINUTE,
        window: float = RATE_WINDOW_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._limit = limit
        self._window = window
        self._clock = clock
        self._hits: defaultdict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = self._clock()
        hits = self._hits[key]
        while hits and now - hits[0] >= self._window:
            hits.popleft()
        if len(hits) >= self._limit:
            return False
        hits.append(now)
        if len(self._hits) > 1024:  # drop idle keys so the map cannot grow without bound
            for k in [k for k, v in self._hits.items() if not v or now - v[-1] >= self._window]:
                del self._hits[k]
        return True


class IssuedIds:
    """Bounded in-memory registry of interview ids handed out and not yet used (PoC)."""

    def __init__(
        self,
        ttl: float = ISSUED_TTL_SECONDS,
        cap: int = ISSUED_CAP,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl = ttl
        self._cap = cap
        self._clock = clock
        self._ids: dict[str, float] = {}  # id -> expiry; insertion order is issue order

    def _prune(self, now: float) -> None:
        for k in [k for k, exp in self._ids.items() if exp <= now]:
            del self._ids[k]
        while len(self._ids) > self._cap:
            del self._ids[next(iter(self._ids))]

    def issue(self, conversation_id: str) -> None:
        now = self._clock()
        self._ids[conversation_id] = now + self._ttl
        self._prune(now)

    def consume(self, conversation_id: str) -> bool:
        """True once for an issued, unexpired id."""
        now = self._clock()
        self._prune(now)
        return self._ids.pop(conversation_id, None) is not None


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


class RevalidatingStaticFiles(StaticFiles):
    """Static files that browsers must revalidate on every load (ETag 304 still applies)."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


def create_app(
    container: AppContainer,
    *,
    session_factory: SessionFactory | None = None,
    rate_limiter: SlidingWindowLimiter | None = None,
    issued_ids: IssuedIds | None = None,
) -> FastAPI:
    app = FastAPI(title="Acme Agent", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.container = container
    app.state.session_factory = session_factory or InterviewSession
    app.state.rate_limiter = rate_limiter or SlidingWindowLimiter()
    app.state.issued_ids = issued_ids or IssuedIds()
    app.state.active_sockets = set()
    allowed_origins = set(container.settings.allowed_origins)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/interviews")
    async def create_interview(request: Request) -> dict[str, str]:
        if not app.state.rate_limiter.allow(_client_ip(request)):
            raise HTTPException(status_code=429, detail="Too many interviews, try again shortly.")
        conversation_id = f"c_{ULID()}"
        app.state.issued_ids.issue(conversation_id)
        scheme = "wss" if request.url.scheme == "https" else "ws"
        ws_url = f"{scheme}://{request.url.netloc}/ws/interview/{conversation_id}"
        return {"conversation_id": conversation_id, "ws_url": ws_url}

    @app.websocket("/ws/interview/{conversation_id}")
    async def interview_socket(ws: WebSocket, conversation_id: str) -> None:
        # Accept first so browsers see the close code instead of a bare 1006.
        await ws.accept()
        origin = ws.headers.get("origin")
        if origin is None or origin not in allowed_origins:
            await ws.close(code=CLOSE_POLICY, reason="origin not allowed")
            return
        try:
            validate_conversation_id(conversation_id)
        except InvalidConversationIdError:
            await ws.close(code=CLOSE_POLICY, reason="invalid conversation id")
            return
        active: set[str] = app.state.active_sockets
        if conversation_id in active:
            await ws.close(code=CLOSE_DUPLICATE, reason="interview already connected")
            return
        if not app.state.issued_ids.consume(conversation_id):
            await ws.close(code=CLOSE_POLICY, reason="unknown or used interview id")
            return
        active.add(conversation_id)
        try:
            runner = app.state.session_factory(ws, conversation_id, container)
            await runner.run()
        except FrameTooLargeError:
            await _close_quietly(ws, CLOSE_TOO_BIG)
        finally:
            active.discard(conversation_id)
        await _close_quietly(ws, 1000)

    # Registered last so the API and socket routes win over the catch-all mount.
    app.mount("/", RevalidatingStaticFiles(directory=STATIC_DIR, html=True), name="static")
    return app


async def _close_quietly(ws: WebSocket, code: int) -> None:
    with contextlib.suppress(RuntimeError):  # already closed
        await ws.close(code=code)
