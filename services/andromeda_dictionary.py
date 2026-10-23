"""a local english dictionary for andromeda, built from wiktionary.

the data is kaikki.org's machine-readable english wiktionary (cc by-sa 4.0, made with the
open-source wiktextract). it is downloaded and turned into one sqlite file once; after that every
lookup, spelling check and "did you mean" is answered on this machine, in milliseconds, and the
word never leaves it. the file lives under models/ like the other rebuildable models, so backups
skip it.

    python -m services.andromeda_dictionary install     # download (~520 MB) and build
    python -m services.andromeda_dictionary build FILE  # build from a downloaded .jsonl(.gz)
"""

from __future__ import annotations

import gzip
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE_URL = "https://kaikki.org/dictionary/English/kaikki.org-dictionary-English.jsonl.gz"
SOURCE_NAME = "Wiktionary"
_conn: sqlite3.Connection | None = None
_conn_path: Path | None = None


def db_path() -> Path:
    return Path(
        os.environ.get("ALLES_DICTIONARY")
        or (ROOT / "models" / "dictionary" / "wiktionary-en.sqlite")
    )


def available() -> bool:
    return db_path().is_file()


def _db() -> sqlite3.Connection | None:
    global _conn, _conn_path
    path = db_path()
    if not path.is_file():
        return None
    if _conn is None or _conn_path != path:
        _conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
        _conn_path = path
    return _conn


def _clip(text, limit: int) -> str:
    value = " ".join(str(text or "").split())
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


def _misspelling_target(sense: dict) -> str:
    tags = sense.get("tags") or []
    if "misspelling" not in tags:
        return ""
    for key in ("alt_of", "form_of"):
        for row in sense.get(key) or []:
            if row.get("word"):
                return row["word"]
    return ""


def _entry(row: dict) -> dict | None:
    """one part of speech, trimmed to what the card shows."""
    senses, misspelt = [], []
    for sense in row.get("senses") or []:
        target = _misspelling_target(sense)
        if target:
            misspelt.append(target)
            continue
        glosses = sense.get("glosses") or []
        if not glosses:
            continue
        example = next(
            (
                _clip(x.get("text"), 220)
                for x in sense.get("examples") or []
                if x.get("text") and not x.get("ref")
            ),
            "",
        )
        senses.append({"text": _clip(glosses[-1], 300), "example": example})
        if len(senses) == 4:
            break
    if not senses and not misspelt:
        return None
    words = lambda key: [  # noqa: E731
        w["word"]
        for w in (row.get(key) or [])
        + [w for s in row.get("senses") or [] for w in s.get(key) or []]
        if w.get("word")
    ]
    ipa = next((s["ipa"] for s in row.get("sounds") or [] if s.get("ipa")), "")
    return {
        "part": str(row.get("pos") or "").replace("_", " "),
        "ipa": ipa,
        "senses": senses,
        "synonyms": list(dict.fromkeys(words("synonyms")))[:12],
        "antonyms": list(dict.fromkeys(words("antonyms")))[:8],
        "misspelling_of": list(dict.fromkeys(misspelt))[:3],
    }


def build(source: Path, target: Path | None = None) -> int:
    """turn a kaikki english .jsonl or .jsonl.gz into the sqlite file. returns entries kept."""
    target = target or db_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(".building")
    temp.unlink(missing_ok=True)
    db = sqlite3.connect(temp)
    db.execute("create table entries (word text not null, n integer not null, data text not null)")
    opener = gzip.open if source.suffix == ".gz" else open
    kept = 0
    batch = []
    counts: dict[str, int] = {}
    with opener(source, "rt", encoding="utf-8") as lines:
        for line in lines:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get("lang_code") != "en" or not row.get("word"):
                continue
            entry = _entry(row)
            if entry is None:
                continue
            word = row["word"].strip().lower()
            n = counts.get(word, 0)
            counts[word] = n + 1
            batch.append((word, n, json.dumps(entry, ensure_ascii=False, separators=(",", ":"))))
            kept += 1
            if len(batch) >= 5000:
                db.executemany("insert into entries values (?, ?, ?)", batch)
                batch.clear()
    if batch:
        db.executemany("insert into entries values (?, ?, ?)", batch)
    db.execute("create index entries_word on entries (word, n)")
    db.commit()
    db.execute("vacuum")
    db.close()
    os.replace(temp, target)
    global _conn
    _conn = None
    return kept


def _rows(word: str) -> list[dict]:
    db = _db()
    if db is None:
        return []
    found = db.execute(
        "select data from entries where word = ? order by n", (word.strip().lower(),)
    ).fetchall()
    return [json.loads(data) for (data,) in found]


def lookup(word: str, focus: str = "") -> dict | None:
    """the dictionary card for a word, None when the local file isn't installed."""
    if not available():
        return None
    rows = _rows(word)
    real = [row for row in rows if row["senses"]]
    misspelt = list(dict.fromkeys(t for row in rows for t in row["misspelling_of"]))
    if not real:
        return {
            "kind": "define",
            "word": word,
            "focus": focus,
            "status": "not_found",
            "suggestions": misspelt[:3],
            "source": f"{SOURCE_NAME} (local copy)",
        }
    meanings = []
    for row in real:
        same = next((m for m in meanings if m["part"] == row["part"]), None)
        if same:
            same["definitions"] = (same["definitions"] + row["senses"])[:4]
        elif len(meanings) < 3:
            meanings.append({"part": row["part"], "definitions": row["senses"]})
    synonyms = [w for w in dict.fromkeys(s for row in real for s in row["synonyms"]) if w != word]
    antonyms = [w for w in dict.fromkeys(s for row in real for s in row["antonyms"]) if w != word]
    return {
        "kind": "define",
        "word": word,
        "phonetic": next((row["ipa"] for row in real if row["ipa"]), ""),
        "meanings": meanings,
        "synonyms": synonyms[:8],
        "antonyms": antonyms[:8],
        "focus": focus,
        "status": "ok",
        "source": f"{SOURCE_NAME} (local copy)",
    }


def spelling(word: str) -> dict | None:
    """{"known", "suggestions"} from the local file, None when it isn't installed."""
    if not available():
        return None
    rows = _rows(word)
    return {
        "known": any(row["senses"] for row in rows),
        "suggestions": list(dict.fromkeys(t for row in rows for t in row["misspelling_of"]))[:3],
    }


def _install() -> None:
    import urllib.request

    target = db_path()
    download = target.parent / "kaikki-en.jsonl.gz"
    target.parent.mkdir(parents=True, exist_ok=True)
    print(f"downloading {SOURCE_URL}")
    urllib.request.urlretrieve(SOURCE_URL, download)
    started = time.time()
    kept = build(download)
    download.unlink(missing_ok=True)
    print(f"built {target} with {kept} entries in {round(time.time() - started)} s")


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "install":
        _install()
    elif command == "build" and len(sys.argv) > 2:
        print(f"{build(Path(sys.argv[2]))} entries")
    else:
        print(__doc__)
        raise SystemExit(2)
