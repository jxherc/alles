"""the same question in other words.

andromeda's tool cards (weather, time, currency, units, calculator, dictionary, dates, timer)
are found by short english patterns in andromeda_answers. people ask in chinese, japanese,
korean, spanish and french, and in longer english: "多伦多明天天气", "100美元等于多少人民币",
"what is 180 lbs in kg", "5'11 in cm", "12 times 12", "東京の天気". plain() rewrites what was
typed into the short form those patterns know, or returns None when it is no tool question.

pure text work: nothing leaves the machine, and a search that is not a tool question is not
touched (天气之子 is a film, 时间简史 a book, 人民币 a word to search).
"""

from __future__ import annotations

import re
import unicodedata

from services.units import find as _unit

# ── numbers ──
_ZH_DIGITS = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "兩": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}
_ZH_SMALL = {"十": 10, "百": 100, "千": 1000}
_ZH_BIG = {"万": 10_000, "萬": 10_000, "亿": 100_000_000, "億": 100_000_000}
_NUM = r"(?:\d[\d,]*(?:\.\d+)?\s*[万萬千百亿億]?|[零〇一二两兩三四五六七八九十百千万萬亿億]+)"


def number(text: str) -> str:
    """ "1万" is 10000, "一百五十" is 150, "2.5" stays 2.5; "" when it is no number."""
    text = str(text or "").replace(",", "").replace(" ", "")
    if not text:
        return ""
    mixed = re.fullmatch(r"(\d+(?:\.\d+)?)([万萬千百亿億]?)", text)
    if mixed:
        value = float(mixed[1]) * ({**_ZH_SMALL, **_ZH_BIG}.get(mixed[2], 1))
        return str(int(value)) if value.is_integer() else str(value)
    if not all(c in _ZH_DIGITS or c in _ZH_SMALL or c in _ZH_BIG for c in text):
        return ""
    total = section = digit = 0
    for char in text:
        if char in _ZH_DIGITS:
            digit = _ZH_DIGITS[char]
        elif char in _ZH_SMALL:
            section += (digit or 1) * _ZH_SMALL[char]
            digit = 0
        else:
            total += (section + digit or 1) * _ZH_BIG[char]
            section = digit = 0
    return str(total + section + digit)


# ── places: the names big cities go by in the app's other languages ──
PLACES = {
    "beijing": "北京 北平 pekín pekin pékin ペキン 베이징 بكين",
    "shanghai": "上海 シャンハイ 상하이",
    "shenzhen": "深圳",
    "guangzhou": "广州 廣州",
    "hong kong": "香港 홍콩",
    "taipei": "台北 臺北",
    "tokyo": "东京 東京 tokio とうきょう 도쿄 طوكيو",
    "osaka": "大阪 오사카",
    "seoul": "首尔 首爾 汉城 ソウル 서울 seúl séoul",
    "singapore": "新加坡 シンガポール 싱가포르 singapur singapour",
    "bangkok": "曼谷 バンコク 방콕",
    "dubai": "迪拜 杜拜 ドバイ 두바이 dubái dubaï دبي",
    "london": "伦敦 倫敦 londres ロンドン 런던 لندن",
    "paris": "巴黎 parís パリ 파리 باريس",
    "berlin": "柏林 berlín ベルリン 베를린",
    "rome": "罗马 羅馬 roma ローマ 로마",
    "madrid": "马德里 馬德里 マドリード 마드리드",
    "moscow": "莫斯科 moscú moscou モスクワ 모스크바",
    "amsterdam": "阿姆斯特丹 ámsterdam アムステルダム",
    "istanbul": "伊斯坦布尔 伊斯坦堡 estambul イスタンブール",
    "new york": "纽约 紐約 nueva york ニューヨーク 뉴욕 نيويورك",
    "los angeles": "洛杉矶 洛杉磯 ロサンゼルス 로스앤젤레스 los ángeles",
    "san francisco": "旧金山 舊金山 三藩市 サンフランシスコ 샌프란시스코",
    "seattle": "西雅图 西雅圖 シアトル 시애틀",
    "chicago": "芝加哥 シカゴ 시카고",
    "boston": "波士顿 波士頓 ボストン 보스턴",
    "toronto": "多伦多 多倫多 トロント 토론토 تورنتو",
    "vancouver": "温哥华 溫哥華 バンクーバー 밴쿠버",
    "montreal": "蒙特利尔 蒙特婁 montréal モントリオール 몬트리올",
    "ottawa": "渥太华 渥太華 オタワ 오타와",
    "sydney": "悉尼 雪梨 sídney シドニー 시드니",
    "melbourne": "墨尔本 墨爾本 メルボルン 멜버른",
    "mumbai": "孟买 孟買 ムンバイ 뭄바이",
    "delhi": "德里 新德里 デリー 델리",
    "china": "中国 中國",
    "japan": "日本 japón japon 일본",
    "korea": "韩国 韓國 corea corée 한국",
    "uk": "英国 英國 reino unido royaume-uni イギリス 영국",
    "france": "法国 法國 francia フランス 프랑스",
    "germany": "德国 德國 alemania allemagne ドイツ 독일",
    "spain": "西班牙 españa espagne スペイン 스페인",
    "italy": "意大利 義大利 italia italie イタリア 이탈리아",
    "india": "印度 インド 인도 inde",
    "australia": "澳大利亚 澳洲 澳大利亞 オーストラリア 호주 australie",
}
_PLACE_EN = {alias: name for name, aliases in PLACES.items() for alias in aliases.split(" ")}
_PLACE_EN |= {"nueva york": "new york", "reino unido": "uk", "los ángeles": "los angeles"}


