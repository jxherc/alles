import { readFileSync } from 'node:fs';
import process from 'node:process';
import { fileURLToPath } from 'node:url';
import { createHash } from 'node:crypto';
import * as api from '@actual-app/api';

const RESULT_PREFIX = 'ALLES_ACTUAL_RESULT=';

class StagedBudgetCleanupError extends Error {
  constructor(primaryError, cleanupError, created) {
    super(`${primaryError.message}; ${cleanupError.message}`);
    this.stagedBudget = {
      budget_id: String(created.budget_id || ''),
      sync_id: String(created.sync_id || ''),
    };
  }
}

class StagedBudgetCleanupVerifiedError extends Error {
  constructor(primaryError) {
    super(primaryError.message);
  }
}

class ExistingStagedBudgetError extends Error {
  constructor(budget) {
    super('existing Actual staging budget requires reconciliation');
    this.stagedBudget = {
      budget_id: String(budget.id || ''),
      sync_id: String(budget.groupId || ''),
    };
  }
}

function safeMinor(value, label) {
  if (!Number.isSafeInteger(value)) throw new Error(`${label} must be a JavaScript-safe integer`);
  return value;
}

const SAFE_BRIDGE_ERRORS = new Set([
  'installed Actual API does not provide its declared client contract',
  'sync_id is required for fresh-client readback',
  'budget_id or sync_id is required',
  'Actual managed category group requires a budget identity',
  'Actual managed category group is not unique',
  'Actual managed category name is not unique',
  'created Actual budget id was not uniquely discoverable',
  'new Actual budget id is ambiguous',
  'failed to remove incomplete Actual staging budget',
  'Actual staged budget id is required for cleanup',
  'Actual staged budget identity is not unique',
  'Actual staged budget sync identity changed',
  'Actual staged budget cleanup could not be verified',
  'existing Actual staging budget requires reconciliation',
  'Actual transfer payees are incomplete',
  'Actual transfer migration linkage could not be verified',
  'Actual account creation requires its stable operation marker',
  'Actual account creation marker is not unique',
  'Actual budget creation requires its stable operation marker',
  'Actual budget creation marker is not unique',
  'Actual transfer payee was not found',
  'Actual transfer legs were not discoverable',
  'Actual transfer linkage is incomplete',
  'Actual transfer deletion requires one complete pair',
  'Actual transfer deletion target is not one reciprocal pair',
  'Actual transfer pair was not fully deleted',
  'Actual transaction deletion could not be verified',
  'Actual partial transfer cleanup could not be verified',
  'Actual budget category name is required',
  'Actual budget category id is required',
]);
const PRIVATE_REQUEST_KEY_FRAGMENTS = [
  'password', 'token', 'secret', 'authorization', 'server_url', 'data_dir',
];

function requestPrivateValues(value, key = '') {
  if (Array.isArray(value)) return value.flatMap(item => requestPrivateValues(item, key));
  if (value && typeof value === 'object') {
    return Object.entries(value).flatMap(([childKey, item]) => requestPrivateValues(item, childKey));
  }
  const normalizedKey = key.toLowerCase();
  const privateRequestField = PRIVATE_REQUEST_KEY_FRAGMENTS.some(
    fragment => normalizedKey.includes(fragment),
  ) || /(?:^|_)(?:id|ids)$/.test(normalizedKey);
  return privateRequestField && typeof value === 'string' && value ? [value] : [];
}

