import { mdToHtml, escapeHtml } from './util.js';

let _returnFocus = null;

export function openArtifact(content, type, title, lang = '') {
  const panel = document.getElementById('artifact-panel');
  if (!panel.classList.contains('open')) _returnFocus = document.activeElement;
  panel.querySelector('.artifact-title').textContent = title || 'artifact';
  panel.querySelector('.artifact-type-badge').textContent = type;

  const body = panel.querySelector('.artifact-body');
  body.innerHTML = '';

  if (type === 'html' || type === 'svg') {
    const iframe = document.createElement('iframe');
    iframe.className = 'artifact-iframe';
    iframe.sandbox = 'allow-scripts';
    iframe.srcdoc = content;
    body.appendChild(iframe);
  } else {
    const div = document.createElement('div');
    div.className = 'artifact-content';
    if (type === 'code') {
      div.innerHTML = `<pre><code class="${lang ? 'language-' + lang : ''}">${escapeHtml(content)}</code></pre>`;
    } else {
      div.innerHTML = mdToHtml(content);
    }
    body.appendChild(div);
  }

  document.querySelector('.app').classList.add('artifact-open');
  panel.classList.add('open');
  panel.inert = false;
  document.getElementById('artifact-close-btn')?.focus();
}

export function closeArtifactPanel() {
  const panel = document.getElementById('artifact-panel');
  const returnFocus = panel.contains(document.activeElement);
  document.querySelector('.app').classList.remove('artifact-open');
  panel.classList.remove('open');
  panel.inert = true;
  if (returnFocus) _returnFocus?.focus();
  _returnFocus = null;
}

export function extractArtifacts(text) {
  const re = /<aide-artifact([^>]*)>([\s\S]*?)<\/aide-artifact>/g;
  const out = [];
  let m;
  while ((m = re.exec(text)) !== null) {
    const attrs = m[1], content = m[2];
    const tM  = attrs.match(/type="([^"]*)"/);
    const tiM = attrs.match(/title="([^"]*)"/);
    const lM  = attrs.match(/lang="([^"]*)"/);
    out.push({
      type:    tM?.[1]  || 'code',
      title:   tiM?.[1] || 'artifact',
      lang:    lM?.[1]  || '',
      content,
    });
  }
  return out;
}

export function stripArtifacts(text) {
  return text.replace(/<aide-artifact[^>]*>[\s\S]*?<\/aide-artifact>/g, '').trim();
}

// wire close button + escape key — guarded so the module is import-safe outside a browser
// (it crashed on `document` at load, which also kept the pure parsers untestable)
if (typeof document !== 'undefined') {
  document.getElementById('artifact-close-btn')?.addEventListener('click', closeArtifactPanel);
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && document.getElementById('artifact-panel')?.classList.contains('open')) {
      closeArtifactPanel();
    }
  });
}