def place(text: str) -> str:
    """the english name of a big city or country, or the name as typed (the weather and time
    cards look an unknown place up in the script it is written in)."""
    text = re.sub(r"\s+", " ", str(text or "").strip().strip("的の"))
    return _PLACE_EN.get(text.lower(), text)


# ── day words ──
_DAYS = {
    "today": "今天 今日 hoy aujourd'hui 오늘",
    "tomorrow": "明天 明日 mañana manana demain 내일 明早",
    "tonight": "今晚 今夜 esta noche ce soir",
    "now": "现在 現在 当前 目前 ahora maintenant 지금",
    "this week": "本周 这周 這週 本週 这个星期 一周 一週 esta semana cette semaine 今週",
    "this weekend": "周末 週末 这个周末 這個週末 este fin de semana ce week-end",
}
_DAY_EN = {alias: name for name, aliases in _DAYS.items() for alias in aliases.split(" ")}
for _name, _aliases in (
    ("tonight", ("esta noche", "ce soir")),
    ("this week", ("esta semana", "cette semaine")),
    ("this weekend", ("este fin de semana", "ce week-end")),
):
    for _alias in _aliases:
        _DAY_EN[_alias] = _name
_ZH_DAY = "今天|明天|后天|後天|今晚|今夜|明早|现在|現在|本周|这周|這週|本週|这个周末|這個週末|周末|週末|一周|一週"
_EN_DAY = r"today|tomorrow|tonight|now|right now|this week|this weekend|next week|hourly|weekly"

