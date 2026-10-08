const EXPLICIT_BACKGROUND = [
  /^\s*\/background\b/i,
  /^\s*in the background\b[\s,:-]*(?:please\s+)?(?:run|do|handle|finish|continue|check|prepare|work)\b/i,
  /^\s*(?:please\s+)?keep (?:working|going)(?: on [\s\S]{1,100})? while i\b/i,
];

const BACKGROUND_IMPERATIVE = /^\s*(?:(?:please)\s+|(?:(?:could|can|would|will)\s+you\s+(?:please\s+)?)|(?:i\s+(?:need|want)\s+you\s+to\s+)|(?:i(?:'d| would)\s+like\s+you\s+to\s+))?(?:run|do|handle|finish|continue|check|prepare|work on|keep working on)\b\s*([\s\S]{0,100}?)\s+in the background\b/i;
const DESCRIPTIVE_OBJECT = /\b(?:guide|explanation|description|documentation|article|question)\b[\s\S]*\b(?:that|which)\b/i;

export function shouldRunInBackground(value) {
  const text = String(value || '').trim();
  if (!text) return false;
  if (EXPLICIT_BACKGROUND.some(pattern => pattern.test(text))) return true;
  const request = text.match(BACKGROUND_IMPERATIVE);
  return Boolean(request && !DESCRIPTIVE_OBJECT.test(request[1] || ''));
}
