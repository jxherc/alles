import test from 'node:test';
import assert from 'node:assert/strict';

import {
  calendarDateParts,
  datePickerWeekdayLabels,
  resolveDatePickerWeekStart,
} from '../../static/js/datepick.js';

test('date picker rejects normalized overflow dates', () => {
  assert.equal(calendarDateParts('2026-02-31'), null);
  assert.equal(calendarDateParts('2025-02-29'), null);
  assert.deepEqual(calendarDateParts('2024-02-29'), { y: 2024, mo: 1, d: 29, h: 0, mi: 0 });
});

test('date picker resolves explicit and automatic week starts', () => {
  assert.equal(resolveDatePickerWeekStart({ weekStart: 'mon', effectiveRegion: 'US' }), 1);
  assert.equal(resolveDatePickerWeekStart({ weekStart: 'sun', effectiveRegion: 'DE' }), 0);
  assert.equal(resolveDatePickerWeekStart({ weekStart: 'auto', effectiveRegion: 'US' }), 0);
  assert.equal(resolveDatePickerWeekStart({ weekStart: 'auto', effectiveRegion: 'DE' }), 1);
});

test('date picker localizes weekday headings', () => {
  const english = datePickerWeekdayLabels({ locale: 'en-US' });
  const japanese = datePickerWeekdayLabels({ locale: 'ja-JP' });
  assert.equal(english.length, 7);
  assert.equal(japanese.length, 7);
  assert.notDeepEqual(japanese, english);
  assert.match(japanese[0], /日/);
});