function redactPrivateDetails(value, request) {
  let message = String(value || 'Actual bridge failed');
  const privateValues = [...new Set(requestPrivateValues(request))].sort((left, right) => right.length - left.length);
  for (const privateValue of privateValues) message = message.split(privateValue).join('[redacted]');
  message = message.replace(/https?:\/\/[^\s"'<>]+/gi, '[redacted url]');
  message = message.replace(/(?:[A-Za-z]:\\|\/)(?:[^\s"'<>]+[\\/])+[^\s"'<>]*/g, '[redacted path]');
  return message;
}

function cleanError(error, request) {
  const message = redactPrivateDetails(error?.message || error, request);
  if (SAFE_BRIDGE_ERRORS.has(message)) return message;
  if (message.endsWith('must be a JavaScript-safe integer')) {
    return 'Actual bridge received an invalid monetary value';
  }
  if (message.startsWith('installed package identity is invalid for ')) {
    return 'installed Actual package identity is invalid';
  }
  return 'Actual bridge operation failed with private details withheld';
}

function packageVersion(name) {
  const packageFile = fileURLToPath(new URL(`./node_modules/${name}/package.json`, import.meta.url));
  const manifest = JSON.parse(readFileSync(packageFile, 'utf8'));
  if (manifest.name !== name || typeof manifest.version !== 'string') {
    throw new Error(`installed package identity is invalid for ${name}`);
  }
  return manifest.version;
}

function serverConfig(request, dataDir = request.data_dir) {
  const config = { dataDir, verbose: false };
  if (request.server_url) {
    config.serverURL = request.server_url;
    config.password = String(request.password || '');
  }
  return config;
}

async function initActualClient(request, dataDir = request.data_dir) {
  // The pinned @actual-app/api 26.7.0 declaration makes init() return the
  // initialized client, including its typed send() method. Budget lifecycle
  // handlers are available on that client rather than as top-level helpers.
  const client = await api.init(serverConfig(request, dataDir));
  if (!client || typeof client.send !== 'function') {
    throw new Error('installed Actual API does not provide its declared client contract');
  }
  return client;
}

async function loadBudget(request, { dataDir, preferSync = false } = {}) {
  const client = await initActualClient(request, dataDir || request.data_dir);
  if (preferSync) {
    if (!request.sync_id) throw new Error('sync_id is required for fresh-client readback');
    await api.downloadBudget(request.sync_id, { password: String(request.password || '') });
  }
  else if (request.budget_id) await api.loadBudget(request.budget_id);
  else if (request.sync_id) await api.downloadBudget(request.sync_id, { password: String(request.password || '') });
  else throw new Error('budget_id or sync_id is required');
  return client;
}

function dateRule(row) {
  const cycle = row.cycle || 'monthly';
  const base = { start: row.next_date, frequency: cycle, interval: 1, endMode: 'never' };
  const anchor = Number(row.anchor_day || 0);
  const patterns = ['monthly', 'quarterly'].includes(cycle) && anchor
    ? [{ type: 'day', value: anchor === 31 ? -1 : anchor }]
    : undefined;
  if (cycle === 'quarterly') return { ...base, frequency: 'monthly', interval: 3, patterns };
  if (cycle === 'custom') return { ...base, frequency: 'daily', interval: Math.max(1, Number(row.cycle_days || 30)) };
  if (!['daily', 'weekly', 'monthly', 'yearly'].includes(base.frequency)) base.frequency = 'monthly';
  return patterns ? { ...base, patterns } : base;
}

async function allTransactions(accounts) {
  const rows = [];
  for (const account of accounts) {
    const transactions = await api.getTransactions(account.id, '1900-01-01', '9999-12-31');
    rows.push(...transactions);
  }
  return rows;
}

async function inspectBudget() {
  const accounts = await api.getAccounts();
  const [payees, categories, categoryGroups, schedules, months, transactions] = await Promise.all([
    api.getPayees(), api.getCategories(), api.getCategoryGroups(),
    api.getSchedules(), api.getBudgetMonths(), allTransactions(accounts),
  ]);
  const payeeNames = new Map(payees.map(item => [item.id, item.name]));
  const categoryNames = new Map(categories.map(item => [item.id, item.name]));
  const balances = {};
  const allDatesCutoff = new Date('9999-12-31T00:00:00.000Z');
  for (const account of accounts) {
    balances[account.id] = await api.getAccountBalance(account.id, allDatesCutoff);
  }
  const budgetMonths = [];
  for (const month of months) budgetMonths.push(await api.getBudgetMonth(month));
  return {
    accounts: accounts.map(item => ({ ...item, balance: balances[item.id] })),
    transactions: transactions.map(item => ({
      ...item,
      payee_name: payeeNames.get(item.payee) || '',
      category_name: categoryNames.get(item.category) || '',
    })),
    payees,
    categories,
    category_groups: categoryGroups,
    schedules,
    budget_months: budgetMonths,
  };
}

async function ensureCategory(name, categoryMap, groupId) {
  const key = String(name || '').trim();
  if (!key) return null;
  if (!categoryMap.has(key)) {
    categoryMap.set(key, await api.createCategory({ name: key, group_id: groupId, is_income: false, hidden: false }));
  }
  return categoryMap.get(key);
}

async function managedBudgetIdentity(request) {
  const syncId = String(request.sync_id || '').trim();
  if (syncId) return syncId;
  const budgetId = String(request.budget_id || '').trim();
  if (!budgetId) throw new Error('Actual managed category group requires a budget identity');
  const matches = (await api.getBudgets()).filter(item => item.id === budgetId);
  if (matches.length > 1) throw new Error('Actual local budget identity is not unique');
  return String(matches[0]?.groupId || '').trim() || budgetId;
}

async function managedCategoryGroupName(request) {
  const budgetIdentity = await managedBudgetIdentity(request);
  const marker = createHash('sha256').update(budgetIdentity).digest('hex').slice(0, 24);
  return `Alles managed ${marker}`;
}

async function managedCategoryContext(request, categories, groups) {
  const name = await managedCategoryGroupName(request);
  const matches = groups.filter(item => item.name === name);
  if (matches.length > 1) throw new Error('Actual managed category group is not unique');
  const groupId = matches[0]?.id || await api.createCategoryGroup({
    name,
    is_income: false,
    hidden: false,
  });
  const categoryMap = new Map();
  for (const item of categories.filter(category => category.group_id === groupId)) {
    if (categoryMap.has(item.name) && categoryMap.get(item.name) !== item.id) {
      throw new Error('Actual managed category name is not unique');
    }
    categoryMap.set(item.name, item.id);
  }
  return { categoryMap, groupId };
}

async function ensurePayee(name, payeeMap) {
  const key = String(name || '').trim();
  if (!key) return null;
  if (payeeMap.get(key) === null) {
    throw new Error('Actual payee name is not unique');
  }
  if (!payeeMap.has(key)) payeeMap.set(key, await api.createPayee({ name: key }));
  return payeeMap.get(key);
}

function canonicalPayeeMap(payees) {
  const payeeMap = new Map();
  for (const item of payees.filter(payee => !payee.transfer_acct)) {
    const name = String(item.name || '').trim();
    if (!name) continue;
    if (payeeMap.has(name) && payeeMap.get(name) !== item.id) {
      payeeMap.set(name, null);
    } else {
      payeeMap.set(name, item.id);
    }
  }
  return payeeMap;
}

async function createBudget(request) {
  const client = await initActualClient(request);
  const marker = String(request.operation_marker || '').trim();
  const markerPattern = /^Alles staged [0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
  if (!markerPattern.test(marker) || String(request.budget_name || '') !== marker) {
    throw new Error('Actual budget creation requires its stable operation marker');
  }
  let matches = (await api.getBudgets()).filter(item => item.name === marker);
  if (matches.length > 1) throw new Error('Actual budget creation marker is not unique');
  let creationAttempted = false;
  let budget = matches[0] || null;
  try {
    if (budget && request.replace_existing_staging === true) {
      // A prior migrate may have completed after its caller lost the response.
      // The marker proves identity, not incompleteness, so never delete or replay
      // into this candidate automatically.
      throw new ExistingStagedBudgetError(budget);
    }
    if (budget) {
      await api.loadBudget(budget.id);
    } else {
      creationAttempted = true;
      await client.send('create-budget', { budgetName: marker });
      matches = (await api.getBudgets()).filter(item => item.name === marker);
      if (matches.length !== 1) throw new Error('created Actual budget id was not uniquely discoverable');
      [budget] = matches;
    }
    if (request.server_url && !budget.groupId) {
      const upload = await client.send('upload-budget');
      if (upload?.error) throw new Error('new Actual budget could not be uploaded');
    }
    await api.sync();
    matches = (await api.getBudgets()).filter(item => item.name === marker);
    if (matches.length !== 1) throw new Error('created Actual budget id was not uniquely discoverable');
    [budget] = matches;
    if (request.server_url && !budget.groupId) {
      throw new Error('new Actual budget did not receive a sync identity');
    }
    return {
      client,
      result: {
        budget_id: budget.id,
        sync_id: budget.groupId || '',
        cloud_file_id: budget.cloudFileId || '',
      },
    };
  } catch (error) {
    // A matching stable marker may already be a fully migrated/cut-over budget.
    // Only clean up a budget that this invocation itself created.
    if (!creationAttempted) throw error;
    let stagedBudget = null;
    try {
      matches = (await api.getBudgets()).filter(item => item.name === marker);
      if (matches.length === 1) {
        [budget] = matches;
        stagedBudget = {
          budget_id: budget.id,
          sync_id: budget.groupId || '',
          cloud_file_id: budget.cloudFileId || '',
        };
        await removeCreatedBudget(client, stagedBudget);
      } else if (matches.length > 1) {
        throw new Error('new Actual budget id is ambiguous');
      }
    } catch (cleanupError) {
      if (stagedBudget) throw new StagedBudgetCleanupError(error, cleanupError, stagedBudget);
      throw new Error(`${error.message}; incomplete Actual staging budget cleanup failed: ${cleanupError.message}`);
    }
    throw error;
  }
}

async function remoteBudgetMatches(client, syncId) {
  if (!syncId) return [];
  const remote = await client.send('get-remote-files');
  if (!Array.isArray(remote)) throw new Error('Actual staged budget cleanup could not be verified');
  return remote.filter(item => String(item.groupId || '') === syncId);
}

async function removeCreatedBudget(client, created) {
  await client.send('close-budget');
  const result = await client.send('delete-budget', {
    id: created.budget_id || undefined,
    cloudFileId: created.cloud_file_id || undefined,
  });
  if (result !== 'ok') throw new Error('failed to remove incomplete Actual staging budget');
  const syncId = String(created.sync_id || '').trim();
  const remainingLocal = (await api.getBudgets()).filter(item => (
    (created.budget_id && item.id === created.budget_id)
      || (syncId && String(item.groupId || '') === syncId)
  ));
  const remainingRemote = await remoteBudgetMatches(client, syncId);
  if (remainingLocal.length || remainingRemote.length) {
    throw new Error('Actual staged budget cleanup could not be verified');
  }
}

async function deleteStagedBudget(request) {
  const budgetId = String(request.budget_id || '').trim();
  const syncId = String(request.sync_id || '').trim();
  if (!budgetId && !syncId) throw new Error('budget_id or sync_id is required');
  const client = await initActualClient(request);
  let localBudgets = await api.getBudgets();
  if (!budgetId && syncId && !localBudgets.some(item => String(item.groupId || '') === syncId)) {
    await api.downloadBudget(syncId, { password: String(request.password || '') });
    localBudgets = await api.getBudgets();
  }
  const idMatches = localBudgets.filter(item => item.id === budgetId);
  const syncMatches = syncId
    ? localBudgets.filter(item => String(item.groupId || '') === syncId)
    : [];
  const remoteMatches = await remoteBudgetMatches(client, syncId);
  if (idMatches.length > 1 || syncMatches.length > 1 || remoteMatches.length > 1) {
    throw new Error('Actual staged budget identity is not unique');
  }
  if (budgetId && idMatches.length !== 1) {
    throw new Error('Actual staged budget id no longer matches');
  }
  if (syncId && syncMatches.length !== 1) {
    throw new Error('Actual staged budget sync identity changed');
  }
  if (budgetId && syncId && idMatches[0] !== syncMatches[0]) {
    throw new Error('Actual staged budget sync identity changed');
  }
  const localBudget = budgetId ? idMatches[0] : syncMatches[0];
  const [remoteBudget] = remoteMatches;
  if (localBudget && remoteBudget && String(localBudget.cloudFileId || '') !== String(remoteBudget.fileId || '')) {
    throw new Error('Actual staged budget sync identity changed');
  }
  if (!localBudget && !remoteBudget) {
    return { budget_id: budgetId, sync_id: syncId, deleted: false, verified_absent: true };
  }
  await removeCreatedBudget(client, {
    budget_id: localBudget?.id || '',
    sync_id: syncId,
    cloud_file_id: localBudget?.cloudFileId || remoteBudget?.fileId || '',
  });
  return {
    budget_id: budgetId || localBudget?.id || '',
    sync_id: syncId,
    deleted: true,
    verified_absent: true,
  };
}

async function migrate(request) {
  if (request.replace_existing_staging !== true) {
    throw new Error('Actual migration requires explicit incomplete staging replacement authority');
  }
  const { client, result: created } = await createBudget(request);
  try {
    request.budget_id = created.budget_id;
    request.sync_id = created.sync_id;
    const snapshot = request.snapshot;
    const accountMap = new Map();
    const entityLinks = [];
    for (const row of snapshot.accounts) {
      const actualId = await api.createAccount(
        { name: row.name, offbudget: ['investment'].includes(row.kind), closed: Boolean(row.archived) },
        safeMinor(row.opening_minor, 'account opening balance'),
      );
      accountMap.set(row.id, actualId);
      entityLinks.push({ kind: 'account', source_id: row.id, actual_id: actualId, metadata: row.evidence });
    }

    const categoryGroupId = await api.createCategoryGroup({
      name: await managedCategoryGroupName(request),
      is_income: false,
      hidden: false,
    });
    // The legacy snapshot contains category/payee strings, not entity records.
    // A single mapping per unique string preserves that source model exactly.
    const categoryMap = new Map();
    for (const name of snapshot.category_names) await ensureCategory(name, categoryMap, categoryGroupId);
    const payeeMap = new Map();
    for (const name of snapshot.payee_names) await ensurePayee(name, payeeMap);

    for (const sourceAccount of snapshot.accounts) {
      const accountId = accountMap.get(sourceAccount.id);
      const rows = snapshot.transactions.filter(item => item.account_id === sourceAccount.id);
      if (!rows.length) continue;
      const result = await api.addTransactions(accountId, rows.map(row => ({
        date: row.date,
        amount: safeMinor(row.amount_minor, 'transaction amount'),
        payee: payeeMap.get(row.payee) || null,
        payee_name: payeeMap.has(row.payee) ? undefined : (row.payee || undefined),
        imported_payee: row.payee || undefined,
        category: categoryMap.get(row.category) || undefined,
        notes: row.notes,
        imported_id: row.import_identity,
        cleared: Boolean(row.cleared),
      })), { learnCategories: false, runTransfers: false });
      if (result !== 'ok') throw new Error('Actual transaction import failed');
    }

    let current = await inspectBudget();
    const importedKey = (accountId, importedId) => `${accountId}\u0000${importedId}`;
    const byImported = new Map(current.transactions
      .filter(item => item.account && item.imported_id)
      .map(item => [importedKey(item.account, item.imported_id), item]));
    const transferPayees = new Map(current.payees.filter(item => item.transfer_acct).map(item => [item.transfer_acct, item.id]));
    for (const row of snapshot.transactions) {
      const actual = byImported.get(importedKey(accountMap.get(row.account_id), row.import_identity));
      if (!actual) throw new Error(`Actual did not return imported transaction ${row.id}`);
      entityLinks.push({ kind: 'transaction', source_id: row.id, actual_id: actual.id, metadata: row.evidence });
    }
    for (const pair of snapshot.transfer_pairs) {
      const left = byImported.get(importedKey(accountMap.get(pair.left.account_id), pair.left.import_identity));
      const right = byImported.get(importedKey(accountMap.get(pair.right.account_id), pair.right.import_identity));
      if (!left || !right) throw new Error(`transfer pair ${pair.id} is incomplete after import`);
      const leftPayee = transferPayees.get(accountMap.get(pair.right.account_id));
      const rightPayee = transferPayees.get(accountMap.get(pair.left.account_id));
      if (!leftPayee || !rightPayee) throw new Error('Actual transfer payees are incomplete');
      await api.updateTransaction(left.id, { transfer_id: right.id, payee: leftPayee });
      await api.updateTransaction(right.id, { transfer_id: left.id, payee: rightPayee });
      await api.sync();
      current = await inspectBudget();
      const verifiedLeft = current.transactions.find(item => item.id === left.id);
      const verifiedRight = current.transactions.find(item => item.id === right.id);
      if (
        !verifiedLeft || !verifiedRight
        || verifiedLeft.transfer_id !== right.id || verifiedRight.transfer_id !== left.id
        || verifiedLeft.payee !== leftPayee || verifiedRight.payee !== rightPayee
      ) {
        throw new Error('Actual transfer migration linkage could not be verified');
      }
      entityLinks.push({ kind: 'transfer', source_id: pair.id, actual_id: `${left.id}:${right.id}`, metadata: {} });
    }

    for (const row of snapshot.budget_assignments) {
      const categoryId = await ensureCategory(row.category, categoryMap, categoryGroupId);
      await api.setBudgetAmount(row.month, categoryId, safeMinor(row.amount_minor, 'budget amount'));
      entityLinks.push({ kind: 'budget_assignment', source_id: row.id, actual_id: `${row.month}:${categoryId}`, metadata: row.metadata });
    }

    for (const row of snapshot.schedules) {
      const accountId = row.account_id ? accountMap.get(row.account_id) : undefined;
      const payee = await ensurePayee(row.payee || row.name, payeeMap);
      // Actual 26.7.0's APIScheduleEntity has no category field. Keep the source
      // category in the immutable entity-link metadata rather than passing an
      // unsupported property that createSchedule() cannot persist or reconcile.
      const actualId = await api.createSchedule({
        name: row.name,
        posts_transaction: Boolean(row.posts_transaction),
        completed: !row.active,
        payee,
        account: accountId,
        amount: safeMinor(row.amount_minor, 'schedule amount'),
        amountOp: 'is',
        date: dateRule(row),
      });
      entityLinks.push({ kind: row.kind, source_id: row.id, actual_id: actualId, metadata: row.metadata });
    }

    await api.sync();
    current = await inspectBudget();
    return { ...created, links: entityLinks, actual: current };
  } catch (error) {
    try {
      await removeCreatedBudget(client, created);
    } catch (cleanupError) {
      throw new StagedBudgetCleanupError(error, cleanupError, created);
    }
    throw new StagedBudgetCleanupVerifiedError(error);
  }
}

async function write(request) {
  await loadBudget(request);
  if (request.action === 'create_account') {
    const marker = String(request.operation_marker || '').trim();
    const markerPattern = /^Alles pending [0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
    if (!markerPattern.test(marker) || String(request.account?.name || '') !== marker) {
      throw new Error('Actual account creation requires its stable operation marker');
    }
    const matches = (await api.getAccounts()).filter(item => item.name === marker);
    if (matches.length > 1) throw new Error('Actual account creation marker is not unique');
    const id = matches[0]?.id || await api.createAccount(
      request.account,
      safeMinor(request.initial_balance_minor || 0, 'account opening balance'),
    );
    await api.sync();
    return { id, ...(await api.getAccounts()).find(item => item.id === id) };
  }
  if (request.action === 'update_account') {
    await api.updateAccount(request.actual_id, request.fields || {});
    await api.sync();
    return (await api.getAccounts()).find(item => item.id === request.actual_id);
  }
  if (request.action === 'close_account') {
    const transferAccountId = String(request.transfer_account_id || '').trim();
    const transferCategoryId = String(request.transfer_category_id || '').trim();
    if (transferAccountId && transferAccountId === request.actual_id) {
      throw new Error('Actual account close transfer target must be a different account');
    }
    await api.closeAccount(
      request.actual_id,
      transferAccountId || undefined,
      transferCategoryId || undefined,
    );
    await api.sync();
    return { id: request.actual_id, closed: true };
  }
  if (request.action === 'create_transaction') {
    const transaction = { ...(request.transaction || {}) };
    const importedId = String(transaction.imported_id || '').trim();
    if (!importedId) throw new Error('Actual transaction import requires a stable imported id');
    transaction.imported_id = importedId;
    transaction.amount = safeMinor(transaction.amount, 'transaction amount');
    const [payees, categories, groups] = await Promise.all([
      api.getPayees(), api.getCategories(), api.getCategoryGroups(),
    ]);
    const payeeMap = canonicalPayeeMap(payees);
    const { categoryMap, groupId } = await managedCategoryContext(request, categories, groups);
    transaction.payee = await ensurePayee(transaction.payee_name, payeeMap);
    transaction.category = await ensureCategory(transaction.category_name, categoryMap, groupId);
    delete transaction.payee_name;
    delete transaction.category_name;
    const result = await api.importTransactions(transaction.account, [transaction], {
      defaultCleared: false,
      reimportDeleted: request.reimport_deleted === true,
    });
    if (result.errors?.length) throw new Error(result.errors[0].message);
    await api.sync();
    const current = await inspectBudget();
    const matches = current.transactions.filter(item => (
      item.account === transaction.account && item.imported_id === transaction.imported_id
    ));
    if (matches.length !== 1) throw new Error('Actual imported transaction was not uniquely discoverable');
    return matches[0];
  }
  if (request.action === 'update_transaction') {
    const fields = { ...(request.fields || {}) };
    if ('amount' in fields) fields.amount = safeMinor(fields.amount, 'transaction amount');
    if ('payee_name' in fields || 'category_name' in fields) {
      const [payees, categories, groups] = await Promise.all([
        api.getPayees(), api.getCategories(), api.getCategoryGroups(),
      ]);
      const payeeMap = canonicalPayeeMap(payees);
      const { categoryMap, groupId } = await managedCategoryContext(request, categories, groups);
      if ('payee_name' in fields) {
        fields.payee = await ensurePayee(fields.payee_name, payeeMap);
        if (!fields.payee_name) fields.imported_payee = null;
      }
      if ('category_name' in fields) fields.category = await ensureCategory(fields.category_name, categoryMap, groupId);
      delete fields.payee_name;
      delete fields.category_name;
    }
    await api.updateTransaction(request.actual_id, fields);
    await api.sync();
    const current = await inspectBudget();
    return current.transactions.find(item => item.id === request.actual_id);
  }
  if (request.action === 'delete_transaction') {
    const beforeRows = await allTransactions(await api.getAccounts());
    const matches = beforeRows.filter(item => item.id === request.actual_id);
    if (matches.length !== 1) throw new Error('Actual transaction was not uniquely discoverable');
    if (matches[0].transfer_id) {
      throw new Error('Actual transfer legs must be deleted with delete_transfer');
    }
    await api.deleteTransaction(request.actual_id);
    await api.sync();
    const remaining = (await allTransactions(await api.getAccounts()))
      .some(item => item.id === request.actual_id);
    if (remaining) throw new Error('Actual transaction deletion could not be verified');
    return { id: request.actual_id, deleted: true };
  }
  if (request.action === 'create_transfer') {
    const transfer = request.transfer || {};
    const importedId = String(transfer.imported_id || '').trim();
    if (!importedId) throw new Error('Actual transfer import requires a stable imported id');
    const outImported = `${importedId}:out`;
    const transferPayee = (await api.getPayees()).find(item => item.transfer_acct === transfer.to_account);
    if (!transferPayee) throw new Error('Actual transfer payee was not found');
    const beforeRows = await allTransactions(await api.getAccounts());
    const beforeIds = new Set(beforeRows.map(item => item.id));
    const beforeMatches = beforeRows.filter(item => (
      item.account === transfer.from_account && item.imported_id === outImported
    ));
    if (beforeMatches.length > 1) {
      throw new Error('Actual imported transfer was not uniquely discoverable');
    }
    if (beforeMatches.length === 1) {
      const out = beforeMatches[0];
      const incoming = beforeRows.find(item => item.id === out.transfer_id);
      if (!incoming || incoming.transfer_id !== out.id) {
        throw new Error('Actual transfer linkage is incomplete');
      }
      return { id: importedId, from_id: out.id, to_id: incoming.id };
    }
    let addedIds = [];
    let reconciliationRequired = false;
    try {
      const result = await api.importTransactions(transfer.from_account, [{
        account: transfer.from_account,
        amount: -Math.abs(safeMinor(transfer.amount_minor, 'transfer amount')),
        imported_id: outImported,
        payee: transferPayee.id,
        date: transfer.date,
        notes: transfer.notes || '',
        cleared: Boolean(transfer.cleared),
      }], { defaultCleared: false, reimportDeleted: false });
      addedIds = [...new Set((result.added || []).map(value => String(value || '')).filter(Boolean))];
      if (result.errors?.length) throw new Error(result.errors[0].message);
      const rows = await allTransactions(await api.getAccounts());
      const matches = rows.filter(item => (
        item.account === transfer.from_account && item.imported_id === outImported
      ));
      if (matches.length !== 1) throw new Error('Actual imported transfer was not uniquely discoverable');
      const out = matches[0];
      const incoming = rows.find(item => item.id === out?.transfer_id);
      if (!out || !incoming) throw new Error('Actual transfer legs were not discoverable');
      if (incoming.transfer_id !== out.id) throw new Error('Actual transfer linkage is incomplete');
      await api.sync();
      return { id: importedId, from_id: out.id, to_id: incoming.id };
    } catch (error) {
      try {
        const rows = await allTransactions(await api.getAccounts());
        const rowsById = new Map(rows.map(item => [item.id, item]));
        const matches = rows.filter(item => (
          item.account === transfer.from_account && item.imported_id === outImported
        ));
        if (matches.length === 1) {
          const candidateIds = [...new Set(
            [...addedIds, matches[0].id, matches[0].transfer_id].filter(Boolean),
          )];
          reconciliationRequired = candidateIds.some(id => beforeIds.has(id));
          if (!reconciliationRequired) addedIds = candidateIds;
        } else if (matches.length > 1) {
          throw new Error('ambiguous partial transfer');
        }
        if (!reconciliationRequired) {
          const candidateIds = new Set(addedIds);
          for (const id of [...candidateIds]) {
            const reciprocalId = rowsById.get(id)?.transfer_id;
            if (reciprocalId) candidateIds.add(reciprocalId);
          }
          if ([...candidateIds].some(id => beforeIds.has(id))) reconciliationRequired = true;
          const reciprocalPairs = [...candidateIds].filter(id => {
            const row = rowsById.get(id);
            const reciprocal = rowsById.get(row?.transfer_id);
            return reciprocal && candidateIds.has(reciprocal.id) && reciprocal.transfer_id === id;
          });
          if (!reconciliationRequired && candidateIds.size && reciprocalPairs.length !== 2) {
            throw new Error('partial transfer pair could not be verified');
          }
          addedIds = [...candidateIds];
          if (!reconciliationRequired && reciprocalPairs.length) {
            await api.deleteTransaction(reciprocalPairs[0]);
            await api.sync();
          }
          const remaining = new Set(
            (await allTransactions(await api.getAccounts())).map(item => item.id),
          );
          if (addedIds.some(id => remaining.has(id))) {
            throw new Error('partial transfer remains');
          }
        }
      } catch {
        throw new Error('Actual partial transfer cleanup could not be verified');
      }
      if (reconciliationRequired) {
        throw new Error('Actual transfer reconciliation requires owner review');
      }
      throw error;
    }
  }
  if (request.action === 'delete_transfer') {
    const ids = Array.isArray(request.actual_ids) ? request.actual_ids : [];
    if (ids.length !== 2 || ids[0] === ids[1]) {
      throw new Error('Actual transfer deletion requires one complete pair');
    }
    const before = new Map(
      (await allTransactions(await api.getAccounts())).map(item => [item.id, item]),
    );
    const left = before.get(ids[0]);
    const right = before.get(ids[1]);
    if (!left || !right || left.transfer_id !== right.id || right.transfer_id !== left.id) {
      throw new Error('Actual transfer deletion target is not one reciprocal pair');
    }
    await api.deleteTransaction(ids[0]);
    await api.sync();
    const remaining = new Set((await allTransactions(await api.getAccounts())).map(item => item.id));
    if (ids.some(id => remaining.has(id))) throw new Error('Actual transfer pair was not fully deleted');
    return { deleted: ids.length };
  }
  if (request.action === 'set_budget') {
    const name = String(request.category_name || '').trim();
    if (!name) throw new Error('Actual budget category name is required');
    const [categories, groups] = await Promise.all([api.getCategories(), api.getCategoryGroups()]);
    const { categoryMap, groupId } = await managedCategoryContext(request, categories, groups);
    const categoryId = await ensureCategory(name, categoryMap, groupId);
    const amountMinor = safeMinor(request.amount_minor, 'budget amount');
    await api.setBudgetAmount(request.month, categoryId, amountMinor);
    await api.sync();
    return { month: request.month, category_id: categoryId, category_name: name, amount_minor: amountMinor };
  }
  if (request.action === 'clear_budget') {
    const categoryId = String(request.category_id || '').trim();
    if (!categoryId) throw new Error('Actual budget category id is required');
    const [categories, groups] = await Promise.all([api.getCategories(), api.getCategoryGroups()]);
    const groupName = await managedCategoryGroupName(request);
    const groupMatches = groups.filter(item => item.name === groupName);
    if (groupMatches.length !== 1) {
      throw new Error('Actual managed category group was not uniquely found');
    }
    const categoryMatches = categories.filter(item => (
      item.id === categoryId && item.group_id === groupMatches[0].id
    ));
    if (categoryMatches.length !== 1) {
      throw new Error('Actual budget category is not owned by Alles');
    }
    await api.setBudgetAmount(request.month, categoryId, 0);
    await api.sync();
    return { month: request.month, category_id: categoryId, amount_minor: 0 };
  }
  throw new Error(`unsupported Actual write action: ${request.action}`);
}

async function handle(request) {
  if (request.command === 'versions') return {
    api: packageVersion('@actual-app/api'),
    cli: packageVersion('@actual-app/cli'),
    sync_server: packageVersion('@actual-app/sync-server'),
    node: process.versions.node,
  };
  if (request.command === 'create_budget') return (await createBudget(request)).result;
  if (request.command === 'migrate') return migrate(request);
  if (request.command === 'delete_staged_budget') return deleteStagedBudget(request);
  if (request.command === 'inspect') {
    await loadBudget(request);
    return inspectBudget();
  }
  if (request.command === 'write') return write(request);
  if (request.command === 'readback') {
    await loadBudget(request, { dataDir: request.fresh_data_dir, preferSync: true });
    return inspectBudget();
  }
  throw new Error(`unsupported Actual bridge command: ${request.command}`);
}

let request = null;
try {
  const chunks = [];
  for await (const chunk of process.stdin) chunks.push(chunk);
  request = JSON.parse(Buffer.concat(chunks).toString('utf8'));
  const data = await handle(request);
  process.stdout.write(`${RESULT_PREFIX}${JSON.stringify({ ok: true, data })}\n`);
} catch (error) {
  const failure = {
    code: error instanceof StagedBudgetCleanupError
      ? 'actual_stage_cleanup_required'
      : error instanceof StagedBudgetCleanupVerifiedError
        ? 'actual_stage_cleanup_verified'
        : error instanceof ExistingStagedBudgetError
          ? 'actual_stage_reconciliation_required'
          : 'actual_bridge_failed',
    message: cleanError(error, request),
  };
  if (error instanceof StagedBudgetCleanupError || error instanceof ExistingStagedBudgetError) {
    failure.staged_budget = error.stagedBudget;
  }
  process.stdout.write(`${RESULT_PREFIX}${JSON.stringify({ ok: false, error: failure })}\n`);
  process.exitCode = 1;
} finally {
  try { await api.shutdown(); } catch {}
}
