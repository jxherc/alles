import { toast } from './util.js';

let _recorder = null;
let _chunks = [];
let _recording = false;

export function isRecording() { return _recording; }

export async function startRecording() {
  if (_recording) return;
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    _chunks = [];
    _recorder = new MediaRecorder(stream);
    _recorder.ondataavailable = e => _chunks.push(e.data);
    _recorder.onstop = _onStop;
    _recorder.start();
    _recording = true;
    document.getElementById('mic-btn')?.classList.add('recording');
  } catch (e) {
    toast('mic access denied', 'error');
  }
}

export function stopRecording() {
  if (!_recorder || !_recording) return;
  _recorder.stop();
  _recorder.stream?.getTracks().forEach(t => t.stop());
  _recording = false;
  document.getElementById('mic-btn')?.classList.remove('recording');
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

function _browserSpeak(text) {
  const utt = new SpeechSynthesisUtterance(text.slice(0, 200));
  window.speechSynthesis.speak(utt);
}
