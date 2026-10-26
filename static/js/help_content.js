// Bundled instructions; actions use the existing guarded app routes.
// Built on each call, so every string follows the current interface language.
import { t } from './i18n.js';

const TOPIC_IDS = Object.freeze(['start', 'home', 'aide', 'coding', 'voice', 'andromeda', 'plan', 'docs', 'files', 'inbox', 'library', 'health', 'finance', 'vault', 'server', 'settings']);

export function helpTopics() {
  return [
    { id: 'start', title: t('help.start.title'), sections: [
      { text: [t('help.start.s1.text1'), t('help.start.s1.text2')] },
      { title: t('help.start.s2.title'), text: [t('help.start.s2.text1'), t('help.start.s2.text2')] },
      { title: t('help.start.s3.title'), text: [t('help.start.s3.text1'), t('help.start.s3.text2')] },
    ], actions: [{ label: t('help.start.action1'), view: 'today' }, { label: t('help.start.action2'), pane: 'general' }] },
    { id: 'home', title: t('help.home.title'), sections: [
      { text: [t('help.home.s1.text1'), t('help.home.s1.text2')] },
    ], actions: [{ label: t('help.home.action1'), view: 'today' }, { label: t('help.home.action2'), pane: 'home' }] },
    { id: 'aide', title: t('help.aide.title'), sections: [
      { title: t('help.aide.s1.title'), text: [t('help.aide.s1.text1'), t('help.aide.s1.text2')] },
      { title: t('help.aide.s2.title'), text: [t('help.aide.s2.text1'), t('help.aide.s2.text2')] },
      { title: t('help.aide.s3.title'), text: [t('help.aide.s3.text1'), t('help.aide.s3.text2')] },
    ], actions: [{ label: t('help.aide.action1'), view: 'chat' }, { label: t('help.aide.action2'), pane: 'models' }] },
    { id: 'coding', title: t('help.coding.title'), sections: [
      { title: t('help.coding.s1.title'), steps: [t('help.coding.s1.step1'), t('help.coding.s1.step2'), t('help.coding.s1.step3')] },
      { title: t('help.coding.s2.title'), text: [t('help.coding.s2.text1'), t('help.coding.s2.text2'), t('help.coding.s2.text3')] },
      { title: t('help.coding.s3.title'), text: [t('help.coding.s3.text1')] },
    ], actions: [{ label: t('help.coding.action1'), view: 'chat' }] },
    { id: 'voice', title: t('help.voice.title'), sections: [
      { title: t('help.voice.s1.title'), text: [t('help.voice.s1.text1'), t('help.voice.s1.text2')] },
      { title: t('help.voice.s2.title'), steps: [t('help.voice.s2.step1'), t('help.voice.s2.step2'), t('help.voice.s2.step3')], text: [t('help.voice.s2.text1')] },
      { title: t('help.voice.s3.title'), text: [t('help.voice.s3.text1'), t('help.voice.s3.text2')] },
      { title: t('help.voice.s4.title'), text: [t('help.voice.s4.text1'), t('help.voice.s4.text2')] },
    ], actions: [{ label: t('help.voice.action1'), view: 'chat' }, { label: t('help.voice.action2'), pane: 'voice' }, { label: t('help.voice.action3'), pane: 'models' }] },
    { id: 'andromeda', title: t('help.andromeda.title'), sections: [
      { text: [t('help.andromeda.s1.text1'), t('help.andromeda.s1.text2')] },
    ], actions: [{ label: t('help.andromeda.action1'), view: 'andromeda' }] },
    { id: 'plan', title: t('help.plan.title'), sections: [
      { text: [t('help.plan.s1.text1'), t('help.plan.s1.text2')] },
    ], actions: [{ label: t('help.plan.action1'), view: 'plan' }, { label: t('help.plan.action2'), view: 'tasks' }, { label: t('help.plan.action3'), view: 'calendar' }] },
    { id: 'docs', title: t('help.docs.title'), sections: [
      { text: [t('help.docs.s1.text1'), t('help.docs.s1.text2')] },
    ], actions: [{ label: t('help.docs.action1'), view: 'wiki' }, { label: t('help.docs.action2'), view: 'journal' }] },
    { id: 'files', title: t('help.files.title'), sections: [
      { text: [t('help.files.s1.text1'), t('help.files.s1.text2')] },
    ], actions: [{ label: t('help.files.action1'), view: 'files' }, { label: t('help.files.action2'), view: 'files-gallery' }] },
    { id: 'inbox', title: t('help.inbox.title'), sections: [
      { text: [t('help.inbox.s1.text1'), t('help.inbox.s1.text2')] },
    ], actions: [{ label: t('help.inbox.action1'), view: 'mail' }, { label: t('help.inbox.action2'), view: 'contacts' }] },
    { id: 'library', title: t('help.library.title'), sections: [
      { text: [t('help.library.s1.text1'), t('help.library.s1.text2')] },
    ], actions: [{ label: t('help.library.action1'), view: 'books' }, { label: t('help.library.action2'), view: 'read' }] },
    { id: 'health', title: t('help.health.title'), sections: [
      { text: [t('help.health.s1.text1'), t('help.health.s1.text2')] },
    ], actions: [{ label: t('help.health.action1'), view: 'health-overview' }, { label: t('help.health.action2'), view: 'habits' }] },
    { id: 'finance', title: t('help.finance.title'), sections: [
      { text: [t('help.finance.s1.text1')] },
      { title: t('help.finance.s2.title'), steps: [t('help.finance.s2.step1'), t('help.finance.s2.step2'), t('help.finance.s2.step3')], text: [t('help.finance.s2.text1')] },
      { title: t('help.finance.s3.title'), text: [t('help.finance.s3.text1'), t('help.finance.s3.text2')], code: "date,payee,amount,currency\n2026-01-01,Example groceries,-8.25,CAD\n2026-01-02,Example income,100.00,CAD", after: [t('help.finance.s3.after1'), t('help.finance.s3.after2')] },
      { title: t('help.finance.s4.title'), text: [t('help.finance.s4.text1'), t('help.finance.s4.text2'), t('help.finance.s4.text3'), t('help.finance.s4.text4')] },
      { title: t('help.finance.s5.title'), text: [t('help.finance.s5.text1'), t('help.finance.s5.text2'), t('help.finance.s5.text3')] },
      { title: t('help.finance.s6.title'), text: [t('help.finance.s6.text1'), t('help.finance.s6.text2'), t('help.finance.s6.text3')] },
      { title: t('help.finance.s7.title'), text: [t('help.finance.s7.text1'), t('help.finance.s7.text2')] },
    ], actions: [{ label: t('help.finance.action1'), view: 'money' }, { label: t('help.finance.action2'), view: 'imports' }, { label: t('help.finance.action3'), view: 'subs' }, { label: t('help.finance.action4'), view: 'finance-overview' }] },
    { id: 'vault', title: t('help.vault.title'), sections: [
      { text: [t('help.vault.s1.text1'), t('help.vault.s1.text2'), t('help.vault.s1.text3')] },
    ], actions: [{ label: t('help.vault.action1'), view: 'vault' }] },
    { id: 'server', title: t('help.server.title'), sections: [
      { text: [t('help.server.s1.text1'), t('help.server.s1.text2')] },
    ], actions: [{ label: t('help.server.action1'), view: 'server' }, { label: t('help.server.action2'), view: 'server-backups' }] },
    { id: 'settings', title: t('help.settings.title'), sections: [
      { text: [t('help.settings.s1.text1'), t('help.settings.s1.text2'), t('help.settings.s1.text3')] },
    ], actions: [{ label: t('help.settings.action1'), pane: 'general' }, { label: t('help.settings.action2'), pane: 'developer' }, { label: t('help.settings.action3'), pane: 'backup' }] },
  ];
}

export function findManualTopics(query = '', topics = helpTopics()) {
  const words = String(query).trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
  return topics.filter(topic => words.every(word => JSON.stringify(topic).toLocaleLowerCase().includes(word)));
}

export function manualTopicForApp({ space = '', app = '' } = {}) {
  if (space === 'today') return 'home';
  if (space === 'aide' || space === 'andromeda') return space;
  const aliases = { alles: 'home', today: 'home', chat: 'aide', wiki: 'docs', journal: 'docs', money: 'finance', subs: 'finance', imports: 'finance', passwords: 'vault', system: 'server', mail: 'inbox', contacts: 'inbox', books: 'library', read: 'library', habits: 'health' };
  const id = aliases[app] || app;
  return TOPIC_IDS.includes(id) ? id : 'start';
}
