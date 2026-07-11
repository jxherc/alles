import tempfile
import unittest
from pathlib import Path

from services.instance_lock import InstanceLock, InstanceLockError, instance_lock_path


class InstanceLockTest(unittest.TestCase):
    def test_only_one_process_handle_can_own_a_data_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            live = Path(tmp) / "data"
            live.mkdir()
            first = InstanceLock(live)
            second = InstanceLock(live)
            first.acquire()
            try:
                self.assertTrue(instance_lock_path(live).is_file())
                with self.assertRaisesRegex(InstanceLockError, "already using"):
                    second.acquire()
            finally:
                first.release()

            second.acquire()
            second.release()

    def test_context_manager_releases_after_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            live = Path(tmp) / "data"
            live.mkdir()
            with self.assertRaisesRegex(RuntimeError, "boom"):
                with InstanceLock(live):
                    raise RuntimeError("boom")
            with InstanceLock(live):
                pass


if __name__ == "__main__":
    unittest.main()