# ── weather ──
_ZH_WEATHER = re.compile(
    rf"^(?P<place>.*?)\s*的?(?P<day>{_ZH_DAY})?的?\s*"
    r"(?:天气预报|天氣預報|天气|天氣|气温|氣溫|温度|溫度)"
    r"(?:预报|預報|怎么样|怎麼樣|怎样|怎樣|如何|情况|情況|好吗|好嗎)?$"
)
_ZH_WEATHER_ASK = re.compile(
    rf"^(?P<place>.*?)\s*(?P<day>{_ZH_DAY})?\s*(?P<ask>多少度|几度|幾度|冷吗|冷嗎|热吗|熱嗎|冷不冷|热不热|熱不熱|"
    r"(?P<will>会|會|要)?(?:不会|不會)?下(?:雨|雪)(?P<q>吗|嗎|么|麼)?)$"
)
_OTHER_WEATHER = (
    # japanese, korean
    re.compile(r"^(?P<place>.+?)\s*の?(?P<day>今日|明日|今夜|週末)?の?\s*(?:天気予報|天気|気温)$"),
    re.compile(r"^(?P<place>.+?)\s*(?P<day>오늘|내일)?\s*(?:날씨|기온)$"),
    # spanish, french
    re.compile(
        r"^(?:el |la )?(?:clima|tiempo|pronóstico|pronostico|temperatura)(?: en| de| para)? "
        r"(?P<place>.+?)(?: (?P<day>hoy|mañana|manana|esta noche|esta semana))?$"
    ),
    re.compile(
        r"^(?:la )?(?:météo|meteo|température)(?: à| a| de| pour| en| au)? "
        r"(?P<place>.+?)(?: (?P<day>aujourd'hui|demain|ce soir|cette semaine))?$"
    ),
    # arabic
    re.compile(r"^(?:ال)?طقس(?: في)? (?P<place>.+)$"),
    re.compile(r"^(?P<place>.+) (?:ال)?طقس$"),
)
# english: the longer ways of asking for the same card
_EN_WEATHER = (
    re.compile(
        r"^(?:what(?:'s| is|s) )?(?:the )?(?:weather|forecast|weather forecast)(?: like)?"
        rf"(?: (?P<day1>{_EN_DAY}))?(?: (?:in|for|at) (?P<place>.+?))?(?: (?P<day>{_EN_DAY}))?$"
    ),
    re.compile(
        r"^(?:is it|will it|is it going to|does it|will it be) "
        r"(?:rain|raining|snow|snowing|sunny|cold|hot|warm|windy|cloudy|be (?:cold|hot|sunny|rainy))"
        rf"(?: (?:in|at) (?P<place>.+?))?(?: (?P<day>{_EN_DAY}))?(?: (?:in|at) (?P<place2>.+))?$"
    ),
    re.compile(
        rf"^how (?:cold|hot|warm) (?:is it|will it be)(?: (?:in|at) (?P<place>.+?))?(?: (?P<day>{_EN_DAY}))?$"
    ),
    re.compile(
        rf"^do i need (?:an umbrella|a jacket|a coat)(?: (?P<day>{_EN_DAY}))?(?: in (?P<place>.+))?$"
    ),
    re.compile(
        r"^(?:(?P<pre>hourly|weekly|snow|rain|\d+ day) )?(?:weather|forecast)(?: forecast)? "
        rf"(?P<place>.+?)(?: (?P<day>{_EN_DAY}))?$"
    ),
    re.compile(
        rf"^(?P<place>.+?) (?:(?:\d+ day|hourly|weekly|snow|rain) )?(?:weather|forecast|weather forecast|temperature|temp)"
        rf"(?: forecast)?(?: (?P<day>{_EN_DAY}))?$"
    ),
    re.compile(rf"^(?P<place>.+?) (?:forecast|weather) (?:for )?(?P<day>{_EN_DAY})$"),
)
# words that follow "weather" and are not a place
NOT_PLACES = frozenset(
    "girls channel network underground app apps radar map maps station stations balloon vane "
    "report reports forecast stripping proof man woman alert alerts warning warnings icon icons "
    "symbols api widget satellite model models patterns vs and or the a".split()
)


def _weather(low: str) -> str:
    for pattern in (_ZH_WEATHER, _ZH_WEATHER_ASK):
        found = pattern.fullmatch(low)
        if not found:
            continue
        where, day = found["place"].strip(), found["day"] or ""
        if pattern is _ZH_WEATHER_ASK and "下" in found["ask"]:
            # 下雨 alone is a word to search; with a place, a day or a question it asks the sky
            if not (where or day or found["will"] or found["q"]):
                continue
        if where in ("今天的", "明天的") or len(where) > 20:
            continue
        return " ".join(part for part in ("weather", place(where), _DAY_EN.get(day, "")) if part)
    for pattern in _OTHER_WEATHER:
        found = pattern.fullmatch(low)
        if found:
            day = found.groupdict().get("day") or ""
            return " ".join(
                part for part in ("weather", place(found["place"]), _DAY_EN.get(day, "")) if part
            )
    for pattern in _EN_WEATHER:
        found = pattern.fullmatch(low)
        if not found:
            continue
        groups = found.groupdict()
        where = (groups.get("place") or groups.get("place2") or "").strip()
        where = re.sub(rf"\b(?:{_EN_DAY})\b", "", where).strip()
        if where.split(" ")[0] in NOT_PLACES or where.split(" ")[-1] in NOT_PLACES:
            return ""
        day = groups.get("day") or groups.get("day1") or ""
        return " ".join(part for part in ("weather", where, day) if part)
    return ""


