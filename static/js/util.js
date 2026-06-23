// shared helpers

// browser window when present, a throwaway object under node (so this module imports in tests)
const _g = typeof window !== 'undefined' ? window : {};

export function escapeHtml(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

// allow only safe url schemes in rendered markdown; block javascript:/vbscript:/data: etc.
// relative paths, anchors, http(s), mailto, and tel are fine.
export function _safeUrl(u) {
  const t = String(u || '').trim();
  if (/^\s*(javascript|vbscript|data|file):/i.test(t)) return '#';
  return t.replace(/"/g, '%22');
}

// very minimal markdown → html
// handles: **bold**, *italic*, `code`, ```blocks```, # headings, - lists
export function mdToHtml(text) {
  if (!text) return '';

  const thinkingBlocks = [];
  text = text.replace(/<think(?:ing)?>([\s\S]*?)<\/think(?:ing)?>/gi, (_, content) => {
    const idx = thinkingBlocks.length;
    thinkingBlocks.push(escapeHtml(content.trim()));
    return `\x00THINK${idx}\x00`;
  });

  // code blocks first (don't process inside them)
  const blocks = [];
  let out = text.replace(/```(\w*)\n?([\s\S]*?)```/g, (_, lang, code) => {
    const idx = blocks.length;
    blocks.push({ lang: lang || '', code });
    return `\x00BLOCK${idx}\x00`;
  });

  // math: $$block$$ and $inline$ → placeholders, rendered later by KaTeX
  const maths = [];
  out = out.replace(/\$\$([\s\S]+?)\$\$/g, (_, tex) => { maths.push({ display: true, tex }); return `\x00MATH${maths.length - 1}\x00`; });
  out = out.replace(/(?<![\\$\d])\$(?!\s)([^\n$]+?)(?<!\s)\$(?!\d)/g, (_, tex) => { maths.push({ display: false, tex }); return `\x00MATH${maths.length - 1}\x00`; });

  // Escape all raw HTML before adding the small Markdown subset below. Code and
  // thinking blocks are restored later from placeholders.
  out = escapeHtml(out);
  // re-allow the safe attribute-less inline tags the docs editor emits
  out = out.replace(/&lt;(\/?)(u|mark|sub|sup)&gt;/g, '<$1$2>');

  // footnotes: pull [^id]: definitions, then turn [^id] refs into superscripts
  const fns = [];
  out = out.replace(/^\[\^([^\]\s]+)\]:[ \t]*(.+)$\n?/gm, (_, id, txt) => { fns.push({ id, txt }); return ''; });
  if (fns.length) out = out.replace(/\[\^([^\]\s]+)\]/g, (full, id) => {
    const i = fns.findIndex(f => f.id === id);
    return i >= 0 ? `<sup class="md-fnref">${i + 1}</sup>` : full;
  });

  // headings → real h1..h6
  out = out.replace(/^(#{1,6})\s+(.+)$/gm, (_, h, t) => `<h${h.length}>${t}</h${h.length}>`);
  // horizontal rule (before inline * so *** isn't eaten by italic)
  out = out.replace(/^\s*(?:---|\*\*\*|___)\s*$/gm, '<hr>');
  // images then links ( ! [ ] ( ) survived escapeHtml ). filter the url scheme so
  // [x](javascript:alert(1)) / data: can't render a clickable script link (click-XSS on untrusted md).
  out = out.replace(/!\[([^\]]*)\]\(([^)\s]+)\)/g, (_, alt, u) => `<img class="md-img" src="${_safeUrl(u)}" alt="${alt}">`);
  out = out.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (_, txt, u) => `<a href="${_safeUrl(u)}" target="_blank" rel="noreferrer">${txt}</a>`);
  // bold, italic, strikethrough, ==highlight==
  out = out.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  out = out.replace(/\*(.+?)\*/g, '<em>$1</em>');
  out = out.replace(/~~(.+?)~~/g, '<del>$1</del>');
  // highlight — require non-space boundaries so "a == b == c" stays untouched
  out = out.replace(/==(\S(?:[^=]*\S)?)==/g, '<mark>$1</mark>');
  // inline code
  out = out.replace(/`([^`]+)`/g, '<code>$1</code>');
  // font color: {color:red}text{/color} — restricted to safe css color chars
  out = out.replace(/\{color:([^}]+)\}([\s\S]*?)\{\/color\}/g, (full, c, inner) =>
    /^[#\w(),.%\s-]+$/.test(c.trim()) ? `<span style="color:${c.trim()}">${inner}</span>` : full);
  // columns: "::: columns" / colA / "+++" / colB / ":::" (3a)
  out = out.replace(/^::: ?columns[^\n]*\n([\s\S]*?)\n::: *$/gm, (m, inner) => {
    const cols = inner.split(/\n\+\+\+\n/).map(c => `<div class="md-col">${c.trim().replace(/\n/g, '<br>')}</div>`).join('');
    return `<div class="md-columns">${cols}</div>`;
  });
  // blockquotes + obsidian callouts ( > [!note] Title )
  out = out.replace(/(?:^&gt;\s?.*(?:\n|$))+/gm, m => {
    const body = m.replace(/^&gt;\s?/gm, '').replace(/\n+$/, '');
    const cal = body.match(/^\[!(\w+)\][+-]?\s*(.*)(?:\n([\s\S]*))?$/);
    if (cal) {
      const type = cal[1].toLowerCase();
      const rest = (cal[3] || '').trim();
      if (type === 'toggle') {   // collapsible block (3a)
        return `<details class="md-toggle"><summary>${cal[2] || 'toggle'}</summary>${rest ? `<div class="md-toggle-body">${rest.replace(/\n/g, '<br>')}</div>` : ''}</details>`;
      }
      return `<div class="md-callout md-callout-${type}"><div class="md-callout-title">${cal[2] || type}</div>${rest ? `<div class="md-callout-body">${rest.replace(/\n/g, '<br>')}</div>` : ''}</div>`;
    }
    return `<blockquote>${body.trim().replace(/\n/g, '<br>')}</blockquote>`;
  });
  // tables ( | a | b | with a |---|---| separator row )
  out = out.replace(/(?:^\|.*\|[ \t]*(?:\n|$))+/gm, block => {
    const rows = block.replace(/\n+$/, '').split('\n').map(r => r.trim()).filter(Boolean);
    if (rows.length < 2 || !/^\|?[\s:|-]+\|?$/.test(rows[1]) || !rows[1].includes('-')) return block;
    const cells = r => r.replace(/^\||\|$/g, '').split('|').map(c => c.trim());
    let html = '<table class="md-table"><thead><tr>' + cells(rows[0]).map(c => `<th>${c}</th>`).join('') + '</tr></thead><tbody>';
    for (const r of rows.slice(2)) html += '<tr>' + cells(r).map(c => `<td>${c}</td>`).join('') + '</tr>';
    return html + '</tbody></table>';
  });
  // lists — line based so blank lines end a list and ul/ol never bleed together
  {
    const lines = out.split('\n');
    const res = [];
    let buf = null;   // { type, items[] }
    const flush = () => { if (buf) { res.push(`<${buf.type}>${buf.items.join('')}</${buf.type}>`); buf = null; } };
    for (const line of lines) {
      let m;
      if ((m = line.match(/^\s*[-*]\s+\[([ xX])\]\s+(.+)/))) {
        if (buf?.type !== 'ul') { flush(); buf = { type: 'ul', items: [] }; }
        buf.items.push(`<li class="md-task"><span class="chk chk-static" aria-checked="${/x/i.test(m[1]) ? 'true' : 'false'}"></span> ${m[2]}</li>`);
      } else if ((m = line.match(/^\s*\d+\.\s+(.+)/))) {
        if (buf?.type !== 'ol') { flush(); buf = { type: 'ol', items: [] }; }
        buf.items.push(`<li>${m[1]}</li>`);
      } else if ((m = line.match(/^\s*[-*]\s+(.+)/))) {
        if (buf?.type !== 'ul') { flush(); buf = { type: 'ul', items: [] }; }
        buf.items.push(`<li>${m[1]}</li>`);
      } else {
        flush();
        res.push(line);
      }
    }
    flush();
    out = res.join('\n');
  }
  // paragraphs — double newlines
  out = out.replace(/\n{2,}/g, '\n\n');
  const paras = out.split('\n\n').map(p => p.trim()).filter(Boolean);
  out = paras.map(p => {
    if (p.startsWith('<') ) return p;   // already html
    return `<p>${p.replace(/\n/g, '<br>')}</p>`;
  }).join('\n');

  // restore math (rendered by KaTeX later; raw shown as fallback)
  out = out.replace(/\x00MATH(\d+)\x00/g, (_, i) => {
    const { display, tex } = maths[i]; const t = escapeHtml(tex.trim());
    return display ? `<div class="md-math" data-tex="${t}">${t}</div>` : `<span class="md-math-inline" data-tex="${t}">${t}</span>`;
  });

  // restore code blocks
  out = out.replace(/\x00BLOCK(\d+)\x00/g, (_, i) => {
    const { lang, code } = blocks[i];
    const escaped = escapeHtml(code);
    if (lang.toLowerCase() === 'mermaid')   // diagrams/graphs — rendered later by mermaid
      return `<div class="md-mermaid" data-src="${escaped}">${escaped}</div>`;
    const runnable = ['js', 'javascript', 'html', 'python', 'py'].includes(lang.toLowerCase());
    const runBtn = runnable
      ? `<button class="code-run" onclick="runCode(this)">run</button>`
      : '';
    return `<div class="code-block" data-lang="${lang}">
