"""2d UI verification — spatial canvas: add/drag nodes, connect edges, persist. :8820."""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

DOCS = "http://docs.localhost:8820"
EVID = Path(__file__).resolve().parent.parent / "docs" / "evidence" / "2d"
IGNORE = ("Failed to load resource", "net::", "ERR_", "favicon", "401", "Load failed")


def main():
    # start from a fresh canvas (the file persists between runs)
    Path(r"C:\Users\jxh\AppData\Local\Temp\alles2d_data\vault\board.canvas").unlink(missing_ok=True)
    r = {}
    errs = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_context().new_page()
        pg.on(
            "console",
            lambda m: (
                errs.append(m.text)
                if m.type == "error" and not any(x in m.text for x in IGNORE)
                else None
            ),
        )
        pg.on(
            "pageerror",
            lambda e: errs.append(str(e)) if not any(x in str(e) for x in IGNORE) else None,
        )

        pg.goto(f"{DOCS}/?canvas=board", wait_until="domcontentloaded")
        pg.wait_for_selector("#canvas-view", state="visible", timeout=15000)
        r["canvas_opens"] = pg.is_visible("#canvas-view")

        # add two nodes
        pg.click("#canvas-add")
        pg.wait_for_timeout(200)
        pg.click("#canvas-add")
        pg.wait_for_timeout(300)
        r["add_node"] = len(pg.query_selector_all(".canvas-node")) >= 1
        r["two_nodes"] = len(pg.query_selector_all(".canvas-node")) == 2

        # drag the top-most node (last in DOM → on top, so mousedown lands on it)
        node = pg.query_selector_all(".canvas-node")[-1]
        nid = node.get_attribute("data-id")
        box = node.bounding_box()
        sel = f'.canvas-node[data-id="{nid}"]'
        before_left = pg.eval_on_selector(sel, "el => el.style.left")
        pg.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] - 8)
        pg.mouse.down()
        pg.mouse.move(box["x"] + 260, box["y"] + 180, steps=8)
        pg.mouse.up()
        pg.wait_for_timeout(400)
        after_left = pg.eval_on_selector(sel, "el => el.style.left")
        r["drag_moves_node"] = before_left != after_left

        # connect the two nodes (JS click on the ↔ handle to avoid overlap interception)
        nodes = pg.query_selector_all(".canvas-node")
        nodes[0].query_selector(".canvas-node-link").evaluate("e => e.click()")
        pg.wait_for_timeout(150)
        nodes[1].query_selector(".canvas-node-link").evaluate("e => e.click()")
        pg.wait_for_timeout(400)
        r["connect_creates_edge"] = pg.query_selector(".canvas-edges line") is not None
        pg.screenshot(path=str(EVID / "canvas.png"))

        # reload → layout + edge persist
        pg.wait_for_timeout(600)  # let autosave flush
        pg.goto(f"{DOCS}/?canvas=board", wait_until="domcontentloaded")
        pg.wait_for_selector("#canvas-view .canvas-node", timeout=15000)
        r["nodes_persist_after_reload"] = len(pg.query_selector_all(".canvas-node")) == 2
        r["edge_persists_after_reload"] = pg.query_selector(".canvas-edges line") is not None

        # delete a node
        n0 = pg.query_selector_all(".canvas-node")[0]
        n0.query_selector(".canvas-node-del").evaluate("e => e.click()")
        pg.wait_for_timeout(300)
        r["delete_node"] = len(pg.query_selector_all(".canvas-node")) == 1

        r["zero_console_errors"] = len(errs) == 0
        b.close()

    ok = all(r.values())
    lines = [f"{'PASS' if v else 'FAIL'}  {k}" for k, v in r.items()]
    if errs:
        lines.append(f"console_errors: {errs[:8]}")
    out = "\n".join(lines)
    (EVID / "pw_canvas_2d.txt").write_text(out, encoding="utf-8")
    print(out)
    print(f"\n{sum(r.values())}/{len(r)} assertions passed")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