# ── time ──
_NOW_WORDS = ("现在", "現在", "当前", "目前", "今天", "此刻")
_ZH_CLOCK = re.compile(
    r"^(?:现在|現在|目前|当前)?是?(?:几点了?|幾點了?|几点钟|幾點鐘|什么时间|什麼時間|时间|時間)$"
)
_ZH_TIME = re.compile(
    r"^(?P<place>.+?)\s*的?(?:现在|現在|当地|當地|目前)?的?\s*"
    r"(?:时间|時間|几点钟|幾點鐘|几点了|幾點了|几点|幾點|是几点|是幾點)"
    r"(?:现在|現在)?(?:是)?(?:几点了?|幾點了?|几点钟|多少)?$"
)
_ZH_DIFFERENCE = re.compile(
    r"^(?P<a>.+?)\s*(?:和|跟|与|與|同|到)\s*(?P<b>.+?)\s*的?(?:时差|時差)(?:是多少|多少)?$"
)
_OTHER_TIME = (
    re.compile(r"^(?:qué |que )?hora (?:es )?en (?P<place>.+)$"),
    re.compile(r"^(?:quelle )?heure (?:est-il |est il )?(?:à|a|au|en) (?P<place>.+)$"),
    re.compile(r"^(?P<place>.+?)\s*の?(?:現在)?(?:の)?(?:時間|時刻|今何時|は今何時|何時)$"),
    re.compile(r"^(?P<place>.+?)\s*(?:현재 )?(?:시간|몇 ?시)$"),
    re.compile(
        r"^(?:what(?:'s| is) the )?(?:current |local )?time (?:zone )?(?:is it )?(?:in |at |for )?(?P<place>.+?)"
        r"(?: right now| now)?$"
    ),
    re.compile(r"^what time is it (?:in|at) (?P<place>.+?)(?: right now| now)?$"),
    re.compile(
        r"^(?:local time|time zone|timezone|current time|time now) (?:in |of |for )?(?P<place>.+)$"
    ),
)
_OTHER_CLOCK = re.compile(
    r"^(?:今何時|今何時ですか|지금 ?몇 ?시|qué hora es|que hora es|quelle heure est-il)$"
)


def _time(low: str) -> str:
    if _ZH_CLOCK.fullmatch(low) or _OTHER_CLOCK.fullmatch(low):
        return "what time is it" if low not in ("时间", "時間") else ""
    found = _ZH_DIFFERENCE.fullmatch(low)
    if found:
        return f"time difference between {place(found['a'])} and {place(found['b'])}"
    found = re.fullmatch(r"time difference (?:between )?(.+?) (?:and |to |vs )?(\S+(?: \S+)?)", low)
    if found and " and " not in low and " to " not in low:
        return f"time difference between {found[1]} and {found[2]}"
    found = _ZH_TIME.fullmatch(low)
    if found and found["place"].strip() not in _NOW_WORDS and len(found["place"]) <= 12:
        return f"time in {place(found['place'])}"
    for pattern in _OTHER_TIME:
        found = pattern.fullmatch(low)
        if found:
            where = place(found["place"])
            # english "x time" stays with the table of zones in andromeda_answers
            if where != found["place"].strip() or pattern.pattern.startswith(
                ("^(?:qué", "^(?:quelle", "^what time", "^(?:local")
            ):
                return f"time in {where}"
    return ""


# ── money ──
MONEY = {
    "usd": "美元 美金 美刀 刀 ドル 달러 dólares dolares dólar dolar dollars",
    "cny": "人民币 人民幣 元 块 塊 块钱 塊錢 rmb 人民元 위안 yuanes",
    "cad": "加元 加币 加幣 加拿大元 加拿大币 加刀 カナダドル dólares canadienses dollars canadiens",
    "hkd": "港币 港元 港幣 香港ドル",
    "jpy": "日元 日圆 日圓 日币 日幣 円 엔 yenes yens",
    "eur": "欧元 歐元 ユーロ 유로 euros",
    "gbp": "英镑 英鎊 ポンド 파운드 libras livres",
    "krw": "韩元 韓元 韩币 韓幣 ウォン 원",
    "aud": "澳元 澳币 澳幣 豪ドル",
    "twd": "新台币 新台幣 台币 台幣",
    "sgd": "新加坡元 新币 新幣 坡币",
    "inr": "卢比 盧比 ルピー",
    "thb": "泰铢 泰銖",
    "mxn": "pesos mexicanos peso mexicano 墨西哥比索",
    "chf": "瑞士法郎 瑞郎",
}
_MONEY_CODE = {}
for _code, _names in MONEY.items():
    for _alias in _names.split(" "):
        _MONEY_CODE[_alias] = _code
