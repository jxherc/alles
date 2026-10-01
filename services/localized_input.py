"""Deterministic locale normalization for Task and Calendar quick-add input."""

from __future__ import annotations

import re

LANGUAGES = ("en", "fr", "es", "zh-Hans", "zh-Hant", "ja", "ko", "ar")
_LANGUAGE_BY_LOWER = {language.lower(): language for language in LANGUAGES}
_MONTHS = (
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
)
_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")

_PHRASES = {
    "fr": {
        "après-demain": "in 2 days",
        "apres-demain": "in 2 days",
        "aujourd'hui": "today",
        "aujourd’hui": "today",
        "ce soir": "tonight",
        "demain": "tomorrow",
        "tous les jours": "every day",
        "chaque jour": "every day",
        "toutes les semaines": "every week",
        "chaque semaine": "every week",
        "tous les mois": "every month",
        "chaque mois": "every month",
        "tous les ans": "every year",
        "chaque année": "every year",
        "chaque": "every",
        "quotidiennement": "daily",
        "hebdomadaire": "weekly",
        "mensuel": "monthly",
        "annuel": "yearly",
        "jusqu'au": "until",
        "jusqu’au": "until",
        "jusqu'à": "until",
        "jusqu’à": "until",
        "pendant": "for",
        "heures": "hours",
        "heure": "hour",
        "minutes": "minutes",
        "minute": "minute",
        "midi": "noon",
        "minuit": "midnight",
        "lundi": "monday",
        "mardi": "tuesday",
        "mercredi": "wednesday",
        "jeudi": "thursday",
        "vendredi": "friday",
        "samedi": "saturday",
        "dimanche": "sunday",
        "janvier": "january",
        "février": "february",
        "fevrier": "february",
        "mars": "march",
        "avril": "april",
        "mai": "may",
        "juin": "june",
        "juillet": "july",
        "août": "august",
        "aout": "august",
        "septembre": "september",
        "octobre": "october",
        "novembre": "november",
        "décembre": "december",
        "decembre": "december",
    },
    "es": {
        "pasado mañana": "in 2 days",
        "esta noche": "tonight",
        "hoy": "today",
        "mañana": "tomorrow",
        "cada día": "every day",
        "todos los días": "every day",
        "cada semana": "every week",
        "cada mes": "every month",
        "cada año": "every year",
        "cada": "every",
        "diariamente": "daily",
        "semanalmente": "weekly",
        "mensualmente": "monthly",
        "anualmente": "yearly",
        "hasta": "until",
        "durante": "for",
        "horas": "hours",
        "hora": "hour",
        "minutos": "minutes",
        "minuto": "minute",
        "mediodía": "noon",
        "mediodia": "noon",
        "medianoche": "midnight",
        "lunes": "monday",
        "martes": "tuesday",
        "miércoles": "wednesday",
        "miercoles": "wednesday",
        "jueves": "thursday",
        "viernes": "friday",
        "sábado": "saturday",
        "sabado": "saturday",
        "domingo": "sunday",
        "enero": "january",
        "febrero": "february",
        "marzo": "march",
        "abril": "april",
        "mayo": "may",
        "junio": "june",
        "julio": "july",
        "agosto": "august",
        "septiembre": "september",
        "octubre": "october",
        "noviembre": "november",
        "diciembre": "december",
    },
    "zh-Hans": {
        "后天": "in 2 days",
        "今天": "today",
        "今晚": "tonight",
        "明天": "tomorrow",
        "每天": "every day",
        "每周": "every week",
        "每週": "every week",
        "每月": "every month",
        "每年": "every year",
        "直到": "until",
        "持续": "for",
        "小時": "hours",
        "小时": "hours",
        "分鐘": "minutes",
        "分钟": "minutes",
        "中午": "noon",
        "午夜": "midnight",
        "星期一": "monday",
        "星期二": "tuesday",
        "星期三": "wednesday",
        "星期四": "thursday",
        "星期五": "friday",
        "星期六": "saturday",
        "星期日": "sunday",
        "星期天": "sunday",
        "周一": "monday",
        "周二": "tuesday",
        "周三": "wednesday",
        "周四": "thursday",
        "周五": "friday",
        "周六": "saturday",
        "周日": "sunday",
        "每周一": "every monday",
        "每周二": "every tuesday",
        "每周三": "every wednesday",
        "每周四": "every thursday",
        "每周五": "every friday",
        "每周六": "every saturday",
        "每周日": "every sunday",
    },
    "zh-Hant": {
        "後天": "in 2 days",
        "今天": "today",
        "今晚": "tonight",
        "明天": "tomorrow",
        "每天": "every day",
        "每週": "every week",
        "每月": "every month",
        "每年": "every year",
        "直到": "until",
        "持續": "for",
        "小時": "hours",
        "分鐘": "minutes",
        "中午": "noon",
        "午夜": "midnight",
        "星期一": "monday",
        "星期二": "tuesday",
        "星期三": "wednesday",
        "星期四": "thursday",
        "星期五": "friday",
        "星期六": "saturday",
        "星期日": "sunday",
        "星期天": "sunday",
        "週一": "monday",
        "週二": "tuesday",
        "週三": "wednesday",
        "週四": "thursday",
        "週五": "friday",
        "週六": "saturday",
        "週日": "sunday",
        "每週一": "every monday",
        "每週二": "every tuesday",
        "每週三": "every wednesday",
        "每週四": "every thursday",
        "每週五": "every friday",
        "每週六": "every saturday",
        "每週日": "every sunday",
    },
    "ja": {
        "明後日": "in 2 days",
        "今日": "today",
        "今夜": "tonight",
        "明日": "tomorrow",
        "毎日": "every day",
        "毎週": "every week",
        "毎月": "every month",
        "毎年": "every year",
        "まで": "until",
        "の間": "for",
        "時間": "hours",
        "分間": "minutes",
        "正午": "noon",
        "真夜中": "midnight",
        "月曜日": "monday",
        "火曜日": "tuesday",
        "水曜日": "wednesday",
        "木曜日": "thursday",
        "金曜日": "friday",
        "土曜日": "saturday",
        "日曜日": "sunday",
    },
    "ko": {
        "오늘 밤": "tonight",
        "오늘": "today",
        "내일": "tomorrow",
        "모레": "in 2 days",
        "매일": "every day",
        "매주": "every week",
        "매월": "every month",
        "매년": "every year",
        "까지": "until",
        "동안": "for",
        "시간": "hours",
        "정오": "noon",
        "자정": "midnight",
        "월요일": "monday",
        "화요일": "tuesday",
        "수요일": "wednesday",
        "목요일": "thursday",
        "금요일": "friday",
        "토요일": "saturday",
        "일요일": "sunday",
    },
    "ar": {
        "بعد غد": "in 2 days",
        "هذه الليلة": "tonight",
        "الليلة": "tonight",
        "اليوم": "today",
        "غدًا": "tomorrow",
        "غدا": "tomorrow",
        "كل يوم": "every day",
        "كل أسبوع": "every week",
        "كل اسبوع": "every week",
        "كل شهر": "every month",
        "كل سنة": "every year",
        "يوميًا": "daily",
        "يوميا": "daily",
        "أسبوعيًا": "weekly",
        "اسبوعيا": "weekly",
        "شهريًا": "monthly",
        "شهريا": "monthly",
        "سنويًا": "yearly",
        "سنويا": "yearly",
        "حتى": "until",
        "لمدة": "for",
        "ساعات": "hours",
        "ساعة": "hour",
        "دقائق": "minutes",
        "دقيقة": "minute",
        "ظهرًا": "noon",
        "ظهرا": "noon",
        "منتصف الليل": "midnight",
        "الاثنين": "monday",
        "الثلاثاء": "tuesday",
        "الأربعاء": "wednesday",
        "الاربعاء": "wednesday",
        "الخميس": "thursday",
        "الجمعة": "friday",
        "السبت": "saturday",
        "الأحد": "sunday",
        "الاحد": "sunday",
        "كل": "every",
        "يناير": "january",
        "فبراير": "february",
        "مارس": "march",
        "أبريل": "april",
        "ابريل": "april",
        "مايو": "may",
        "يونيو": "june",
        "يوليو": "july",
        "أغسطس": "august",
        "اغسطس": "august",
        "سبتمبر": "september",
        "أكتوبر": "october",
        "اكتوبر": "october",
        "نوفمبر": "november",
        "ديسمبر": "december",
    },
}


