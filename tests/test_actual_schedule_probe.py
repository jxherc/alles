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

_SEED_DELETE_TRANSACTION = r"""
import * as api from '@actual-app/api';
let input = '';
for await (const chunk of process.stdin) input += chunk;
const request = JSON.parse(input);
try {
  await api.init({dataDir: request.data_dir, serverURL: request.server_url, password: request.password});
  await api.loadBudget(request.budget_id);
  await api.addTransactions(request.account_id, [{
    date: '2026-10-01', amount: -700, payee: request.payee_id,
    schedule: request.schedule_id, notes: 'kept after deletion',
  }]);
  await api.sync();
  const transactions = await api.getTransactions(request.account_id, '2026-10-01', '2026-10-01');
  const matches = transactions.filter(row => row.notes === 'kept after deletion' && row.amount === -700);
  if (matches.length !== 1) throw new Error('deletion probe transaction was not uniquely found');
  console.log('ALLES_PROBE_RESULT=' + JSON.stringify({transaction_id: matches[0].id}));
} catch (error) {
  console.log('ALLES_PROBE_RESULT=' + JSON.stringify({error: String(error?.message || error)}));
  process.exitCode = 1;
} finally {
  await api.shutdown();
}
"""

_VERIFY_DELETED_SCHEDULE = r"""
import * as api from '@actual-app/api';
let input = '';
for await (const chunk of process.stdin) input += chunk;
const request = JSON.parse(input);
try {
  await api.init({dataDir: request.data_dir, serverURL: request.server_url, password: request.password});
  await api.loadBudget(request.budget_id);
  const transactions = await api.getTransactions(request.account_id, '1900-01-01', '9999-12-31');
  const transaction = transactions.find(row => row.id === request.transaction_id);
  console.log('ALLES_PROBE_RESULT=' + JSON.stringify({
    schedule_present: (await api.getSchedules()).some(row => row.id === request.schedule_id),
    rule_present: (await api.getRules()).some(row => row.id === request.rule_id),
    transaction: transaction ? {id: transaction.id, amount: transaction.amount, notes: transaction.notes} : null,
    observed_transaction_ids: transactions.map(row => row.id),
  }));
} catch (error) {
  console.log('ALLES_PROBE_RESULT=' + JSON.stringify({error: String(error?.message || error)}));
  process.exitCode = 1;
} finally {
  await api.shutdown();
}
"""

_EDIT_SCHEDULE_PROBE = r"""
import * as api from '@actual-app/api';
let input = '';
for await (const chunk of process.stdin) input += chunk;
const request = JSON.parse(input);
try {
  await api.init({dataDir: request.data_dir, serverURL: request.server_url, password: request.password});
  await api.loadBudget(request.budget_id);
  const id = request.schedule_id;
  const inspect = async () => {
    const schedule = (await api.getSchedules()).find(row => row.id === id);
    const rule = (await api.getRules()).find(row => row.id === schedule?.rule);
    return {
      schedule: {
        id: schedule?.id, rule: schedule?.rule, name: schedule?.name,
        account: schedule?.account, payee: schedule?.payee, amount: schedule?.amount,
        date: schedule?.date, next_date: schedule?.next_date,
        posts_transaction: schedule?.posts_transaction,
      },
      conditions: rule?.conditions,
      actions: rule?.actions,
    };
  };
  const before = await inspect();
  await api.updateSchedule(id, {posts_transaction: false});
  await api.updateSchedule(id, {amount: -650});
  await api.sync();
  const amount = await inspect();
  await api.updateSchedule(id, {
    date: {start: '2026-12-03', frequency: 'weekly', interval: 1, endMode: 'never'},
  });
  await api.sync();
  const date = await inspect();
  const account = await api.createAccount({name: 'edit checking', offbudget: false, closed: false});
  const payee = await api.createPayee({name: 'edit landlord'});
  await api.updateSchedule(id, {account, payee});
  await api.sync();
  const party = await inspect();
  console.log('ALLES_PROBE_RESULT=' + JSON.stringify({before, amount, date, party}));
} catch (error) {
  console.log('ALLES_PROBE_RESULT=' + JSON.stringify({error: String(error?.message || error)}));
  process.exitCode = 1;
} finally {
  await api.shutdown();
}
"""

