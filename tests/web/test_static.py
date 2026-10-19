from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from acme_agent.bootstrap import build_container
from acme_agent.config import Settings
from acme_agent.web.app import STATIC_DIR, create_app

ASSETS = {
    "app.js": "javascript",
    "format.js": "javascript",
    "pcm-recorder.js": "javascript",
    "pcm-player.js": "javascript",
    "styles.css": "text/css",
}
FORBIDDEN = re.compile(r"gemini|api_key|token", re.IGNORECASE)


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(build_container(Settings(_env_file=None))))


def _files() -> list[Path]:
    return [p for p in STATIC_DIR.rglob("*") if p.is_file()]


def test_index_served_with_module_script(client: TestClient) -> None:
    res = client.get("/")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
    assert re.search(r'<script[^>]+type="module"[^>]+src="app\.js"', res.text)
    assert 'href="styles.css"' in res.text


@pytest.mark.parametrize(("name", "ctype"), ASSETS.items())
def test_assets_served_with_content_type(client: TestClient, name: str, ctype: str) -> None:
    res = client.get(f"/{name}")
    assert res.status_code == 200
    assert ctype in res.headers["content-type"]


def test_total_payload_under_100_kb() -> None:
    assert sum(p.stat().st_size for p in _files()) < 100 * 1024


def test_no_forbidden_words_in_static() -> None:
    hits = [p.name for p in _files() if FORBIDDEN.search(p.read_text(encoding="utf-8"))]
    assert hits == []


