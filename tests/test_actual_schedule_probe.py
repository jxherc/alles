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
  const rule = (await api.getRules()).find(row => row.id === before.rule);
  if (!rule) throw new Error('schedule rule missing');
  await api.updateRule({
    ...rule,
    conditions: [...rule.conditions, {op: 'is', field: 'notes', value: `alles:never-match:${id}`}],
    actions: [...rule.actions,
      {op: 'set', field: 'category', value: category},
      {op: 'set', field: 'notes', value: 'probe scheduled note'},
    ],
  });
  await api.updateSchedule(id, {posts_transaction: true});
  await api.addTransactions(account, [
    {date: '2026-10-01', amount: -500, payee, notes: 'manual baseline'},
    {date: '2026-10-01', amount: -500, payee, schedule: id},
  ]);
  await api.sync();
  const after = (await api.getSchedules()).find(row => row.id === id);
  const rows = await api.getTransactions(account, '2026-10-01', '2026-10-01');
  const manual = rows.filter(row => row.notes === 'manual baseline');
  const scheduled = rows.filter(row => row.schedule === id && row.notes === 'probe scheduled note');
  console.log('ALLES_PROBE_RESULT=' + JSON.stringify({
    before: {posts_transaction: before.posts_transaction, next_date: before.next_date},
    after: {posts_transaction: after.posts_transaction, next_date: after.next_date},
    manual: manual.map(row => ({category: row.category, schedule: row.schedule, notes: row.notes})),
    scheduled: scheduled.map(row => ({category: row.category, schedule: row.schedule, notes: row.notes})),
    expected_category: category,
  }));
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
                self.assertEqual(len(output["manual"]), 1, output)
                self.assertIsNone(output["manual"][0]["category"])
                self.assertFalse(output["manual"][0]["schedule"])
                self.assertEqual(len(output["scheduled"]), 1, output)
                self.assertEqual(output["scheduled"][0]["category"], output["expected_category"])
        finally:
            if old_data is None:
                os.environ.pop("ALLES_DATA", None)
            else:
                os.environ["ALLES_DATA"] = old_data
            if old_port is None:
                os.environ.pop("ALLES_ACTUAL_PORT", None)
            else:
                os.environ["ALLES_ACTUAL_PORT"] = old_port