_MONEY_CODE |= {
    "pesos mexicanos": "mxn",
    "peso mexicano": "mxn",
    "dólares canadienses": "cad",
    "dollars canadiens": "cad",
}
_CUR = (
    "(?:"
    + "|".join(sorted((re.escape(k) for k in _MONEY_CODE), key=len, reverse=True))
    + "|[a-z]{3})"
)
_ZH_MONEY = re.compile(
    rf"^(?P<amount>{_NUM})?\s*(?P<a>{_CUR})\s*"
    r"(?:等于|等於|是|换成|換成|换|換|兑换|兌換|兑|兌|对|對|折合|合|=|to|は|を|a|en|para|vers)?\s*"
    r"(?:多少|几|幾|何|いくら)?\s*"
    rf"(?P<b>{_CUR})?\s*的?(?P<rate>汇率|匯率|是多少|多少钱|多少錢|レート|환율)?$"
)


def _money(low: str) -> str:
    found = _ZH_MONEY.fullmatch(low)
    if not found:
        return ""
    a, b = found["a"], found["b"]
    foreign = a in _MONEY_CODE or (b or "") in _MONEY_CODE
    if not foreign or not (b or found["rate"]):
        return ""  # two latin codes are english, handled there; one name alone is a word
    source = _MONEY_CODE.get(a, a)
    target = _MONEY_CODE.get(b, b) if b else ("usd" if source == "cny" else "cny")
    amount = number(found["amount"] or "") or "1"
    if (
        source == target
        or not re.fullmatch(r"[a-z]{3}", source + "")
        or not re.fullmatch(r"[a-z]{3}", target)
    ):
        return ""
    return f"{amount} {source} to {target}"


# ── units ──
UNIT_WORDS = {
    "lb": "磅 英磅 ポンド 파운드 libras livres",
    "kg": "公斤 千克 キロ キログラム 킬로그램 kilos kilo",
    "g": "克 公克 グラム 그램 gramos grammes",
    "oz": "盎司 オンス onzas onces",
    "ft": "英尺 尺 呎 フィート 피트 pies pieds",
    "in": "英寸 寸 吋 インチ 인치 pulgadas pouces",
    "cm": "厘米 公分 センチ センチメートル 센티미터 centímetros centimetros centimètres",
    "mm": "毫米 ミリ",
    "m": "米 公尺 メートル 미터 metros mètres",
    "km": "公里 千米 キロメートル 킬로미터 kilómetros kilometros kilomètres",
    "mi": "英里 哩 マイル 마일 millas milles",
    "c": "摄氏度 攝氏度 摄氏 攝氏 ℃ 度 celsius",
    "f": "华氏度 華氏度 华氏 華氏 ℉ fahrenheit",
    "l": "升 公升 リットル 리터 litros litres",
    "ml": "毫升 ミリリットル",
    "gal": "加仑 加侖 ガロン galones gallons",
    "h": "小时 小時 钟头 時間 horas heures",
    "min": "分钟 分鐘 分 minutos",
    "s": "秒 秒钟 秒鐘 segundos secondes",
}
_UNIT_KEY = {alias: key for key, names in UNIT_WORDS.items() for alias in names.split(" ")}
_UNIT_NAME = (
    "(?:"
    + "|".join(sorted((re.escape(k) for k in _UNIT_KEY), key=len, reverse=True))
    + "|[a-z°/]{1,12})"
)
_ZH_UNITS = re.compile(
    rf"^(?P<amount>{_NUM})\s*(?P<a>{_UNIT_NAME})(?:\s*(?P<amount2>{_NUM})\s*(?P<a2>{_UNIT_NAME}))?\s*"
    r"(?:等于|等於|是|换算成|換算成|换成|換成|合|=|to|は|a|en|son)?\s*(?:多少|几|幾|何|cuántos|cuantos|combien de)?\s*个?個?"
    rf"(?P<b>{_UNIT_NAME})$"
)
_FEET_INCHES = re.compile(
    r"^(?P<feet>\d+)\s*(?:'|′|ft|foot|feet)\s*(?P<inches>\d+(?:\.\d+)?)\s*(?:\"|″|''|in|inch|inches)?\s*"
    r"(?:in|to|into|as|=)\s*(?P<to>[a-z]+)$"
)
_HOW_MANY = re.compile(
    r"^how (?:many|much) (?P<to>[a-z°/ ]+?) (?:is|are|in|equals?|makes?|=) (?P<amount>-?[\d.,]+)\s*(?P<from>[a-z°/ ]+)$"
)
_HOW_TALL = re.compile(
    r"^how (?:tall|long|far|heavy|big|hot|cold|much|high|wide|fast) is (?P<amount>-?[\d.,]+)\s*(?P<from>[a-z°/ ]+?) "
    r"(?:in|to|as) (?P<to>[a-z°/ ]+)$"
)


