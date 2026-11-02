"""every word a habit's day log shows is in all 8 catalogs (c.05): each field's name, each choice's
options, each rating's words, each unit. a field the server adds without a name here would show
its raw key in english to everyone."""

import json
import re
import unittest
from pathlib import Path

from services import habit_kinds

ROOT = Path(__file__).resolve().parent.parent
LANGUAGES = ("en", "fr", "es", "zh-Hans", "zh-Hant", "ja", "ko", "ar")
LOGGERS = (ROOT / "static/js/habit_loggers.js").read_text(encoding="utf-8")
UNITS_JS = (ROOT / "static/js/units.js").read_text(encoding="utf-8")


def _catalog(language):
    return json.loads((ROOT / f"static/locales/{language}.json").read_text(encoding="utf-8"))[
        "messages"
    ]


def _english_built_in():
    text = (ROOT / "static/js/i18n.js").read_text(encoding="utf-8")
    return set(re.findall(r'^\s+"(habits\.[a-z0-9_.]+)":', text, re.M))


def _fields():
    def walk(fields):
        for field in fields:
            yield field
            yield from walk(field.get("columns", ()))

    for spec in habit_kinds.kinds().values():
        yield from walk(spec["fields"])


def needed_keys():
    keys = set()
    for field in _fields():
        if field["type"] == "exercises":
            continue
        keys.add(f"habits.field_{field['key']}")
        keys.update(f"habits.option_{option}" for option in field.get("options", ()))
    # the rating words: every scale named in habit_loggers.js, 5 words each (10 for 1 to 10 ones)
    scales = set(
        re.findall(r"'([a-z]+)'", re.search(r"const SCALES = \{(.*?)\};", LOGGERS).group(1))
    )
    ten = set(
        re.findall(r"'([a-z]+)'", re.search(r"const TEN = new Set\(\[(.*?)\]\)", LOGGERS).group(1))
    )
    for scale in scales | {"good"}:
        keys.update(f"habits.scale_{scale}_{n}" for n in range(1, (10 if scale in ten else 5) + 1))
    # every unit a measure offers or a number field names
    measures = re.search(r"MEASURE_UNITS = \{(.*?)\};", UNITS_JS, re.S).group(1)
    named = re.search(r"const FIELD_UNITS = \{(.*?)\};", UNITS_JS, re.S).group(1)
    units = set(re.findall(r"'([a-z_]+)'", measures)) | set(re.findall(r":\s*'([a-z_]+)'", named))
    keys.update(f"habits.unit_{unit}" for unit in units | {"min", "s"})
    # and every literal t('habits.…') the loggers call
    keys.update(re.findall(r"t\('(habits\.[a-z0-9_]+)'", LOGGERS))
    return keys


class HabitLoggerStringsTest(unittest.TestCase):
    def test_every_logger_string_is_in_every_catalog(self):
        keys = needed_keys()
        self.assertGreater(len(keys), 400)
        built_in = _english_built_in()
        missing_built_in = sorted(key for key in keys if key not in built_in)
        self.assertEqual(missing_built_in, [], "missing from static/js/i18n.js")
        for language in LANGUAGES:
            catalog = _catalog(language)
            plurals = json.loads(
                (ROOT / f"static/locales/{language}.json").read_text(encoding="utf-8")
            ).get("plurals", {})
            missing = sorted(key for key in keys if key not in catalog and key not in plurals)
            with self.subTest(language=language):
                self.assertEqual(missing, [])

    def test_field_names_are_translated_not_english(self):
        english = _catalog("en")
        for language in LANGUAGES[1:]:
            catalog = _catalog(language)
            same = [
                key
                for key in english
                if key.startswith("habits.field_") and catalog.get(key) == english[key]
            ]
            # cognates read the same (french distance, sport, style; gym, spf, xp): most must not
            with self.subTest(language=language):
                self.assertLess(len(same), 40, same)

    def test_a_missing_name_fails(self):
        catalog = dict(_catalog("fr"))
        catalog.pop("habits.field_latency")
        self.assertIn("habits.field_latency", needed_keys())
        self.assertNotIn("habits.field_latency", catalog)


if __name__ == "__main__":
    unittest.main()
