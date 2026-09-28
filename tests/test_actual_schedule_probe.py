"""Opt-in live proof of the pinned Actual schedule-rule contract."""

import contextlib
import json
import os
import socket
import subprocess
import tempfile
import unittest
import uuid

from services import managed_actual
from tests.test_actual_live import _stop_managed_actual_or_fail

_PROBE = r"""
import * as api from '@actual-app/api';
let input = '';
for await (const chunk of process.stdin) input += chunk;
const request = JSON.parse(input);
try {
  await api.init({dataDir: request.data_dir, serverURL: request.server_url, password: request.password});
  await api.loadBudget(request.budget_id);
  const account = await api.createAccount({name: 'probe checking', offbudget: false, closed: false});
  const payee = await api.createPayee({name: 'probe landlord'});
  const group = await api.createCategoryGroup({name: 'probe group', is_income: false, hidden: false});
  const category = await api.createCategory({name: 'probe housing', group_id: group, is_income: false, hidden: false});
  const id = await api.createSchedule({
    name: 'probe rent', posts_transaction: false,
    payee, account, amount: -500, amountOp: 'is',
    date: {start: '2026-10-01', frequency: 'monthly', interval: 1, endMode: 'never'},
  });
  const before = (await api.getSchedules()).find(row => row.id === id);
  const oldId = await api.createSchedule({
    name: 'probe old rent', posts_transaction: true,
    payee, account, amount: -500, amountOp: 'is',
    date: {start: '2026-10-01', frequency: 'monthly', interval: 1, endMode: 'never'},
  });
  let duplicateNameRejected = false;
  let duplicateNameError = '';
  try {
    await api.createSchedule({
      name: 'probe old rent', posts_transaction: false,
      payee, account, amount: -500, amountOp: 'is',
      date: {start: '2026-10-01', frequency: 'monthly', interval: 1, endMode: 'never'},
    });
  } catch (error) {
    duplicateNameRejected = true;
    duplicateNameError = String(error?.message || error);
  }
  const oldBefore = (await api.getSchedules()).find(row => row.id === oldId);
  const oldRule = (await api.getRules()).find(row => row.id === oldBefore.rule);
  await api.updateSchedule(oldId, {posts_transaction: false});
  const oldPaused = (await api.getSchedules()).find(row => row.id === oldId);
  async function configure(scheduleId) {
    const schedule = (await api.getSchedules()).find(row => row.id === scheduleId);
    const rule = (await api.getRules()).find(row => row.id === schedule.rule);
    if (!rule) throw new Error('schedule rule missing');
    await api.updateRule({
      ...rule,
      conditions: [...rule.conditions, {op: 'is', field: 'notes', value: `alles:never-match:${scheduleId}`}],
      actions: [...rule.actions,
        {op: 'set', field: 'category', value: category},
        {op: 'set', field: 'notes', value: 'probe scheduled note'},
      ],
    });
  }
  await configure(id);
  await configure(oldId);
  await api.updateSchedule(id, {posts_transaction: true});
  await api.updateSchedule(oldId, {posts_transaction: true});
  await api.addTransactions(account, [
    {date: '2026-10-01', amount: -500, payee, notes: 'manual baseline'},
    {date: '2026-10-01', amount: -500, payee, schedule: id},
    {date: '2026-10-01', amount: -500, payee, schedule: oldId},
  ]);
  await api.sync();
  const after = (await api.getSchedules()).find(row => row.id === id);
  const oldAfter = (await api.getSchedules()).find(row => row.id === oldId);
  const rows = await api.getTransactions(account, '2026-10-01', '2026-10-01');
  const manual = rows.filter(row => row.notes === 'manual baseline');
  const scheduled = rows.filter(row => row.schedule === id && row.notes === 'probe scheduled note');
  const oldScheduled = rows.filter(row => row.schedule === oldId && row.notes === 'probe scheduled note');
  console.log('ALLES_PROBE_RESULT=' + JSON.stringify({
    before: {posts_transaction: before.posts_transaction, next_date: before.next_date},
    after: {posts_transaction: after.posts_transaction, next_date: after.next_date},
    old_before: {id: oldBefore.id, posts_transaction: oldBefore.posts_transaction, next_date: oldBefore.next_date},
    old_rule_conditions: oldRule.conditions.map(({field, op, type}) => ({field, op, type})),
    old_rule_matches_schedule: oldRule.conditions[0].value === oldBefore.payee
      && oldRule.conditions[1].value === oldBefore.account
      && JSON.stringify(oldRule.conditions[2].value) === JSON.stringify(oldBefore.date)
      && oldRule.conditions[3].value === oldBefore.amount,
    old_paused: {id: oldPaused.id, posts_transaction: oldPaused.posts_transaction, next_date: oldPaused.next_date},
    old_after: {id: oldAfter.id, posts_transaction: oldAfter.posts_transaction, next_date: oldAfter.next_date},
    manual: manual.map(row => ({category: row.category, schedule: row.schedule, notes: row.notes})),
    scheduled: scheduled.map(row => ({category: row.category, schedule: row.schedule, notes: row.notes})),
    old_scheduled: oldScheduled.map(row => ({category: row.category, schedule: row.schedule, notes: row.notes})),
    expected_category: category,
    duplicate_name_rejected: duplicateNameRejected,
    duplicate_name_error: duplicateNameError,
    same_name_count: (await api.getSchedules()).filter(row => row.name === 'probe old rent').length,
  }));
} catch (error) {
  console.log('ALLES_PROBE_RESULT=' + JSON.stringify({error: String(error?.message || error)}));
  process.exitCode = 1;
} finally {
  await api.shutdown();
}
"""

