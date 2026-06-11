// Toast UI Editor integration for docs — real WYSIWYG + Markdown, vendored locally
// (offline). The editor emits markdown, so .md files / wikilinks / backlinks keep
// working. We lazy-load the libs on first docs visit to keep the rest of the app light.
let _loadP = null;
let _editor = null;

function _css(href) {
  if (document.querySelector(`link[data-toast="${href}"]`)) return;
  const l = document.createElement('link');
  l.rel = 'stylesheet'; l.href = href; l.dataset.toast = href;
  document.head.appendChild(l);
}
function _js(src) {
  return new Promise((res, rej) => {
    if (document.querySelector(`script[data-toast="${src}"]`)) return res();
    const s = document.createElement('script');
    s.src = src; s.dataset.toast = src;
    s.onload = res; s.onerror = () => rej(new Error('failed to load ' + src));
    document.head.appendChild(s);
  });
}

function ensureToast() {
  if (_loadP) return _loadP;
  const v = '/static/vendor/';
  _loadP = (async () => {
    _css(v + 'toastui-editor.min.css');
    _css(v + 'toastui-editor-dark.min.css');
    _css(v + 'tui-color-picker.min.css');
    await _js(v + 'tui-color-picker.min.js');       // window.tui.colorPicker
    await _js(v + 'toastui-editor-all.min.js');       // window.toastui.Editor (ProseMirror bundled in)
    await _js(v + 'toastui-editor-plugin-color-syntax.min.js');  // toastui.Editor.plugin.uml
    if (!window.toastui?.Editor) throw new Error('toast ui editor missing');
    return window.toastui.Editor;
  })().catch(e => {
    _loadP = null;   // a failed load must not poison every later attempt
    throw e;
  });
  return _loadP;
}

// register <u> and <mark> as real wysiwyg marks so they round-trip to markdown
const _htmlInline = {
  u(n, { entering })    { return { type: entering ? 'openTag' : 'closeTag', tagName: 'u' }; },
  mark(n, { entering }) { return { type: entering ? 'openTag' : 'closeTag', tagName: 'mark' }; },
};

function _inlinePlugin() {
  const toggle = name => (payload, state, dispatch) => {
    const mark = state.schema.marks[name];
    if (!mark) return false;
    const { from, to, empty } = state.selection;
    if (empty) return false;
    const has = state.doc.rangeHasMark(from, to, mark);
    dispatch(has ? state.tr.removeMark(from, to, mark) : state.tr.addMark(from, to, mark.create()));
    return true;
  };
  return { wysiwygCommands: { underline: toggle('u'), highlight: toggle('mark') } };
}

function _mdWrap(open, close) {
  const sel = _editor.getSelectedText();
  _editor.replaceSelection(`${open}${sel}${close}`);
}