_TAMPER_EDITED_SCHEDULE = r"""
import * as api from '@actual-app/api';
let input = '';
for await (const chunk of process.stdin) input += chunk;
const request = JSON.parse(input);
try {
  await api.init({dataDir: request.data_dir, serverURL: request.server_url, password: request.password});
  await api.loadBudget(request.budget_id);
  await api.updateSchedule(request.schedule_id, {amount: -751});
  await api.sync();
  console.log('ALLES_PROBE_RESULT=' + JSON.stringify({ok: true}));
} catch (error) {
  console.log('ALLES_PROBE_RESULT=' + JSON.stringify({error: String(error?.message || error)}));
  process.exitCode = 1;
} finally {
  await api.shutdown();
}
"""

_STAGE_PARTIAL_EDIT = r"""
import * as api from '@actual-app/api';
let input = '';
for await (const chunk of process.stdin) input += chunk;
const request = JSON.parse(input);
try {
  await api.init({dataDir: request.data_dir, serverURL: request.server_url, password: request.password});
  await api.loadBudget(request.budget_id);
  await api.updateSchedule(request.schedule_id, {posts_transaction: false});
  await api.updateSchedule(request.schedule_id, {amount: -800});
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
    def test_bridge_create_uses_one_marker_and_replays_without_a_second_schedule(self):
        old_data = os.environ.get("ALLES_DATA")
        old_port = os.environ.get("ALLES_ACTUAL_PORT")
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
        try:
            with contextlib.ExitStack() as stack:
                root = stack.enter_context(
                    tempfile.TemporaryDirectory(prefix="alles-created-schedule-")
                )
                stack.callback(_stop_managed_actual_or_fail)
                os.environ["ALLES_DATA"] = root
                os.environ["ALLES_ACTUAL_PORT"] = str(port)
                self.assertTrue(managed_actual.install()["healthy"])
                budget_marker = f"Alles staged {uuid.uuid4()}"
                created = managed_actual.bridge_request(
                    {
                        "command": "create_budget",
                        "budget_name": budget_marker,
                        "operation_marker": budget_marker,
                    },
                    timeout=180,
                )
                seed = subprocess.run(
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
                outputs = [
                    line.removeprefix("ALLES_PROBE_RESULT=")
                    for line in seed.stdout.splitlines()
                    if line.startswith("ALLES_PROBE_RESULT=")
                ]
                self.assertEqual(seed.returncode, 0, seed.stdout)
                self.assertEqual(len(outputs), 1)
                setup = json.loads(outputs[0])
                request_id = str(uuid.uuid4())
                source = {
                    "kind": "recurring",
                    "id": request_id,
                    "name": f"Alles recurring {request_id}",
                    "account_id": setup["expected_schedule"]["account"],
                    "payee": "repair landlord",
                    "amount_minor": -500,
                    "next_date": "2026-11-01",
                    "cycle": "monthly",
                    "cycle_days": 30,
                    "anchor_day": 1,
                    "active": True,
                    "posts_transaction": True,
                }
                request = {
                    "command": "write",
                    "action": "create_recurring_schedule",
                    "budget_id": created["budget_id"],
                    "operation_marker": source["name"],
                    "schedule": source,
                    "category_id": setup["category"],
                    "notes": "new lease",
                    "active": True,
                    "allow_create": True,
                }
                first = managed_actual.bridge_request(request, timeout=180)
                self.assertTrue(first["posts_transaction"])
                self.assertEqual(first["payee_id"], setup["expected_schedule"]["payee"])
                retry = managed_actual.bridge_request(
                    {**request, "allow_create": False}, timeout=180
                )
                self.assertEqual(retry["id"], first["id"])
                after = managed_actual.bridge_request(
                    {"command": "inspect", "budget_id": created["budget_id"]}, timeout=180
                )
                matches = [row for row in after["schedules"] if row["name"] == source["name"]]
                self.assertEqual(len(matches), 1)
                self.assertEqual(matches[0]["id"], first["id"])
                self.assertEqual(
                    matches[0]["posting"],
                    {
                        "pristine": False,
                        "guarded": True,
                        "category": setup["category"],
                        "notes": "new lease",
                    },
                )
                uncategorized_id = str(uuid.uuid4())
                uncategorized_source = {
                    **source,
                    "id": uncategorized_id,
                    "name": f"Alles recurring {uncategorized_id}",
                    "amount_minor": -700,
                }
                uncategorized = managed_actual.bridge_request(
                    {
                        **request,
                        "operation_marker": uncategorized_source["name"],
                        "schedule": uncategorized_source,
                        "category_id": "",
                        "notes": "",
                    },
                    timeout=180,
                )
                self.assertTrue(uncategorized["posts_transaction"])
                after_uncategorized = managed_actual.bridge_request(
                    {"command": "inspect", "budget_id": created["budget_id"]}, timeout=180
                )
                uncategorized_rows = [
                    row
                    for row in after_uncategorized["schedules"]
                    if row["name"] == uncategorized_source["name"]
                ]
                self.assertEqual(len(uncategorized_rows), 1)
                self.assertEqual(
                    uncategorized_rows[0]["posting"],
                    {"pristine": False, "guarded": True, "category": None, "notes": ""},
                )

                def deletion_probe(script, **values):
                    process = subprocess.run(
                        ["node", "--input-type=module", "-e", script],
                        input=json.dumps(
                            {
                                "data_dir": str(managed_actual.client_data_dir()),
                                "server_url": managed_actual.managed_url(),
                                "password": managed_actual._managed_password(),
                                "budget_id": created["budget_id"],
                                **values,
                            }
                        ),
                        text=True,
                        capture_output=True,
                        cwd=managed_actual.app_dir(),
                        timeout=180,
                        check=False,
                    )
                    outputs = [
                        line.removeprefix("ALLES_PROBE_RESULT=")
                        for line in process.stdout.splitlines()
                        if line.startswith("ALLES_PROBE_RESULT=")
                    ]
                    self.assertEqual(len(outputs), 1, process.stdout)
                    result = json.loads(outputs[0])
                    self.assertEqual(process.returncode, 0, result)
                    return result

                delete_row = uncategorized_rows[0]
                seeded = deletion_probe(
                    _SEED_DELETE_TRANSACTION,
                    account_id=delete_row["account"],
                    payee_id=delete_row["payee"],
                    schedule_id=delete_row["id"],
                )
                verification = {
                    "account_id": delete_row["account"],
                    "schedule_id": delete_row["id"],
                    "rule_id": delete_row["rule"],
                    "transaction_id": seeded["transaction_id"],
                }
                before_delete = deletion_probe(_VERIFY_DELETED_SCHEDULE, **verification)
                self.assertTrue(before_delete["schedule_present"])
                self.assertTrue(before_delete["rule_present"])
                self.assertIsNotNone(
                    before_delete["transaction"], {"seeded": seeded, **before_delete}
                )
                delete_request = {
                    "command": "write",
                    "action": "delete_recurring_schedule",
                    "budget_id": created["budget_id"],
                    "actual_id": delete_row["id"],
                    "before": {
                        key: delete_row[key]
                        for key in (
                            "name",
                            "rule",
                            "account",
                            "payee",
                            "amount",
                            "amountOp",
                            "date",
                        )
                    }
                    | {"category_id": "", "notes": "", "posts_transaction": True},
                }
                with self.assertRaises(managed_actual.ManagedActualError):
                    managed_actual.bridge_request(
                        {
                            **delete_request,
                            "before": {**delete_request["before"], "amount": -701},
                        },
                        timeout=180,
                    )
                self.assertEqual(
                    managed_actual.bridge_request(delete_request, timeout=180),
                    {"id": delete_row["id"], "deleted": True},
                )
                self.assertEqual(
                    managed_actual.bridge_request(delete_request, timeout=180),
                    {"id": delete_row["id"], "deleted": True},
                )
                verified = deletion_probe(_VERIFY_DELETED_SCHEDULE, **verification)
                self.assertFalse(verified["schedule_present"])
                self.assertFalse(verified["rule_present"])
                self.assertEqual(
                    verified["transaction"],
                    {
                        "id": seeded["transaction_id"],
                        "amount": -700,
                        "notes": "kept after deletion",
                    },
                )
                with self.assertRaisesRegex(managed_actual.ManagedActualError, "schedule changed"):
                    managed_actual.bridge_request(
                        {
                            **request,
                            "allow_create": False,
                            "schedule": {**source, "amount_minor": -600},
                        },
                        timeout=180,
                    )
                missing_id = str(uuid.uuid4())
                with self.assertRaisesRegex(managed_actual.ManagedActualError, "marker is missing"):
                    managed_actual.bridge_request(
                        {
                            **request,
                            "allow_create": False,
                            "operation_marker": f"Alles recurring {missing_id}",
                            "schedule": {
                                **source,
                                "id": missing_id,
                                "name": f"Alles recurring {missing_id}",
                            },
                        },
                        timeout=180,
                    )
                edit = subprocess.run(
                    ["node", "--input-type=module", "-e", _EDIT_SCHEDULE_PROBE],
                    input=json.dumps(
                        {
                            "data_dir": str(managed_actual.client_data_dir()),
                            "server_url": managed_actual.managed_url(),
                            "password": managed_actual._managed_password(),
                            "budget_id": created["budget_id"],
                            "schedule_id": first["id"],
                        }
                    ),
                    text=True,
                    capture_output=True,
                    cwd=managed_actual.app_dir(),
                    timeout=180,
                    check=False,
                )
                edit_outputs = [
                    line.removeprefix("ALLES_PROBE_RESULT=")
                    for line in edit.stdout.splitlines()
                    if line.startswith("ALLES_PROBE_RESULT=")
                ]
                self.assertEqual(len(edit_outputs), 1, edit.stdout)
                edit_result = json.loads(edit_outputs[0])
                self.assertEqual(edit.returncode, 0, edit_result)
                before_edit = edit_result["before"]
                for stage in ("amount", "date", "party"):
                    changed = edit_result[stage]
                    self.assertEqual(changed["schedule"]["id"], before_edit["schedule"]["id"])
                    self.assertEqual(changed["schedule"]["rule"], before_edit["schedule"]["rule"])
                    self.assertFalse(changed["schedule"]["posts_transaction"])
                    self.assertEqual(changed["actions"], before_edit["actions"])
                    self.assertEqual(changed["conditions"][4], before_edit["conditions"][4])
                    for index, field in enumerate(("payee", "account", "date", "amount")):
                        self.assertEqual(
                            changed["conditions"][index]["value"],
                            changed["schedule"][field],
                        )
                self.assertEqual(edit_result["amount"]["schedule"]["next_date"], "2026-11-01")
                self.assertEqual(edit_result["date"]["schedule"]["next_date"], "2026-12-03")
                self.assertNotEqual(
                    edit_result["party"]["schedule"]["account"],
                    before_edit["schedule"]["account"],
                )
                self.assertNotEqual(
                    edit_result["party"]["schedule"]["payee"],
                    before_edit["schedule"]["payee"],
                )
                before_bridge_edit = {
                    **edit_result["party"]["schedule"],
                    "amountOp": "is",
                    "category_id": setup["category"],
                    "notes": "new lease",
                }
                target_bridge_edit = {
                    **before_bridge_edit,
                    "account": source["account_id"],
                    "payee": first["payee_id"],
                    "amount": -750,
                    "date": {
                        "start": "2027-01-03",
                        "frequency": "weekly",
                        "interval": 1,
                        "endMode": "never",
                    },
                    "category_id": "",
                    "notes": "",
                    "posts_transaction": True,
                }
                edit_request = {
                    "command": "write",
                    "action": "edit_recurring_schedule",
                    "budget_id": created["budget_id"],
                    "actual_id": first["id"],
                    "before": before_bridge_edit,
                    "target": target_bridge_edit,
                }
                updated = managed_actual.bridge_request(edit_request, timeout=180)
                self.assertEqual(updated["id"], first["id"])
                self.assertEqual(updated["payee_id"], first["payee_id"])
                self.assertTrue(updated["posts_transaction"])
                self.assertEqual(managed_actual.bridge_request(edit_request, timeout=180), updated)
                confirmed = managed_actual.bridge_request(
                    {"command": "inspect", "budget_id": created["budget_id"]}, timeout=180
                )
                edited = [row for row in confirmed["schedules"] if row["id"] == first["id"]]
                self.assertEqual(len(edited), 1)
                self.assertEqual(edited[0]["rule"], before_edit["schedule"]["rule"])
                self.assertEqual(edited[0]["amount"], -750)
                self.assertEqual(edited[0]["account"], source["account_id"])
                self.assertEqual(edited[0]["payee"], first["payee_id"])
                self.assertEqual(edited[0]["next_date"], "2027-01-03")
                self.assertEqual(
                    edited[0]["posting"],
                    {"pristine": False, "guarded": True, "category": None, "notes": ""},
                )
                second_before = {
                    **target_bridge_edit,
                    "date": edited[0]["date"],
                }
                second_target = {
                    **second_before,
                    "amount": -800,
                    "category_id": setup["category"],
                    "notes": "revised lease",
                }
                second_request = {
                    **edit_request,
                    "before": second_before,
                    "target": second_target,
                }
                stage = subprocess.run(
                    ["node", "--input-type=module", "-e", _STAGE_PARTIAL_EDIT],
                    input=json.dumps(
                        {
                            "data_dir": str(managed_actual.client_data_dir()),
                            "server_url": managed_actual.managed_url(),
                            "password": managed_actual._managed_password(),
                            "budget_id": created["budget_id"],
                            "schedule_id": first["id"],
                        }
                    ),
                    text=True,
                    capture_output=True,
                    cwd=managed_actual.app_dir(),
                    timeout=180,
                    check=False,
                )
                self.assertEqual(stage.returncode, 0, stage.stdout)
                recovered = managed_actual.bridge_request(second_request, timeout=180)
                self.assertEqual(recovered["id"], first["id"])
                self.assertTrue(recovered["posts_transaction"])
                confirmed_recovery = managed_actual.bridge_request(
                    {"command": "inspect", "budget_id": created["budget_id"]}, timeout=180
                )
                recovered_row = next(
                    row for row in confirmed_recovery["schedules"] if row["id"] == first["id"]
                )
                self.assertEqual(recovered_row["rule"], before_edit["schedule"]["rule"])
                self.assertEqual(recovered_row["amount"], -800)
                self.assertEqual(recovered_row["posting"]["category"], setup["category"])
                self.assertEqual(recovered_row["posting"]["notes"], "revised lease")
                third_before = {
                    **second_target,
                    "date": recovered_row["date"],
                }
                third_target = {
                    **third_before,
                    "amount": -850,
                    "posts_transaction": False,
                }
                third_request = {
                    **edit_request,
                    "before": third_before,
                    "target": third_target,
                }
                paused_edit = managed_actual.bridge_request(third_request, timeout=180)
                self.assertEqual(paused_edit["id"], first["id"])
                self.assertFalse(paused_edit["posts_transaction"])
                self.assertEqual(
                    managed_actual.bridge_request(third_request, timeout=180), paused_edit
                )
                tamper = subprocess.run(
                    ["node", "--input-type=module", "-e", _TAMPER_EDITED_SCHEDULE],
                    input=json.dumps(
                        {
                            "data_dir": str(managed_actual.client_data_dir()),
                            "server_url": managed_actual.managed_url(),
                            "password": managed_actual._managed_password(),
                            "budget_id": created["budget_id"],
                            "schedule_id": first["id"],
                        }
                    ),
                    text=True,
                    capture_output=True,
                    cwd=managed_actual.app_dir(),
                    timeout=180,
                    check=False,
                )
                self.assertEqual(tamper.returncode, 0, tamper.stdout)
                with self.assertRaisesRegex(
                    managed_actual.ManagedActualError, "outside its before and target states"
                ):
                    managed_actual.bridge_request(third_request, timeout=180)
        finally:
            if old_data is None:
                os.environ.pop("ALLES_DATA", None)
            else:
                os.environ["ALLES_DATA"] = old_data
            if old_port is None:
                os.environ.pop("ALLES_ACTUAL_PORT", None)
            else:
                os.environ["ALLES_ACTUAL_PORT"] = old_port

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
