// shared helpers

export function escapeHtml(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
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

  // Escape all raw HTML before adding the small Markdown subset below. Code and
  // thinking blocks are restored later from placeholders.
  out = escapeHtml(out);

  // headings → real h1..h6
  out = out.replace(/^(#{1,6})\s+(.+)$/gm, (_, h, t) => `<h${h.length}>${t}</h${h.length}>`);
  // horizontal rule (before inline * so *** isn't eaten by italic)
  out = out.replace(/^\s*(?:---|\*\*\*|___)\s*$/gm, '<hr>');
  // images then links ( ! [ ] ( ) survived escapeHtml )
  out = out.replace(/!\[([^\]]*)\]\(([^)\s]+)\)/g, '<img class="md-img" src="$2" alt="$1">');
  out = out.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noreferrer">$1</a>');
  // bold, italic, strikethrough, ==highlight==
  out = out.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  out = out.replace(/\*(.+?)\*/g, '<em>$1</em>');
  out = out.replace(/~~(.+?)~~/g, '<del>$1</del>');
  // highlight — require non-space boundaries so "a == b == c" stays untouched
  out = out.replace(/==(\S(?:[^=]*\S)?)==/g, '<mark>$1</mark>');
  // inline code
  out = out.replace(/`([^`]+)`/g, '<code>$1</code>');
  // blockquotes — consecutive > lines into one block (> was escaped to &gt;)
  out = out.replace(/(?:^&gt;\s?.*(?:\n|$))+/gm, m =>
    `<blockquote>${m.replace(/^&gt;\s?/gm, '').trim().replace(/\n/g, '<br>')}</blockquote>`);
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
        buf.items.push(`<li class="md-task"><input type="checkbox" disabled ${/x/i.test(m[1]) ? 'checked' : ''}> ${m[2]}</li>`);
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

  // restore code blocks
  out = out.replace(/\x00BLOCK(\d+)\x00/g, (_, i) => {
    const { lang, code } = blocks[i];
    const escaped = escapeHtml(code);
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

  return out;
}


export function toast(msg, type = '', duration = 3000) {
  const c = document.getElementById('toast-container');
  const el = document.createElement('div');
  el.className = `toast${type ? ' ' + type : ''}`;
  el.textContent = msg;
  c.appendChild(el);
  setTimeout(() => el.remove(), duration);
}


export function closeAllModals() {
  document.querySelectorAll('.modal-overlay').forEach(m => m.style.display = 'none');
  document.getElementById('ctx-menu').style.display = 'none';
}

export function resetNavToChat() {
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  document.querySelector('.nav-item[data-view="chat"]')?.classList.add('active');
}


// copy code button — global so inline onclick works
window.copyCode = function(btn) {
  const pre = btn.closest('.code-block').querySelector('pre');
  navigator.clipboard.writeText(pre.innerText).then(() => {
    btn.textContent = 'copied';
    setTimeout(() => btn.textContent = 'copy', 1500);
  });
};

// run code button
window.runCode = async function(btn) {
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
