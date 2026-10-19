from __future__ import annotations

import pytest
from fastapi import WebSocket
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from ulid import ULID

from acme_agent.bootstrap import AppContainer, build_container
from acme_agent.config import Settings
from acme_agent.web.app import IssuedIds, SlidingWindowLimiter, create_app
from acme_agent.web.frames import receive_frame
from acme_agent.web.protocol import (
    EndMessage,
    PingMessage,
    PongMessage,
    ProtocolError,
    dump_server_message,
)

ORIGIN = {"origin": "http://localhost:8000"}


class StubSession:
    """Test double for `InterviewSession`: pong on ping, stop on end."""

    def __init__(self, ws: WebSocket, conversation_id: str, container: AppContainer) -> None:
        self._ws = ws

    async def run(self) -> None:
        while True:
            frame = await receive_frame(self._ws)
            if frame is None or isinstance(frame, EndMessage):
                return
            if isinstance(frame, PingMessage):
                await self._ws.send_text(dump_server_message(PongMessage()))
            elif isinstance(frame, ProtocolError):
                continue


@pytest.fixture
def client(settings: Settings) -> TestClient:
    return TestClient(
        create_app(
            build_container(settings),
            session_factory=StubSession,
            rate_limiter=SlidingWindowLimiter(10_000),
        )
    )


def _ws_path(client: TestClient) -> str:
    return f"/ws/interview/{client.post('/api/interviews').json()['conversation_id']}"


def test_healthz(client: TestClient) -> None:
    assert client.get("/healthz").json() == {"status": "ok"}


def test_index_page(client: TestClient) -> None:
    res = client.get("/")
    assert res.status_code == 200
    assert "Acme Burgers" in res.text


def test_create_interview(client: TestClient) -> None:
    body = client.post("/api/interviews").json()
    assert body["conversation_id"].startswith("c_")
    assert body["ws_url"] == f"ws://testserver/ws/interview/{body['conversation_id']}"


def test_rate_limit_five_per_minute_per_ip(settings: Settings) -> None:
    client = TestClient(create_app(build_container(settings), session_factory=StubSession))
    assert [client.post("/api/interviews").status_code for _ in range(6)] == [200] * 5 + [429]


def test_sliding_window_expires() -> None:
    now = [0.0]
    limiter = SlidingWindowLimiter(2, 60.0, lambda: now[0])
    assert limiter.allow("a") and limiter.allow("a") and not limiter.allow("a")
    assert limiter.allow("b")
    now[0] = 61.0
    assert limiter.allow("a")


def test_ping_pong_and_end(client: TestClient) -> None:
    with client.websocket_connect(_ws_path(client), headers=ORIGIN) as ws:
        ws.send_text('{"type":"ping"}')
        assert ws.receive_json() == {"type": "pong"}
        ws.send_text('{"type":"end"}')
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_text()
        assert exc.value.code == 1000


def test_origin_rejected(client: TestClient) -> None:
    for headers in ({"origin": "https://evil.example"}, {}):
        with client.websocket_connect(_ws_path(client), headers=headers) as ws:
            with pytest.raises(WebSocketDisconnect) as exc:
                ws.receive_text()
            assert exc.value.code == 1008


def test_invalid_id_rejected(client: TestClient) -> None:
    with client.websocket_connect("/ws/interview/not-an-id", headers=ORIGIN) as ws:
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_text()
        assert exc.value.code == 1008


def test_duplicate_socket_4409_and_id_not_reusable_after_close(client: TestClient) -> None:
    path = _ws_path(client)
    with client.websocket_connect(path, headers=ORIGIN) as first:
        first.send_text('{"type":"ping"}')
        assert first.receive_json() == {"type": "pong"}
        with client.websocket_connect(path, headers=ORIGIN) as second:
            with pytest.raises(WebSocketDisconnect) as exc:
                second.receive_text()
            assert exc.value.code == 4409
        first.send_text('{"type":"ping"}')
        assert first.receive_json() == {"type": "pong"}
    with client.websocket_connect(path, headers=ORIGIN) as again:
        with pytest.raises(WebSocketDisconnect) as exc:
            again.receive_text()
        assert exc.value.code == 1008


def test_unissued_id_rejected(client: TestClient) -> None:
    with client.websocket_connect(f"/ws/interview/c_{ULID()}", headers=ORIGIN) as ws:
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_text()
        assert exc.value.code == 1008


def test_issued_ids_expire_and_are_bounded() -> None:
    now = [0.0]
    ids = IssuedIds(ttl=10.0, cap=2, clock=lambda: now[0])
    ids.issue("a")
    now[0] = 11.0
    assert not ids.consume("a")
    ids.issue("b")
    ids.issue("c")
    ids.issue("d")
    assert not ids.consume("b")
    assert ids.consume("c") and not ids.consume("c")


@pytest.mark.parametrize("payload", [b"\x00" * 16385, None])
def test_oversized_frames_close_1009(client: TestClient, payload: bytes | None) -> None:
    with client.websocket_connect(_ws_path(client), headers=ORIGIN) as ws:
        if payload is not None:
            ws.send_bytes(payload)
        else:
            ws.send_text('{"type":"text","text":"' + "x" * 3000 + '"}')
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_text()
        assert exc.value.code == 1009


def test_max_audio_frame_accepted(client: TestClient) -> None:
    with client.websocket_connect(_ws_path(client), headers=ORIGIN) as ws:
        ws.send_bytes(b"\x00" * 16384)
        ws.send_text('{"type":"ping"}')
        assert ws.receive_json() == {"type": "pong"}


def test_malformed_frame_does_not_kill_socket(client: TestClient) -> None:
    with client.websocket_connect(_ws_path(client), headers=ORIGIN) as ws:
        ws.send_text("garbage")
        ws.send_text('{"type":"ping"}')
        assert ws.receive_json() == {"type": "pong"}


def test_custom_session_factory_is_used(settings: Settings) -> None:
    seen: list[str] = []

    class Runner:
        def __init__(self, ws, cid, container):  # type: ignore[no-untyped-def]
            seen.append(cid)

        async def run(self) -> None:
            return

    app = create_app(build_container(settings), session_factory=Runner)
    test_client = TestClient(app)
    path = _ws_path(test_client)
    with (
        test_client.websocket_connect(path, headers=ORIGIN) as ws,
        pytest.raises(WebSocketDisconnect),
    ):
        ws.receive_text()
    assert seen == [path.rsplit("/", 1)[1]]
