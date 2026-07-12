const MESSAGES = {
  en: {
    'schedule.confirmed': 'scheduled — aide will answer it {when}',
  },
};

const RTL_LANGUAGES = new Set(['ar', 'fa', 'he', 'ur']);
let _language = 'en';
let _region = '';
let _timezone = '';

export function localeTag(language = _language, region = _region) {
  const base = MESSAGES[language] ? language : 'en';
  const candidate = region ? `${base}-${String(region).toUpperCase()}` : base;
  try { return Intl.getCanonicalLocales(candidate)[0]; } catch { return base; }
}

export function textDirection(language = _language) {
  return RTL_LANGUAGES.has(String(language).split('-')[0].toLowerCase()) ? 'rtl' : 'ltr';
}

export function configureLocalization(settings = {}) {
  _language = MESSAGES[settings.language] ? settings.language : 'en';
  const region = String(settings.region || '').toUpperCase();
  _region = /^(?:[A-Z]{2}|[0-9]{3})$/.test(region) ? region : '';
  const timezone = String(settings.timezone || '');
  try {
    if (timezone) new Intl.DateTimeFormat('en', { timeZone: timezone }).format();
    _timezone = timezone;
  } catch {
    _timezone = '';
  }
  if (typeof document !== 'undefined') {
    document.documentElement.lang = localeTag();
    document.documentElement.dir = textDirection();
  }
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent('alles:localization-change'));
  }
  return localizationState();
}

export function localizationState() {
  return { language: _language, region: _region, timezone: _timezone, locale: localeTag() };
}

export function t(key, values = {}) {
  const template = MESSAGES[_language]?.[key] || MESSAGES.en[key] || key;
  return template.replace(/\{([a-z0-9_]+)\}/gi, (_match, name) => String(values[name] ?? ''));
}

function _options(options = {}) {
  return _timezone ? { ...options, timeZone: _timezone } : { ...options };
}

export function formatDate(value, options = {}) {
  return new Intl.DateTimeFormat(localeTag(), _options(options)).format(new Date(value));
}

export function formatTime(value, options = {}) {
  return new Intl.DateTimeFormat(localeTag(), _options(options)).format(new Date(value));
}

export function formatDateTime(value, options = {}) {
  return new Intl.DateTimeFormat(localeTag(), _options(options)).format(new Date(value));
}
