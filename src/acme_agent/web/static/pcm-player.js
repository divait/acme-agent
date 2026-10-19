// AudioWorklet: plays PCM16 LE chunks at 24 kHz from a ring buffer.
// Messages in: ArrayBuffer (PCM16 chunk), {flush: true} (drop everything queued, immediately)
// {levels: true} (opt in to level messages; default off) or {query: "drain"}. Messages out:
// {level: number} (only after opt-in; smoothed RMS 0..1, ~every 50 ms while audible, then once more at ~0), {drained: true} when the buffer runs empty after having
// held audio (immediately for a query when it is already empty).
// If the context does not run at 24 kHz, samples are resampled on the fly (linear).
const SOURCE_RATE = 24000;
const CAPACITY = SOURCE_RATE * 30; // 30 s; oldest audio is overwritten on overflow

class PcmPlayer extends AudioWorkletProcessor {
  constructor() {
    super();
    this.ring = new Float32Array(CAPACITY);
    this.read = 0; // absolute index of next sample to read
    this.write = 0; // absolute index of next sample to write
    this.frac = 0;
    this.hadData = false;
    this.step = SOURCE_RATE / sampleRate;
    this.levelEvery = Math.round(sampleRate * 0.05); // report the output level every ~50 ms
    this.sumSq = 0;
    this.seen = 0;
    this.level = 0; // smoothed RMS
    this.posted = 0;
    this.levels = false;
    this.port.onmessage = (e) => {
      if (e.data && e.data.levels === true) {
        this.levels = true;
        return;
      }
      if (e.data && e.data.flush) {
        this.read = this.write;
        this.frac = 0;
        this.hadData = false;
        this.level = 0;
        return;
      }
      if (e.data && e.data.query) {
        if (this.write - this.read < 2) {
          this.hadData = false;
          this.port.postMessage({ drained: true });
        }
        return;
      }
      const pcm = new Int16Array(e.data);
      if (pcm.length) this.hadData = true;
      for (let i = 0; i < pcm.length; i++) {
        this.ring[this.write % CAPACITY] = pcm[i] / 32768;
        this.write++;
      }
      if (this.write - this.read > CAPACITY) this.read = this.write - CAPACITY;
    };
  }

  process(inputs, outputs) {
    const out = outputs[0][0];
    for (let i = 0; i < out.length; i++) {
      if (this.write - this.read < 2) {
        out[i] = 0; // underrun: silence
        if (this.hadData) {
          this.hadData = false;
          this.port.postMessage({ drained: true });
        }
        continue;
      }
      const a = this.ring[this.read % CAPACITY];
      const b = this.ring[(this.read + 1) % CAPACITY];
      out[i] = a + (b - a) * this.frac;
      this.sumSq += out[i] * out[i];
      this.frac += this.step;
      const whole = Math.floor(this.frac);
      this.frac -= whole;
      this.read += whole;
    }
    this.seen += out.length;
    if (this.seen >= this.levelEvery) {
      const rms = Math.sqrt(this.sumSq / this.seen);
      // Fast attack, slow release, so the orb does not flicker between syllables.
      this.level = rms > this.level ? rms : this.level * 0.7 + rms * 0.3;
      this.sumSq = 0;
      this.seen = 0;
      if (this.levels && (this.level > 0.001 || this.posted > 0.001)) {
        this.posted = this.level;
        this.port.postMessage({ level: this.level });
      }
    }
    for (let c = 1; c < outputs[0].length; c++) outputs[0][c].set(out);
    return true;
  }
}

registerProcessor("pcm-player", PcmPlayer);
