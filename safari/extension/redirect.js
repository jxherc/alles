// on a search page, open the same words in andromeda. the redirect rules usually got here first;
// this covers a safari that didn't run them. never on a page andromeda itself sent you to
(async () => {
  const { origin } = await browser.storage.local.get('origin');
  if (!origin || (document.referrer && document.referrer.startsWith(origin))) return;
  const words = searchedWords(new URL(location.href));
  if (!words) return;
  // the popup shows the last search it caught, so you can tell it's working
  await browser.storage.local.set({ caught: { host: location.hostname, at: Date.now() } });
  location.replace(andromedaUrl(origin, words));
})();
