import asyncio
import os
from unittest import mock

from services import andromeda_answers as answers
from services.elements import ELEMENTS
from tests._client import ApiTest


def run(found, **kwargs):
    return asyncio.run(answers.resolve(found, **kwargs))


class OnlineDictionary:
    """these tests cover the online sources, so a local wiktionary copy must not answer first."""

    def setUp(self):
        super().setUp()
        patcher = mock.patch.dict(
            os.environ, {"ALLES_DICTIONARY": "/nonexistent/wiktionary.sqlite"}
        )
        patcher.start()
        self.addCleanup(patcher.stop)


class DetectTest(ApiTest):
    CASES = {
        "what is bonjour in english": ("translate", {"text": "bonjour", "to": "english"}),
        "how do you say thank you in japanese": (
            "translate",
            {"text": "thank you", "to": "japanese"},
        ),
        "define serendipity": ("define", {"word": "serendipity"}),
        "what is serendipity": ("define", {"word": "serendipity"}),
        "what is fluorine?": ("element", {"number": 9}),
        "what is 12% of 80": ("calc", {"expression": "12% of 80"}),
        "periodic table": ("periodic", {}),
        "periodic table of elements": ("periodic", {}),
        "element table": ("periodic", {}),
        "chemistry periodic table": ("periodic", {}),
        "sodium": ("element", {"number": 11}),
        "atomic number of gold": ("element", {"number": 79}),
        "12% of 80": ("calc", {}),
        "10 km in miles": ("units", {"from": "km", "to": "mi"}),
        "100 usd to cad": ("currency", {"from": "usd", "to": "cad"}),
        "time in tokyo": ("time", {"zone": "Asia/Tokyo"}),
        "toronto weather": ("weather", {"place": "toronto"}),
    }

    def test_each_kind_is_recognised(self):
        for query, (kind, fields) in self.CASES.items():
            with self.subTest(query=query):
                found = answers.detect(query)
                self.assertEqual(found["kind"], kind)
                for key, value in fields.items():
                    self.assertEqual(found[key], value)

    def test_ordinary_searches_stay_searches(self):
        for query in (
            "flights to france",
            "tailscale serve",
            "what is love",
            "what is it",
            "what is happening",
            "best laptop 2026",
            "iphone 17 in canada",
        ):
            with self.subTest(query=query):
                self.assertIsNone(answers.detect(query))


class ResolveTest(OnlineDictionary, ApiTest):
    def test_calculator_and_units_are_exact(self):
        self.assertEqual(run({"kind": "calc", "expression": "12% of 80"})["result"], "9.6")
        self.assertEqual(run({"kind": "calc", "expression": "2^10"})["result"], "1,024")
        self.assertIsNone(answers.calculate("__import__('os')"))
        self.assertIsNone(answers.calculate("9**9**9"))
        self.assertEqual(run(answers.detect("72f to c"))["result"], "22.2222")
        self.assertEqual(run(answers.detect("1 mi to km"))["result"], "1.60934")

    def test_periodic_table_is_complete(self):
        self.assertEqual([row["number"] for row in ELEMENTS], list(range(1, 119)))
        gold = run({"kind": "element", "number": 79})
        self.assertEqual(gold["selected"], 79)
        self.assertEqual(gold["elements"][78]["symbol"], "Au")

    def test_currency_weather_and_dictionary_use_their_service(self):
        replies = {
            "api.frankfurter.dev": {"date": "2026-10-19", "rates": {"CAD": 1.4074}},
            "api.datamuse.com": [{"word": "chance", "tags": ["f:40.0"]}],
            "en.wiktionary.org": {"query": {"pages": [{}]}},
            "geocoding-api.open-meteo.com": {
                "results": [
                    {
                        "name": "Toronto",
                        "admin1": "Ontario",
                        "country": "Canada",
                        "latitude": 43.7,
                        "longitude": -79.4,
                    }
                ]
            },
            "api.open-meteo.com": {
                "current": {"temperature_2m": 16.6, "weather_code": 0},
                "daily": {
                    "time": ["2026-10-19"],
                    "temperature_2m_max": [18],
                    "temperature_2m_min": [9],
                    "weather_code": [2],
                },
            },
            "api.dictionaryapi.dev": [
                {
                    "word": "serendipity",
                    "phonetic": "/x/",
                    "meanings": [{"partOfSpeech": "noun", "definitions": [{"definition": "luck"}]}],
                }
            ],
        }
        seen = []

        async def fake(url):
            seen.append(url)
            return next(v for k, v in replies.items() if f"//{k}/" in url)

        with mock.patch.object(answers, "_get_json", side_effect=fake):
            money = run(answers.detect("100 usd to cad"))
            weather = run(answers.detect("weather toronto"))
            word = run(answers.detect("define serendipity"))
        self.assertEqual((money["result"], money["to"]), ("140.74", "CAD"))
        self.assertEqual(
            (weather["place"], weather["sky"], weather["days"][0]["sky"]),
            ("Toronto, Ontario, Canada", "clear", "partly cloudy"),
        )
        self.assertEqual(word["meanings"][0]["definitions"][0]["text"], "luck")
        self.assertEqual(word["synonyms"], ["chance"])
        self.assertAlmostEqual(money["rate"], 1.4074)
        self.assertTrue(all(url.startswith("https://") for url in seen))

    def test_definition_falls_back_to_wiktionary_when_blocked(self):
        wiki = {
            "en": [
                {
                    "partOfSpeech": "Noun",
                    "definitions": [
                        {
                            "definition": 'a <a href="/wiki/fortunate">fortunate</a> find &amp; more',
                            "examples": ["<i>pure</i> serendipity"],
                        }
                    ],
                }
            ]
        }

        async def fake(url):
            if "dictionaryapi.dev" in url:
                raise RuntimeError("403 challenge page")
            return wiki

        with mock.patch.object(answers, "_get_json", side_effect=fake):
            word = run(answers.detect("define serendipity"))
        first = word["meanings"][0]
        self.assertEqual(first["part"], "noun")
        self.assertEqual(first["definitions"][0]["text"], "a fortunate find & more")
        self.assertEqual(first["definitions"][0]["example"], "pure serendipity")
        self.assertEqual(word["source"], "Wiktionary")

    def test_translation_with_text_waits_for_the_translator(self):
        found = answers.detect("what is bonjour in english")
        card = run(found)
        self.assertEqual(
            (card["status"], card["text"], card["to"]), ("pending", "bonjour", "english")
        )
        self.assertEqual(card["translation"], "")


class AnswerRouteTest(ApiTest):
    def test_route_returns_a_card_or_nothing(self):
        with (
            mock.patch.dict(os.environ, {"ALLES_AFTERLIFE_FEATURES": "afterlife_andromeda"}),
            mock.patch.object(answers, "did_you_mean", mock.AsyncMock(return_value="")),
        ):
            card = self.client.post("/api/andromeda/answer", json={"query": "12% of 80"}).json()
            none = self.client.post(
                "/api/andromeda/answer", json={"query": "tailscale serve"}
            ).json()
        self.assertEqual((card["kind"], card["result"]), ("calc", "9.6"))
        self.assertIsNone(none["kind"])