const _svg = paths => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${paths}</svg>`;
const _txt = (text, cls = '') => `<span class="alles-tool-text ${cls}">${text}</span>`;
const _TOOLBAR_ICONS = {
  heading: _txt('H', 'alles-tool-heading'),
  bold: _txt('B', 'alles-tool-bold'),
  italic: _txt('I', 'alles-tool-italic'),
  color: _txt('A', 'alles-tool-color'),
  strike: _txt('S', 'alles-tool-strike'),
  hrline: _svg('<line x1="5" y1="12" x2="19" y2="12"/>'),
  quote: _txt('66', 'alles-tool-quote'),
  'bullet-list': _svg('<line x1="9" y1="6" x2="20" y2="6"/><line x1="9" y1="12" x2="20" y2="12"/><line x1="9" y1="18" x2="20" y2="18"/><circle cx="4.5" cy="6" r="1"/><circle cx="4.5" cy="12" r="1"/><circle cx="4.5" cy="18" r="1"/>'),
  'ordered-list': '<span class="alles-tool-ordered"><span>1</span><span>2</span></span>',
  'task-list': _svg('<rect x="4" y="4" width="16" height="16" rx="2"/><path d="m8 12 2.5 2.5L16 9"/>'),
  indent: _svg('<path d="M4 6h16M12 12h8M12 18h8"/><path d="m4 10 4 2-4 2z"/>'),
  outdent: _svg('<path d="M4 6h16M12 12h8M12 18h8"/><path d="m8 10-4 2 4 2z"/>'),
  table: _svg('<rect x="4" y="4" width="16" height="16" rx="1"/><path d="M4 10h16M4 16h16M10 4v16M16 4v16"/>'),
  image: _svg('<rect x="4" y="5" width="16" height="14" rx="2"/><circle cx="9" cy="10" r="1.3"/><path d="m7 17 4-4 3 3 2-2 2 3"/>'),
  link: _svg('<path d="M10 13a5 5 0 0 0 7 0l2-2a5 5 0 0 0-7-7l-1 1"/><path d="M14 11a5 5 0 0 0-7 0l-2 2a5 5 0 0 0 7 7l1-1"/>'),
  code: _svg('<path d="m9 18-6-6 6-6"/><path d="m15 6 6 6-6 6"/>'),
  codeblock: _txt('CB', 'alles-tool-codeblock'),
  more: _txt('...', 'alles-tool-more'),
};
function _polishToolbarIcons(root) {
  root.querySelectorAll('.toastui-editor-toolbar-icons').forEach(btn => {
    // toast rewrites className on state toggles (active etc.) which drops our
    // classes — the dataset marker survives, so re-add them. the contains-check
    // matters: classList.add fires a mutation record even when nothing changes,
    // which would loop with the observer below
    if (btn.dataset.allesTool) {
      if (!btn.classList.contains('alles-tool-btn'))
        btn.classList.add('alles-tool-btn', 'alles-vendor-tool-btn');
      return;
    }
    const key = Object.keys(_TOOLBAR_ICONS).find(k => btn.classList.contains(k));
    if (!key) return;
    btn.dataset.allesTool = key;
    btn.classList.add('alles-tool-btn', 'alles-vendor-tool-btn');
    btn.innerHTML = _TOOLBAR_ICONS[key];
  });
}

function _toolBtn(html, tooltip, onClick) {
  const b = document.createElement('button');
  b.type = 'button';
  b.className = `toastui-editor-toolbar-icons alles-tool-btn alles-tool-${tooltip}`;
  b.innerHTML = html;
  b.addEventListener('click', e => { e.preventDefault(); onClick(); });
  return { name: tooltip, tooltip, el: b };
}

export async function createDocEditor(el, { initialValue = '', onChange } = {}) {
  const Editor = await ensureToast();
  const colorSyntax = window.toastui?.Editor?.plugin?.uml;   // color-syntax (mis-named in the umd)
  el.innerHTML = '';

  const underlineBtn = _toolBtn(_svg('<path d="M6 4v6a6 6 0 0 0 12 0V4"/><line x1="4" y1="21" x2="20" y2="21"/>'), 'underline', () => {
    if (_editor.isMarkdownMode()) _mdWrap('<u>', '</u>');
    else _editor.exec('underline');
  });
  const highlightBtn = _toolBtn(_svg('<path d="m9 11-6 6v3h9l3-3"/><path d="m22 12-4.6 4.6a2 2 0 0 1-2.8 0l-5.2-5.2a2 2 0 0 1 0-2.8L14 4l8 8Z"/>'), 'highlight', () => {
    if (_editor.isMarkdownMode()) _mdWrap('<mark>', '</mark>');
    else _editor.exec('highlight');
  });
  const wikiBtn = _toolBtn(_svg('<path d="M8 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h2"/><path d="M16 3h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-2"/>'), 'wikilink', () => {
    // plain text — safe in both modes; cursor lands inside empty brackets
    const sel = _editor.getSelectedText();
    _editor.replaceSelection(`[[${sel}]]`);
  });

  _editor = new Editor({
    el,
    height: '100%',
    initialValue,
    initialEditType: 'wysiwyg',
    previewStyle: 'tab',
    // follow the app's theme; our CSS tokens restyle both, this just picks the
    // right icon set (light icons on dark, dark icons on light)
    theme: document.documentElement.dataset.theme === 'light' ? 'default' : 'dark',
    usageStatistics: false,
    autofocus: false,
    customHTMLRenderer: _htmlInline ? { htmlInline: _htmlInline } : undefined,
    plugins: colorSyntax ? [colorSyntax, _inlinePlugin] : [_inlinePlugin],
    toolbarItems: [
      ['heading', 'bold', 'italic', 'strike', underlineBtn, highlightBtn],
      ['hr', 'quote'],
      ['ul', 'ol', 'task', 'indent', 'outdent'],
      ['table', 'image', 'link', wikiBtn],
      ['code', 'codeblock'],
    ],
    events: { change: () => onChange?.() },
  });
  _polishToolbarIcons(el);
  // re-polish whenever toast re-renders toolbar buttons (mode/state changes wipe
  // our icons). re-entry is a no-op thanks to the dataset marker, so no loop.
  const tb = el.querySelector('.toastui-editor-defaultUI-toolbar') || el;
  new MutationObserver(() => _polishToolbarIcons(el))
    .observe(tb, { childList: true, subtree: true, attributes: true, attributeFilter: ['class'] });
  return _editor;
}

export function getDocMarkdown() { return _editor ? _editor.getMarkdown() : ''; }
export function setDocMarkdown(md) { if (_editor) _editor.setMarkdown(md || '', false); }
export function docEditorReady() { return !!_editor; }
