// the server's english reaches screens in the chosen language; logic keeps seeing the english
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { configureLocalization, installCatalog, installServerMessages, loadServerMessages, serverText } from '../../static/js/i18n.js';
import { plainError } from '../../static/js/util.js';

installCatalog({ schema_version: 1, language: 'fr', messages: {}, plurals: {} });

const FR = {
  'unknown account': 'compte inconnu',
  'no note {name}': 'aucune note {name}',
  'could not read {path}': 'impossible de lire {path}',
  'could not read {path} from {source}': 'impossible de lire {path} depuis {source}',
};

test('exact and template messages read in the chosen language', () => {
  configureLocalization({ language: 'fr' });
  installServerMessages('fr', FR);
  assert.equal(serverText('unknown account'), 'compte inconnu');
  assert.equal(serverText('no note shopping list'), 'aucune note shopping list');
  // the template with more fixed words wins over a looser one
  assert.equal(serverText('could not read a.md from backup'), 'impossible de lire a.md depuis backup');
  assert.equal(serverText('could not read a.md'), 'impossible de lire a.md');
  // our own lead-in stays, the server part after it is translated
  assert.equal(serverText('envoi impossible: unknown account'), 'envoi impossible: compte inconnu');
  assert.equal(serverText('something the server never says'), 'something the server never says');
  configureLocalization({ language: 'en' });
});

test('a toast shows the translation through plainError', () => {
  configureLocalization({ language: 'fr' });
  installServerMessages('fr', FR);
  assert.equal(plainError('unknown account'), 'compte inconnu');
  configureLocalization({ language: 'en' });
});

test('a server message that names bad json keeps its words; the browser’s own parse error is swapped', () => {
  configureLocalization({ language: 'en' });
  const server = 'policy is not valid JSON at line 1, column 2: Expecting property name enclosed in double quotes';
  assert.equal(plainError(server), server);
  assert.equal(plainError('backup manifest is not valid JSON'), 'backup manifest is not valid JSON');
  assert.notEqual(plainError('"undefined" is not valid JSON'), '"undefined" is not valid JSON');
  assert.notEqual(plainError(`Unexpected token '<', "<!DOCTYPE "... is not valid JSON`), `Unexpected token '<', "<!DOCTYPE "... is not valid JSON`);
});

test('until the language’s file is in, and in english, the server text is shown as written', async () => {
  installServerMessages('fr', FR);
  configureLocalization({ language: 'en' });
  assert.equal(serverText('unknown account'), 'unknown account');
  await loadServerMessages('en');
  configureLocalization({ language: 'fr' });
  assert.equal(serverText('unknown account'), 'unknown account');
  const fetched = [];
  await loadServerMessages('fr', async url => {
    fetched.push(url);
    return { ok: true, json: async () => ({ messages: FR }) };
  });
  assert.deepEqual(fetched, ['/static/locales/server/fr.json']);
  assert.equal(serverText('unknown account'), 'compte inconnu');
  configureLocalization({ language: 'en' });
});