def _key(word: str) -> str:
    word = str(word or "").strip()
    return _UNIT_KEY.get(word) or _unit(word) or ""


def _units(low: str) -> str:
    found = _FEET_INCHES.fullmatch(low)
    if found and _key(found["to"]):
        inches = int(found["feet"]) * 12 + float(found["inches"])
        return f"{inches:g} in to {_key(found['to'])}"
    for pattern in (_HOW_MANY, _HOW_TALL):
        found = pattern.fullmatch(low)
        if found and _key(found["from"]) and _key(found["to"]):
            return f"{found['amount']} {_key(found['from'])} to {_key(found['to'])}"
    found = _ZH_UNITS.fullmatch(low)
    if not found:
        return ""
    words = (found["a"], found["a2"] or "", found["b"])
    if not any(word in _UNIT_KEY for word in words):
        return ""  # all latin: english, handled there
    a, b = _key(found["a"]), _key(found["b"])
    amount = number(found["amount"])
    if not (a and b and amount) or a == b:
        return ""
    if found["a2"]:
        a2, amount2 = _key(found["a2"]), number(found["amount2"])
        if (a, a2) == ("ft", "in") and amount2:
            return f"{float(amount) * 12 + float(amount2):g} in to {b}"
        return ""
    return f"{amount} {a} to {b}"


# ── arithmetic in words ──
_ZH_MATH_TAIL = re.compile(
    r"\s*(?:等于几|等於幾|等于多少|等於多少|是多少|等于|等於|得多少|是几|=\??|＝)$"
)
_MATH_HEAD = re.compile(r"^(?:what(?:'s| is|s)|calculate|calc|compute|solve|how much is)\s+")
_N = r"(\d+(?:\.\d+)?)"


def _math(low: str) -> str:
    text = _MATH_HEAD.sub("", _ZH_MATH_TAIL.sub("", low)).strip()
    if not re.search(r"\d", text):
        return ""
    before = text
    rules = (
        (rf"^{_N}\s*%\s*的\s*{_N}$", r"\1% of \2"),
        (rf"^{_N}\s*的\s*{_N}\s*%$", r"\2% of \1"),
        (rf"^{_N}\s*(?:percent|per cent|pct)\s*of\s*{_N}$", r"\1% of \2"),
        (rf"^{_N}\s*(?:plus|\+)\s*{_N}\s*(?:%|percent)$", r"\1*(1+\2/100)"),
        (rf"^{_N}\s*(?:minus|-|less)\s*{_N}\s*(?:%|percent)$", r"\1*(1-\2/100)"),
        (rf"^{_N}\s*打\s*{_N}\s*折$", r"\1*\2/10"),
        (rf"^{_N}\s*折\s*{_N}$", r"\2*\1/10"),
        (rf"^(?:a )?half of {_N}$", r"\1/2"),
        (rf"^(?:a )?third of {_N}$", r"\1/3"),
        (rf"^(?:a )?quarter of {_N}$", r"\1/4"),
        (rf"^{_N}\s*(?:factorial|!|的阶乘|的階乘)$", r"factorial(\1)"),
        (rf"(?:square root of|sqrt of|根号|根號)\s*{_N}", r"sqrt(\1)"),
        (rf"{_N}\s*(?:的平方根|开方|開方)", r"sqrt(\1)"),
        (rf"(?:cube root of)\s*{_N}", r"\1^(1/3)"),
        (rf"{_N}\s*(?:的立方根)", r"\1^(1/3)"),
        (rf"{_N}\s*(?:squared|的平方|平方)", r"\1^2"),
        (rf"{_N}\s*(?:cubed|的立方|立方)", r"\1^3"),
        (
            rf"{_N}\s*(?:to the power of|to the|raised to|的)\s*{_N}\s*(?:th power|次方|次幂)?",
            r"\1^\2",
        ),
        (rf"(sin|cos|tan)\(\s*{_N}\s*(?:degrees?|deg|°|度)\s*\)", r"\1(\2*pi/180)"),
        (r"\s*(?:multiplied by|times|乘以|乘|×|✕)\s*", "*"),
        (r"(?<=\d)\s*x\s*(?=\d)", "*"),
        (r"\s*(?:divided by|over|除以|÷)\s*", "/"),
        (r"\s*(?:plus|加上|加)\s*", "+"),
        (r"\s*(?:minus|减去|減去|减|減)\s*", "-"),
        (r"\s*(?:mod|modulo)\s*", "%"),
    )
    for pattern, into in rules:
        text = re.sub(pattern, into, text)
    return text if text != before or before != low else ""