_SETUP_OLD = r"""
import * as api from '@actual-app/api';
let input = '';
for await (const chunk of process.stdin) input += chunk;
const request = JSON.parse(input);
try {
  await api.init({dataDir: request.data_dir, serverURL: request.server_url, password: request.password});
  await api.loadBudget(request.budget_id);
  const account = await api.createAccount({name: 'repair checking', offbudget: false, closed: false});
  const payee = await api.createPayee({name: 'repair landlord'});
  const group = await api.createCategoryGroup({name: 'repair group', is_income: false, hidden: false});
  const category = await api.createCategory({name: 'repair housing', group_id: group, is_income: false, hidden: false});
  const id = await api.createSchedule({
    name: 'old rent', posts_transaction: true, payee, account, amount: -500, amountOp: 'is',
    date: {start: '2026-10-01', frequency: 'monthly', interval: 1, endMode: 'never'},
  });
  await api.sync();
  const schedule = (await api.getSchedules()).find(row => row.id === id);
  console.log('ALLES_PROBE_RESULT=' + JSON.stringify({
    id, category, next_date: schedule.next_date,
    expected_schedule: {
      name: schedule.name, account: schedule.account, payee: schedule.payee,
      amount: schedule.amount, amountOp: schedule.amountOp, date: schedule.date,
    },
  }));
} catch (error) {
  console.log('ALLES_PROBE_RESULT=' + JSON.stringify({error: String(error?.message || error)}));
  process.exitCode = 1;
} finally {
  await api.shutdown();
}
"""

_EDIT_REPAIRED_RULE = r"""
import * as api from '@actual-app/api';
let input = '';
for await (const chunk of process.stdin) input += chunk;
const request = JSON.parse(input);
try {
  await api.init({dataDir: request.data_dir, serverURL: request.server_url, password: request.password});
  await api.loadBudget(request.budget_id);
  const schedule = (await api.getSchedules()).find(row => row.id === request.schedule_id);
  const rule = (await api.getRules()).find(row => row.id === schedule.rule);
  await api.updateRule({
    ...rule,
    conditions: [...rule.conditions, {op: 'is', field: 'notes', value: 'owner changed this rule'}],
  });
  await api.sync();
  console.log('ALLES_PROBE_RESULT=' + JSON.stringify({ok: true}));
} catch (error) {
  console.log('ALLES_PROBE_RESULT=' + JSON.stringify({error: String(error?.message || error)}));
  process.exitCode = 1;
} finally {
  await api.shutdown();
}
"""


