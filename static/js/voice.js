import { toast } from './util.js';

let _recorder = null;
let _chunks = [];
let _recording = false;
let _micIdleHtml = '';
let _sendIdleHtml = '';
let _audioCtx = null;
let _analyser = null;
let _waveRaf = 0;
let _recStart = 0;       // ms timestamp recording began (for the live timer)
let _sr = null;          // browser SpeechRecognition (live)
let _srText = '';        // accumulated transcript
let _srFatal = false;    // stop restarting after a real error
let _stream = null;      // active mic stream
let _mode = 'browser';

// 10f — reveal the full-duplex live-voice button only when a realtime provider is configured
export async function initLiveVoice() {
  const btn = document.getElementById('live-voice-btn');
  if (!btn) return;
  try {
    const st = await fetch('/api/voice/realtime/status').then(r => r.json());
    btn.style.display = st.available ? '' : 'none';
    if (st.available) btn.title = `live voice (${st.model})`;
  } catch { btn.style.display = 'none'; }
  btn.onclick = async () => {
    try {
      const r = await fetch('/api/voice/realtime/session', { method: 'POST' });
      if (!r.ok) { toast('live voice unavailable', 'error'); return; }
      const d = await r.json();
      // a realtime provider is configured → negotiate the full-duplex session with it here
      toast(`live voice ready — ${d.model}`, 'success');
    } catch { toast('live voice failed', 'error'); }
  };
}

export function isRecording() { return _recording; }

export async function startRecording() {
  if (_recording) return;
  const s = await fetch('/api/settings').then(r => r.json()).catch(() => ({}));
  const provider = s.stt_provider || 'browser';

  const micId = localStorage.getItem('alles-mic-id') || '';
  const audio = { echoCancellation: true, noiseSuppression: true, autoGainControl: true };
  if (micId) audio.deviceId = { exact: micId };
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio });
  } catch {
    // the saved device may be gone — fall back to the default mic before giving up
    try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }); }
    catch { toast('mic access denied', 'error'); return; }
  }
  _stream = stream;
  _recording = true;
  _setMicRecording(true);
  _startLiveWave(stream);

  if (provider === 'browser') {
    _mode = 'browser';
    _startBrowserSR(s);
  } else {
    // whisper_api OR local — record audio + upload to /api/stt (server picks engine)
    _mode = 'whisper';
    _chunks = [];
    _recorder = new MediaRecorder(stream);
    _recorder.ondataavailable = e => _chunks.push(e.data);
    _recorder.onstop = _whisperDone;
    _recorder.start();
  }
}

// live speech recognition — the only browser API that actually transcribes
function _startBrowserSR(s) {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) {
    toast('speech recognition needs Chrome/Edge — or switch STT to Whisper in settings', 'error');
    _recording = false; _setMicRecording(false);
    _stream?.getTracks().forEach(t => t.stop());
    return;
  }
  _srText = '';
  _srFatal = false;
  _sr = new SR();
  _sr.continuous = true;
  _sr.interimResults = true;
  if (s.stt_language) _sr.lang = s.stt_language;

  _sr.onresult = e => {
    let fin = '';
    for (let i = e.resultIndex; i < e.results.length; i++) {
      if (e.results[i].isFinal) fin += e.results[i][0].transcript;
    }
    if (fin.trim()) _srText += (_srText ? ' ' : '') + fin.trim();
  };
  _sr.onerror = e => {
    if (e.error === 'no-speech' || e.error === 'aborted') return;   // benign
    _srFatal = true;   // real error — do NOT restart (avoids toast storm)
    if (e.error === 'network') toast('speech recognition needs internet', 'error');
    else if (e.error === 'not-allowed' || e.error === 'service-not-allowed') toast('mic blocked', 'error');
    else toast('speech error: ' + e.error, 'error');
    stopRecording();
  };
  _sr.onend = () => {
    // only auto-restart on a benign silence timeout while still recording
    if (_recording && !_srFatal) { try { _sr.start(); return; } catch {} }
    const text = _srText.trim();
    _sr = null;
    if (text) _inject(text);
    else if (!_srFatal) toast('no speech detected', 'error');   // stay quiet after a real error
  };
  try { _sr.start(); } catch {}
}

export function stopRecording() {
  if (!_recording) return;
  _recording = false;
  _setMicRecording(false);   // also stops the wave
  if (_mode === 'whisper') {
    try { _recorder?.stop(); } catch {}
  } else {
    try { _sr?.stop(); } catch {}   // → onend → inject
  }
  _stream?.getTracks().forEach(t => t.stop());
  _stream = null;
}

