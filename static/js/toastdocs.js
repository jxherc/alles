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

function _toolBtn(html, tooltip, onClick) {
  const b = document.createElement('button');
  b.type = 'button';
  b.className = 'toastui-editor-toolbar-icons alles-tool-btn';
  b.innerHTML = html;
  b.addEventListener('click', e => { e.preventDefault(); onClick(); });
  return { name: tooltip, tooltip, el: b };
}

export async function createDocEditor(el, { initialValue = '', onChange } = {}) {
  const Editor = await ensureToast();
  const colorSyntax = window.toastui?.Editor?.plugin?.uml;   // color-syntax (mis-named in the umd)
  el.innerHTML = '';

  const _svg = paths => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${paths}</svg>`;
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
  return _editor;
}

export function getDocMarkdown() { return _editor ? _editor.getMarkdown() : ''; }
export function setDocMarkdown(md) { if (_editor) _editor.setMarkdown(md || '', false); }
export function docEditorReady() { return !!_editor; }
