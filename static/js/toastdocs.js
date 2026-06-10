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

export async function createDocEditor(el, { initialValue = '', onChange } = {}) {
  const Editor = await ensureToast();
  const colorSyntax = window.toastui?.Editor?.plugin?.uml;   // color-syntax (mis-named in the umd)
  el.innerHTML = '';
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
    plugins: colorSyntax ? [colorSyntax] : [],
    toolbarItems: [
      ['heading', 'bold', 'italic', 'strike'],
      ['hr', 'quote'],
      ['ul', 'ol', 'task', 'indent', 'outdent'],
      ['table', 'image', 'link'],
      ['code', 'codeblock'],
    ],
    events: { change: () => onChange?.() },
  });
  return _editor;
}

export function getDocMarkdown() { return _editor ? _editor.getMarkdown() : ''; }
export function setDocMarkdown(md) { if (_editor) _editor.setMarkdown(md || '', false); }
export function docEditorReady() { return !!_editor; }