def normalize_language(language: str) -> str:
    canonical = _LANGUAGE_BY_LOWER.get(str(language or "en").strip().lower())
    if not canonical:
        raise ValueError("unsupported quick-add language")
    return canonical


def _replace_phrases(text: str, language: str) -> str:
    phrases = _PHRASES.get(language, {})
    if language == "es":
        text = re.sub(
            r"(?<!\w)((?:por|de|en|a)\s+la\s+)?mañana(?!\w)",
            lambda match: match.group(0) if match.group(1) else " tomorrow ",
            text,
            flags=re.IGNORECASE,
        )
    for source in sorted(phrases, key=len, reverse=True):
        target = phrases[source]
        if language == "es" and source == "mañana":
            continue
        if target in _MONTHS or target in {"for", "hour", "hours", "minute", "minutes"}:
            continue
        pattern = re.escape(source)
        if language not in {"zh-Hans", "zh-Hant", "ja", "ko"}:
            if source[0].isalnum():
                pattern = rf"(?<!\w){pattern}"
            if source[-1].isalnum():
                pattern = rf"{pattern}(?!\w)"
        text = re.sub(pattern, f" {target} ", text, flags=re.IGNORECASE)
    return text


def _normalize_named_dates(text: str, language: str) -> str:
    phrases = _PHRASES.get(language, {})
    for source in sorted(phrases, key=len, reverse=True):
        target = phrases[source]
        if target not in _MONTHS:
            continue
        month = re.escape(source)
        text = re.sub(
            rf"(?<!\w)(\d{{1,2}})\s+{month}(?!\w)",
            lambda match: f" {match.group(1)} {target} ",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(
            rf"(?<!\w){month}\s+(\d{{1,2}})(?!\d)",
            lambda match: f" {target} {match.group(1)} ",
            text,
            flags=re.IGNORECASE,
        )
    return text


def _normalize_east_asian_dates(text: str) -> str:
    def full(match: re.Match) -> str:
        return f" {match.group(1)}-{int(match.group(2)):02d}-{int(match.group(3)):02d} "

    def month_day(match: re.Match) -> str:
        month = int(match.group(1))
        if not 1 <= month <= 12:
            return match.group(0)
        return f" {_MONTHS[month - 1]} {int(match.group(2))} "

    text = re.sub(r"(\d{4})\s*[年년]\s*(\d{1,2})\s*[月월]\s*(\d{1,2})\s*[日일]?", full, text)
    return re.sub(r"(\d{1,2})\s*[月월]\s*(\d{1,2})\s*[日일]", month_day, text)


def _normalize_times(text: str, language: str) -> str:
    if language == "fr":
        text = re.sub(
            r"\b(\d{1,2})\s*h\s*(\d{2})?\b",
            lambda match: f" {match.group(1)}:{match.group(2) or '00'} ",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(
            r"\b(?:pendant\s+)?(\d+)\s+heures?\b",
            lambda match: f" for {match.group(1)} hours ",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(
            r"\b(?:pendant\s+)?(\d+)\s+minutes?\b",
            lambda match: f" for {match.group(1)} minutes ",
            text,
            flags=re.IGNORECASE,
        )
    if language == "es":
        text = re.sub(
            r"\b(?:durante\s+)?(\d+)\s+horas?\b",
            lambda match: f" for {match.group(1)} hours ",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(
            r"\b(?:durante\s+)?(\d+)\s+minutos?\b",
            lambda match: f" for {match.group(1)} minutes ",
            text,
            flags=re.IGNORECASE,
        )
    if language in {"zh-Hans", "zh-Hant", "ja"}:
        meridiem = r"(上午|午前|下午|午後)\s*(\d{1,2})\s*[点點時时]\s*(\d{1,2})?\s*[分]?"

        def east_time(match: re.Match) -> str:
            suffix = "am" if match.group(1) in {"上午", "午前"} else "pm"
            return f" {match.group(2)}:{match.group(3) or '00'}{suffix} "

        text = re.sub(meridiem, east_time, text)
        if language in {"zh-Hans", "zh-Hant"}:
            text = re.sub(
                r"(?:持续|持續)?\s*(\d+)\s*(?:小时|小時)",
                lambda match: f" for {match.group(1)} hours ",
                text,
            )
            text = re.sub(
                r"(?:持续|持續)?\s*(\d+)\s*(?:分钟|分鐘)",
                lambda match: f" for {match.group(1)} minutes ",
                text,
            )
        else:
            text = re.sub(
                r"(\d+)\s*時間(?:の間)?",
                lambda match: f" for {match.group(1)} hours ",
                text,
            )
            text = re.sub(
                r"(\d+)\s*分間",
                lambda match: f" for {match.group(1)} minutes ",
                text,
            )
        text = re.sub(
            r"(\d{1,2})\s*[点點時时]\s*(\d{1,2})?\s*[分]?",
            lambda match: f" {match.group(1)}:{match.group(2) or '00'} ",
            text,
        )
    if language == "ko":
        text = re.sub(
            r"(오전|오후)\s*(\d{1,2})\s*시\s*(\d{1,2})?\s*분?",
            lambda match: (
                f" {match.group(2)}:{match.group(3) or '00'}"
                f"{'am' if match.group(1) == '오전' else 'pm'} "
            ),
            text,
        )
        text = re.sub(
            r"(\d{1,2})\s*시(?!간)\s*(\d{1,2})?\s*분?",
            lambda match: f" {match.group(1)}:{match.group(2) or '00'} ",
            text,
        )
        text = re.sub(
            r"(\d+)\s*시간(?:\s*동안)?",
            lambda match: f" for {match.group(1)} hours ",
            text,
        )
        text = re.sub(
            r"(\d+)\s*분(?:\s*동안)?",
            lambda match: f" for {match.group(1)} minutes ",
            text,
        )
    if language == "ar":
        text = re.sub(r"لمدة\s+ساعتين", " for 2 hours ", text)
        text = re.sub(r"لمدة\s+ساعة", " for 1 hour ", text)
        text = re.sub(
            r"(?:الساعة\s*)?(\d{1,2})(?::(\d{2}))?\s*(صباحًا|صباحا|ص|مساءً|مساء|م)",
            lambda match: (
                f" {match.group(1)}:{match.group(2) or '00'}"
                f"{'am' if match.group(3).startswith('ص') else 'pm'} "
            ),
            text,
        )
    return text


def _normalize_numeric_date(text: str, language: str) -> str:
    if language == "en":
        return text

    east_asian = language in {"zh-Hans", "zh-Hant", "ja", "ko"}

    def convert_east_asian_full(match: re.Match) -> str:
        year, month, day = map(int, match.groups())
        if not 1 <= month <= 12 or not 1 <= day <= 31:
            return match.group(0)
        return f" {year:04d}-{month:02d}-{day:02d} "

    if east_asian:
        text = re.sub(
            r"\b(\d{4})[/.](\d{1,2})[/.](\d{1,2})\b",
            convert_east_asian_full,
            text,
        )

    def convert(match: re.Match) -> str:
        first, separator, second = int(match.group(1)), match.group(2), int(match.group(3))
        month, day = (first, second) if east_asian else (second, first)
        year = int(match.group(4)) if match.group(4) else None
        if not 1 <= month <= 12 or not 1 <= day <= 31:
            return match.group(0)
        if year:
            return f" {year:04d}-{month:02d}-{day:02d} "
        if separator == "." or (first <= 12 and second <= 12):
            return match.group(0)
        return f" {_MONTHS[month - 1]} {day} "

    return re.sub(r"\b(\d{1,2})([/.])(\d{1,2})(?:\2(\d{4}))?\b", convert, text)


def normalize_quick_add(text: str, language: str = "en") -> str:
    """Normalize only deterministic locale syntax; unrecognized owner text stays untouched."""

    canonical = normalize_language(language)
    normalized = str(text or "").translate(_DIGITS)
    if canonical in {"zh-Hans", "zh-Hant", "ja", "ko"}:
        normalized = _normalize_east_asian_dates(normalized)
    normalized = _normalize_numeric_date(normalized, canonical)
    normalized = _normalize_named_dates(normalized, canonical)
    normalized = _normalize_times(normalized, canonical)
    normalized = _replace_phrases(normalized, canonical)
    return re.sub(r"\s+", " ", normalized).strip()
