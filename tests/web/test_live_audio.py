"""Real Gemini Live round trip through the gateway: synthetic Spanish consent, real model.

Run with `uv run pytest -m live tests/web/test_live_audio.py -q` (costs a few cents).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import socket
import wave
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
import uvicorn
import websockets

from acme_agent.bootstrap import build_container
from acme_agent.config import Settings
from acme_agent.domain.models import ConversationRecord
from acme_agent.web.app import create_app
from acme_agent.web.session import InterviewSession

pytestmark = pytest.mark.live

AUDIO_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "audio"
CHUNK_BYTES = 3200  # 100 ms of 16 kHz PCM16 mono
CHUNK_S = 0.1


def _pcm(name: str) -> bytes:
    with wave.open(str(AUDIO_DIR / name), "rb") as w:
        assert (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (16000, 1, 2)
        return w.readframes(w.getnframes())


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture
async def server(live_settings: Settings) -> AsyncIterator[tuple[int, Any]]:
    container = build_container(live_settings)
    app = create_app(container, session_factory=InterviewSession)
    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    srv = uvicorn.Server(config)
    task = asyncio.create_task(srv.serve())
    while not srv.started:
        await asyncio.sleep(0.05)
    try:
        yield port, container
    finally:
        srv.should_exit = True
        await task


class Collector:
    def __init__(self) -> None:
        self.audio = bytearray()
        self.texts: list[dict[str, Any]] = []
        self.last_audio = 0.0
        self._loop = asyncio.get_running_loop()

    async def pump(self, ws: Any) -> None:
        async for frame in ws:
            if isinstance(frame, bytes):
                self.audio += frame
                self.last_audio = self._loop.time()
            else:
                self.texts.append(json.loads(frame))

    async def wait_for(self, predicate: Callable[[], bool], timeout: float, what: str) -> None:
        deadline = self._loop.time() + timeout
        while not predicate():
            if self._loop.time() > deadline:
                pytest.fail(f"timed out waiting for {what}; frames so far: {self.texts}")
            await asyncio.sleep(0.05)

    def has(self, kind: str, **fields: Any) -> bool:
        return any(
            m["type"] == kind and all(m.get(k) == v for k, v in fields.items()) for m in self.texts
        )


async def test_spanish_consent_over_real_live_model(server: tuple[int, Any]) -> None:
    port, container = server
    async with httpx.AsyncClient() as http:
        res = await http.post(f"http://127.0.0.1:{port}/api/interviews")
    cid = res.json()["conversation_id"]
    uri = f"ws://127.0.0.1:{port}/ws/interview/{cid}"
    async with websockets.connect(
        uri, additional_headers={"Origin": "http://localhost:8000"}
    ) as ws:
        got = Collector()
        pump = asyncio.create_task(got.pump(ws))
        await ws.send(json.dumps({"type": "start", "locale": "es-ES"}))
        await got.wait_for(lambda: len(got.audio) > 0, 30, "Ana's greeting audio")
        # Let the greeting finish (no new audio for 800 ms) before the candidate speaks.
        loop = asyncio.get_running_loop()
        await got.wait_for(lambda: loop.time() - got.last_audio > 0.8, 30, "greeting to end")

        greeting_bytes = len(got.audio)
        pcm = _pcm("es_consent.wav") + bytes(16000 * 2)  # ~1 s of trailing silence
        for i in range(0, len(pcm), CHUNK_BYTES):
            await ws.send(pcm[i : i + CHUNK_BYTES])
            await asyncio.sleep(CHUNK_S)

        def filled() -> bool:
            return got.has("slot", name="consent_recording", status="filled")

        # Keep the stream alive with silence while the model answers.
        for _ in range(300):
            if filled():
                break
            await ws.send(bytes(CHUNK_BYTES))
            await asyncio.sleep(CHUNK_S)
        await got.wait_for(filled, 5, "consent_recording filled")
        await got.wait_for(
            lambda: got.has("transcript", speaker="agent", final=True), 30, "final agent transcript"
        )

        assert greeting_bytes > 0 and len(got.audio) > 0
        assert got.has("transcript", speaker="candidate", final=True)

        await ws.send(json.dumps({"type": "end"}))
        await got.wait_for(lambda: got.has("completed"), 30, "completed")
        assert got.has("ended")
        pump.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await pump

    record: ConversationRecord | None = await container.repository.get(cid)
    assert record is not None
    assert record.channel == "web_voice"
