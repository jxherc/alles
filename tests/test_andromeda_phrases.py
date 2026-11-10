"""the same tool question asked many ways opens the same card.

nov 10: the owner searched 多伦多天气 and 东京现在几点 and got no card. of 293 natural ways to ask
for a card (english long forms, chinese, japanese, korean, spanish, french) the english
patterns found 147. this table is those phrases: every one must open its card, and every plain
search below must stay a search.
"""

import asyncio
import unittest
from unittest import mock

from services import andromeda_answers, andromeda_phrases

detect = andromeda_answers.detect

CARDS = {
    "weather": (
        "weather toronto",
        "toronto weather",
        "tokyo weather tomorrow",
        "weather in tokyo tomorrow",
        "weather tomorrow",
        "weather",
        "will it rain tomorrow",
        "will it rain in toronto tomorrow",
        "is it going to snow in toronto",
        "toronto forecast this weekend",
        "temperature in toronto",
        "toronto temperature",
        "how cold is it in toronto",
        "toronto 7 day forecast",
        "weather this weekend",
        "is it raining in vancouver",
        "what's the weather like in shenzhen",
        "whats the weather",
        "how hot is it in dubai",
        "toronto weather today",
        "weather toronto tonight",
        "do i need an umbrella today",
        "snow forecast toronto",
        "hourly weather toronto",
        "多伦多天气",
        "多伦多的天气",
        "多伦多明天天气",
        "多伦多天气预报",
        "今天天气",
        "明天天气怎么样",
        "深圳气温",
        "北京今天多少度",
        "明天会下雨吗",
        "多倫多天氣",
        "天气",
        "东京 天气",
        "東京 天気",
        "東京の天気",
        "clima en toronto",
        "tiempo en madrid",
        "météo paris",
        "meteo toronto",
    ),
    "time": (
        "time in tokyo",
        "tokyo time",
        "what time is it in london",
        "current time in beijing",
        "tokyo time now",
        "time difference toronto tokyo",
        "time difference between toronto and beijing",
        "utc time",
        "3pm est in pst",
        "9am toronto time in beijing",
        "est to pst",
        "what time is it in toronto right now",
        "local time shenzhen",
        "time zone toronto",
        "10am pst to est",
        "time in new york",
        "london time",
        "东京现在几点",
        "东京时间",
        "北京时间",
        "多伦多和北京时差",
        "纽约几点了",
        "多伦多现在时间",
        "伦敦现在几点钟",
        "北京时间现在几点",
        "東京 時間",
        "hora en tokio",
        "heure à tokyo",
    ),
    "clock": (
        "what time is it",
        "time now",
        "current time",
        "现在几点",
        "今何時",
    ),
    "currency": (
        "100 usd to cad",
        "usd to cad",
        "100 dollars in yuan",
        "$100 in cad",
        "100 cad in rmb",
        "usd cad",
        "100 usd cny",
        "how much is 100 usd in cad",
        "what is 100 usd in cad",
        "5000 yen to cad",
        "100 hkd to cny",
        "euro to dollar",
        "1 usd in cad",
        "cad to cny exchange rate",
        "100 canadian dollars to us dollars",
        "convert 250 cad to usd",
        "usd to rmb",
        "1000 rmb in cad",
        "100美元等于多少人民币",
        "100美元换人民币",
        "美元兑人民币",
        "美元人民币汇率",
        "100加元是多少人民币",
        "1万日元多少人民币",
        "100刀多少人民币",
        "加币兑人民币",
        "人民币兑美元",
        "100港币等于多少人民币",
        "1美元多少加元",
        "美元汇率",
        "100ドルは何円",
        "100 dolares a pesos mexicanos",
        "100 euros en dollars",
    ),
    "units": (
        "5 ft 11 in cm",
        "5'11 in cm",
        "5'11\" to cm",
        "5 foot 11 in cm",
        "180 lb to kg",
        "180 pounds in kg",
        "how many kg is 180 lb",
        "what is 180 lbs in kg",
        "70 f to c",
        "70 fahrenheit in celsius",
        "100 km to miles",
        "how many feet in a mile",
        "1 cup in ml",
        "2 tbsp to ml",
        "10 oz to grams",
        "6 feet in cm",
        "175 cm in feet",
        "100 mph in kmh",
        "1 gb in mb",
        "500 ml to cups",
        "30 c to f",
        "1.5 l to oz",
        "5 feet 11 inches in cm",
        "how tall is 180 cm in feet",
        "175cm to ft",
        "72 inches in feet",
        "how many ounces in a pound",
        "1 mile in km",
        "100 f in c",
        "350 f to c",
        "how many ml in a cup",
        "2 hours in minutes",
        "how many seconds in a day",
        "10 kg in lbs",
        "60 mph to km/h",
        "180磅是多少公斤",
        "5英尺11英寸是多少厘米",
        "100公里等于多少英里",
        "30摄氏度是多少华氏度",
        "一磅等于多少克",
        "180cm是多少英尺",
        "1英里等于多少公里",
        "10公斤是多少磅",
        "1米等于多少英尺",
        "100华氏度等于多少摄氏度",
        "1加仑等于多少升",
        "5尺11寸多少厘米",
    ),
    "calc": (
        "15% of 230",
        "sqrt(144) + 3^2",
        "2^10",
        "5!",
        "what is 20% of 80",
        "230 * 1.13",
        "(5+3)*2",
        "1/3 + 1/6",
        "log(100)",
        "e^2",
        "15 percent of 230",
        "square root of 144",
        "3 squared",
        "2 to the power of 10",
        "12 times 12",
        "100 divided by 7",
        "230 plus 13%",
        "half of 230",
        "what is 12 x 12",
        "1000 / 12",
        "5 + 5",
        "cube root of 27",
        "230 minus 15%",
        "7 factorial",
        "sin(30 degrees)",
        "10 mod 3",
        "what's 15 times 4",
        "15%的230是多少",
        "230的15%",
        "1+1等于几",
        "根号144",
        "2的10次方",
        "12乘以12",
        "100除以7",
        "3的平方",
        "12乘12等于多少",
        "8折 230",
    ),
    "percent": ("20% off 80",),
    "define": (
        "define ubiquitous",
        "serendipity meaning",
        "what does ubiquitous mean",
        "ubiquitous definition",
        "synonym for happy",
        "meaning of ephemeral",
        "what is the meaning of ephemeral",
        "pronounce worcestershire",
        "ephemeral synonym",
        "opposite of happy",
        "how to pronounce niche",
        "definition of irony",
        "whats the meaning of ubiquitous",
        "what's another word for happy",
        "ubiquitous meaning in english",
        "is irregardless a word",
        "etymology of quarantine",
        "bonjour meaning",
    ),
    "spell": ("how do you spell definitely",),
    "translate": (
        "how to say thank you in japanese",
        "thank you in japanese",
        "translate hello to french",
        "hello in chinese",
        "what is 你好 in english",
        "你好 in english",
        "translate 你好",
        "女孩的英文",
        "你好用日语怎么说",
        "serendipity是什么意思",
        "苹果英文怎么说",
        "ubiquitous 中文",
        "ubiquitous的意思",
        "how do you say water in spanish",
        "谢谢的日语",
        "gracias in english",
        "what does 加油 mean",
        "加油 meaning",
        "你好 英语",
        "谢谢 日文怎么说",
        "english to chinese",
        "翻译 hello world",
        "hello world 翻译",
    ),
    "date": (
        "days until christmas",
        "how many days until december 25",
        "what day of the week is nov 20 2026",
        "30 days from today",
        "what day is it",
        "what is today's date",
        "weeks until june 1",
        "how many days between nov 10 and dec 25",
        "90 days from now",
        "what day was november 5 2026",
        "距离圣诞节还有多少天",
        "今天星期几",
        "今天几号",
        "30天后是几号",
        "今天是几月几号",
    ),
    "timer": (
        "timer 5 minutes",
        "set a timer for 10 minutes",
        "5 minute timer",
        "stopwatch",
        "计时器 5分钟",
        "倒计时10分钟",
        "5分钟计时器",
    ),
    "random": (
        "flip a coin",
        "roll a dice",
        "random number 1-100",
        "pick a number between 1 and 10",
        "抛硬币",
        "掷骰子",
        "随机数",
    ),
    "color": (
        "#ff0000",
        "rgb(255,0,0)",
        "color picker",
    ),
}

