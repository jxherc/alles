import { toast } from './util.js';

let _recorder = null;
let _chunks = [];
let _recording = false;
let _micIdleHtml = '';
let _sendIdleHtml = '';
let _audioCtx = null;
let _analyser = null;
let _waveRaf = 0;
let _sr = null;          // browser SpeechRecognition (live)
let _srText = '';        // accumulated transcript
let _srFatal = false;    // stop restarting after a real error
let _stream = null;      // active mic stream
let _mode = 'browser';

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
  if (!on) _stopLiveWave();
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

// dotted waveform — a field of equal dots, columns scrolling left, each column's
// height = loudness. apple-voice-memos vibe but made of dots. getAmp()→0..1 (null stops).
function _runDotWave(canvas, getAmp) {
  if (!canvas) return;
  canvas.width  = canvas.offsetWidth  || 360;
  canvas.height = canvas.offsetHeight || 40;
  const ctx = canvas.getContext('2d');
  const W = canvas.width, H = canvas.height, cy = H / 2;
  // small + tight = a finer, more accurate trace (not a chunky purple blob)
  const colGap = 4, dotR = 1.1, rowGap = 3.4;
  const cols = Math.max(8, Math.floor(W / colGap));
  const maxRows = Math.max(2, Math.floor((cy - dotR) / rowGap));
  const hist = new Array(cols).fill(0);
  const left = (W - cols * colGap) / 2 + colGap / 2;
  const color = '#f87171';   // voice waveform = red
  let smooth = 0;

  const dot = (x, y, a) => { ctx.globalAlpha = a; ctx.beginPath(); ctx.arc(x, y, dotR, 0, 7); ctx.fill(); };

  const tick = () => {
    const a = getAmp();
    if (a == null) { _stopDotWave(); ctx.clearRect(0, 0, W, H); return; }
    _waveRaf = requestAnimationFrame(tick);
    smooth += (a - smooth) * 0.35;
    hist.push(Math.min(1, smooth)); hist.shift();
    ctx.clearRect(0, 0, W, H);
    ctx.fillStyle = color;
    for (let i = 0; i < cols; i++) {
      const x = left + i * colGap;
      const lit = Math.round(hist[i] * maxRows);
      dot(x, cy, 0.22);                              // faint baseline dot
      for (let r = 1; r <= lit; r++) {
        const al = 1 - (r / maxRows) * 0.55;
        dot(x, cy - r * rowGap, al);
        dot(x, cy + r * rowGap, al);
      }
    }
    ctx.globalAlpha = 1;
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
    _runDotWave(document.getElementById('mic-wave'), _micAmp);
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

export async function speak(text) {
  const s = await fetch('/api/settings').then(r => r.json()).catch(() => ({}));
  const provider = s.tts_provider || 'browser';

  if (provider === 'openai') {
    try {
      const r = await fetch('/api/tts', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ text, voice: s.tts_voice || 'alloy' }),
      });
      if (!r.ok) throw new Error(await r.text());
      const buf = await r.arrayBuffer();
      const ctx = new AudioContext();
      const decoded = await ctx.decodeAudioData(buf);
      const src = ctx.createBufferSource();
      src.buffer = decoded;
      const an = ctx.createAnalyser(); an.fftSize = 1024;
      src.connect(an); an.connect(ctx.destination);
      let ended = false;
      src.onended = () => { ended = true; _outWaveStop(); ctx.close().catch(() => {}); };
      src.start();
      const td = new Uint8Array(an.fftSize);
      _outWaveStart(() => {
        if (ended) return null;
        an.getByteTimeDomainData(td);
        let sum = 0; for (let i = 0; i < td.length; i++) { const v = (td[i] - 128) / 128; sum += v * v; }
        return Math.min(1, Math.sqrt(sum / td.length) * 9);
      });
    } catch (e) {
      toast('TTS failed — falling back to browser', 'error');
      _browserSpeak(text);
    }
  } else {
    _browserSpeak(text);
  }
}

async function _browserSpeak(text) {
  const s = await fetch('/api/settings').then(r => r.json()).catch(() => ({}));
  const utt = new SpeechSynthesisUtterance(text.slice(0, 200));
  if (s.tts_speed) utt.rate = parseFloat(s.tts_speed);
  if (s.stt_language) utt.lang = s.stt_language;
  let speaking = true;
  utt.onend = utt.onerror = () => { speaking = false; _outWaveStop(); };
  window.speechSynthesis.cancel();   // clear any stuck utterance (a common 'mic/voice broken' cause)
  window.speechSynthesis.speak(utt);
  let t = 0;
  _outWaveStart(() => {
    if (!speaking && !window.speechSynthesis.speaking) return null;
    t += 0.3;
    return 0.3 + 0.32 * Math.abs(Math.sin(t)) + 0.14 * Math.abs(Math.sin(t * 2.7));
  });
}