<div class="code-block-header">
  <span class="code-lang">${lang}</span>
  <button class="code-copy" onclick="copyCode(this)">copy</button>
  ${runBtn}
</div>
<pre data-lang="${lang}"><code class="${lang ? 'language-' + lang : ''}">${escaped}</code></pre>
</div>`;
  });

  out = out.replace(/\x00THINK(\d+)\x00/g, (_, i) => {
    const content = thinkingBlocks[i] || '';
    return `<details class="thinking-block"><summary>thinking</summary><div class="thinking-content">${content.replace(/\n/g, '<br>')}</div></details>`;
  });

  if (fns.length)
    out += `<div class="md-footnotes">` + fns.map((f, i) =>
      `<div class="md-fn"><span class="md-fn-n">${i + 1}.</span> ${f.txt}</div>`).join('') + `</div>`;

  return out;
}

// lazy-render mermaid diagrams + katex math inside a freshly-rendered container.
// libs load from CDN on first use; if that fails the raw text just stays.
let _mermaidP, _katexP;
function _loadMermaid() {
  if (!_mermaidP) _mermaidP = import('https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs')
    .then(m => { m.default.initialize({ startOnLoad: false, theme: 'dark', securityLevel: 'loose', fontFamily: 'Inter, sans-serif' }); return m.default; });
  return _mermaidP;
}
function _loadKatex() {
  if (!_katexP) {
    if (!document.getElementById('katex-css')) {
      const l = document.createElement('link');
      l.id = 'katex-css'; l.rel = 'stylesheet';
      l.href = 'https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.css';
      document.head.appendChild(l);
    }
    _katexP = import('https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.mjs').then(m => m.default);
  }
  return _katexP;
}
export async function enhanceMarkdown(root) {
  if (!root) return;
  const mer = [...root.querySelectorAll('.md-mermaid:not([data-done])')];
  if (mer.length) {
    try {
      const mermaid = await _loadMermaid();
      for (const el of mer) {
        el.dataset.done = '1';
        try {
          const { svg } = await mermaid.render('mmd' + Math.random().toString(36).slice(2), el.dataset.src);
          el.innerHTML = svg;
        } catch { el.classList.add('md-mermaid-err'); }
      }
    } catch {}
  }
  const math = [...root.querySelectorAll('.md-math:not([data-done]),.md-math-inline:not([data-done])')];
  if (math.length) {
    try {
      const katex = await _loadKatex();
      for (const el of math) {
        el.dataset.done = '1';
        try { katex.render(el.dataset.tex, el, { displayMode: el.classList.contains('md-math'), throwOnError: false }); } catch {}
      }
    } catch {}
  }
}
_g.enhanceMarkdown = enhanceMarkdown;


// thin fetch wrapper — json in/out by default, throws on !ok with the server's
// detail message. plain objects get JSON-encoded; FormData/strings pass through.
// adopt incrementally; raw fetch is still fine where this doesn't fit.
export async function api(path, opts = {}) {
  const o = { ...opts };
  const body = o.body;
  if (body != null && !(body instanceof FormData) && typeof body !== 'string') {
    o.headers = { 'content-type': 'application/json', ...(o.headers || {}) };
    o.body = JSON.stringify(body);
  }
  const r = await fetch(path, o);
  const ct = r.headers.get('content-type') || '';
  const data = ct.includes('application/json') ? await r.json().catch(() => null) : await r.text();
  if (!r.ok) {
    const msg = (data && data.detail) || (typeof data === 'string' && data) || `request failed (${r.status})`;
    throw Object.assign(new Error(msg), { status: r.status, data });
  }
  return data;
}


export function toast(msg, type = '', duration = 3000) {
  const c = document.getElementById('toast-container');
  const el = document.createElement('div');
  el.className = `toast${type ? ' ' + type : ''}`;
  el.textContent = msg;
  c.appendChild(el);
  setTimeout(() => el.remove(), duration);
}


// generic share/publish (1a) — mint a public read-only link for any resource,
// copy it, and toast. kind = doc|file|photo|... ref = id or vault/files path.
export async function shareResource(kind, ref, level = 'view') {
  const r = await fetch('/api/share', {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ kind, ref, level }),
  });
  if (!r.ok) { toast('share failed', 'error'); return null; }
  const j = await r.json();
  const url = location.origin + j.url;
  try { await navigator.clipboard.writeText(url); toast('public link copied', ''); }
  catch { toast(url, ''); }   // clipboard blocked (insecure ctx) — at least show it
  return j;
}

export function closeAllModals() {
  document.querySelectorAll('.modal-overlay').forEach(m => m.style.display = 'none');
  document.getElementById('ctx-menu').style.display = 'none';
}


// copy code button — global so inline onclick works
_g.copyCode = function(btn) {
  const pre = btn.closest('.code-block').querySelector('pre');
  navigator.clipboard.writeText(pre.innerText).then(() => {
    btn.textContent = 'copied';
    setTimeout(() => btn.textContent = 'copy', 1500);
  });
};

// run code button
_g.runCode = async function(btn) {
  const block = btn.closest('.code-block');
  const lang  = (block.dataset.lang || '').toLowerCase();
  const code  = block.querySelector('pre')?.innerText || '';

  // remove old output
  block.querySelector('.code-output')?.remove();
  block.querySelector('.code-iframe')?.remove();

  const out = document.createElement('div');
  out.className = 'code-output';

  if (lang === 'html') {
    const iframe = document.createElement('iframe');
    iframe.className = 'code-iframe';
    iframe.sandbox = 'allow-scripts';
    iframe.srcdoc = code;
    block.appendChild(iframe);
    return;
  }

  if (lang === 'js' || lang === 'javascript') {
    const iframe = document.createElement('iframe');
    iframe.className = 'code-iframe';
    iframe.sandbox = 'allow-scripts';
    iframe.srcdoc = `<script>${code}<\/script>`;
    block.appendChild(iframe);
    return;
  }

  if (lang === 'python' || lang === 'py') {
    out.textContent = 'running…';
    block.appendChild(out);
    try {
      const r = await fetch('/api/execute/python', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ code }),
      });
      const { stdout, stderr, exit_code } = await r.json();
      out.textContent = (stdout || '') + (stderr ? '\n' + stderr : '');
      if (exit_code !== 0) out.classList.add('error');
    } catch (e) {
      out.textContent = 'run failed: ' + e.message;
      out.classList.add('error');
    }
  }
};
