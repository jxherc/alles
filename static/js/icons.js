// one place for every ui icon. SF-ish: 24 grid, currentColor stroke, round caps.
// not SF Symbols (can't embed that in a web app) — our own monochrome set so everything matches.
// usage:  el.innerHTML = icon('search')        // string
//         node.append(iconEl('trash',{cls:'danger'}))
// per-app emoji get swapped to these as each app's stage lands.

const P = {
  _fallback: '<rect x="4" y="4" width="16" height="16" rx="3"/><line x1="9" y1="9" x2="15" y2="15"/>',

  search: '<circle cx="11" cy="11" r="7"/><line x1="20.5" y1="20.5" x2="16.5" y2="16.5"/>',
  plus: '<line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>',
  minus: '<line x1="5" y1="12" x2="19" y2="12"/>',
  close: '<line x1="6" y1="6" x2="18" y2="18"/><line x1="18" y1="6" x2="6" y2="18"/>',
  check: '<polyline points="4 12.5 9.5 18 20 6.5"/>',
  'check-circle': '<circle cx="12" cy="12" r="9"/><polyline points="8 12.5 11 15.5 16.5 9"/>',
  'x-circle': '<circle cx="12" cy="12" r="9"/><line x1="9" y1="9" x2="15" y2="15"/><line x1="15" y1="9" x2="9" y2="15"/>',
  star: '<polygon points="12 3 14.6 8.6 20.8 9.3 16.2 13.6 17.4 19.8 12 16.7 6.6 19.8 7.8 13.6 3.2 9.3 9.4 8.6"/>',
  'star-fill': '<polygon points="12 3 14.6 8.6 20.8 9.3 16.2 13.6 17.4 19.8 12 16.7 6.6 19.8 7.8 13.6 3.2 9.3 9.4 8.6" fill="currentColor" stroke="none"/>',
  eye: '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z"/><circle cx="12" cy="12" r="3"/>',
  'eye-off': '<path d="M10.6 6.2A9.7 9.7 0 0 1 12 6c6.5 0 10 6 10 6a17 17 0 0 1-3.2 3.6M6.4 7.5A17 17 0 0 0 2 12s3.5 6 10 6a9.7 9.7 0 0 0 3.5-.6"/><line x1="4" y1="4" x2="20" y2="20"/>',
  lock: '<rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>',
  unlock: '<rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 0 1 7.5-2"/>',
  gear: '<circle cx="12" cy="12" r="3.2"/><path d="M19 12a7 7 0 0 0-.1-1.2l1.9-1.5-2-3.4-2.3.9a7 7 0 0 0-2-1.2l-.3-2.4h-4l-.3 2.4a7 7 0 0 0-2 1.2l-2.3-.9-2 3.4 1.9 1.5A7 7 0 0 0 5 12a7 7 0 0 0 .1 1.2l-1.9 1.5 2 3.4 2.3-.9a7 7 0 0 0 2 1.2l.3 2.4h4l.3-2.4a7 7 0 0 0 2-1.2l2.3.9 2-3.4-1.9-1.5A7 7 0 0 0 19 12z"/>',
  trash: '<polyline points="4 7 20 7"/><path d="M6 7l1 13h10l1-13"/><path d="M9.5 7V4.5h5V7"/><line x1="10" y1="10.5" x2="10" y2="16.5"/><line x1="14" y1="10.5" x2="14" y2="16.5"/>',
  edit: '<path d="M4 20h4L18.5 9.5a2 2 0 0 0 0-2.8l-1.2-1.2a2 2 0 0 0-2.8 0L4 16z"/><line x1="13.5" y1="6.5" x2="17.5" y2="10.5"/>',
  copy: '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M4 16V5a1 1 0 0 1 1-1h11"/>',
  link: '<path d="M9 15l6-6"/><path d="M11 7l1-1a4 4 0 0 1 5.7 5.7l-2 2"/><path d="M13 17l-1 1A4 4 0 0 1 6.3 12.3l2-2"/>',
  share: '<circle cx="6" cy="12" r="2.5"/><circle cx="18" cy="6" r="2.5"/><circle cx="18" cy="18" r="2.5"/><line x1="8.2" y1="10.8" x2="15.8" y2="7.2"/><line x1="8.2" y1="13.2" x2="15.8" y2="16.8"/>',
  download: '<line x1="12" y1="4" x2="12" y2="15"/><polyline points="7 11 12 16 17 11"/><path d="M5 19h14"/>',
  upload: '<line x1="12" y1="20" x2="12" y2="9"/><polyline points="7 13 12 8 17 13"/><path d="M5 5h14"/>',
  refresh: '<path d="M20 11a8 8 0 0 0-14-4.5L4 8"/><polyline points="4 4 4 8 8 8"/><path d="M4 13a8 8 0 0 0 14 4.5L20 16"/><polyline points="20 20 20 16 16 16"/>',
  'chevron-left': '<polyline points="14.5 5 8 12 14.5 19"/>',
  'chevron-right': '<polyline points="9.5 5 16 12 9.5 19"/>',
  'chevron-up': '<polyline points="5 14.5 12 8 19 14.5"/>',
  'chevron-down': '<polyline points="5 9.5 12 16 19 9.5"/>',
  calendar: '<rect x="4" y="5.5" width="16" height="15" rx="2"/><line x1="4" y1="9.5" x2="20" y2="9.5"/><line x1="8" y1="3.5" x2="8" y2="7"/><line x1="16" y1="3.5" x2="16" y2="7"/>',
  clock: '<circle cx="12" cy="12" r="8.5"/><polyline points="12 7 12 12 15.5 14"/>',
  mail: '<rect x="3" y="5.5" width="18" height="13" rx="2"/><polyline points="3.5 7 12 13 20.5 7"/>',
  paperclip: '<path d="M19 11l-7.5 7.5a4 4 0 0 1-5.7-5.7L13 5.6a2.6 2.6 0 0 1 3.7 3.7l-7.3 7.3a1.3 1.3 0 0 1-1.9-1.9l6.8-6.8"/>',
  comment: '<path d="M5 5h14a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H9l-4 3.5V6a1 1 0 0 1 1-1z"/>',
  image: '<rect x="3.5" y="4.5" width="17" height="15" rx="2"/><circle cx="8.5" cy="9.5" r="1.6"/><polyline points="5 17 10 12 13 15 16 12 20 16"/>',
  file: '<path d="M7 3.5h7L19 8v12a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V4.5a1 1 0 0 1 1-1z"/><polyline points="13.5 3.5 13.5 8.5 18.5 8.5"/>',
  folder: '<path d="M4 7a2 2 0 0 1 2-2h3l2 2.5h7a2 2 0 0 1 2 2V18a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2z"/>',
  tag: '<path d="M4 4h7l9 9-7 7-9-9z"/><circle cx="8" cy="8" r="1.4"/>',
  bell: '<path d="M7 17V11a5 5 0 0 1 10 0v6l1.5 2H5.5z"/><path d="M10 19a2 2 0 0 0 4 0"/>',
  play: '<polygon points="7 5 19 12 7 19"/>',
  pause: '<line x1="9" y1="5" x2="9" y2="19"/><line x1="15" y1="5" x2="15" y2="19"/>',
  stop: '<rect x="6" y="6" width="12" height="12" rx="2"/>',
  mic: '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5.5 11.5a6.5 6.5 0 0 0 13 0"/><line x1="12" y1="18" x2="12" y2="21"/>',
  volume: '<polygon points="4 9.5 8 9.5 12.5 5.5 12.5 18.5 8 14.5 4 14.5"/><path d="M16 9a4 4 0 0 1 0 6"/>',
  mute: '<polygon points="4 9.5 8 9.5 12.5 5.5 12.5 18.5 8 14.5 4 14.5"/><line x1="16" y1="9.5" x2="20" y2="14.5"/><line x1="20" y1="9.5" x2="16" y2="14.5"/>',
  video: '<rect x="3" y="6" width="13" height="12" rx="2"/><polygon points="16 10 21 7 21 17 16 14"/>',
  grid: '<rect x="4" y="4" width="7" height="7" rx="1.5"/><rect x="13" y="4" width="7" height="7" rx="1.5"/><rect x="4" y="13" width="7" height="7" rx="1.5"/><rect x="13" y="13" width="7" height="7" rx="1.5"/>',
  list: '<line x1="8" y1="6.5" x2="20" y2="6.5"/><line x1="8" y1="12" x2="20" y2="12"/><line x1="8" y1="17.5" x2="20" y2="17.5"/><circle cx="4.5" cy="6.5" r="1"/><circle cx="4.5" cy="12" r="1"/><circle cx="4.5" cy="17.5" r="1"/>',
  'map-pin': '<path d="M12 21s7-6.3 7-11a7 7 0 0 0-14 0c0 4.7 7 11 7 11z"/><circle cx="12" cy="10" r="2.5"/>',
  plane: '<path d="M21 15.5l-7-2V7.5a1.5 1.5 0 0 0-3 0V13l-7 2v2l7-1.5V19l-2 1.2V21l3-1 3 1v-.8L13 19v-3.5l7 1.5z"/>',
  shield: '<path d="M12 3l7 2.5V11c0 4.5-3 7.7-7 9-4-1.3-7-4.5-7-9V5.5z"/>',
  sun: '<circle cx="12" cy="12" r="4"/><line x1="12" y1="3" x2="12" y2="5.5"/><line x1="12" y1="18.5" x2="12" y2="21"/><line x1="3" y1="12" x2="5.5" y2="12"/><line x1="18.5" y1="12" x2="21" y2="12"/><line x1="5.6" y1="5.6" x2="7.4" y2="7.4"/><line x1="16.6" y1="16.6" x2="18.4" y2="18.4"/><line x1="18.4" y1="5.6" x2="16.6" y2="7.4"/><line x1="7.4" y1="16.6" x2="5.6" y2="18.4"/>',
  moon: '<path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"/>',
  send: '<path d="M4 4l16 8-16 8 3-8z"/><line x1="7" y1="12" x2="20" y2="12"/>',
  archive: '<rect x="4" y="5" width="16" height="4" rx="1"/><path d="M5.5 9v9a1 1 0 0 0 1 1h11a1 1 0 0 0 1-1V9"/><line x1="10" y1="13" x2="14" y2="13"/>',
  snooze: '<circle cx="12" cy="13" r="7.5"/><polyline points="12 9 12 13 15 15"/><path d="M9 3h4l-4 4h4" transform="translate(4 -1) scale(0.6)"/>',
  sparkles: '<path d="M12 4l1.6 4.4L18 10l-4.4 1.6L12 16l-1.6-4.4L6 10l4.4-1.6z"/><path d="M18 14l.8 2.2L21 17l-2.2.8L18 20l-.8-2.2L15 17l2.2-.8z"/>',
  heart: '<path d="M12 20s-7-4.5-7-9.5A3.8 3.8 0 0 1 12 7a3.8 3.8 0 0 1 7 3c0 5-7 9.5-7 9.5z"/>',
  'heart-fill': '<path d="M12 20s-7-4.5-7-9.5A3.8 3.8 0 0 1 12 7a3.8 3.8 0 0 1 7 3c0 5-7 9.5-7 9.5z" fill="currentColor" stroke="none"/>',
  columns: '<rect x="4" y="5" width="16" height="14" rx="2"/><line x1="12" y1="5" x2="12" y2="19"/>',
  board: '<rect x="4" y="5" width="16" height="14" rx="2"/><line x1="10" y1="5" x2="10" y2="19"/><line x1="15" y1="5" x2="15" y2="19"/>',
  palette: '<path d="M12 3a9 9 0 0 0 0 18c1.7 0 2-1.3 1.2-2.2-.8-.9-.3-2.3 1-2.3H17a4 4 0 0 0 4-4c0-4.6-4-9.5-9-9.5z"/><circle cx="8" cy="11" r="1"/><circle cx="12" cy="8" r="1"/><circle cx="16" cy="11" r="1"/>',
  history: '<path d="M4 12a8 8 0 1 0 2.5-5.8L4 8.5"/><polyline points="4 4 4 9 9 9"/><polyline points="12 8 12 12 15 14"/>',
  bookmark: '<path d="M7 4h10a1 1 0 0 1 1 1v15l-6-4-6 4V5a1 1 0 0 1 1-1z"/>',
  'bookmark-fill': '<path d="M7 4h10a1 1 0 0 1 1 1v15l-6-4-6 4V5a1 1 0 0 1 1-1z" fill="currentColor" stroke="none"/>',
  menu: '<line x1="4" y1="7" x2="20" y2="7"/><line x1="4" y1="12" x2="20" y2="12"/><line x1="4" y1="17" x2="20" y2="17"/>',
  key: '<circle cx="8" cy="8" r="4"/><line x1="11" y1="11" x2="20" y2="20"/><line x1="17" y1="17" x2="19" y2="15"/><line x1="14" y1="14" x2="16.5" y2="11.5"/>',
  fingerprint: '<path d="M7 12a5 5 0 0 1 10 0v2"/><path d="M9.5 12a2.5 2.5 0 0 1 5 0c0 2 .3 4 1 5.5"/><path d="M5 13a7 7 0 0 1 1.5-5.5"/><path d="M12 12v3c0 1.5.4 3 1 4"/><path d="M17.5 6A7 7 0 0 0 8 5.2"/>',
  more: '<circle cx="5" cy="12" r="1.4"/><circle cx="12" cy="12" r="1.4"/><circle cx="19" cy="12" r="1.4"/>',
  'more-v': '<circle cx="12" cy="5" r="1.4"/><circle cx="12" cy="12" r="1.4"/><circle cx="12" cy="19" r="1.4"/>',
  drag: '<circle cx="9" cy="6" r="1.3"/><circle cx="15" cy="6" r="1.3"/><circle cx="9" cy="12" r="1.3"/><circle cx="15" cy="12" r="1.3"/><circle cx="9" cy="18" r="1.3"/><circle cx="15" cy="18" r="1.3"/>',
  info: '<circle cx="12" cy="12" r="9"/><line x1="12" y1="11" x2="12" y2="16.5"/><circle cx="12" cy="7.8" r="0.6" fill="currentColor"/>',
  warning: '<path d="M12 4l9 15.5H3z"/><line x1="12" y1="10" x2="12" y2="14.5"/><circle cx="12" cy="17.2" r="0.7" fill="currentColor"/>',
  sigma: '<polyline points="17 5 7 5 13 12 7 19 17 19"/>',
  target: '<circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="4.5"/><circle cx="12" cy="12" r="0.8" fill="currentColor"/>',
  scale: '<line x1="12" y1="4" x2="12" y2="20"/><path d="M6 20h12"/><path d="M5 8l-2.5 5a2.5 2.5 0 0 0 5 0z"/><path d="M19 8l-2.5 5a2.5 2.5 0 0 0 5 0z"/><line x1="5" y1="8" x2="19" y2="8"/>',
  fire: '<path d="M12 3c1 3-1.5 4-1.5 6.5a3 3 0 0 0 6 0c0-1-.3-1.8-.8-2.5C18 9 19 11 19 13.5a7 7 0 0 1-14 0C5 10 8 7 9 4c.5 1.2 1.5 1.8 3-1z"/>',
  undo: '<polyline points="9 7 4 12 9 17"/><path d="M4 12h10a5 5 0 0 1 0 10h-2"/>',
  redo: '<polyline points="15 7 20 12 15 17"/><path d="M20 12H10a5 5 0 0 0 0 10h2"/>',
  dollar: '<line x1="12" y1="3" x2="12" y2="21"/><path d="M16 6.5a4 4 0 0 0-4-1.5c-2 0-4 1-4 3s2 2.5 4 3 4 1 4 3-2 3-4 3a4 4 0 0 1-4-1.5"/>',
  cake: '<path d="M4 20h16v-7a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2z"/><path d="M4 15c1.5 1.5 3 1.5 4 0s2.5-1.5 4 0 2.5 1.5 4 0"/><line x1="12" y1="4" x2="12" y2="9"/><circle cx="12" cy="3.2" r="0.8" fill="currentColor"/>',
  gift: '<rect x="4" y="9" width="16" height="11" rx="1"/><line x1="4" y1="13" x2="20" y2="13"/><line x1="12" y1="9" x2="12" y2="20"/><path d="M12 9C12 6 9 5 8 6.5S9 9 12 9zM12 9c0-3 3-4 4-2.5S15 9 12 9z"/>',
  party: '<path d="M4 20l5-13 8 8z"/><path d="M9 7l8 8"/><circle cx="17" cy="5" r="0.8" fill="currentColor"/><circle cx="20" cy="9" r="0.8" fill="currentColor"/><circle cx="14" cy="4" r="0.8" fill="currentColor"/>',
  user: '<circle cx="12" cy="8" r="4"/><path d="M5 20a7 7 0 0 1 14 0"/>',
  filter: '<polygon points="4 5 20 5 14 12.5 14 19 10 21 10 12.5"/>',
  sort: '<line x1="5" y1="7" x2="15" y2="7"/><line x1="5" y1="12" x2="12" y2="12"/><line x1="5" y1="17" x2="9" y2="17"/><polyline points="17 9 19 7 21 9" transform="translate(-1 0)"/>',
  pin: '<path d="M9 3h6l-1 6 3 3v2h-5v5l-1 1-1-1v-5H4v-2l3-3z" transform="translate(2 0)"/>',
  external: '<path d="M14 5h5v5"/><line x1="19" y1="5" x2="11" y2="13"/><path d="M18 13.5V18a1.5 1.5 0 0 1-1.5 1.5h-9A1.5 1.5 0 0 1 6 18V8.5A1.5 1.5 0 0 1 7.5 7H12"/>',
  globe: '<circle cx="12" cy="12" r="8.5"/><ellipse cx="12" cy="12" rx="3.8" ry="8.5"/><line x1="3.5" y1="12" x2="20.5" y2="12"/>',
};

export function icon(name, opts = {}) {
  const body = P[name] || P._fallback;
  const cls = "ic" + (opts.cls ? " " + opts.cls : "");
  let style = "";
  if (opts.size) {
    const s = typeof opts.size === "number" ? opts.size + "px" : opts.size;
    style = ` style="font-size:${s}"`;
  }
  return (
    `<svg class="${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" ` +
    `stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" ` +
    `aria-hidden="true"${style}>${body}</svg>`
  );
}

export function iconEl(name, opts) {
  const d = document.createElement("div");
  d.innerHTML = icon(name, opts).trim();
  return d.firstChild;
}

export const ICON_NAMES = Object.keys(P).filter((k) => k[0] !== "_");