# ── dates ──
_HOLIDAYS = {
    "christmas": "圣诞节 聖誕節 圣诞 聖誕 navidad noël noel クリスマス 크리스마스",
    "new year": "元旦 新年 año nuevo nouvel an",
    "chinese new year": "春节 春節 农历新年 農曆新年 过年 過年",
    "halloween": "万圣节 萬聖節",
    "valentine's day": "情人节 情人節",
    "thanksgiving": "感恩节 感恩節",
    "easter": "复活节 復活節",
}
_HOLIDAY_EN = {alias: name for name, names in _HOLIDAYS.items() for alias in names.split(" ")}
_MONTHS = (
    "january february march april may june july august september october november december".split()
)


def _day(text: str) -> str:
    text = text.strip()
    if text in _HOLIDAY_EN:
        return _HOLIDAY_EN[text]
    found = re.fullmatch(r"(?:(\d{4})年)?(\d{1,2})月(\d{1,2})[日号號]?", text)
    if found and 1 <= int(found[2]) <= 12:
        return f"{_MONTHS[int(found[2]) - 1]} {int(found[3])}" + (
            f" {found[1]}" if found[1] else ""
        )
    return text


def _dates(low: str) -> str:
    if re.fullmatch(r"今天是?(?:星期几|星期幾|周几|週幾|礼拜几|禮拜幾)|今日は何曜日", low):
        return "what day is it"
    if re.fullmatch(
        r"今天是?(?:几号|幾號|几月几号|幾月幾號|几月几日|幾月幾日|什么日期|什麼日期)|今天日期|今日は何日",
        low,
    ):
        return "today's date"
    found = re.fullmatch(
        r"(?:距离|距離|距|离|離)?(.+?)(?:还有|還有|还剩|還剩)(?:多少|几|幾)天|(.+?)倒计时|(.+?)倒數",
        low,
    )
    if found:
        return f"days until {_day(found[1] or found[2] or found[3])}"
    found = re.fullmatch(
        r"(\d+)\s*(天|日|周|週|星期|个星期|個星期)(?:后|後|之后|之後|以后|以後)(?:是)?(?:几号|幾號|星期几|星期幾|哪天|哪一天)?",
        low,
    )
    if found:
        return f"{found[1]} {'weeks' if found[2] not in ('天', '日') else 'days'} from today"
    found = re.fullmatch(r"(\d+)\s*(天|日)前(?:是)?(?:几号|幾號|星期几|哪天)?", low)
    if found:
        return f"{found[1]} days ago"
    found = re.fullmatch(r"(?:how many )?(weeks|months) (until|till|to|before) (.+)", low)
    if found:
        return f"days until {found[3]}"
    return ""


# ── timer, dice and the tools by name ──
_ZH_SPAN = {
    "小时": "hours",
    "小時": "hours",
    "分钟": "minutes",
    "分鐘": "minutes",
    "分": "minutes",
    "秒": "seconds",
    "秒钟": "seconds",
}
_TOOLS = {
    "calculator": "计算器 計算機 計算器 calculadora calculatrice 電卓 계산기",
    "timer": "计时器 計時器 定时器 タイマー 타이머 temporizador minuteur 倒计时 倒計時",
    "stopwatch": "秒表 碼錶 ストップウォッチ cronómetro chronomètre",
    "flip a coin": "抛硬币 拋硬幣 扔硬币 掷硬币 擲硬幣 コイントス",
    "roll a dice": "掷骰子 擲骰子 摇骰子 扔骰子 投骰子 サイコロ",
    "random number": "随机数 隨機數 随机数生成器 亂數 乱数",
    "unit converter": "单位换算 單位換算 单位转换 単位変換",
    "currency converter": "汇率换算 匯率換算 货币换算 貨幣換算 汇率计算器 為替",
    "color picker": "取色器 颜色选择器 顏色選擇器 调色板 カラーピッカー",
    "periodic table": "元素周期表 元素週期表 周期表",
    "world clock": "世界时钟 世界時鐘 世界时间",
    "dictionary": "词典 詞典 字典 辞書",
    "weather": "天气 天氣 天気 날씨",
}
_TOOL_EN = {alias: name for name, names in _TOOLS.items() for alias in names.split(" ")}