function _setMicRecording(on) {
  // ONLY the mic button becomes the stop control — the send button is left
  // alone (was turning into a 2nd stop square, which looked like two close btns)
  const btn = document.getElementById('mic-btn');
  const box = document.querySelector('.composer-box');
  if (!btn) return;
  if (!_micIdleHtml) _micIdleHtml = btn.innerHTML;
  btn.classList.toggle('recording', on);
  btn.setAttribute('aria-pressed', String(on));
  btn.title = on ? 'stop recording' : 'voice input';
  btn.innerHTML = on
    ? '<svg viewBox="0 0 24 24" fill="none"><rect x="7" y="7" width="10" height="10" rx="1.5" fill="currentColor"/></svg>'
    : _micIdleHtml;
  if (box) box.classList.toggle('mic-recording', on);
  if (on) _recStart = (typeof performance !== 'undefined' ? performance.now() : Date.now());
  else { _recStart = 0; _stopLiveWave(); }
}

// the mic's current loudness, 0..1 (RMS off the analyser). null → not live.
function _micAmp() {
  if (!_analyser) return null;
  const td = new Uint8Array(_analyser.fftSize);
  _analyser.getByteTimeDomainData(td);
  let sum = 0;
  for (let i = 0; i < td.length; i++) { const v = (td[i] - 128) / 128; sum += v * v; }
  return Math.min(1, Math.sqrt(sum / td.length) * 9);
}

// apple voice-memos waveform: centered rounded bars scrolling left, height = loudness,
// with a live MM:SS timer on the left. getAmp()→0..1 (null stops). withTimer draws the clock.
function _roundBar(ctx, x, y, w, h) {
  const r = Math.min(w / 2, h / 2);
  ctx.beginPath();
  ctx.moveTo(x, y + r);
  ctx.arcTo(x, y, x + r, y, r);
  ctx.arcTo(x + w, y, x + w, y + r, r);
  ctx.lineTo(x + w, y + h - r);
  ctx.arcTo(x + w, y + h, x + w - r, y + h, r);
  ctx.arcTo(x, y + h, x, y + h - r, r);
  ctx.closePath();
  ctx.fill();
}

function _runDotWave(canvas, getAmp, withTimer) {
  if (!canvas) return;
  canvas.width  = canvas.offsetWidth  || 360;
  canvas.height = canvas.offsetHeight || 52;
  const ctx = canvas.getContext('2d');
  const W = canvas.width, H = canvas.height, cy = H / 2;
  const barW = 2.6, gap = 2.2, step = barW + gap;
  const cap = Math.max(16, Math.floor(W / step));
  const hist = [];
  const color = '#ff453a';   // apple recording red
  let smooth = 0;

  const tick = () => {
    const a = getAmp();
    if (a == null) { _stopDotWave(); ctx.clearRect(0, 0, W, H); return; }
    _waveRaf = requestAnimationFrame(tick);
    smooth += (a - smooth) * 0.4;
    hist.push(Math.min(1, smooth));
    if (hist.length > cap) hist.shift();
    ctx.clearRect(0, 0, W, H);

    // left timer (voice-memos style)
    let leftPad = 4;
    if (withTimer && _recStart) {
      const now = (typeof performance !== 'undefined' ? performance.now() : Date.now());
      const s = Math.max(0, Math.floor((now - _recStart) / 1000));
      const t = Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0');
      ctx.fillStyle = 'rgba(232,230,227,0.75)';
      ctx.font = '600 12px ui-monospace, SFMono-Regular, monospace';
      ctx.textBaseline = 'middle';
      ctx.fillText(t, 4, cy + 0.5);
      leftPad = ctx.measureText(t).width + 14;
    }

    // rounded bars, newest on the right, scrolling left, mirrored around the centre
    ctx.fillStyle = color;
    const usableW = W - leftPad - 4;
    const n = Math.min(hist.length, Math.floor(usableW / step));
    const startX = W - 4 - n * step;
    for (let i = 0; i < n; i++) {
      const v = hist[hist.length - n + i] || 0;
      const h = Math.max(barW, v * (H - 8));
      _roundBar(ctx, startX + i * step, cy - h / 2, barW, h);
    }
  };
  tick();
}

function _stopDotWave() {
  if (_waveRaf) cancelAnimationFrame(_waveRaf);
  _waveRaf = 0;
}

