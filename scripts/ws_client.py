"""Dev tool: talk to a running `acme-agent serve` over WebSocket (not part of the package).

WAV mode streams 16 kHz mono PCM16 files as successive candidate turns, each one after Ana has
finished speaking (no agent audio for 800 ms). `--mic` streams the microphone instead and needs
the optional `sounddevice` dev dependency (`uv sync --group mic`); Ana's audio plays live through
the chosen output device and barge-in drops queued playback. By default the mic is half-duplex
(silence is sent while Ana speaks plus `--echo-tail-ms`) because this client has no echo
cancellation; `--full-duplex` allows barge-in and needs headphones that do not leak.

Usage (server running via `acme-agent serve`; defaults: --url ws://127.0.0.1:8000,
--origin http://localhost:8000, --locale es-ES):

    uv sync --group mic
    uv run python scripts/ws_client.py --mic                    # live voice test, Spanish
    uv run python scripts/ws_client.py --mic --locale en-US     # English
    uv run python scripts/ws_client.py --list-devices
    uv run python scripts/ws_client.py --mic --input-device MacBook   # Mac mic, earbuds as output
    uv run python scripts/ws_client.py --wav tests/fixtures/audio/es_consent.wav --out ana.wav

Ctrl-C ends the interview cleanly.
"""

from __future__ import annotations

import argparse
import array
import asyncio
import contextlib
import json
import math
import statistics
import threading
import time
import urllib.request
import wave
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import websockets

CHUNK_BYTES = 3200  # 100 ms of 16 kHz PCM16 mono
CHUNK_S = 0.1
AGENT_RATE = 24000
AGENT_DONE_SILENCE_S = 0.8
TURN_TIMEOUT_S = 30.0
FRAME_BYTES = 640  # 20 ms
PLAY_BLOCK_FRAMES = 480  # 20 ms of 24 kHz output
VOICED_RMS = 32768 * 10 ** (-40 / 20)  # -40 dBFS


