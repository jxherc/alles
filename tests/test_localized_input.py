import unittest
from datetime import date

from services.event_nl import parse_event
from services.localized_input import LANGUAGES, normalize_quick_add
from services.task_nl import parse_task

TODAY = date(2026, 6, 15)


class LocalizedQuickAddTests(unittest.TestCase):
    TASK_CASES = {
        "en": ("call mom tomorrow", "call mom"),
        "fr": ("appeler maman demain", "appeler maman"),
        "es": ("llamar a mamá mañana", "llamar a mamá"),
        "zh-Hans": ("给妈妈打电话 明天", "给妈妈打电话"),
        "zh-Hant": ("打電話給媽媽 明天", "打電話給媽媽"),
        "ja": ("母に電話 明日", "母に電話"),
        "ko": ("엄마에게 전화 내일", "엄마에게 전화"),
        "ar": ("اتصل بأمي غدًا", "اتصل بأمي"),
    }
    EVENT_CASES = {
        "en": ("meet alex tomorrow 3pm for 2 hours", "meet alex"),
        "fr": ("réunion demain 15h30 pendant 2 heures", "réunion"),
        "es": ("reunión mañana 15:30 durante 2 horas", "reunión"),
        "zh-Hans": ("会议 明天 下午3点30分 持续2小时", "会议"),
        "zh-Hant": ("會議 明天 下午3點30分 持續2小時", "會議"),
        "ja": ("会議 明日 午後3時30分 2時間", "会議"),
        "ko": ("회의 내일 오후 3시 30분 2시간 동안", "회의"),
        "ar": ("اجتماع غدًا الساعة ٣ مساءً لمدة ساعتين", "اجتماع"),
    }
    DATE_CASES = {
        "en": "renew passport june 20 2027",
        "fr": "renouveler le passeport 20 juin 2027",
        "es": "renovar el pasaporte 20 junio 2027",
        "zh-Hans": "更新护照 2027年6月20日",
        "zh-Hant": "更新護照 2027年6月20日",
        "ja": "パスポート更新 2027年6月20日",
        "ko": "여권 갱신 2027년6월20일",
        "ar": "تجديد جواز السفر ٢٠ يونيو ٢٠٢٧",
    }
    REPEAT_CASES = {
        "en": "water plants every monday",
        "fr": "arroser les plantes chaque lundi",
        "es": "regar las plantas cada lunes",
        "zh-Hans": "浇花 每周一",
        "zh-Hant": "澆花 每週一",
        "ja": "植物に水をやる 毎週月曜日",
        "ko": "식물에 물주기 매주 월요일",
        "ar": "اسق النباتات كل الاثنين",
    }

    def test_task_relative_dates_work_in_all_eight_languages(self):
        self.assertEqual(tuple(self.TASK_CASES), LANGUAGES)
        for language, (source, title) in self.TASK_CASES.items():
            with self.subTest(language=language):
                parsed = parse_task(source, TODAY, language)
                self.assertEqual(parsed["title"], title)
                self.assertEqual(parsed["due_date"], "2026-06-16")

    def test_calendar_time_and_duration_work_in_all_eight_languages(self):
        for language, (source, title) in self.EVENT_CASES.items():
            with self.subTest(language=language):
                parsed = parse_event(source, TODAY, language)
                self.assertEqual(parsed["title"], title)
                self.assertEqual(
                    parsed["start_dt"],
                    "2026-06-16T15:30"
                    if language != "en" and language != "ar"
                    else "2026-06-16T15:00",
                )
                self.assertEqual(
                    parsed["end_dt"],
                    "2026-06-16T17:30"
                    if language != "en" and language != "ar"
                    else "2026-06-16T17:00",
                )
                self.assertFalse(parsed["all_day"])

    def test_spanish_morning_phrase_is_not_rewritten_as_a_second_tomorrow(self):
        parsed = parse_task("reunión mañana por la mañana", TODAY, "es")

        self.assertEqual(parsed["title"], "reunión por la mañana")
        self.assertEqual(parsed["due_date"], "2026-06-16")

    def test_spanish_clock_period_is_not_rewritten_as_tomorrow(self):
        parsed = parse_event("reunión a las 9 de la mañana", TODAY, "es")

        self.assertEqual(parsed["title"], "reunión a las 9 de la mañana")
        self.assertEqual(parsed["start_dt"], "2026-06-15")
        self.assertIsNone(parsed["end_dt"])

    def test_korean_clock_minutes_are_not_rewritten_as_a_duration(self):
        parsed = parse_event("회의 내일 3시 30분", TODAY, "ko")
        self.assertEqual(parsed["title"], "회의")
        self.assertEqual(parsed["start_dt"], "2026-06-16T03:30")
        self.assertEqual(parsed["end_dt"], "2026-06-16T04:30")

    def test_korean_words_containing_bun_are_preserved(self):
        parsed = parse_event("분석 보고서", TODAY, "ko")
        self.assertEqual(parsed["title"], "분석 보고서")

    def test_korean_unit_words_outside_numeric_syntax_are_preserved(self):
        parsed = parse_task("시간 관리", TODAY, "ko")
        self.assertEqual(parsed["title"], "시간 관리")
        self.assertIsNone(parsed["due_date"])

    def test_explicit_local_dates_work_in_all_eight_languages(self):
        for language, source in self.DATE_CASES.items():
            with self.subTest(language=language):
                self.assertEqual(parse_task(source, TODAY, language)["due_date"], "2027-06-20")

    def test_east_asian_numeric_dates_use_month_day_and_year_month_day_order(self):
        for language in ("zh-Hans", "zh-Hant", "ja", "ko"):
            with self.subTest(language=language, form="month-day"):
                self.assertEqual(
                    parse_task("更新 7/23", TODAY, language)["due_date"],
                    "2026-07-23",
                )
            with self.subTest(language=language, form="year-month-day"):
                self.assertEqual(
                    parse_task("更新 2027/7/23", TODAY, language)["due_date"],
                    "2027-07-23",
                )

    def test_versions_and_fractions_are_not_rewritten_as_yearless_dates(self):
        version = parse_task("mettre à jour vers la version 2.3", TODAY, "fr")
        fraction = parse_task("utiliser 3/4 de tasse", TODAY, "fr")

        self.assertEqual(version["title"], "mettre à jour vers la version 2.3")
        self.assertIsNone(version["due_date"])
        self.assertEqual(fraction["title"], "utiliser 3/4 de tasse")
        self.assertIsNone(fraction["due_date"])

    def test_weekly_recurrence_works_in_all_eight_languages(self):
        for language, source in self.REPEAT_CASES.items():
            with self.subTest(language=language):
                parsed = parse_task(source, TODAY, language)
                self.assertEqual(parsed["repeat"], "weekly")
                self.assertEqual(parsed["due_date"], "2026-06-22")

    def test_canonical_recurrence_tokens_and_french_ordinal_are_consumed(self):
        for language, source, repeat in (
            ("fr", "arroser quotidiennement", "daily"),
            ("es", "regar diariamente", "daily"),
            ("fr", "payer le loyer chaque 1er", "monthly"),
        ):
            with self.subTest(language=language, source=source):
                parsed = parse_task(source, TODAY, language)
                self.assertEqual(parsed["repeat"], repeat)
                self.assertNotRegex(parsed["title"], r"\b(?:daily|every 1er)\b")

    def test_unknown_text_stays_local_owner_text_instead_of_being_guessed(self):
        for language, source in (
            ("fr", "réparer le vélo"),
            ("zh-Hans", "整理书架"),
            ("ar", "قراءة الكتاب"),
        ):
            with self.subTest(language=language):
                parsed = parse_event(source, TODAY, language)
                self.assertEqual(parsed["title"], source)
                self.assertTrue(parsed["all_day"])

    def test_unsupported_language_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "unsupported"):
            normalize_quick_add("tomorrow", "de")

    def test_locale_tokens_do_not_rewrite_substrings_inside_owner_words(self):
        parsed = parse_task("envoyer un email demain", TODAY, "fr")
        self.assertEqual(parsed["title"], "envoyer un email")

    def test_bare_localized_month_names_remain_owner_title_text(self):
        self.assertEqual(parse_task("informe de mayo", TODAY, "es")["title"], "informe de mayo")
        self.assertEqual(parse_task("Mayo", TODAY, "es")["title"], "Mayo")
        self.assertIsNone(parse_task("informe de mayo", TODAY, "es")["due_date"])


if __name__ == "__main__":
    unittest.main()
