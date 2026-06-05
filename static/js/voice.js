import { toast } from './util.js';

let _recorder = null;
let _chunks = [];
let _recording = false;
let _micIdleHtml = '';
let _sendIdleHtml = '';
let _audioCtx = null;
let _analyser = null;
let _waveRaf = 0;

export function isRecording() { return _recording; }

export async function startRecording() {
  if (_recording) return;
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    _chunks = [];
    _recorder = new MediaRecorder(stream);
    _recording = true;        // must be true before tick loop starts
    _setMicRecording(true);   // show #mic-wave before driving bars
    _startLiveWave(stream);
    _recorder.ondataavailable = e => _chunks.push(e.data);
    _recorder.onstop = _onStop;
    _recorder.start();
  } catch (e) {
    toast('mic access denied', 'error');
  }
}

export function stopRecording() {
  if (!_recorder || !_recording) return;
  _recorder.stop();
  _recorder.stream?.getTracks().forEach(t => t.stop());
  _recording = false;
  _setMicRecording(false);
}

function _setMicRecording(on) {
  const btn = document.getElementById('mic-btn');
  const box = document.querySelector('.composer-box');
  const send = document.getElementById('send-btn');
  if (!btn) return;
  if (!_micIdleHtml) _micIdleHtml = btn.innerHTML;
  if (send && !_sendIdleHtml) _sendIdleHtml = send.innerHTML;
  btn.classList.toggle('recording', on);
  btn.setAttribute('aria-pressed', String(on));
  btn.innerHTML = on
    ? '<svg viewBox="0 0 24 24" fill="none"><rect x="8" y="8" width="8" height="8" rx="1" fill="currentColor"/></svg> stop'
    : _micIdleHtml;
  if (send) {
    send.classList.toggle('recording', on);
    send.title = on ? 'stop recording' : '';
    // simple stop square when recording — wave is now on #mic-wave
    send.innerHTML = on
      ? '<svg viewBox="0 0 24 24" fill="none"><rect x="7" y="7" width="10" height="10" rx="1" fill="currentColor"/></svg>'
      : _sendIdleHtml;
  }
  if (box) box.classList.toggle('mic-recording', on);
  if (!on) _stopLiveWave();
}

function _startLiveWave(stream) {
  try {
    _audioCtx = new AudioContext();
    _analyser = _audioCtx.createAnalyser();
    _analyser.fftSize = 512;
    _audioCtx.createMediaStreamSource(stream).connect(_analyser);
    const data = new Uint8Array(_analyser.frequencyBinCount);
    const tick = () => {
      if (!_recording || !_analyser) return;
      _analyser.getByteFrequencyData(data);
      // drive #mic-wave bars — full-width live waveform
      const bars = document.querySelectorAll('#mic-wave span');
      const step = Math.max(1, Math.floor(data.length / Math.max(1, bars.length)));
      bars.forEach((bar, i) => {
        let sum = 0;
        for (let j = i * step; j < Math.min(data.length, (i + 1) * step); j++) sum += data[j];
        const avg = sum / step / 255;
        bar.style.setProperty('--level', String(Math.max(0.06, Math.min(1, avg * 2.4))));
      });
      _waveRaf = requestAnimationFrame(tick);
    };
    tick();
  } catch {}
}

function _stopLiveWave() {
  if (_waveRaf) cancelAnimationFrame(_waveRaf);
  _waveRaf = 0;
  _analyser = null;
  if (_audioCtx) _audioCtx.close().catch(() => {});
  _audioCtx = null;
}

async function _onStop() {
  const blob = new Blob(_chunks, { type: 'audio/webm' });
  const s = await fetch('/api/settings').then(r => r.json()).catch(() => ({}));
  const provider = s.stt_provider || 'browser';

  if (provider === 'whisper_api') {
    const fd = new FormData();
    fd.append('file', blob, 'audio.webm');
    try {
      const r = await fetch('/api/stt', { method: 'POST', body: fd });
      if (!r.ok) throw new Error(await r.text());
      const { text } = await r.json();
      _inject(text);
    } catch (e) {
      toast('transcription failed — check openai_api_key', 'error');
    }
  } else {
    // browser STT fallback
    if (!('webkitSpeechRecognition' in window) && !('SpeechRecognition' in window)) {
      toast('speech recognition not available in this browser', 'error');
      return;
    }
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    const rec = new SR();
    if (s.stt_language) rec.lang = s.stt_language;
    rec.onresult = e => _inject(e.results[0][0].transcript);
    rec.onerror = () => toast('speech recognition error', 'error');
    rec.start();
  }
}

function _inject(text) {
  const ta = document.getElementById('composer-ta');
  if (!ta || !text) return;
  ta.value = (ta.value ? ta.value + ' ' : '') + text;
  ta.dispatchEvent(new Event('input'));
  ta.focus();
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
      src.connect(ctx.destination);
      src.start();
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
  window.speechSynthesis.speak(utt);
}
