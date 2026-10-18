import sys
import threading
import time
import types
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest import mock

from services.research import search


class PageParseLockTest(unittest.TestCase):
    # trafilatura/lxml abort the process when two threads parse at once
    def test_parallel_fetches_never_parse_two_pages_at_once(self):
        state = {"now": 0, "most": 0}
        guard = threading.Lock()

        def extract(html, **_kwargs):
            with guard:
                state["now"] += 1
                state["most"] = max(state["most"], state["now"])
            time.sleep(0.02)
            with guard:
                state["now"] -= 1
            return "article text " + html[-3:]

        page = mock.Mock(text="<html><title>t</title><p>body</p></html>", headers={})
        page.raise_for_status = mock.Mock()
        fake = types.SimpleNamespace(extract=extract)
        with (
            mock.patch.dict(sys.modules, {"trafilatura": fake}),
            mock.patch("services.net_guard.safe_get", return_value=page),
        ):
            with ThreadPoolExecutor(6) as pool:
                rows = list(
                    pool.map(
                        search.fetch_webpage_content, [f"https://e.com/{i}" for i in range(12)]
                    )
                )

        self.assertTrue(all(row["success"] for row in rows))
        self.assertEqual(state["most"], 1)


if __name__ == "__main__":
    unittest.main()