def _small(low: str) -> str:
    if low in _TOOL_EN:
        return _TOOL_EN[low]
    found = re.fullmatch(
        r"(?:计时器|計時器|倒计时|倒計時|定时|定時|计时|計時)?\s*(\d+(?:\.\d+)?)\s*(小时|小時|分钟|分鐘|分|秒钟|秒)\s*"
        r"(?:的)?(?:计时器|計時器|倒计时|倒計時|计时|計時)?",
        low,
    )
    if found and re.search(r"计时|計時|倒计时|倒計時|定时|定時", low):
        return f"timer {found[1]} {_ZH_SPAN[found[2]]}"
    return ""


# ── words ──
_HAN = r"[\u4e00-\u9fff]"
# questions people ask about these, not words they need spelled out
BIG_WORDS = frozenset(
    "life love god time art truth death happiness everything it this that".split()
)


def _words(low: str) -> str:
    found = re.fullmatch(r"(?:what(?:'s| is|s) )?the meaning of ([a-z][a-z' -]{0,40})", low)
    if found and found[1] not in BIG_WORDS:
        return f"define {found[1]}"
    found = re.fullmatch(
        r"(?:what(?:'s| is|s) )?(?:another|a different|a better) word for ([a-z][a-z' -]{0,40})",
        low,
    )
    if found:
        return f"synonyms for {found[1]}"
    found = re.fullmatch(r"([a-z][a-z'-]{0,40}) (?:meaning|definition) in english", low)
    if found:
        return f"define {found[1]}"
    found = re.fullmatch(r"is ([a-z][a-z'-]{0,40}) (?:a|a real) word", low)
    if found:
        return f"define {found[1]}"
    found = re.fullmatch(
        r"(?:etymology|origin) of (?:the word )?([a-z][a-z'-]{0,40})|([a-z][a-z'-]{0,40}) etymology",
        low,
    )
    if found:
        return f"define {found[1] or found[2]}"
    found = re.fullmatch(r"([a-z][a-z' -]{0,60})\s*的(?:意思|中文意思|含义|含義)", low)
    if found:
        return f"{found[1].strip()}是什么意思"
    found = re.fullmatch(
        rf"what does ((?:{_HAN}){{1,20}}) mean|((?:{_HAN}){{1,20}}) (?:meaning|means|in english)|meaning of ((?:{_HAN}){{1,20}})",
        low,
    )
    if found:
        return f"{found[1] or found[2] or found[3]} in english"
    return ""


_HEAD = re.compile(
    r"^(?:(?:can|could) you )?(?:please )?(?:tell me |show me )?"
    r"(?:what(?:'s| is|s) |how much is |how much are |convert |calculate )"
)
_NO_SEPARATOR = re.compile(r"^(-?[\d.,]+)\s*([a-z]{3}) ([a-z]{3})$")


def fold(text: str) -> str:
    text = unicodedata.normalize("NFKC", str(text or ""))
    text = re.sub(r"\s+", " ", text).strip().lower()
    text = text.rstrip("?？。. ").strip()
    # "5!" is a factorial, "wow!" is not
    return text if re.search(r"[0-9]!$", text) else text.rstrip("!！ ").strip()


def plain(text: str) -> list[str]:
    """other ways to write the same tool question, best first; [] when there is none."""
    low = fold(text)
    if not low or len(low) > 120:
        return []
    out = []
    for rewrite in (_small, _weather, _time, _money, _units, _dates, _words, _math):
        found = rewrite(low)
        if found and found != low:
            out.append(found)
    stripped = _HEAD.sub("", low)
    if stripped != low:
        out.append(stripped)
        out += [
            found
            for rewrite in (_units, _math)
            if (found := rewrite(stripped)) and found != stripped
        ]
    pair = _NO_SEPARATOR.fullmatch(low)
    if pair:
        out.append(f"{pair[1]} {pair[2]} to {pair[3]}")
    return list(dict.fromkeys(out))
