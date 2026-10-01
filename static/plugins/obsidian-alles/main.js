// minimal alles companion plugin: open the current note in the alles app.
// drop this folder into your vault's .obsidian/plugins/ and enable it.
const { Plugin, PluginSettingTab, Setting, Notice } = require("obsidian");

const DEFAULTS = { base: "http://localhost:6769" };

module.exports = class AllesPlugin extends Plugin {
  async onload() {
    this.settings = Object.assign({}, DEFAULTS, await this.loadData());
    this.addCommand({
      id: "open-in-alles",
      name: "Open current note in alles",
      callback: () => this.openCurrent(),
    });
    this.addRibbonIcon("link", "Open in alles", () => this.openCurrent());
    this.addSettingTab(new AllesSettingTab(this.app, this));
  }

  openCurrent() {
    const f = this.app.workspace.getActiveFile();
    if (!f) { new Notice("no note open"); return; }
    const base = (this.settings.base || "").replace(/\/+$/, "");
    if (!base) { new Notice("set your alles URL in plugin settings"); return; }
    // docs view resolves the note by name (works for notes + docs)
    window.open(`${base}/?app=wiki#${encodeURIComponent(f.basename)}`);
  }

  async saveSettings() { await this.saveData(this.settings); }
};

class AllesSettingTab extends PluginSettingTab {
  constructor(app, plugin) { super(app, plugin); this.plugin = plugin; }
  display() {
    const { containerEl } = this;
    containerEl.empty();
    new Setting(containerEl)
      .setName("alles URL")
      .setDesc("Base URL of your alles app — e.g. http://localhost:6769 or your home server.")
      .addText(t => t
        .setPlaceholder("http://localhost:6769")
        .setValue(this.plugin.settings.base)
        .onChange(async v => { this.plugin.settings.base = v.trim(); await this.plugin.saveSettings(); }));
  }
}