@unittest.skipUnless(os.environ.get("ALLES_RUN_ACTUAL_LIVE") == "1", "opt-in live probe")
class ActualScheduleProbeTests(unittest.TestCase):
    def test_schedule_rule_only_changes_attached_transaction(self):
        old_data = os.environ.get("ALLES_DATA")
        old_port = os.environ.get("ALLES_ACTUAL_PORT")
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
        try:
            with contextlib.ExitStack() as stack:
                root = stack.enter_context(
                    tempfile.TemporaryDirectory(prefix="alles-schedule-probe-")
                )
                stack.callback(_stop_managed_actual_or_fail)
                os.environ["ALLES_DATA"] = root
                os.environ["ALLES_ACTUAL_PORT"] = str(port)
                self.assertTrue(managed_actual.install()["healthy"])
                marker = f"Alles staged {uuid.uuid4()}"
                created = managed_actual.bridge_request(
                    {"command": "create_budget", "budget_name": marker, "operation_marker": marker},
                    timeout=180,
                )
                payload = {
                    "data_dir": str(managed_actual.client_data_dir()),
                    "server_url": managed_actual.managed_url(),
                    "password": managed_actual._managed_password(),
                    "budget_id": created["budget_id"],
                }
                result = subprocess.run(
                    ["node", "--input-type=module", "-e", _PROBE],
                    input=json.dumps(payload),
                    text=True,
                    capture_output=True,
                    cwd=managed_actual.app_dir(),
                    timeout=180,
                    check=False,
                )
                lines = [
                    line.removeprefix("ALLES_PROBE_RESULT=")
                    for line in result.stdout.splitlines()
                    if line.startswith("ALLES_PROBE_RESULT=")
                ]
                self.assertEqual(
                    len(lines), 1, f"probe returned {result.returncode} without one result"
                )
                output = json.loads(lines[0])
                self.assertEqual(result.returncode, 0, output)
                self.assertFalse(output["before"]["posts_transaction"])
                self.assertTrue(output["after"]["posts_transaction"])
                self.assertEqual(output["before"]["next_date"], output["after"]["next_date"])
                self.assertTrue(output["duplicate_name_rejected"])
                self.assertRegex(
                    output["duplicate_name_error"].lower(), "name|unique|exist|duplicate"
                )
                self.assertEqual(output["same_name_count"], 1)
                self.assertTrue(output["old_before"]["posts_transaction"])
                self.assertEqual(
                    output["old_rule_conditions"],
                    [
                        {"field": "payee", "op": "is", "type": "id"},
                        {"field": "account", "op": "is", "type": "id"},
                        {"field": "date", "op": "isapprox", "type": "date"},
                        {"field": "amount", "op": "is", "type": "number"},
                    ],
                )
                self.assertTrue(output["old_rule_matches_schedule"])
                self.assertFalse(output["old_paused"]["posts_transaction"])
                self.assertTrue(output["old_after"]["posts_transaction"])
                self.assertEqual(output["old_before"]["id"], output["old_paused"]["id"])
                self.assertEqual(output["old_before"]["id"], output["old_after"]["id"])
                self.assertEqual(
                    output["old_before"]["next_date"], output["old_paused"]["next_date"]
                )
                self.assertEqual(
                    output["old_before"]["next_date"], output["old_after"]["next_date"]
                )
                self.assertEqual(len(output["manual"]), 1, output)
                self.assertIsNone(output["manual"][0]["category"])
                self.assertFalse(output["manual"][0]["schedule"])
                self.assertEqual(len(output["scheduled"]), 1, output)
                self.assertEqual(output["scheduled"][0]["category"], output["expected_category"])
                self.assertEqual(len(output["old_scheduled"]), 1, output)
                self.assertEqual(
                    output["old_scheduled"][0]["category"], output["expected_category"]
                )
        finally:
            if old_data is None:
                os.environ.pop("ALLES_DATA", None)
            else:
                os.environ["ALLES_DATA"] = old_data
            if old_port is None:
                os.environ.pop("ALLES_ACTUAL_PORT", None)
            else:
                os.environ["ALLES_ACTUAL_PORT"] = old_port

    def test_bridge_repairs_an_existing_schedule_without_replacing_it(self):
        old_data = os.environ.get("ALLES_DATA")
        old_port = os.environ.get("ALLES_ACTUAL_PORT")
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
        try:
            with contextlib.ExitStack() as stack:
                root = stack.enter_context(
                    tempfile.TemporaryDirectory(prefix="alles-schedule-repair-probe-")
                )
                stack.callback(_stop_managed_actual_or_fail)
                os.environ["ALLES_DATA"] = root
                os.environ["ALLES_ACTUAL_PORT"] = str(port)
                self.assertTrue(managed_actual.install()["healthy"])
                marker = f"Alles staged {uuid.uuid4()}"
                created = managed_actual.bridge_request(
                    {"command": "create_budget", "budget_name": marker, "operation_marker": marker},
                    timeout=180,
                )
                result = subprocess.run(
                    ["node", "--input-type=module", "-e", _SETUP_OLD],
                    input=json.dumps(
                        {
                            "data_dir": str(managed_actual.client_data_dir()),
                            "server_url": managed_actual.managed_url(),
                            "password": managed_actual._managed_password(),
                            "budget_id": created["budget_id"],
                        }
                    ),
                    text=True,
                    capture_output=True,
                    cwd=managed_actual.app_dir(),
                    timeout=180,
                    check=False,
                )
                lines = [
                    line.removeprefix("ALLES_PROBE_RESULT=")
                    for line in result.stdout.splitlines()
                    if line.startswith("ALLES_PROBE_RESULT=")
                ]
                self.assertEqual(
                    len(lines), 1, f"setup returned {result.returncode} without one result"
                )
                setup = json.loads(lines[0])
                self.assertEqual(result.returncode, 0, setup)
                before = managed_actual.bridge_request(
                    {"command": "inspect", "budget_id": created["budget_id"]}, timeout=180
                )
                schedule = next(row for row in before["schedules"] if row["id"] == setup["id"])
                self.assertTrue(schedule["posting"]["pristine"])
                request = {
                    "command": "write",
                    "action": "repair_recurring_schedule",
                    "budget_id": created["budget_id"],
                    "actual_id": setup["id"],
                    "category_id": setup["category"],
                    "notes": "repaired note",
                    "expected_schedule": setup["expected_schedule"],
                    "original_posts_transaction": True,
                }
                repaired = managed_actual.bridge_request(request, timeout=180)
                self.assertEqual(repaired["id"], setup["id"])
                self.assertTrue(repaired["posts_transaction"])
                self.assertTrue(repaired["posting"]["guarded"])
                again = managed_actual.bridge_request(
                    {**request, "allow_paused_retry": True}, timeout=180
                )
                self.assertEqual(again["id"], setup["id"])
                after = managed_actual.bridge_request(
                    {"command": "inspect", "budget_id": created["budget_id"]}, timeout=180
                )
                self.assertEqual(len(after["schedules"]), len(before["schedules"]))
                selected = next(row for row in after["schedules"] if row["id"] == setup["id"])
                self.assertEqual(selected["next_date"], setup["next_date"])
                self.assertEqual(selected["posting"]["category"], setup["category"])
                self.assertEqual(selected["posting"]["notes"], "repaired note")
                toggle = {
                    "command": "write",
                    "action": "set_recurring_posting",
                    "budget_id": created["budget_id"],
                    "actual_id": setup["id"],
                    "category_id": setup["category"],
                    "notes": "repaired note",
                    "expected_schedule": {**setup["expected_schedule"], "rule": selected["rule"]},
                    "previous_posts_transaction": True,
                    "active": False,
                }
                paused = managed_actual.bridge_request(toggle, timeout=180)
                self.assertFalse(paused["posts_transaction"])
                with self.assertRaisesRegex(managed_actual.ManagedActualError, "state changed"):
                    managed_actual.bridge_request(toggle, timeout=180)
                paused_retry = managed_actual.bridge_request(
                    {**toggle, "allow_retry": True}, timeout=180
                )
                self.assertFalse(paused_retry["posts_transaction"])
                resumed = managed_actual.bridge_request(
                    {**toggle, "previous_posts_transaction": False, "active": True},
                    timeout=180,
                )
                self.assertTrue(resumed["posts_transaction"])
                toggled = managed_actual.bridge_request(
                    {"command": "inspect", "budget_id": created["budget_id"]}, timeout=180
                )
                self.assertEqual(len(toggled["schedules"]), len(before["schedules"]))
                selected = next(row for row in toggled["schedules"] if row["id"] == setup["id"])
                self.assertEqual(selected["next_date"], setup["next_date"])
                self.assertTrue(selected["posting"]["guarded"])
                changed = subprocess.run(
                    ["node", "--input-type=module", "-e", _EDIT_REPAIRED_RULE],
                    input=json.dumps(
                        {
                            "data_dir": str(managed_actual.client_data_dir()),
                            "server_url": managed_actual.managed_url(),
                            "password": managed_actual._managed_password(),
                            "budget_id": created["budget_id"],
                            "schedule_id": setup["id"],
                        }
                    ),
                    text=True,
                    capture_output=True,
                    cwd=managed_actual.app_dir(),
                    timeout=180,
                    check=False,
                )
                self.assertEqual(changed.returncode, 0, changed.stdout)
                modified = managed_actual.bridge_request(
                    {"command": "inspect", "budget_id": created["budget_id"]}, timeout=180
                )
                selected = next(row for row in modified["schedules"] if row["id"] == setup["id"])
                self.assertFalse(selected["posting"]["guarded"])
                with self.assertRaisesRegex(
                    managed_actual.ManagedActualError, "linked rule changed"
                ):
                    managed_actual.bridge_request(
                        {**request, "allow_paused_retry": True}, timeout=180
                    )
                with self.assertRaisesRegex(
                    managed_actual.ManagedActualError, "posting rule changed"
                ):
                    managed_actual.bridge_request(toggle, timeout=180)
        finally:
            if old_data is None:
                os.environ.pop("ALLES_DATA", None)
            else:
                os.environ["ALLES_DATA"] = old_data
            if old_port is None:
                os.environ.pop("ALLES_ACTUAL_PORT", None)
            else:
                os.environ["ALLES_ACTUAL_PORT"] = old_port