function _startLiveWave(stream) {
  try {
    _audioCtx = new AudioContext();
    _analyser = _audioCtx.createAnalyser();
    _analyser.fftSize = 1024;
    _audioCtx.createMediaStreamSource(stream).connect(_analyser);
    _runDotWave(document.getElementById('mic-wave'), _micAmp, true);
  } catch {}
}

function _stopLiveWave() {
  _stopDotWave();
  _analyser = null;
  if (_audioCtx) _audioCtx.close().catch(() => {});
  _audioCtx = null;
}

async function _whisperDone() {
  const blob = new Blob(_chunks, { type: 'audio/webm' });
  const fd = new FormData();
  fd.append('file', blob, 'audio.webm');
  try {
    const r = await fetch('/api/stt', { method: 'POST', body: fd });
    if (!r.ok) {
      const msg = await r.text().catch(() => '');
      try { toast(JSON.parse(msg).detail || 'transcription failed', 'error'); }
      catch { toast('transcription failed', 'error'); }
      return;
    }
    const { text } = await r.json();
    if (text && text.trim()) _inject(text.trim());
    else toast('no speech detected', 'error');
  } catch (e) {
    toast('transcription failed', 'error');
  }
}

function _inject(text) {
  const ta = document.getElementById('composer-ta');
  if (!ta || !text) return;
  ta.value = (ta.value ? ta.value + ' ' : '') + text;
  ta.dispatchEvent(new Event('input'));
  ta.focus();
}

// the little floating dot-wave shown while the assistant is talking (same look as
// the mic wave). real levels when we own the audio (openai), a synthetic pulse for
// the browser voice (speechSynthesis gives us no audio graph to tap).
function _outWaveStart(getAmp) {
  if (_recording) return;   // don't fight the input wave
  const pop = document.getElementById('tts-wave');
  if (!pop) return;
  pop.hidden = false;
  _runDotWave(pop.querySelector('canvas'), getAmp);
}
function _outWaveStop() {
  _stopDotWave();
  const pop = document.getElementById('tts-wave');
  if (pop) pop.hidden = true;
}

// voiceOverride lets the audio-overview play two hosts in distinct voices.
// resolves when playback finishes so callers can narrate segments in sequence.
export async function speak(text, voiceOverride) {
  const s = await fetch('/api/settings').then(r => r.json()).catch(() => ({}));
  const provider = s.tts_provider || 'browser';

  if (provider === 'openai') {
    try {
      const r = await fetch('/api/tts', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ text, voice: voiceOverride || s.tts_voice || 'alloy' }),
      });
      if (!r.ok) throw new Error(await r.text());
      const buf = await r.arrayBuffer();
      const ctx = new AudioContext();
      const decoded = await ctx.decodeAudioData(buf);
      const src = ctx.createBufferSource();
      src.buffer = decoded;
      const an = ctx.createAnalyser(); an.fftSize = 1024;
      src.connect(an); an.connect(ctx.destination);
      const td = new Uint8Array(an.fftSize);
      let ended = false;
      await new Promise(resolve => {
        src.onended = () => { ended = true; _outWaveStop(); ctx.close().catch(() => {}); resolve(); };
        src.start();
        _outWaveStart(() => {
          if (ended) return null;
          an.getByteTimeDomainData(td);
          let sum = 0; for (let i = 0; i < td.length; i++) { const v = (td[i] - 128) / 128; sum += v * v; }
          return Math.min(1, Math.sqrt(sum / td.length) * 9);
        });
      });
    } catch (e) {
      toast('TTS failed — falling back to browser', 'error');
      await _browserSpeak(text);
    }
  } else {
    await _browserSpeak(text);
  }
}

async function _browserSpeak(text) {
  const s = await fetch('/api/settings').then(r => r.json()).catch(() => ({}));
  const utt = new SpeechSynthesisUtterance(text.slice(0, 600));
  if (s.tts_speed) utt.rate = parseFloat(s.tts_speed);
  if (s.stt_language) utt.lang = s.stt_language;
  window.speechSynthesis.cancel();   // clear any stuck utterance (a common 'mic/voice broken' cause)
  await new Promise(resolve => {
    let speaking = true;
    utt.onend = utt.onerror = () => { speaking = false; _outWaveStop(); resolve(); };
    window.speechSynthesis.speak(utt);
    let t = 0;
    _outWaveStart(() => {
      if (!speaking && !window.speechSynthesis.speaking) return null;
      t += 0.3;
      return 0.3 + 0.32 * Math.abs(Math.sin(t)) + 0.14 * Math.abs(Math.sin(t * 2.7));
    });
  });
}
