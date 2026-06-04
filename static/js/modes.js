let _incognitoMode = false;

export function isIncognitoMode() {
  return _incognitoMode;
}

export function setIncognitoMode(on) {
  _incognitoMode = !!on;
  const btn = document.getElementById('incognito-btn');
  if (btn) {
    btn.classList.toggle('active', _incognitoMode);
    btn.setAttribute('aria-pressed', String(_incognitoMode));
    btn.title = _incognitoMode
      ? 'incognito mode active - click to disable'
      : 'enable incognito mode';
  }
}

export function toggleIncognitoMode() {
  setIncognitoMode(!_incognitoMode);
  return _incognitoMode;
}