def voiced_end_byte(pcm: bytes) -> int:
    """Byte offset just past the last 20 ms frame whose RMS is above -40 dBFS (0 if none)."""
    samples = array.array("h")
    samples.frombytes(pcm[: len(pcm) // 2 * 2])
    n = FRAME_BYTES // 2
    for start in range((len(samples) // n - 1) * n, -1, -n):
        frame = samples[start : start + n]
        if math.sqrt(sum(x * x for x in frame) / len(frame)) > VOICED_RMS:
            return (start + n) * 2
    return 0


def read_pcm(path: Path) -> bytes:
    with wave.open(str(path), "rb") as w:
        if (w.getframerate(), w.getnchannels(), w.getsampwidth()) != (16000, 1, 2):
            raise SystemExit(f"{path}: expected 16 kHz mono PCM16")
        return w.readframes(w.getnframes())


class Player:
    """Live playback of Ana's PCM16 audio; a lock-guarded buffer drained by the audio callback."""

    def __init__(self, sounddevice: Any, device: int | str | None = None) -> None:
        self._buf = bytearray()
        self._last_played = 0.0
        self._lock = threading.Lock()
        self._stream = sounddevice.RawOutputStream(
            samplerate=AGENT_RATE,
            channels=1,
            dtype="int16",
            blocksize=PLAY_BLOCK_FRAMES,
            device=device,
            callback=self._callback,
        )

    def _callback(self, outdata: Any, frames: int, time_info: Any, status: Any) -> None:
        need = frames * 2
        with self._lock:
            chunk = bytes(self._buf[:need])
            del self._buf[:need]
            if chunk:
                self._last_played = time.monotonic()
        outdata[: len(chunk)] = chunk
        outdata[len(chunk) : need] = bytes(need - len(chunk))  # underrun -> silence

    def muted(self, tail_s: float) -> bool:
        """True while playing, or within `tail_s` after the last played sample."""
        with self._lock:
            if self._buf:
                return True
            return time.monotonic() - self._last_played < tail_s

    def push(self, pcm: bytes) -> None:
        with self._lock:
            self._buf += pcm

    def clear(self) -> None:
        with self._lock:
            self._buf.clear()

    def __enter__(self) -> Player:
        self._stream.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stream.stop()
        self._stream.close()


class Client:
    def __init__(self, ws: Any, player: Player | None = None, compact: bool = False) -> None:
        self.ws = ws
        self.player = player
        self.compact = compact
        self.audio = bytearray()
        self.last_audio = 0.0
        self.audio_seen = asyncio.Event()
        self.awaiting_since: float | None = None
        self.voice_since: float | None = None
        self.latencies: list[float] = []
        self.voice_latencies: list[float] = []
        self.greeting_ms: float | None = None
        self.started_at: float | None = None
        self.ended = asyncio.Event()
        self.t0 = time.monotonic()

    def log(self, line: str) -> None:
        print(f"[{time.monotonic() - self.t0:6.1f}s] {line}", flush=True)

    async def receive(self) -> None:
        async for frame in self.ws:
            now = time.monotonic()
            if isinstance(frame, bytes):
                self.audio += frame
                if self.player is not None:
                    self.player.push(frame)
                self.last_audio = now
                if self.greeting_ms is None and self.started_at is not None:
                    self.greeting_ms = (now - self.started_at) * 1000
                self.audio_seen.set()
                if self.awaiting_since is not None:
                    ms = (now - self.awaiting_since) * 1000
                    self.latencies.append(ms)
                    voice_ms = (now - (self.voice_since or self.awaiting_since)) * 1000
                    self.voice_latencies.append(voice_ms)
                    self.log(
                        f"latency {ms:.0f} ms from end of file, {voice_ms:.0f} ms from end of "
                        "voice (first agent audio)"
                    )
                    self.awaiting_since = None
                    self.voice_since = None
                continue
            msg = json.loads(frame)
            kind = msg.get("type")
            if kind == "interrupted" and self.player is not None:
                self.player.clear()  # barge-in: stop talking over the candidate
            if self.compact:
                self.show_compact(kind, msg)
                continue
            if kind == "transcript":
                if msg["final"]:
                    self.log(f"transcript {msg['speaker']} #{msg['turn']}: {msg['text']}")
            elif kind == "slot":
                self.log(
                    f"slot {msg['name']} {msg['status']} value={msg['value']!r} "
                    f"progress={msg['progress']:.2f}"
                )
            elif kind in ("ended", "completed"):
                self.log(f"{kind}: {json.dumps(msg)}")
                if kind == "completed":
                    self.ended.set()
            elif kind != "pong":
                self.log(f"{kind}: {json.dumps(msg)}")

    def show_compact(self, kind: str | None, msg: dict[str, Any]) -> None:
        if kind == "transcript" and msg["final"]:
            who = "Tú" if msg["speaker"] == "candidate" else "Ana"
            print(f"{who}: {msg['text']}", flush=True)
        elif kind == "slot" and msg["status"] == "filled":
            print(f"✓ {msg['name']}", flush=True)
        elif kind in ("ended", "completed"):
            print(f"{kind}: {msg.get('reason') or msg.get('status')}", flush=True)
            if kind == "completed":
                self.ended.set()
        elif kind == "error":
            print(f"error: {json.dumps(msg)}", flush=True)

    async def wait_agent_done(self) -> None:
        """Return once the agent has spoken and then been quiet for 800 ms."""
        deadline = time.monotonic() + TURN_TIMEOUT_S
        while time.monotonic() < deadline:
            await asyncio.sleep(0.1)
            if self.ended.is_set():
                return
            if self.audio_seen.is_set() and time.monotonic() - self.last_audio >= (
                AGENT_DONE_SILENCE_S
            ):
                self.audio_seen.clear()
                return
        self.log("timed out waiting for the agent to finish")

    async def send_silence(self, seconds: float) -> None:
        for _ in range(int(seconds / CHUNK_S)):
            await self.ws.send(bytes(CHUNK_BYTES))
            await asyncio.sleep(CHUNK_S)

    async def say(self, pcm: bytes, name: str) -> None:
        """Stream one utterance in real time, then silence until the agent answers."""
        self.log(f"candidate audio: {name}")
        voiced_end = voiced_end_byte(pcm)
        voice_since: float | None = None
        for i in range(0, len(pcm), CHUNK_BYTES):
            await self.ws.send(pcm[i : i + CHUNK_BYTES])
            if voice_since is None and i + CHUNK_BYTES >= voiced_end:
                voice_since = time.monotonic()
            await asyncio.sleep(CHUNK_S)
        self.awaiting_since = time.monotonic()
        self.voice_since = voice_since
        waited = 0.0
        self.audio_seen.clear()
        while not self.audio_seen.is_set() and not self.ended.is_set() and waited < TURN_TIMEOUT_S:
            await self.send_silence(CHUNK_S)
            waited += CHUNK_S
        await self.wait_agent_done()


def http_base(url: str) -> str:
    return url.replace("wss://", "https://", 1).replace("ws://", "http://", 1).rstrip("/")


async def run_wavs(client: Client, wavs: list[Path]) -> None:
    await client.wait_agent_done()  # greeting
    for path in wavs:
        if client.ended.is_set():
            client.log(f"interview already completed; not sending {path.name}")
            break
        await client.say(read_pcm(path), path.name)


@contextlib.contextmanager
def open_player(device: int | str | None = None) -> Iterator[Player]:
    try:
        import sounddevice  # type: ignore[import-not-found]
    except ImportError:
        raise SystemExit("--mic needs sounddevice: uv sync --group mic") from None
    with Player(sounddevice, device) as player:
        yield player


def parse_device(value: str | None) -> int | str | None:
    """An all-digit value is a device index, anything else a name substring."""
    if value is None:
        return None
    return int(value) if value.isdigit() else value


def list_devices() -> None:
    try:
        import sounddevice  # type: ignore[import-not-found]
    except ImportError:
        raise SystemExit("--list-devices needs sounddevice: uv sync --group mic") from None
    for index, dev in enumerate(sounddevice.query_devices()):
        kinds = [
            label
            for label, key in (("input", "max_input_channels"), ("output", "max_output_channels"))
            if dev[key] > 0
        ]
        print(f"{index:3d}  {'/'.join(kinds) or '-':12s} {dev['name']}")


async def run_mic(ws: Any, client: Client, args: argparse.Namespace) -> None:
    import sounddevice  # type: ignore[import-not-found]

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[bytes] = asyncio.Queue()

    def on_audio(indata: Any, frames: int, time_info: Any, status: Any) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, bytes(indata))

    tail_s = args.echo_tail_ms / 1000
    half_duplex = not args.full_duplex and client.player is not None
    if half_duplex:
        print(
            "Modo half-duplex: el micrófono se silencia mientras Ana habla "
            "(usa --full-duplex para poder interrumpir) / "
            "Half-duplex: mic muted while Ana speaks",
            flush=True,
        )
    else:
        print(
            "Modo full-duplex: se puede interrumpir a Ana, usa auriculares sin fuga / "
            "Full-duplex: barge-in enabled, needs headphones that do not leak",
            flush=True,
        )
    print(
        "Consejo / Tip: si Ana se oye a sí misma, baja el volumen o usa el micrófono del Mac "
        "(--input-device MacBook) / if Ana still hears herself, lower the volume or use the "
        "Mac microphone.",
        flush=True,
    )
    print("Streaming the microphone; Ctrl-C to end.", flush=True)
    with sounddevice.RawInputStream(
        samplerate=16000,
        channels=1,
        dtype="int16",
        blocksize=1600,
        device=parse_device(args.input_device),
        callback=on_audio,
    ):
        while not client.ended.is_set():
            try:
                block = await asyncio.wait_for(queue.get(), 0.2)
            except TimeoutError:
                continue
            if half_duplex and client.player is not None and client.player.muted(tail_s):
                block = bytes(len(block))  # keep the stream flowing, VAD hears silence
            await ws.send(block)


async def main(args: argparse.Namespace) -> int:
    req = urllib.request.Request(f"{http_base(args.url)}/api/interviews", method="POST")
    with urllib.request.urlopen(req) as res:
        body = json.load(res)
    ws_url = f"{args.url.rstrip('/')}/ws/interview/{body['conversation_id']}"
    print(f"conversation_id: {body['conversation_id']}", flush=True)
    async with (
        websockets.connect(ws_url, additional_headers={"Origin": args.origin}, max_size=None) as ws,
        contextlib.AsyncExitStack() as stack,
    ):
        player = (
            stack.enter_context(open_player(parse_device(args.output_device))) if args.mic else None
        )
        client = Client(ws, player, compact=args.mic)
        receiver = asyncio.create_task(client.receive())
        client.started_at = time.monotonic()
        await ws.send(json.dumps({"type": "start", "locale": args.locale}))
        try:
            if args.mic:
                await run_mic(ws, client, args)
            else:
                await run_wavs(client, args.wav)
        except (KeyboardInterrupt, asyncio.CancelledError, websockets.ConnectionClosed):
            pass
        finally:
            try:
                if not client.ended.is_set():
                    await ws.send(json.dumps({"type": "end"}))
                await asyncio.wait_for(client.ended.wait(), 30)
            except TimeoutError:
                client.log("no `completed` frame within 30 s")
            except websockets.ConnectionClosed:
                pass  # the server closed the socket after `completed`
            receiver.cancel()
    if args.out:
        with wave.open(str(args.out), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(AGENT_RATE)
            w.writeframes(bytes(client.audio))
        print(f"agent audio: {len(client.audio)} bytes -> {args.out}")
    if client.greeting_ms is not None:
        print(f"greeting_first_audio_ms: {client.greeting_ms:.0f}")
    if client.latencies:
        print("latencies_from_end_of_file_ms: " + ", ".join(f"{x:.0f}" for x in client.latencies))
        print(
            "latencies_from_end_of_voice_ms: "
            + ", ".join(f"{x:.0f}" for x in client.voice_latencies)
        )
        print(f"median_from_end_of_file_ms: {statistics.median(client.latencies):.0f}")
        print(
            f"median_from_end_of_voice_ms: {statistics.median(client.voice_latencies):.0f} "
            "(bound <= 2500, target <= 1500)"
        )
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--url", default="ws://127.0.0.1:8000")
    parser.add_argument("--origin", default="http://localhost:8000")
    parser.add_argument("--locale", default="es-ES", choices=["es-ES", "en-US"])
    parser.add_argument("--wav", nargs="*", type=Path, default=[], help="candidate turns, in order")
    parser.add_argument("--mic", action="store_true", help="stream the microphone (sounddevice)")
    parser.add_argument("--out", type=Path, help="write Ana's audio here (24 kHz mono WAV)")
    parser.add_argument("--full-duplex", action="store_true", help="mic always live (barge-in)")
    parser.add_argument("--echo-tail-ms", type=int, default=600, help="half-duplex mute tail")
    parser.add_argument("--list-devices", action="store_true", help="list audio devices and exit")
    parser.add_argument("--input-device", help="input device index or name substring")
    parser.add_argument("--output-device", help="output device index or name substring")
    ns = parser.parse_args()
    if ns.list_devices:
        list_devices()
        raise SystemExit(0)
    if not ns.mic and not ns.wav:
        parser.error("give --wav FILE... or --mic")
    try:
        raise SystemExit(asyncio.run(main(ns)))
    except KeyboardInterrupt:
        raise SystemExit(130) from None
