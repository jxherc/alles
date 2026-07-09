import assert from 'node:assert/strict';
import { test } from 'node:test';

import { appSettingValue, renderAppSettingField } from '../../static/js/appsettings.js';

test('numeric text app setting renders with data-num and keeps zero visible', () => {
  const html = renderAppSettingField(
    { k: 'cal_work_start', type: 'text', num: true, label: 'work start', ph: '9' },
    0,
  );
  assert.match(html, /data-num="1"/);
  assert.match(html, /inputmode="numeric"/);
  assert.match(html, /value="0"/);
});

test('plain text app setting does not render as numeric', () => {
  const html = renderAppSettingField(
    { k: 'cal_secondary_tz', type: 'text', label: 'tz', ph: 'Europe\/London' },
    'Asia/Taipei',
  );
  assert.doesNotMatch(html, /data-num="1"/);
  assert.match(html, /value="Asia\/Taipei"/);
});

test('appSettingValue coerces numeric text values', () => {
  assert.equal(appSettingValue({ value: ' 23 ', dataset: { num: '1' } }), 23);
  assert.equal(appSettingValue({ value: '1.5', dataset: { num: '1' } }), 1.5);
  assert.equal(appSettingValue({ value: '', dataset: { num: '1' } }), '');
  assert.equal(appSettingValue({ value: 'Asia/Taipei', dataset: {} }), 'Asia/Taipei');
});
