"""10c UI — git-backed skills: source badge, update + export actions, github import affordance.
aide.localhost:8874.  ALLES_DATA=/tmp/alles10c PORT=8874 AUTH_ENABLED=false python app.py
"""

import shutil
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

AIDE = "http://aide.localhost:8874"
EVID = Path(__file__).resolve().parent.parent / "docs" / "evidence" / "10c"
SKILLS_DIR = Path(__file__).resolve().parent.parent / "data" / "skills"
IGNORE = ("Failed to load resource", "net::", "ERR_", "favicon", "401", "403", "Load failed")

GIT_MD = (
    "---\nname: Demo Git Skill\ndescription: a git-backed demo\nwhen_to_use: demoing 10c\n"
    "source: https://github.com/o/r/blob/main/demo/SKILL.md\n---\n\nstep one\nstep two\n"
)
LOCAL_MD = "---\nname: Demo Local Skill\ndescription: a hand-written one\n---\n\njust local\n"


def _seed(slug, md):
    d = SKILLS_DIR / slug
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(md, "utf-8")


def main():
    EVID.mkdir(parents=True, exist_ok=True)
    r = {}
    errs = []
    _seed("demo-git-skill", GIT_MD)
    _seed("demo-local-skill", LOCAL_MD)
    try:
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

            pg.goto(f"{AIDE}/", wait_until="domcontentloaded")
            pg.wait_for_selector('.nav-item[data-view="skills"]', timeout=15000)
            pg.eval_on_selector('.nav-item[data-view="skills"]', "el => el.click()")
            pg.wait_for_selector("#skl-list .skl-row", timeout=10000)
            pg.wait_for_timeout(300)

            r["github_import_present"] = pg.is_visible("#skl-github")
            list_txt = pg.text_content("#skl-list") or ""
            r["skills_list_renders"] = (
                "Demo Git Skill" in list_txt and "Demo Local Skill" in list_txt
            )
            # the git-backed row carries a git badge
            r["source_badge_on_imported"] = (
                pg.query_selector('.skl-row[data-slug="demo-git-skill"] .skl-git') is not None
            )
            pg.screenshot(path=str(EVID / "skills-list.png"))

            # open the git-backed skill → update + export + source visible
            pg.eval_on_selector('.skl-row[data-slug="demo-git-skill"]', "el => el.click()")
            pg.wait_for_timeout(400)
            r["update_button_present"] = pg.is_visible("#skl-update")
            r["export_button_present"] = pg.is_visible("#skl-export")
            pg.screenshot(path=str(EVID / "skills-git-open.png"))

            # export downloads the SKILL.md
            try:
                with pg.expect_download(timeout=6000) as dl:
                    pg.eval_on_selector("#skl-export", "el => el.click()")
                r["export_downloads_md"] = "SKILL.md" in (dl.value.suggested_filename or "")
            except Exception:
                r["export_downloads_md"] = False

            # a local (non-git) skill hides the update action
            pg.eval_on_selector('.skl-row[data-slug="demo-local-skill"]', "el => el.click()")
            pg.wait_for_timeout(400)
            r["update_hidden_for_local"] = not pg.is_visible("#skl-update")

            r["zero_console_errors"] = len(errs) == 0
            b.close()
    finally:
        shutil.rmtree(SKILLS_DIR / "demo-git-skill", ignore_errors=True)
        shutil.rmtree(SKILLS_DIR / "demo-local-skill", ignore_errors=True)

    ok = all(r.values())
    lines = [f"{'PASS' if v else 'FAIL'}  {k}" for k, v in r.items()]
    if errs:
        lines.append(f"console_errors: {errs[:8]}")
    out = "\n".join(lines)
    (EVID / "pw_skills_10c.txt").write_text(out, encoding="utf-8")
    print(out)
    print(f"\n{sum(bool(v) for v in r.values())}/{len(r)} assertions passed")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
