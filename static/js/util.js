// shared helpers

export function escapeHtml(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

// very minimal markdown → html
// handles: **bold**, *italic*, `code`, ```blocks```, # headings, - lists
export function mdToHtml(text) {
  if (!text) return '';

  // code blocks first (don't process inside them)
  const blocks = [];
  let out = text.replace(/```(\w*)\n?([\s\S]*?)```/g, (_, lang, code) => {
    const idx = blocks.length;
    blocks.push({ lang: lang || '', code });
    return `\x00BLOCK${idx}\x00`;
  });

  // headings
  out = out.replace(/^#{1,6}\s+(.+)$/gm, (_, t) => `<p><strong>${t}</strong></p>`);
  // bold + italic
  out = out.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  out = out.replace(/\*(.+?)\*/g, '<em>$1</em>');
  // inline code
  out = out.replace(/`([^`]+)`/g, (_, c) => `<code>${escapeHtml(c)}</code>`);
  // unordered lists
  out = out.replace(/^\s*[-*]\s+(.+)/gm, '<li>$1</li>');
  out = out.replace(/(<li>.*<\/li>\n?)+/g, m => `<ul>${m}</ul>`);
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
    return `<div class="code-block">
<div class="code-block-header">
  <span class="code-lang">${lang}</span>
  <button class="code-copy" onclick="copyCode(this)">copy</button>
</div>
<pre><code class="${lang ? 'language-' + lang : ''}">${escaped}</code></pre>
</div>`;
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


// copy code button — global so inline onclick works
window.copyCode = function(btn) {
  const pre = btn.closest('.code-block').querySelector('pre');
  navigator.clipboard.writeText(pre.innerText).then(() => {
    btn.textContent = 'copied';
    setTimeout(() => btn.textContent = 'copy', 1500);
  });
};