# words that look like a tool question and are something else
SEARCHES = (
    "toronto",
    "python tutorial",
    "沙底下一个女",
    "商务英语",
    "学英语",
    "天气之子",
    "time magazine",
    "weather girls",
    "the weeknd",
    "苹果是什么意思",
    "时间简史",
    "in the heights",
    "to be or not to be",
    "5 feet apart",
    "人民币",
    "英语",
    "times new roman",
    "weatherproof jacket",
    "the meaning of life",
    "timer resolution windows",
    "一万小时定律",
    "美元指数",
    "计算机",
    "翻译官",
    "北京",
)


class PhraseTableTest(unittest.TestCase):
    def test_every_way_of_asking_opens_its_card(self):
        for kind, phrases in CARDS.items():
            for phrase in phrases:
                with self.subTest(kind=kind, phrase=phrase):
                    found = detect(phrase)
                    self.assertEqual(found and found["kind"], kind)

    def test_a_plain_search_stays_a_search(self):
        for phrase in SEARCHES:
            with self.subTest(phrase=phrase):
                self.assertIsNone(detect(phrase))

    def test_the_card_gets_what_was_asked(self):
        cases = {
            "多伦多明天天气": {"kind": "weather", "place": "toronto"},
            "成都天气": {"kind": "weather", "place": "成都"},
            "東京の天気": {"kind": "weather", "place": "tokyo"},
            "will it rain in vancouver tomorrow": {"kind": "weather", "place": "vancouver"},
            "今天天气": {"kind": "weather", "place": ""},
            "100美元等于多少人民币": {
                "kind": "currency",
                "amount": 100.0,
                "from": "usd",
                "to": "cny",
            },
            "1万日元多少人民币": {
                "kind": "currency",
                "amount": 10000.0,
                "from": "jpy",
                "to": "cny",
            },
            "一百加元是多少美元": {"kind": "currency", "amount": 100.0, "from": "cad", "to": "usd"},
            "100 usd cny": {"kind": "currency", "amount": 100.0, "from": "usd", "to": "cny"},
            "180磅是多少公斤": {"kind": "units", "amount": 180.0, "from": "lb", "to": "kg"},
            "5 ft 11 in cm": {"kind": "units", "amount": 71.0, "from": "in", "to": "cm"},
            "5'11\" to cm": {"kind": "units", "amount": 71.0, "from": "in", "to": "cm"},
            "5英尺11英寸是多少厘米": {"kind": "units", "amount": 71.0, "from": "in", "to": "cm"},
            "how many kg is 180 lb": {"kind": "units", "amount": 180.0, "from": "lb", "to": "kg"},
            "1.5 l to oz": {"kind": "units", "amount": 1.5, "from": "l", "to": "floz"},
            "东京现在几点": {"kind": "time", "place": "tokyo", "zone": "Asia/Tokyo"},
            "time in markham": {"kind": "time", "place": "markham", "zone": ""},
            "距离圣诞节还有多少天": {
                "kind": "date",
                "mode": "until",
                "day": "christmas",
                "live": False,
            },
            "倒计时10分钟": {"kind": "timer", "mode": "timer", "seconds": 600, "start": True},
        }
        for phrase, want in cases.items():
            with self.subTest(phrase=phrase):
                self.assertEqual(detect(phrase), want)

    def test_arithmetic_in_words_is_worked_out(self):
        for phrase, value in (
            ("12 times 12", 144),
            ("100 divided by 8", 12.5),
            ("15 percent of 230", 34.5),
            ("230 plus 13%", 259.9),
            ("230 minus 15%", 195.5),
            ("square root of 144", 12),
            ("2 to the power of 10", 1024),
            ("3 squared", 9),
            ("half of 230", 115),
            ("5!", 120),
            ("7 factorial", 5040),
            ("e^2", 7.389056),
            ("15%的230是多少", 34.5),
            ("230的15%", 34.5),
            ("1+1等于几", 2),
            ("根号144", 12),
            ("2的10次方", 1024),
            ("12乘以12", 144),
            ("100除以8", 12.5),
            ("230打8折", 184),
        ):
            with self.subTest(phrase=phrase):
                found = detect(phrase)
                self.assertEqual(found and found["kind"], "calc")
                self.assertAlmostEqual(andromeda_answers.calculate(found["expression"]), value, 5)
        self.assertIsNone(andromeda_answers.calculate("factorial(171)"))
        self.assertIsNone(andromeda_answers.calculate("factorial(2.5)"))

    def test_numbers_written_in_chinese(self):
        for text, value in (
            ("1万", "10000"),
            ("1.5万", "15000"),
            ("一百", "100"),
            ("两百五十", "250"),
            ("三千", "3000"),
            ("十", "10"),
            ("二十三", "23"),
            ("一万两千", "12000"),
            ("2.5", "2.5"),
            ("abc", ""),
        ):
            with self.subTest(text=text):
                self.assertEqual(andromeda_phrases.number(text), value)

    def test_a_clock_time_is_read_in_another_zone(self):
        found = detect("3pm est in pst")
        self.assertEqual(
            (found["zone"], found["other_zone"], found["at"]),
            ("America/New_York", "America/Los_Angeles", "15:00"),
        )
        self.assertEqual(detect("9:30 toronto time in beijing")["at"], "09:30")
        self.assertEqual(detect("12am pst to est")["at"], "00:00")
        card = asyncio.run(andromeda_answers.resolve(found))
        self.assertEqual((card["at"], card["difference_hours"]), ("15:00", -3.0))
        self.assertIn("T15:00:00", card["at_iso"])
        # two places with "to" between them are a trip unless a zone or the word time says otherwise
        self.assertIsNone(detect("toronto to beijing"))
        self.assertEqual(detect("toronto to beijing time")["other_zone"], "Asia/Shanghai")
        self.assertEqual(detect("est to pst")["other_zone"], "America/Los_Angeles")

    def test_a_place_the_table_does_not_know_is_looked_up_in_its_own_script(self):
        self.assertIn("language=zh", andromeda_answers._place_query("成都"))
        self.assertIn("language=ja", andromeda_answers._place_query("さっぽろ"))
        self.assertNotIn("language", andromeda_answers._place_query("markham"))
        answer = {"results": [{"name": "Markham", "timezone": "America/Toronto"}]}
        with mock.patch.object(
            andromeda_answers, "_get_json", new=mock.AsyncMock(return_value=answer)
        ) as ask:
            card = asyncio.run(andromeda_answers.resolve(detect("time in markham")))
        self.assertEqual((card["zone"], card["status"]), ("America/Toronto", "ok"))
        ask.assert_awaited_once()
        # no such place, or the lookup down: no card, the search stays a search
        with mock.patch.object(
            andromeda_answers, "_get_json", new=mock.AsyncMock(return_value={"results": []})
        ):
            self.assertIsNone(asyncio.run(andromeda_answers.resolve(detect("time in a bottle"))))
        with mock.patch.object(
            andromeda_answers, "_get_json", new=mock.AsyncMock(side_effect=OSError("down"))
        ):
            self.assertIsNone(asyncio.run(andromeda_answers.resolve(detect("time in markham"))))
