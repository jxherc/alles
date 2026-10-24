import { leave } from './motion.js';
// shared helpers

// browser window when present, a throwaway object under node (so this module imports in tests)
const _g = typeof window !== 'undefined' ? window : {};

export function escapeHtml(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

// allow only safe url schemes in rendered markdown: relative paths, anchors, http(s), mailto and
// tel. the scheme is read the way the browser reads it, with control characters and spaces taken
// out first, so "\u0001javascript:" or "java<tab>script:" can't slip past
export function _safeUrl(u) {
  const t = String(u || '').trim();
  const probe = t.replace(/[\u0000-\u0020\u007f-\u009f]/g, '');
  const scheme = /^([a-z][a-z0-9+.-]*):/i.exec(probe)?.[1]?.toLowerCase();
  if (scheme && !['http', 'https', 'mailto', 'tel'].includes(scheme)) return '#';
  return t.replace(/"/g, '%22');
}

// very minimal markdown → html
// handles: **bold**, *italic*, `code`, ```blocks```, # headings, - lists
// remoteImages: model answers, artifacts and the like show a remote image as a link, because
// loading it would tell that server the page was read (and a steered answer can put chat text in
// its address). the owner's own notes load them
export function mdToHtml(text, { remoteImages = false } = {}) {
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
  out = out.replace(/\$\$([\s\S]+?)\$\$/g, (source, tex) => { maths.push({ display: true, tex, source }); return `\x00MATH${maths.length - 1}\x00`; });
  out = out.replace(/(?<![\\$\d])\$(?!\s)([^\n$]+?)(?<!\s)\$(?!\d)/g, (source, tex) => { maths.push({ display: false, tex, source }); return `\x00MATH${maths.length - 1}\x00`; });

  // Preserve Markdown escapes until formatting has finished. Decode URL escapes
  // before scheme validation so an escaped colon cannot turn into a live script.
  let escapePrefix = '\x00ESCAPED';
  while (text.includes(escapePrefix)) escapePrefix += '_';
  const escapes = [];
  out = out.replace(/\\([!"#$%&'()*+,\-./:;<=>?@[\]\\^_`{|}~])/g, (_, value) => {
    escapes.push(value);
    return `${escapePrefix}${escapes.length - 1}\x00`;
  });
  const restoreEscapes = (value, html = false) => value.replace(
    new RegExp(escapePrefix + '(\\d+)\\x00', 'g'),
    (_, index) => html ? escapeHtml(escapes[index]) : escapes[index],
  );

  const attributeText = value => {
    const entities = { amp: '&', lt: '<', gt: '>', quot: '"', '#39': "'" };
    const original = value.replace(/&(amp|lt|gt|quot|#39);/g, (_, name) => entities[name]);
    // Math was extracted before links. Attributes need its literal source, never
    // rendered math markup or an internal placeholder in the destination.
    return restoreEscapes(original).replace(/\x00MATH(\d+)\x00/g, (_, index) =>
      maths[index].source.replace(/\\([!"#$%&'()*+,\-./:;<=>?@[\]\\^_`{|}~])/g, '$1'));
  };
  const urlAttribute = value => escapeHtml(_safeUrl(attributeText(value)));

  // Escape all raw HTML before adding the small Markdown subset below. Code and
  // thinking blocks are restored later from placeholders.
  out = escapeHtml(out);
  // Generated attributes must not pass through Markdown again: a URL can itself
  // contain link delimiters or formatting syntax. Keep markup opaque until the end.
  let markupPrefix = '\x00MARKUP';
  while (text.includes(markupPrefix)) markupPrefix += '_';
  const markup = [];
  const keepMarkup = html => {
    markup.push(html);
    return `${markupPrefix}${markup.length - 1}\x00`;
  };
  out = out.replace(/!\[([^\]]*)\]\(([^)\s]+)\)/g, (_, alt, u) => {
    const label = escapeHtml(attributeText(alt));
    // read the way the browser reads it: "//host", "/\host" and "\u0001https:" load remotely too
    const probe = attributeText(u).replace(/[\u0000-\u0020\u007f-\u009f]/g, '');
    if (!remoteImages && /^(https?:|[\\/]{2})/i.test(probe)) {
      return keepMarkup(`<a class="md-img-link" href="${urlAttribute(u)}" target="_blank" rel="noreferrer">image: ${label || 'open'}</a>`);
    }
    return keepMarkup(`<img class="md-img" src="${urlAttribute(u)}" alt="${label}">`);
  });
  out = out.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (_, txt, u) =>
    keepMarkup(`<a href="${urlAttribute(u)}" target="_blank" rel="noreferrer">`) + txt + keepMarkup('</a>'));

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
  // bold, italic, strikethrough, ==highlight==
  out = out.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  out = out.replace(/\*(.+?)\*/g, '<em>$1</em>');
  // _italic_ too, but only with no letters glued on either side, so snake_case_names stay as typed
  out = out.replace(/(^|[^\p{L}\p{N}_\x00])_(?!\s)([^_\n]+?)(?<!\s)_(?![\p{L}\p{N}_])/gu, '$1<em>$2</em>');
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
  // lists — line based so blank lines end a list and ul/ol never bleed together. an item indented
  // past the one above it (2+ spaces or a tab) opens a list inside that item
  {
    const lines = out.split('\n');
    const res = [];
    let html = '';
    const stack = [];   // { type, indent }, each level with its last <li> still open
    const close = () => { const top = stack.pop(); html += `</li></${top.type}>`; };
    const flush = () => { while (stack.length) close(); if (html) { res.push(html); html = ''; } };
    for (const line of lines) {
      let m, type, item;
      if ((m = line.match(/^(\s*)[-*]\s+\[([ xX])\]\s+(.+)/))) {
        type = 'ul'; item = `<li class="md-task"><span class="chk chk-static" aria-checked="${/x/i.test(m[2]) ? 'true' : 'false'}"></span> ${m[3]}`;
      } else if ((m = line.match(/^(\s*)\d+\.\s+(.+)/))) {
        type = 'ol'; item = `<li>${m[2]}`;
      } else if ((m = line.match(/^(\s*)[-*]\s+(.+)/))) {
        type = 'ul'; item = `<li>${m[2]}`;
      } else {
        flush();
        res.push(line);
        continue;
      }
      const indent = m[1].replace(/\t/g, '    ').length;
      while (stack.length && indent < stack.at(-1).indent - 1) close();
      const top = stack.at(-1);
      if (!top || indent >= top.indent + 2) {
        html += `<${type}>`;
        stack.push({ type, indent });
      } else if (top.type !== type) {
        close();
        html += `<${type}>`;
        stack.push({ type, indent });
      } else html += '</li>';
      html += item;
    }
    flush();
    out = res.join('\n');
  }
  // paragraphs — double newlines
  out = out.replace(/\n{2,}/g, '\n\n');
  const paras = out.split('\n\n').map(p => p.trim()).filter(Boolean);
  out = paras.map(p => {
    // already a block; a paragraph that only starts with <em> or <strong> still needs its <p>
    // (a code, thinking or display-math block standing alone is one too)
    if (/^<(h[1-6]|ul|ol|li|table|thead|tbody|tr|blockquote|div|pre|hr|details|section|figure|p)\b/i.test(p) || /^\x00(BLOCK|THINK|MATH)\d+\x00$/.test(p)) return p;
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

  return restoreEscapes(out, true).replace(
    new RegExp(markupPrefix + '(\\d+)\\x00', 'g'),
    (_, index) => markup[index],
  );
}

// Markdown stays complete and readable without a network connection. Mermaid and
// TeX source are intentionally preserved as text until reviewed local renderers
// are bundled; runtime CDN imports are forbidden in core UI paths.
export async function enhanceMarkdown(root) {
  return root;
}
_g.enhanceMarkdown = enhanceMarkdown;


// thin fetch wrapper — json in/out by default, throws on !ok with the server's
// detail message. plain objects get JSON-encoded; FormData/strings pass through.
// adopt incrementally; raw fetch is still fine where this doesn't fit.
export async function api(path, opts = {}, fetcher = fetch) {
  const o = { ...opts };
  const body = o.body;
  if (body != null && !(body instanceof FormData) && typeof body !== 'string') {
    o.headers = { 'content-type': 'application/json', ...(o.headers || {}) };
    o.body = JSON.stringify(body);
  }
  const r = await fetcher(path, o);
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
  // one problem at a time: a fixed mistake's old error ("enter reminder text") shouldn't sit
  // beside the new one
  if (type === 'error') c?.querySelectorAll?.('.toast.error').forEach(old => old.remove());
  const el = document.createElement('div');
  el.className = `toast${type ? ' ' + type : ''}`;
  el.textContent = type === 'error' ? plainError(msg) : msg;
  c.appendChild(el);
  setTimeout(() => leave(el), duration);
}

// text the browser itself throws (offline, blocked, a reply that isn't json) means nothing to
// a person. 146 callers hand e.message to toast, so it gets swapped here, once. the app's own
// messages pass through untouched, and a plain prefix like "upload failed: " is kept
const RAW_ERRORS = [
  [/failed to fetch|\bload failed|networkerror|network error|err_network|err_internet|err_connection/i,
    "can't reach alles right now. check the connection and try again"],
  [/push service/i, "this browser can't get push notifications. try safari, chrome or firefox"],
  [/unexpected token|json\.parse|not valid json|unexpected end of (json|input)/i,
    "alles sent back something it couldn't read. try again"],
  [/notallowederror|not allowed by the user agent|permission denied/i,
    "the browser blocked this. allow it in the site's settings and try again"],
  [/quotaexceeded|exceeded the quota/i, 'this browser is out of space for alles'],
  [/the (user|operation) (was )?aborted|signal is aborted/i, 'stopped before it finished. try again'],
  [/path escapes vault/i, 'that name points outside your documents folder'],
  [/^(\w*Error|DOMException)\b|\b(undefined|NaN)\b|\[object \w+\]|^null$/,
    'something went wrong. try again'],
];

export function plainError(msg) {
  const text = String(msg ?? '').trim();
  if (!text) return 'something went wrong. try again';
  for (const [raw, plain] of RAW_ERRORS) {
    const hit = text.match(raw);
    if (!hit) continue;
    // keep a short plain lead-in ("upload failed: Failed to fetch" -> "upload failed: can't reach...")
    const cut = text.lastIndexOf(': ', hit.index);
    const lead = cut > 0 ? text.slice(0, cut) : '';
    return lead && !RAW_ERRORS.some(([r]) => r.test(lead)) ? `${lead}: ${plain}` : plain;
  }
  return text;
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
  document.querySelectorAll('.modal-overlay:not(#photos-lightbox)').forEach(m => m.style.display = 'none');
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

// html going into an editable box in the page itself (mail compose) is cleaned first: a reply
// quote or a draft from another mail app could carry <img onerror> or <script>, which would run
// as alles. it's parsed in an inert document, then only plain formatting, safe links and
// images survive; every attribute but href/src/alt is dropped, and an image gets its width cap
// back since the compose image button's style="max-width:100%" goes with the rest
const SAFE_TAGS = new Set(['A', 'B', 'BLOCKQUOTE', 'BR', 'CODE', 'DIV', 'EM', 'H1', 'H2', 'H3', 'H4', 'HR', 'I', 'IMG',
  'LI', 'OL', 'P', 'PRE', 'S', 'SPAN', 'STRONG', 'SUB', 'SUP', 'TABLE', 'TBODY', 'TD', 'TH', 'THEAD', 'TR', 'U', 'UL']);
const DROP_TAGS = new Set(['SCRIPT', 'STYLE', 'IFRAME', 'OBJECT', 'EMBED', 'TEMPLATE', 'NOSCRIPT', 'SVG', 'MATH', 'LINK', 'META', 'BASE', 'FORM', 'INPUT', 'TEXTAREA', 'BUTTON', 'SELECT']);
export function safeMailHtml(html) {
  const doc = new DOMParser().parseFromString(`<body>${String(html ?? '')}</body>`, 'text/html');
  const clean = node => {
    for (const child of [...node.childNodes]) {
      if (child.nodeType === 3) continue;
      if (child.nodeType !== 1) { child.remove(); continue; }
      // svg and math children keep lowercase names, so compare in one case
      const tag = child.tagName.toUpperCase();
      if (DROP_TAGS.has(tag)) { child.remove(); continue; }
      clean(child);
      if (!SAFE_TAGS.has(tag) || child.namespaceURI !== 'http://www.w3.org/1999/xhtml') { child.replaceWith(...child.childNodes); continue; }
      for (const attr of [...child.attributes]) {
        const name = attr.name.toLowerCase();
        const value = attr.value.trim();
        const ok = (tag === 'A' && name === 'href' && /^(https?:|mailto:)/i.test(value))
          || (tag === 'IMG' && name === 'src' && /^(https:|data:image\/(png|jpe?g|gif|webp);|cid:|\/api\/uploads\/[\w-]+$)/i.test(value))
          || (tag === 'IMG' && name === 'alt')
          // the signature switcher finds its block by these
          || (tag === 'DIV' && ((name === 'class' && value === 'mail-sig') || name === 'data-sig'));
        if (!ok) child.removeAttribute(attr.name);
      }
      if (tag === 'IMG') child.setAttribute('style', 'max-width:100%');
    }
  };
  clean(doc.body);
  return doc.body.innerHTML;
}
