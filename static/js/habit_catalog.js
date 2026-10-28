// the habits you can start from: each one knows its emoji, what its day log holds (kind) and,
// for counts, its unit. names are i18n keys (habits.cat_<id>); the id and `words` are english
// search words, so "gym" finds workout in any language.
import { t } from './i18n.js';

export const HABIT_GROUPS = ['fitness', 'health', 'mind', 'learning', 'home', 'money', 'social'];

const H = (group, id, icon, kind, unit = '', words = '') => ({ group, id, icon, kind, unit, words });

export const HABIT_CATALOG = [
  H('fitness', 'workout', '🏋️', 'workout', '', 'gym lift weights strength sets reps'),
  H('fitness', 'run', '🏃', 'distance', 'km', 'jog cardio'),
  H('fitness', 'walk', '🚶', 'duration', '', 'stroll'),
  H('fitness', 'cycle', '🚴', 'distance', 'km', 'bike cycling'),
  H('fitness', 'swim', '🏊', 'duration', '', 'pool laps'),
  H('fitness', 'hike', '🥾', 'distance', 'km', 'trail'),
  H('fitness', 'stretch', '🤸', 'duration', '', 'mobility'),
  H('fitness', 'yoga', '🧘', 'duration', '', ''),
  H('fitness', 'pushups', '💪', 'count', 'reps', 'push ups'),
  H('fitness', 'squats', '🦵', 'count', 'reps', 'legs'),
  H('fitness', 'pullups', '🙌', 'count', 'reps', 'pull ups chin'),
  H('fitness', 'steps', '👣', 'count', 'steps', 'walk'),
  H('fitness', 'climb', '🧗', 'duration', '', 'climbing bouldering'),
  H('fitness', 'sport', '⚽', 'duration', '', 'soccer football basketball tennis'),
  H('health', 'water', '💧', 'count', 'glasses', 'drink hydrate'),
  H('health', 'sleep', '😴', 'duration', '', 'rest bed'),
  H('health', 'vitamins', '💊', 'check', '', 'pills supplements'),
  H('health', 'floss', '🦷', 'check', '', 'teeth'),
  H('health', 'skincare', '🧴', 'check', '', 'skin'),
  H('health', 'no_sugar', '🍬', 'check', '', 'sweets candy'),
  H('health', 'no_alcohol', '🍷', 'check', '', 'drink sober'),
  H('health', 'veggies', '🥦', 'count', 'servings', 'fruit vegetables eat'),
  H('health', 'cold_shower', '🧊', 'check', '', 'cold plunge'),
  H('health', 'early_bed', '🌙', 'check', '', 'sleep bedtime'),
  H('health', 'sunlight', '☀️', 'duration', '', 'sun light morning'),
  H('mind', 'meditate', '🪷', 'duration', '', 'meditation calm mindfulness'),
  H('mind', 'journal', '📓', 'check', '', 'journaling diary write'),
  H('mind', 'gratitude', '🙏', 'check', '', 'thankful'),
  H('mind', 'breathe', '🌬️', 'duration', '', 'breathing breathwork'),
  H('mind', 'no_social', '📵', 'check', '', 'social media phone screen'),
  H('mind', 'outside', '🌳', 'duration', '', 'outdoors nature'),
  H('learning', 'reading', '📚', 'reading', '', 'read book pages chapters'),
  H('learning', 'language', '🗣️', 'duration', '', 'duolingo speak'),
  H('learning', 'instrument', '🎸', 'duration', '', 'music guitar piano practice'),
  H('learning', 'study', '📝', 'duration', '', 'homework school'),
  H('learning', 'coding', '💻', 'duration', '', 'code programming'),
  H('learning', 'writing', '✍️', 'count', 'words', 'write'),
  H('learning', 'flashcards', '🗂️', 'count', 'cards', 'anki review'),
  H('learning', 'drawing', '🎨', 'duration', '', 'draw art sketch paint'),
  H('learning', 'podcast', '🎧', 'duration', '', 'listen lecture audio'),
  H('home', 'tidy', '🧹', 'check', '', 'clean'),
  H('home', 'make_bed', '🛏️', 'check', '', ''),
  H('home', 'cook', '🍳', 'check', '', 'cooking meal'),
  H('home', 'dishes', '🍽️', 'check', '', 'wash'),
  H('home', 'laundry', '🧺', 'check', '', 'clothes wash'),
  H('home', 'plants', '🪴', 'check', '', 'water garden'),
  H('home', 'dog_walk', '🐕', 'duration', '', 'dog pet'),
  H('money', 'budget', '💰', 'check', '', 'money finance'),
  H('money', 'no_spend', '💳', 'check', '', 'spending money'),
  H('money', 'save', '🐷', 'check', '', 'savings money'),
  H('money', 'expenses', '🧾', 'check', '', 'track spending receipts'),
  H('social', 'call_family', '📞', 'check', '', 'phone parents'),
  H('social', 'message_friend', '💬', 'check', '', 'text chat'),
  H('social', 'kindness', '🤝', 'check', '', 'help kind'),
  H('social', 'friends', '🫂', 'duration', '', 'hang out social'),
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
