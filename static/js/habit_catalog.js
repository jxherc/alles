// the habits you can start from: each one knows its emoji and its kind. names are i18n keys
// (habits.cat_<id>); the id and `words` are english search words, so "gym" finds workout in any
// language.
import { t } from './i18n.js';

export const HABIT_GROUPS = ['fitness', 'health', 'mind', 'learning', 'home', 'money', 'social'];

// every catalog habit is its own kind (services/habit_kinds.py CATALOG): its day log holds that
// kind's own fields, from GET /api/habits/kinds
const H = (group, id, icon, words = '') => ({ group, id, icon, kind: id, unit: '', words });

export const HABIT_CATALOG = [
  H('fitness', 'workout', '🏋️', 'gym lift weights strength sets reps'),
  H('fitness', 'run', '🏃', 'jog cardio'),
  H('fitness', 'walk', '🚶', 'stroll'),
  H('fitness', 'cycle', '🚴', 'bike cycling'),
  H('fitness', 'swim', '🏊', 'pool laps'),
  H('fitness', 'hike', '🥾', 'trail'),
  H('fitness', 'stretch', '🤸', 'mobility'),
  H('fitness', 'yoga', '🧘', ''),
  H('fitness', 'pushups', '💪', 'push ups'),
  H('fitness', 'squats', '🦵', 'legs'),
  H('fitness', 'pullups', '🙌', 'pull ups chin'),
  H('fitness', 'steps', '👣', 'walk'),
  H('fitness', 'climb', '🧗', 'climbing bouldering'),
  H('fitness', 'sport', '⚽', 'soccer football basketball tennis'),
  H('health', 'water', '💧', 'drink hydrate'),
  H('health', 'sleep', '😴', 'rest bed'),
  H('health', 'vitamins', '💊', 'pills supplements'),
  H('health', 'floss', '🦷', 'teeth'),
  H('health', 'skincare', '🧴', 'skin'),
  H('health', 'no_sugar', '🍬', 'sweets candy'),
  H('health', 'no_alcohol', '🍷', 'drink sober'),
  H('health', 'veggies', '🥦', 'fruit vegetables eat'),
  H('health', 'cold_shower', '🧊', 'cold plunge'),
  H('health', 'early_bed', '🌙', 'sleep bedtime'),
  H('health', 'sunlight', '☀️', 'sun light morning'),
  H('mind', 'meditate', '🪷', 'meditation calm mindfulness'),
  H('mind', 'journal', '📓', 'journaling diary write'),
  H('mind', 'gratitude', '🙏', 'thankful'),
  H('mind', 'breathe', '🌬️', 'breathing breathwork'),
  H('mind', 'no_social', '📵', 'social media phone screen'),
  H('mind', 'outside', '🌳', 'outdoors nature'),
  H('learning', 'reading', '📚', 'read book pages chapters'),
  H('learning', 'language', '🗣️', 'duolingo speak'),
  H('learning', 'instrument', '🎸', 'music guitar piano practice'),
  H('learning', 'study', '📝', 'homework school'),
  H('learning', 'coding', '💻', 'code programming'),
  H('learning', 'writing', '✍️', 'write'),
  H('learning', 'flashcards', '🗂️', 'anki review'),
  H('learning', 'drawing', '🎨', 'draw art sketch paint'),
  H('learning', 'podcast', '🎧', 'listen lecture audio'),
  H('home', 'tidy', '🧹', 'clean'),
  H('home', 'make_bed', '🛏️', ''),
  H('home', 'cook', '🍳', 'cooking meal'),
  H('home', 'dishes', '🍽️', 'wash'),
  H('home', 'laundry', '🧺', 'clothes wash'),
  H('home', 'plants', '🪴', 'water garden'),
  H('home', 'dog_walk', '🐕', 'dog pet'),
  H('money', 'budget', '💰', 'money finance'),
  H('money', 'no_spend', '💳', 'spending money'),
  H('money', 'save', '🐷', 'savings money'),
  H('money', 'expenses', '🧾', 'track spending receipts'),
  H('social', 'call_family', '📞', 'phone parents'),
  H('social', 'message_friend', '💬', 'text chat'),
  H('social', 'kindness', '🤝', 'help kind'),
  H('social', 'friends', '🫂', 'hang out social'),
];

export const catalogName = entry => t(`habits.cat_${entry.id}`);
export const catalogEntry = id => HABIT_CATALOG.find(entry => entry.id === id) || null;

// options for dialog.pick(): grouped, with the emoji and english words to search on
export function catalogOptions() {
  return HABIT_CATALOG.map(entry => ({
    value: entry.id,
    label: catalogName(entry),
    icon: entry.icon,
    group: t(`habits.group_${entry.group}`),
    words: `${entry.id.replace(/_/g, ' ')} ${entry.words}`,
  }));
}
