// journal — one entry per day. mood + tags + prompt + streak + on-this-day + AI reflect.
import { toast, mdToHtml } from './util.js';

const MOODS = ['😄', '🙂', '😐', '😕', '😢', '😠', '😴', '🤔', '🥳', '😍'];
let _day = todayISO();
let _saveTimer = null;
let _built = false;

function todayISO() { return new Date().toISOString().slice(0, 10); }
function esc(s = '') { return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }
function shift(iso, n) { const d = new Date(iso + 'T00:00:00'); d.setDate(d.getDate() + n); return d.toISOString().slice(0, 10); }
function pretty(iso) {
  const d = new Date(iso + 'T00:00:00');
  return d.toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' });
}

async function jget(url) { const r = await fetch(url); if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.status); return r.json(); }
async function jput(url, body) {
  const r = await fetch(url, { method: 'PUT', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
  if (!r.ok) throw new Error('save failed');
  return r.json();
}

export function initJournal() {
  const body = document.getElementById('journal-body');
  if (!body) return;
  if (!_built) {
    body.innerHTML = `
      <div class="jrnl-wrap">
        <div class="jrnl-main">
          <div class="jrnl-datebar">
            <button class="btn" id="jrnl-prev" title="previous day">‹</button>
            <div class="jrnl-date" id="jrnl-date"></div>
            <button class="btn" id="jrnl-next" title="next day">›</button>
            <button class="btn" id="jrnl-today">today</button>
            <span class="jrnl-words" id="jrnl-words"></span>
          </div>
          <div class="jrnl-prompt" id="jrnl-prompt"></div>
          <div class="jrnl-moods" id="jrnl-moods">${MOODS.map(m => `<button class="jrnl-mood" data-m="${m}">${m}</button>`).join('')}</div>
          <textarea id="jrnl-text" class="jrnl-text" placeholder="how was your day?"></textarea>
          <input id="jrnl-tags" class="jrnl-tags" placeholder="tags (comma separated)">
          <div class="jrnl-actions">
            <button class="btn primary" id="jrnl-save">save</button>
            <button class="btn" id="jrnl-reflect">✨ reflect</button>
            <span class="jrnl-saved" id="jrnl-saved"></span>
          </div>
          <div class="jrnl-reflection" id="jrnl-reflection" style="display:none"></div>
        </div>
        <div class="jrnl-side">
          <input id="jrnl-search" class="jrnl-tags" placeholder="search entries…" style="margin:0 0 0.5rem">
          <div id="jrnl-results"></div>
          <button class="btn" id="jrnl-export" style="margin-bottom:0.6rem">export .md</button>
          <div class="jrnl-side-title">on this day</div>
          <div id="jrnl-otd" class="jrnl-otd"><div class="jrnl-empty">nothing from past years yet</div></div>
          <div class="jrnl-side-title">recent</div>
          <div id="jrnl-recent" class="jrnl-recent"></div>
        </div>
      </div>`;

    document.getElementById('jrnl-prev').onclick = () => { _day = shift(_day, -1); load(); };
    document.getElementById('jrnl-next').onclick = () => { _day = shift(_day, 1); load(); };
    document.getElementById('jrnl-today').onclick = () => { _day = todayISO(); load(); };
    document.getElementById('jrnl-save').onclick = () => save(true);
    document.getElementById('jrnl-reflect').onclick = reflect;
    document.getElementById('jrnl-text').addEventListener('input', () => {
      updateWords();
      clearTimeout(_saveTimer);
      _saveTimer = setTimeout(() => save(false), 1200);   // gentle autosave
    });
    document.getElementById('jrnl-moods').addEventListener('click', e => {
      const b = e.target.closest('.jrnl-mood'); if (!b) return;
      const on = b.classList.contains('active');
      document.querySelectorAll('.jrnl-mood').forEach(x => x.classList.remove('active'));
      if (!on) b.classList.add('active');
      save(false);
    });
    let _js;
    document.getElementById('jrnl-search').addEventListener('input', e => {
      clearTimeout(_js);
      const q = e.target.value.trim();
      const box = document.getElementById('jrnl-results');
      if (!q) { box.innerHTML = ''; return; }
      _js = setTimeout(async () => {
        const d = await jget('/api/journal/search?q=' + encodeURIComponent(q));
        box.innerHTML = d.results.map(r =>
          `<div class="jrnl-otd-row" data-d="${r.date}"><b>${r.date}</b> ${r.mood || ''} ${esc(r.snippet)}</div>`).join('')
          || '<div class="jrnl-empty">no matches</div>';
        box.querySelectorAll('.jrnl-otd-row').forEach(x => x.onclick = () => { _day = x.dataset.d; load(); });
      }, 250);
    });
    document.getElementById('jrnl-export').addEventListener('click', async () => {
      const d = await jget('/api/journal/export');
      const a = document.createElement('a');
      a.href = URL.createObjectURL(new Blob([d.markdown], { type: 'text/markdown' }));
      a.download = 'journal.md'; a.click();
      URL.revokeObjectURL(a.href);
    });
    _built = true;
  }
  load();
  loadPrompt();
  loadOnThisDay();
}

function curMood() { return document.querySelector('.jrnl-mood.active')?.dataset.m || ''; }

async function load() {
  document.getElementById('jrnl-date').textContent = pretty(_day) + (_day === todayISO() ? '' : '');
  document.getElementById('jrnl-next').disabled = _day >= todayISO();
  try {
    const e = await jget('/api/journal/' + _day);
    document.getElementById('jrnl-text').value = e.content || '';
    document.getElementById('jrnl-tags').value = e.tags || '';
    document.querySelectorAll('.jrnl-mood').forEach(x => x.classList.toggle('active', x.dataset.m === e.mood));
    document.getElementById('jrnl-reflection').style.display = 'none';
    document.getElementById('jrnl-saved').textContent = '';
    updateWords();
  } catch { /* fresh shell is fine */ }
  loadStats();
  loadRecent();
}

function updateWords() {
  const n = (document.getElementById('jrnl-text').value.trim().match(/\S+/g) || []).length;
  document.getElementById('jrnl-words').textContent = n ? `${n} word${n === 1 ? '' : 's'}` : '';
}

async function save(explicit) {
  const content = document.getElementById('jrnl-text').value;
  const tags = document.getElementById('jrnl-tags').value;
  try {
    await jput('/api/journal/' + _day, { content, mood: curMood(), tags });
    document.getElementById('jrnl-saved').textContent = 'saved ' + new Date().toLocaleTimeString();
    if (explicit) toast('entry saved', 'success');
    loadStats(); loadRecent();
  } catch (e) {
    if (explicit) toast(e.message || 'save failed', 'error');
  }
}

async function loadStats() {
  try {
    const d = await jget('/api/journal');
    const s = d.stats || {};
    const el = document.getElementById('journal-stats');
    if (el) el.textContent = `🔥 ${s.streak || 0} day streak · ${s.total || 0} entries · ${s.this_month || 0} this month`;
  } catch {}
}

async function loadPrompt() {
  try {
    const d = await jget('/api/journal/prompt');
    const el = document.getElementById('jrnl-prompt');
    if (el) el.textContent = '“' + d.prompt + '”';
  } catch {}
}

async function loadOnThisDay() {
  try {
    const d = await jget('/api/journal/on-this-day');
    const el = document.getElementById('jrnl-otd');
    if (!el) return;
    if (!d.entries.length) { el.innerHTML = '<div class="jrnl-empty">nothing from past years yet</div>'; return; }
    el.innerHTML = d.entries.map(e =>
      `<div class="jrnl-otd-row" data-d="${e.date}"><b>${e.date.slice(0, 4)}</b> ${e.mood || ''} ${esc((e.content || '').slice(0, 90))}…</div>`
    ).join('');
    el.querySelectorAll('.jrnl-otd-row').forEach(r => r.onclick = () => { _day = r.dataset.d; load(); });
  } catch {}
}

async function loadRecent() {
  try {
    const d = await jget('/api/journal?limit=30');
    const el = document.getElementById('jrnl-recent');
    if (!el) return;
    el.innerHTML = (d.entries || []).map(e =>
      `<div class="jrnl-recent-row ${e.date === _day ? 'active' : ''}" data-d="${e.date}">
        <span class="jrnl-recent-mood">${e.mood || '·'}</span>
        <span class="jrnl-recent-date">${e.date}</span>
        <span class="jrnl-recent-snip">${esc((e.content || '').slice(0, 60))}</span>
      </div>`
    ).join('') || '<div class="jrnl-empty">no entries yet — write one</div>';
    el.querySelectorAll('.jrnl-recent-row').forEach(r => r.onclick = () => { _day = r.dataset.d; load(); });
  } catch {}
}

async function reflect() {
  const btn = document.getElementById('jrnl-reflect');
  const box = document.getElementById('jrnl-reflection');
  if (!document.getElementById('jrnl-text').value.trim()) { toast('write something first', 'error'); return; }
  await save(false);
  btn.disabled = true; btn.textContent = 'reflecting…';
  try {
    const r = await fetch('/api/journal/' + _day + '/reflect', { method: 'POST' });
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || 'reflect failed');
    box.innerHTML = mdToHtml(d.reflection || '');
    box.style.display = 'block';
  } catch (e) {
    toast(e.message || 'reflect failed', 'error');
  }
  btn.disabled = false; btn.textContent = '✨ reflect';
}
