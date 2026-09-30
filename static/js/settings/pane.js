// Reads belong to one opening. Disposal keeps the pane's drafts and pending saves.
export function createSettingsPane({ init = () => {}, load, dispose = () => {} }) {
  let initialized = false;
  let generation = 0;
  let active = false;
  return {
    init() {
      if (initialized) return;
      init();
      initialized = true;
    },
    load() {
      this.init();
      active = true;
      const request = ++generation;
      return load(() => active && request === generation);
    },
    dispose() {
      active = false;
      generation += 1;
      dispose();
    },
  };
}
