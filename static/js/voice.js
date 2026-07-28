import { toast } from './util.js';

let _recorder = null;
let _chunks = [];
let _recording = false;
let _starting = false;
let _settling = false;
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
let _take = 0;           // invalidates late callbacks after cancel or a newer recording
let _transcriptionAbort = null;

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

export function isRecording() { return _recording || _starting || _settling; }

export async function startRecording() {
  if (_recording || _starting || _settling) return;
  _starting = true;
  const take = ++_take;
  _chunks = [];
  _recorder = null;
  _sr = null;
  try {
    const s = await fetch('/api/settings').then(r => r.json()).catch(() => ({}));
    if (take !== _take) return;
    const provider = s.stt_provider || 'browser';
    const micId = localStorage.getItem('alles-mic-id') || '';
    const audio = { echoCancellation: true, noiseSuppression: true, autoGainControl: true };
    if (micId) audio.deviceId = { exact: micId };
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio });
    } catch (error) {
      // Retry only when a saved device is unavailable. Permission denial must
      // not trigger a second browser prompt for the default microphone.
      if (take !== _take) return;
      const retryDefault = Boolean(micId && [
        'AbortError', 'NotFoundError', 'NotReadableError', 'OverconstrainedError',
      ].includes(error?.name));
      if (!retryDefault) {
        const denied = ['NotAllowedError', 'SecurityError'].includes(error?.name);
        toast(denied ? 'mic access denied' : 'voice recording could not start', 'error');
        return;
      }
      try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }); }
      catch (fallbackError) {
        const denied = ['NotAllowedError', 'SecurityError'].includes(fallbackError?.name);
        toast(denied ? 'mic access denied' : 'voice recording could not start', 'error');
        return;
      }
    }
    if (take !== _take) {
      stream.getTracks().forEach(track => track.stop());
      return;
    }
    _stream = stream;
    _recording = true;
    _setMicRecording(true);
    _startLiveWave(stream);

    if (provider === 'browser') {
      _mode = 'browser';
      _startBrowserSR(s, take);
    } else {
      // whisper_api OR local — record audio + upload to /api/stt (server picks engine)
      _mode = 'whisper';
      const chunks = [];
      _chunks = chunks;
      _recorder = new MediaRecorder(stream);
      _recorder.ondataavailable = e => { if (take === _take) chunks.push(e.data); };
      _recorder.onstop = () => _whisperDone(take, chunks);
      _recorder.start();
    }
  } catch (error) {
    if (take === _take) {
      _recording = false;
      _settling = false;
      _recorder = null;
      _sr = null;
      _setMicRecording(false);
      _stream?.getTracks().forEach(track => track.stop());
      _stream = null;
      toast(`voice recording could not start: ${error?.message || 'unavailable'}`, 'error');
    }
  } finally {
    if (take === _take) _starting = false;
  }
}

// live speech recognition — the only browser API that actually transcribes
function _startBrowserSR(s, take) {
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
    if (take !== _take) return;
    let fin = '';
    for (let i = e.resultIndex; i < e.results.length; i++) {
      if (e.results[i].isFinal) fin += e.results[i][0].transcript;
    }
    if (fin.trim()) _srText += (_srText ? ' ' : '') + fin.trim();
  };
  _sr.onerror = e => {
    if (take !== _take) return;
    if (e.error === 'no-speech' || e.error === 'aborted') return;   // benign
    _srFatal = true;   // real error — do NOT restart (avoids toast storm)
    if (e.error === 'network') toast('speech recognition needs internet', 'error');
    else if (e.error === 'not-allowed' || e.error === 'service-not-allowed') toast('mic blocked', 'error');
    else toast('speech error: ' + e.error, 'error');
    stopRecording();
  };
  _sr.onend = () => {
    if (take !== _take) return;
    // only auto-restart on a benign silence timeout while still recording
    if (_recording && !_srFatal) { try { _sr.start(); return; } catch {} }
    const text = _srText.trim();
    _sr = null;
    _settling = false;
    if (text) _inject(text);
    else if (!_srFatal) toast('no speech detected', 'error');   // stay quiet after a real error
  };
  try { _sr.start(); } catch {
    _sr = null;
    _recording = false;
    _settling = false;
    _setMicRecording(false);
    _stream?.getTracks().forEach(track => track.stop());
    _stream = null;
    toast('speech recognition could not start', 'error');
  }
}

export function stopRecording() {
  if (!_recording) {
    if (_starting || _settling) cancelRecording();
    return;
  }
  _recording = false;
  _setMicRecording(false);   // also stops the wave
  if (_mode === 'whisper') {
    _settling = Boolean(_recorder);
    try { _recorder?.stop(); } catch { _settling = false; }
  } else {
    _settling = Boolean(_sr);
    try { _sr?.stop(); } catch { _settling = false; }   // → onend → inject
  }
  _stream?.getTracks().forEach(t => t.stop());
  _stream = null;
}

export function cancelRecording() {
  if (!_recording && !_starting && !_settling) return;
  _take += 1;
  _starting = false;
  _recording = false;
  _settling = false;
  _transcriptionAbort?.abort();
  _transcriptionAbort = null;
  _setMicRecording(false);
  if (_mode === 'whisper') {
    try { _recorder?.stop(); } catch {}
  } else {
    try { _sr?.abort(); } catch {}
  }
  _stream?.getTracks().forEach(track => track.stop());
  _stream = null;
  _chunks = [];
  _recorder = null;
  _sr = null;
  toast('recording cancelled');
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
  btn.title = on ? 'stop recording · esc cancels' : 'voice input';
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

async function _whisperDone(take, chunks) {
  if (take !== _take) return;
  const blob = new Blob(chunks, { type: 'audio/webm' });
  const fd = new FormData();
  fd.append('file', blob, 'audio.webm');
  const controller = new AbortController();
  let timedOut = false;
  const timeout = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, 60_000);
  _transcriptionAbort = controller;
  try {
    const r = await fetch('/api/stt', { method: 'POST', body: fd, signal: controller.signal });
    if (!r.ok) {
      const msg = await r.text().catch(() => '');
      if (take !== _take) return;
      try { toast(JSON.parse(msg).detail || 'transcription failed', 'error'); }
      catch { toast('transcription failed', 'error'); }
      return;
    }
    const { text } = await r.json();
    if (take !== _take) return;
    if (text && text.trim()) _inject(text.trim());
    else toast('no speech detected', 'error');
  } catch (e) {
    if (timedOut && take === _take) toast('transcription timed out', 'error');
    else if (e?.name !== 'AbortError' && take === _take) toast('transcription failed', 'error');
  } finally {
    clearTimeout(timeout);
    if (_transcriptionAbort === controller) _transcriptionAbort = null;
    if (take === _take) {
      _settling = false;
      _chunks = [];
      _recorder = null;
    }
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
