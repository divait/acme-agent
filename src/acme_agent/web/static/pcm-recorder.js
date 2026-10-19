// AudioWorklet: converts microphone audio at the context rate to 16 kHz mono PCM16 LE
// and posts ~100 ms frames (1600 samples = 3200 bytes) to the main thread. It also posts
// {level: number} (smoothed RMS 0..1) about every 50 ms, but only after the main thread has
// sent {levels: true}; those are plain objects, not frames. Default off, so an older main
// script that forwards every port message to the socket never sees them.
const TARGET_RATE = 16000;
const FRAME_SAMPLES = 1600;

class PcmRecorder extends AudioWorkletProcessor {
  constructor() {
    super();
    this.step = sampleRate / TARGET_RATE; // input samples per output sample
    this.pos = 0; // fractional read position into the current block; -1 means the carried sample
    this.prev = 0; // last (filtered) sample of the previous block, index -1 of the next one
    this.x1 = 0; // raw input history for the anti-alias filter
    this.x2 = 0;
    this.out = new Int16Array(FRAME_SAMPLES);
    this.n = 0;
    this.levelEvery = Math.round(sampleRate * 0.05); // report the mic level every ~50 ms
    this.sumSq = 0;
    this.seen = 0;
    this.level = 0;
    this.levels = false; // opt-in: {levels: true} from the main thread
    this.port.onmessage = (e) => {
      if (e.data && e.data.levels === true) this.levels = true;
    };
  }

  meter(ch) {
    for (let i = 0; i < ch.length; i++) this.sumSq += ch[i] * ch[i];
    this.seen += ch.length;
    if (this.seen >= this.levelEvery) {
      const rms = Math.sqrt(this.sumSq / this.seen);
      this.level = rms > this.level ? rms : this.level * 0.7 + rms * 0.3;
      this.sumSq = 0;
      this.seen = 0;
      if (this.levels) this.port.postMessage({ level: this.level });
    }
  }

  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (!ch) return true;
    this.meter(ch);
    if (this.step === 1) {
      for (let i = 0; i < ch.length; i++) this.push(ch[i]);
      return true;
    }
    // Cheap anti-alias before decimating: [1 2 1] / 4 low-pass.
    const y = new Float32Array(ch.length);
    for (let i = 0; i < ch.length; i++) {
      y[i] = 0.25 * ch[i] + 0.5 * this.x1 + 0.25 * this.x2;
      this.x2 = this.x1;
      this.x1 = ch[i];
    }
    // Linear interpolation between y[i] and y[i + 1]; i = -1 is the sample carried over from
    // the previous block, so no output sample ever straddles a block boundary unseen.
    const last = y.length - 1;
    while (this.pos < last) {
      const i = Math.floor(this.pos);
      const frac = this.pos - i;
      const a = i < 0 ? this.prev : y[i];
      const b = y[i + 1];
      this.push(a + (b - a) * frac);
      this.pos += this.step;
    }
    this.pos -= y.length; // now in [-1, step - 1)
    this.prev = y[last];
    return true;
  }

  push(x) {
    const s = Math.max(-1, Math.min(1, x));
    this.out[this.n++] = s < 0 ? s * 32768 : s * 32767;
    if (this.n === FRAME_SAMPLES) {
      const buf = this.out.buffer;
      this.port.postMessage(buf, [buf]);
      this.out = new Int16Array(FRAME_SAMPLES);
      this.n = 0;
    }
  }
}

registerProcessor("pcm-recorder", PcmRecorder);
