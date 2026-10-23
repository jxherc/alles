// Shared sizing behavior for compact, content-sized text entry.
// Long-form editors intentionally do not opt into this contract.

function numericHeight(value) {
  const parsed = Number.parseFloat(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 0;
}

export function autosizeTextarea(textarea) {
  if (!textarea) return { height: 0, overflow: false };
  textarea.style.height = 'auto';
  const computed = getComputedStyle(textarea);
  const minimum = numericHeight(computed.minHeight);
  const configuredMaximum = numericHeight(computed.maxHeight);
  const viewportMaximum = Math.max(88, window.innerHeight - 96);
  const maximum = configuredMaximum ? Math.min(configuredMaximum, viewportMaximum) : viewportMaximum;
  const natural = Math.max(minimum, textarea.scrollHeight);
  const height = Math.min(natural, maximum);
  const overflow = natural > maximum;
  textarea.style.height = `${height}px`;
  textarea.style.overflowY = overflow ? 'auto' : 'hidden';
  return { height, overflow };
}

export function wireAutosizeTextarea(textarea) {
  if (!textarea || textarea.dataset.kokuenAutosizeReady === '1') return () => {};
  textarea.dataset.kokuenAutosizeReady = '1';
  const resize = () => autosizeTextarea(textarea);
  textarea.addEventListener('input', resize);
  window.addEventListener('resize', resize);
  resize();
  return () => {
    textarea.removeEventListener('input', resize);
    window.removeEventListener('resize', resize);
    delete textarea.dataset.kokuenAutosizeReady;
  };
}
