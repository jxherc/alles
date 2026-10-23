export function parsePrivateLines(text) {
  const values = {};
  for (const raw of String(text || '').split(/\r?\n/)) {
    const line = raw.trim();
    if (!line) continue;
    const split = line.indexOf('=');
    if (split < 1) throw new Error('use name=value for each private value');
    values[line.slice(0, split).trim()] = line.slice(split + 1).trim();
  }
  return values;
}