def test_index_has_no_external_urls() -> None:
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert re.findall(r"""(?:src|href)\s*=\s*["'](?:https?:)?//""", html) == []
    assert "<style" not in html and not re.search(r"<script(?![^>]*\bsrc=)", html)


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_recorder_resamples_to_16khz_pcm16_frames() -> None:
    script = r"""
    const fs = require("fs");
    globalThis.sampleRate = 48000;
    globalThis.AudioWorkletProcessor = class {
      constructor() {
        this.port = { postMessage: (b) => (b instanceof ArrayBuffer ? frames : levels).push(b) };
      }
    };
    globalThis.registerProcessor = (_, cls) => { globalThis.Proc = cls; };
    const frames = [], levels = [];
    let res0 = -1;
    eval(fs.readFileSync(process.argv[1], "utf8"));
    const p = new Proc();
    const block = new Float32Array(128);
    let t = 0;
    for (let b = 0; b < 3000; b++) {  // 8 s at 48 kHz
      if (b === 1000) { res0 = levels.length; p.port.onmessage({ data: { levels: true } }); }
      for (let i = 0; i < 128; i++) block[i] = 0.5 * Math.sin(2 * Math.PI * 440 * (t++) / 48000);
      p.process([[block]]);
    }
    const s = new Int16Array(frames[10]);
    let cross = 0;
    for (let i = 1; i < s.length; i++) if (s[i - 1] < 0 && s[i] >= 0) cross++;
    const lv = levels.map((m) => m.level);
    console.log(JSON.stringify({ n: frames.length, bytes: frames[0].byteLength, cross,
      beforeOptIn: res0, nLevels: lv.length, lastLevel: lv[lv.length - 1] }));
    """
    out = subprocess.run(
        ["node", "-e", script, str(STATIC_DIR / "pcm-recorder.js")],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    res = json.loads(out)
    assert res["bytes"] == 3200
    assert 75 <= res["n"] <= 80  # 8 s of 100 ms frames
    assert 43 <= res["cross"] <= 45  # 440 Hz over 100 ms
    assert res["beforeOptIn"] == 0  # no level messages until the main thread opts in
    assert 100 <= res["nLevels"] <= 110  # ~every 50 ms over the last ~5.3 s
    assert 0.3 < res["lastLevel"] < 0.4  # sine of amplitude 0.5 has RMS ~0.35


def _node(script: str, *args: Path) -> dict[str, object]:
    out = subprocess.run(
        ["node", "-e", script, *map(str, args)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return json.loads(out)  # type: ignore[no-any-return]


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_recorder_44k_blocks_are_continuous() -> None:
    script = r"""
    const fs = require("fs");
    globalThis.sampleRate = 44100;
    globalThis.AudioWorkletProcessor = class {
      constructor() {
        this.port = { postMessage: (b) => (b instanceof ArrayBuffer ? frames : levels).push(b) };
      }
    };
    globalThis.registerProcessor = (_, cls) => { globalThis.Proc = cls; };
    const frames = [], levels = [];
    eval(fs.readFileSync(process.argv[1], "utf8"));
    const p = new Proc();
    const block = new Float32Array(128);
    let t = 0;
    for (let b = 0; b < 2800; b++) {  // about 8 s at 44.1 kHz
      for (let i = 0; i < 128; i++) block[i] = 0.5 * Math.sin(2 * Math.PI * 440 * (t++) / 44100);
      p.process([[block]]);
    }
    const all = [];
    for (const f of frames.slice(5, 60)) all.push(...new Int16Array(f));
    let cross = 0, maxStep = 0;
    for (let i = 1; i < all.length; i++) {
      if (all[i - 1] < 0 && all[i] >= 0) cross++;
      maxStep = Math.max(maxStep, Math.abs(all[i] - all[i - 1]));
    }
    console.log(JSON.stringify({ bytes: frames[0].byteLength, n: all.length, cross, maxStep }));
    """
    res = _node(script, STATIC_DIR / "pcm-recorder.js")
    assert res["bytes"] == 3200
    seconds = res["n"] / 16000  # type: ignore[operator]
    assert abs(res["cross"] - 440 * seconds) <= 2  # type: ignore[operator]
    # A 440 Hz sine at 0.5 amplitude moves at most ~2830 per 16 kHz sample; a boundary glitch
    # would show as a much bigger jump.
    assert res["maxStep"] < 3000  # type: ignore[operator]


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_player_flush_overflow_resample_and_drained() -> None:
    script = r"""
    const fs = require("fs");
    const src = fs.readFileSync(process.argv[1], "utf8");
    function make(rate) {
      const posted = [];
      globalThis.sampleRate = rate;
      globalThis.AudioWorkletProcessor = class {
        constructor() { this.port = { postMessage: (m) => posted.push(m) }; }
      };
      let Proc;
      globalThis.registerProcessor = (_, cls) => { Proc = cls; };
      eval(src);
      const p = new Proc();
      const send = (data) => p.port.onmessage({ data });
      const pull = (n = 128) => {
        const out = [new Float32Array(n)];
        p.process([], [out]);
        return out[0];
      };
      return { p, posted, send, pull };
    }
    const pcm = (n, v) => new Int16Array(n).fill(v).buffer;
    const res = {};

    let a = make(24000);
    a.send(pcm(24000, 16384));            // 1 s
    res.beforeFlush = a.pull()[10];
    a.send({ flush: true });
    res.afterFlush = Array.from(a.pull()).every((x) => x === 0);

    a = make(24000);                       // overflow: 31 s of old (1000) then 1 s new (8000)
    for (let i = 0; i < 31; i++) a.send(pcm(24000, 1000));
    a.send(pcm(24000, 8000));
    let total = 0, lastVal = 0;
    for (;;) {
      const o = a.pull();
      const nz = o.findIndex((x) => x === 0);
      if (nz >= 0) { total += nz; break; }
      total += 128;
      lastVal = o[127];
    }
    res.keptSeconds = Math.round(total / 24000);
    res.newestKept = Math.abs(lastVal - 8000 / 32768) < 1e-6;

    const c = make(48000);                 // 24 kHz source on a 48 kHz context
    res.step = c.p.step;
    c.send(pcm(2400, 16384));
    c.pull(128);
    res.consumed = c.p.read;               // 128 output samples = 64 source samples

    const d = make(24000);
    d.send(pcm(256, 5000));
    d.pull(128);
    const before = d.posted.length;
    d.pull(128);
    d.pull(128);
    res.drained = d.posted.filter((m) => m.drained).length;
    res.drainedAfterEmpty = before === 0;
    d.send({ query: "drain" });
    res.queryEmpty = d.posted.filter((m) => m.drained).length;
    const off = make(24000);               // no level messages without opt-in
    off.send(pcm(24000, 16384));
    for (let i = 0; i < 100; i++) off.pull(128);
    res.noLevelsByDefault = off.posted.filter((m) => "level" in m).length === 0;
    const e = make(24000);                 // level messages while audible, one last ~0 after
    e.send({ levels: true });
    e.send(pcm(24000, 16384));
    for (let i = 0; i < 100; i++) e.pull(128);
    const mid = e.posted.filter((m) => "level" in m).map((m) => m.level);
    res.levelCount = mid.length;
    res.levelOk = mid.every((x) => x > 0.45 && x < 0.55);
    e.send({ flush: true });
    for (let i = 0; i < 200; i++) e.pull(128);
    const all = e.posted.filter((m) => "level" in m).map((m) => m.level);
    res.levelEnds = all[all.length - 1] < 0.01;
    const n0 = all.length;
    for (let i = 0; i < 200; i++) e.pull(128);
    res.quietWhenIdle = e.posted.filter((m) => "level" in m).length === n0;
    console.log(JSON.stringify(res));
    """
    res = _node(script, STATIC_DIR / "pcm-player.js")
    assert 9 <= int(str(res["levelCount"])) <= 11 and res["levelOk"] is True
    assert res["noLevelsByDefault"] is True
    assert res["levelEnds"] is True and res["quietWhenIdle"] is True
    assert res["beforeFlush"] == pytest.approx(0.5)
    assert res["afterFlush"] is True
    assert res["keptSeconds"] == 30 and res["newestKept"] is True
    assert res["step"] == 0.5 and res["consumed"] == 64
    assert res["drained"] == 1 and res["drainedAfterEmpty"] is True
    assert res["queryEmpty"] == 2


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_format_value_renders_readable_text() -> None:
    script = r"""
    const fs = require("fs");
    const src = fs.readFileSync(process.argv[1], "utf8");
    import("data:text/javascript;base64," + Buffer.from(src).toString("base64")).then((m) => {
      const f = m.formatValue;
      const av = JSON.stringify([{day:"mon",shift:"morning"},{day:"tue",shift:"morning"},
                                 {day:"sat",shift:"night"}]);
      console.log(JSON.stringify({
        yes: f("is_18_or_over", "true", "en"), no: f("own_vehicle", "false", "es"),
        si: f("consent_recording", "true", "es"),
        role: f("role", "delivery_rider", "es"), kitchen: f("role", "kitchen", "en"),
        av_en: f("availability", av, "en"), av_es: f("availability", "mon:morning,sat:night", "es"),
        date: f("start_date", "2026-11-03", "en"), date_es: f("start_date", "2026-11-03", "es"),
        hours: f("weekly_hours", "25", "en"), hours_es: f("weekly_hours", "25", "es"),
        months: f("experience_months", "30", "en"), months_es: f("experience_months", "30", "es"),
        langs: f("languages", '["es","en"]', "en"), langs_es: f("languages", '["es","en"]', "es"),
        store: f("preferred_store_id", "mad-sol", "en"), unknown: f("role", "chef", "en"),
      }));
    });
    """
    out = subprocess.run(
        ["node", "-e", script, str(STATIC_DIR / "format.js")],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    res = json.loads(out)
    assert (res["yes"], res["no"], res["si"]) == ("Yes", "No", "Sí")
    assert (res["role"], res["kitchen"], res["unknown"]) == ("Repartidor", "Kitchen team", "chef")
    assert res["av_en"] == "Mornings: Mon, Tue · Nights: Sat"
    assert res["av_es"] == "Mañanas: lun · Noches: sáb"
    assert "3" in res["date"] and "2026" in res["date"] and "Nov" in res["date"]
    assert "nov" in res["date_es"]
    assert (res["hours"], res["hours_es"]) == ("25 h/week", "25 h/semana")
    assert (res["months"], res["months_es"]) == ("30 months", "30 meses")
    assert res["langs"] == "Spanish, English"
    assert res["langs_es"] == "español, inglés"
    assert res["store"] == "mad-sol"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_declined_line_only_for_declined_consent() -> None:
    script = r"""
    const fs = require("fs");
    const src = fs.readFileSync(process.argv[1], "utf8");
    import("data:text/javascript;base64," + Buffer.from(src).toString("base64")).then((m) => {
      console.log(JSON.stringify({
        en: m.declinedLine("declined_consent", "en"), es: m.declinedLine("declined_consent", "es"),
        done: m.declinedLine("completed", "en"), none: m.declinedLine(undefined, "es"),
      }));
    });
    """
    out = subprocess.run(
        ["node", "-e", script, str(STATIC_DIR / "format.js")],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    res = json.loads(out)
    assert res["en"].startswith("Thank you for your time. Nothing")
    assert res["es"].startswith("Gracias por tu tiempo. No se ha guardado")
    assert res["done"] is None and res["none"] is None


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_pick_default_language() -> None:
    script = r"""
    const fs = require("fs");
    const src = fs.readFileSync(process.argv[1], "utf8");
    import("data:text/javascript;base64," + Buffer.from(src).toString("base64")).then((m) => {
      const inputs = ["es-ES", "es", "ES-mx", "en-US", "fr", "", undefined];
      console.log(JSON.stringify(inputs.map((v) => m.pickDefaultLanguage(v))));
    });
    """
    out = subprocess.run(
        ["node", "-e", script, str(STATIC_DIR / "format.js")],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert json.loads(out) == ["es", "es", "es", "en", "en", "en", "en"]


def test_static_files_must_revalidate(client: TestClient) -> None:
    first = client.get("/app.js")
    assert first.headers["cache-control"] == "no-cache"
    again = client.get("/app.js", headers={"if-none-match": first.headers["etag"]})
    assert again.status_code == 304


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_orb_state_and_intensity() -> None:
    script = r"""
    const fs = require("fs");
    const src = fs.readFileSync(process.argv[1], "utf8");
    import("data:text/javascript;base64," + Buffer.from(src).toString("base64")).then((m) => {
      console.log(JSON.stringify({
        agent: m.orbState(0.1, 0.5), cand: m.orbState(0.0, 0.1), idle: m.orbState(0.005, 0.01),
        edge: m.orbState(0.02, 0.04), bad: m.orbState(undefined, NaN),
        i0: m.orbIntensity(0), i1: m.orbIntensity(5), imid: m.orbIntensity(0.1),
        inan: m.orbIntensity(NaN),
      }));
    });
    """
    res = _node(script, STATIC_DIR / "format.js")
    assert (res["agent"], res["cand"], res["idle"]) == ("agent", "candidate", "idle")
    assert (res["edge"], res["bad"]) == ("idle", "idle")
    assert (res["i0"], res["i1"], res["inan"]) == (0, 1, 0)
    assert 0 < float(str(res["imid"])) < 1
