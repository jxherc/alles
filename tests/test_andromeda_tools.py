import asyncio
import json
import os
import shutil
import tempfile
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from services import (
    andromeda,
    andromeda_answers,
    andromeda_dates,
    andromeda_dictionary,
    andromeda_f1,
    andromeda_translate,
)
from tests._client import ApiTest

detect = andromeda_answers.detect


def run(coro):
    return asyncio.run(coro)


class OnlineDictionary:
    """these tests cover the online sources, so a local wiktionary copy must not answer first."""

    def setUp(self):
        super().setUp()
        patcher = mock.patch.dict(
            os.environ, {"ALLES_DICTIONARY": "/nonexistent/wiktionary.sqlite"}
        )
        patcher.start()
        self.addCleanup(patcher.stop)


class ToolWithoutInputTest(ApiTest):
    """asking for a tool opens the tool, empty. nothing is translated, picked or looked up."""

    CASES = {
        "english to french": {"kind": "translate", "text": "", "from": "english", "to": "french"},
        "English to French": {"kind": "translate", "text": "", "from": "english", "to": "french"},
        "translate english to spanish": {
            "kind": "translate",
            "text": "",
            "from": "english",
            "to": "spanish",
        },
        "spanish to english translation": {
            "kind": "translate",
            "text": "",
            "from": "spanish",
            "to": "english",
        },
        "french translator": {"kind": "translate", "text": "", "from": "english", "to": "french"},
        "translate to german": {"kind": "translate", "text": "", "from": "english", "to": "german"},
        "translate": {"kind": "translate", "text": "", "from": "", "to": "english"},
        "google translate": {"kind": "translate", "text": "", "from": "", "to": "english"},
        "periodic table": {"kind": "periodic"},
        "the periodic table of elements": {"kind": "periodic"},
        "show me the periodic table": {"kind": "periodic"},
        "calculator": {"kind": "calc", "expression": ""},
        "dictionary": {"kind": "define", "word": "", "focus": ""},
        "thesaurus": {"kind": "define", "word": "", "focus": "synonyms"},
        "spell check": {"kind": "spell", "word": ""},
        "weather": {"kind": "weather", "place": ""},
        "weather today": {"kind": "weather", "place": ""},
        "world clock": {"kind": "clock"},
        "what time is it": {"kind": "clock"},
        "timer": {"kind": "timer", "mode": "timer", "seconds": 0, "start": False},
        "stopwatch": {"kind": "timer", "mode": "stopwatch", "seconds": 0, "start": False},
        "dice roller": {"kind": "random", "mode": "dice", "count": 1, "sides": 6, "roll": False},
        "random number generator": {
            "kind": "random",
            "mode": "number",
            "min": 1,
            "max": 10,
            "roll": False,
        },
        "color picker": {"kind": "color", "value": ""},
        "unit converter": {"kind": "units", "amount": 1.0, "from": "m", "to": "ft"},
        "temperature converter": {"kind": "units", "amount": 1.0, "from": "c", "to": "f"},
        "currency converter": {"kind": "currency", "amount": 1.0, "from": "usd", "to": "eur"},
        "f1": {"kind": "f1", "view": "next"},
    }

    def test_each_tool_opens_empty(self):
        for query, expected in self.CASES.items():
            with self.subTest(query=query):
                self.assertEqual(detect(query), expected)

    def test_a_language_pair_is_never_translated(self):
        engine = mock.AsyncMock()
        with mock.patch.object(andromeda_translate, "translate", engine):
            for query in (
                "english to french",
                "french to english",
                "translate english to japanese",
            ):
                with self.subTest(query=query):
                    card = run(andromeda_answers.resolve(detect(query)))
                    self.assertEqual((card["status"], card["translation"]), ("empty", ""))
        engine.assert_not_called()

    def test_the_periodic_table_opens_without_a_chosen_element(self):
        card = run(andromeda_answers.resolve(detect("periodic table")))
        self.assertEqual(card["kind"], "periodic")
        self.assertNotIn("selected", card)
        self.assertEqual(len(card["elements"]), 118)

    def test_empty_tools_do_not_fetch_anything(self):
        fetch = mock.AsyncMock()
        with mock.patch.object(andromeda_answers, "_get_json", fetch):
            for query in ("dictionary", "weather", "spell check", "calculator"):
                with self.subTest(query=query):
                    self.assertEqual(
                        run(andromeda_answers.resolve(detect(query)))["status"], "empty"
                    )
        fetch.assert_not_called()


class ToolWithInputTest(ApiTest):
    """a query that carries its input answers it right away, inside the same tool."""

    CASES = {
        "translate hello to french": {"kind": "translate", "text": "hello", "to": "french"},
        "hello in french": {"kind": "translate", "text": "hello", "to": "french"},
        "how do you say thank you in japanese": {"kind": "translate", "text": "thank you"},
        "hola from spanish to english": {"kind": "translate", "text": "hola", "from": "spanish"},
        "中文in english": {"kind": "translate", "text": "中文", "to": "english"},
        "你好 in french": {"kind": "translate", "text": "你好", "to": "french"},
        "carbon atomic mass": {"kind": "element", "number": 6, "fact": "mass"},
        "periodic table carbon": {"kind": "element", "number": 6, "fact": ""},
        "atomic number of gold": {"kind": "element", "number": 79, "fact": "number"},
        "what element is fe": {"kind": "element", "number": 26},
        "element 92": {"kind": "element", "number": 92},
        "12*7": {"kind": "calc", "expression": "12*7"},
        "km to miles": {"kind": "units", "amount": 1.0, "from": "km", "to": "mi"},
        "how many feet in a mile": {"kind": "units", "from": "mi", "to": "ft"},
        "convert 5 kg": {"kind": "units", "amount": 5.0, "from": "kg", "to": "lb"},
        "usd to cad": {"kind": "currency", "amount": 1.0, "from": "usd", "to": "cad"},
        "50 euros to dollars": {"kind": "currency", "amount": 50.0, "from": "eur", "to": "usd"},
        "$20 to yen": {"kind": "currency", "amount": 20.0, "from": "usd", "to": "jpy"},
        "10 pounds to kg": {"kind": "units", "from": "lb", "to": "kg"},
        "tokyo time": {"kind": "time", "zone": "Asia/Tokyo"},
        "time difference between london and tokyo": {"kind": "time", "other_zone": "Asia/Tokyo"},
        "toronto weather forecast": {"kind": "weather", "place": "toronto"},
        "weather in paris tomorrow": {"kind": "weather", "place": "paris"},
        "is it raining in london": {"kind": "weather", "place": "london"},
        "synonyms for happy": {"kind": "define", "word": "happy", "focus": "synonyms"},
        "how to pronounce quinoa": {"kind": "define", "word": "quinoa", "focus": "pronunciation"},
        "how to spell receive": {"kind": "spell", "word": "receive"},
        "5 minute timer": {"kind": "timer", "seconds": 300, "start": True},
        "set a timer for 1 hour 30 minutes": {"kind": "timer", "seconds": 5400, "start": True},
        "flip a coin": {"kind": "random", "mode": "coin", "roll": True},
        "roll 2d6": {"kind": "random", "mode": "dice", "count": 2, "sides": 6, "roll": True},
        "roll a d20": {"kind": "random", "count": 1, "sides": 20},
        "random number between 1 and 100": {"kind": "random", "min": 1, "max": 100, "roll": True},
        "#ff6600": {"kind": "color", "value": "#ff6600"},
        "rgb(255, 102, 0)": {"kind": "color", "value": "#ff6600"},
        "hex fff": {"kind": "color", "value": "#ffffff"},
        "days until christmas": {"kind": "date", "mode": "until", "day": "christmas"},
        "countdown to new year": {"kind": "date", "mode": "until", "live": True},
        "100 days from today": {"kind": "date", "mode": "offset", "days": 100},
        "what day is christmas": {"kind": "date", "mode": "weekday"},
        "f1 standings": {"kind": "f1", "view": "drivers"},
        "f1 constructors standings": {"kind": "f1", "view": "teams"},
        "next f1 race": {"kind": "f1", "view": "next"},
        "who won the last grand prix": {"kind": "f1", "view": "results"},
    }

    def test_each_query_with_input_answers(self):
        for query, fields in self.CASES.items():
            with self.subTest(query=query):
                found = detect(query)
                self.assertIsNotNone(found)
                for key, value in fields.items():
                    self.assertEqual(found[key], value)

    def test_searches_stay_searches(self):
        for query in (
            "flights to france",
            "introduction to german cars history",
            "try php",
            "bad",
            "facade",
            "showers in toronto",
            "best laptop 2026",
            "python vs rust",
            "how to install python",
            "climate change",
            "tip calculator",
            "spelling bee",
            "f1 2019 standings",
        ):
            with self.subTest(query=query):
                self.assertIsNone(detect(query))


class OverviewFitTest(ApiTest):
    def test_tools_that_answer_skip_the_overview(self):
        self.assertEqual(andromeda_answers.overview_mode(detect("100 usd to cad")), "skip")
        self.assertEqual(andromeda_answers.overview_mode(detect("english to french")), "skip")
        self.assertEqual(andromeda_answers.overview_mode(detect("carbon")), "brief")
        self.assertEqual(andromeda_answers.overview_mode(detect("f1")), "brief")
        self.assertEqual(andromeda_answers.overview_mode(None, "why is the sky blue"), "full")
        self.assertEqual(andromeda_answers.overview_mode(None, "tailscale serve"), "ask")

    def test_shape_follows_the_query(self):
        shapes = {
            "how to install python on a mac": "steps",
            "python vs rust": "compare",
            "difference between ram and storage": "compare",
            "best laptops for students": "list",
            "alternatives to notion": "list",
            "what is the capital of peru": "answer",
        }
        for query, shape in shapes.items():
            with self.subTest(query=query):
                self.assertEqual(andromeda_answers.overview_shape(query), shape)

    def test_the_prompt_asks_for_the_shape_and_a_brief_overview(self):
        steps = andromeda.overview_prompt("how to x", [], {}, shape="steps")[0]["content"]
        self.assertIn("one step in order", steps)
        self.assertIn("at most six claims", steps)
        brief = andromeda.overview_prompt("carbon", [], {}, brief=True)[0]["content"]
        self.assertIn("at most two claims", brief)
        self.assertIn("tool card", brief)

    def test_labels_must_come_from_the_claim(self):
        self.assertEqual(
            andromeda.claim_label("Battery life is longer on the Pixel.", "battery life"),
            "battery life",
        )
        self.assertEqual(andromeda.claim_label("Battery life is longer.", "winner: pixel"), "")
        self.assertEqual(andromeda.claim_label("Short.", "a b c d e f"), "")

    def test_verified_overview_keeps_its_shape_only_with_items(self):
        passage = "Install Python from python.org. Run the installer and tick add to path. Open a terminal and type python."
        evidence = [
            {
                "id": "s1",
                "url": "https://python.org",
                "title": "python",
                "passages": [passage],
                "source_kind": "docs",
                "source_quality": 1,
            }
        ]
        quotes = [
            "Install Python from python.org.",
            "Run the installer and tick add to path.",
            "Open a terminal and type python.",
        ]
        raw = json.dumps(
            {
                "claims": [
                    {
                        "text": q,
                        "focus": "",
                        "label": "",
                        "citations": [{"source_id": "s1", "quote": q}],
                    }
                    for q in quotes
                ]
            }
        )
        checked = andromeda.verify_overview(raw, "how to install python", evidence, shape="steps")
        self.assertEqual((checked["status"], checked["shape"]), ("ready", "steps"))
        one = json.dumps({"claims": json.loads(raw)["claims"][:1]})
        self.assertEqual(
            andromeda.verify_overview(one, "how to install python", evidence, shape="steps")[
                "shape"
            ],
            "answer",
        )


class DateTest(ApiTest):
    TODAY = date(2026, 10, 20)

    def solve(self, query):
        return andromeda_dates.resolve(detect(query), today=self.TODAY)

    def test_countdowns_and_offsets(self):
        self.assertEqual(self.solve("days until christmas")["days"], 66)
        self.assertEqual(self.solve("how many days until december 25")["days"], 66)
        self.assertEqual(self.solve("days since halloween")["days"], 354)
        self.assertEqual(self.solve("100 days from today")["date"], "2027-01-28")
        self.assertEqual(self.solve("2 weeks ago")["date"], "2026-10-06")
        self.assertEqual(self.solve("days between 2026-01-01 and 2026-03-01")["days"], 59)
        self.assertEqual(self.solve("what day is 2026-12-25")["date"], "2026-12-25")
        self.assertEqual(self.solve("days until easter")["date"], "2027-03-28")
        self.assertEqual(self.solve("days until thanksgiving")["date"], "2026-11-26")
        self.assertEqual(self.solve("today's date")["date"], "2026-10-20")
        self.assertIsNone(self.solve("days until the heat death of the universe"))


def _f1_reply(url):
    if url.endswith("/driverstandings.json"):
        return {
            "MRData": {
                "StandingsTable": {
                    "season": "2026",
                    "StandingsLists": [
                        {
                            "round": "17",
                            "DriverStandings": [
                                {
                                    "position": "1",
                                    "points": "340",
                                    "wins": "8",
                                    "Driver": {
                                        "givenName": "Andrea Kimi",
                                        "familyName": "Antonelli",
                                        "code": "ANT",
                                    },
                                    "Constructors": [{"name": "Mercedes"}],
                                }
                            ],
                        }
                    ],
                }
            }
        }
    if url.endswith("/constructorstandings.json"):
        raise RuntimeError("down")
    if "/races.json" in url:
        return {
            "MRData": {
                "RaceTable": {
                    "season": "2026",
                    "Races": [
                        {
                            "round": "18",
                            "raceName": "United States Grand Prix",
                            "date": "2026-10-25",
                            "time": "20:00:00Z",
                            "Circuit": {
                                "circuitName": "Circuit of the Americas",
                                "Location": {"locality": "Austin", "country": "USA"},
                            },
                            "Qualifying": {"date": "2026-10-24", "time": "21:00:00Z"},
                        }
                    ],
                }
            }
        }
    return {"MRData": {"RaceTable": {"Races": []}}}


class F1Test(ApiTest):
    def setUp(self):
        super().setUp()
        andromeda_f1._CACHE.update(at=0.0, data=None)

    def test_a_missing_part_leaves_the_rest(self):
        async def fake(url):
            return _f1_reply(url)

        card = run(andromeda_f1.resolve({"view": "drivers"}, fake))
        self.assertEqual(
            (card["status"], card["season"], card["after_round"]), ("ok", "2026", "17")
        )
        self.assertEqual(card["drivers"][0]["name"], "Andrea Kimi Antonelli")
        self.assertIn("teams", card["missing"])
        race = card["schedule"][0]
        self.assertEqual((race["start"], race["place"]), ("2026-10-25T20:00:00Z", "Austin, USA"))
        self.assertEqual(race["sessions"][0]["name"], "qualifying")

    def test_a_dead_source_says_so(self):
        async def down(_url):
            raise RuntimeError("down")

        card = run(andromeda_f1.resolve({"view": "next"}, down))
        self.assertEqual(card["status"], "unavailable")
        self.assertNotIn("drivers", card)


class LookupStatusTest(OnlineDictionary, ApiTest):
    def test_spelling_uses_wiktionary_misspellings(self):
        async def fake(url):
            if "wiktionary" in url:
                return {
                    "query": {
                        "pages": [
                            {
                                "revisions": [
                                    {
                                        "slots": {
                                            "main": {
                                                "content": "==English==\n{{misspelling of|en|their}}\n"
                                            }
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                }
            return [{"word": "thier", "tags": ["f:0.04"]}, {"word": "tier", "tags": ["f:3.1"]}]

        with mock.patch.object(andromeda_answers, "_get_json", side_effect=fake):
            card = run(andromeda_answers.resolve(detect("how to spell thier")))
        self.assertEqual((card["correct"], card["suggestions"]), (False, ["their"]))

    def test_a_down_dictionary_differs_from_a_missing_word(self):
        missing = SimpleNamespace(response=SimpleNamespace(status_code=404))

        async def not_found(url):
            if "wiktionary.org/api" in url:
                raise type("E", (Exception,), {"response": missing.response})()
            if "dictionaryapi" in url:
                return {"title": "No Definitions Found"}
            return []

        async def down(_url):
            raise RuntimeError("timeout")

        with mock.patch.object(andromeda_answers, "_get_json", side_effect=not_found):
            self.assertEqual(
                run(andromeda_answers.resolve(detect("define qwzx")))["status"], "not_found"
            )
        with mock.patch.object(andromeda_answers, "_get_json", side_effect=down):
            self.assertEqual(
                run(andromeda_answers.resolve(detect("define qwzx")))["status"], "unavailable"
            )

    def test_weather_and_currency_say_when_their_source_is_down(self):
        async def down(_url):
            raise RuntimeError("503")

        with (
            mock.patch.object(andromeda_answers, "_get_json", side_effect=down),
            mock.patch.object(andromeda_answers.asyncio, "sleep", mock.AsyncMock()),
        ):
            self.assertEqual(
                run(andromeda_answers.resolve(detect("weather toronto")))["status"], "unavailable"
            )
            money = run(andromeda_answers.resolve(detect("100 usd to cad")))
        self.assertEqual(money["status"], "unavailable")
        self.assertNotIn("result", money)

    def test_an_unknown_place_is_a_search_unless_typed_into_the_tool(self):
        async def nowhere(_url):
            return {"results": []}

        with mock.patch.object(andromeda_answers, "_get_json", side_effect=nowhere):
            self.assertIsNone(run(andromeda_answers.resolve(detect("climate weather"))))
            tool = run(andromeda_answers.resolve(detect("weather narnia"), strict=True))
        self.assertEqual(tool["status"], "not_found")


class ToolRouteTest(ApiTest):
    ENV = {"ALLES_AFTERLIFE_FEATURES": "afterlife_andromeda"}

    def test_a_tool_field_answers_only_its_own_kind(self):
        with mock.patch.dict(os.environ, self.ENV):
            bare = self.client.post(
                "/api/andromeda/answer", json={"query": "5", "kind": "calc"}
            ).json()
            wrong = self.client.post(
                "/api/andromeda/answer", json={"query": "12*7", "kind": "define"}
            ).json()
            junk = self.client.post(
                "/api/andromeda/answer", json={"query": "2 +", "kind": "calc"}
            ).json()
        self.assertEqual((bare["kind"], bare["result"]), ("calc", "5"))
        self.assertIsNone(wrong["kind"])
        self.assertEqual(junk["status"], "invalid")

    def test_translate_uses_libretranslate_not_a_model(self):
        replies = []

        async def fake_call(_settings, path, payload=None, timeout=6):
            replies.append((path, payload))
            if path == "/languages":
                return SimpleNamespace(
                    json=lambda: [{"code": "en"}, {"code": "fr"}, {"code": "zh-Hans"}]
                )
            body = {"translatedText": "bonjour", "detectedLanguage": {"language": "en"}}
            return SimpleNamespace(status_code=200, content=b"x", json=lambda: body)

        andromeda_translate._LANGUAGES.update(at=0.0, url="", names=[])
        with (
            mock.patch.dict(os.environ, self.ENV),
            mock.patch.object(andromeda_translate, "_call", side_effect=fake_call),
        ):
            done = self.client.post(
                "/api/andromeda/translate", json={"text": "hello", "to": "french"}
            ).json()
            card = self.client.post(
                "/api/andromeda/answer", json={"query": "hello in french"}
            ).json()
            bad = self.client.post("/api/andromeda/translate", json={"text": "hi", "to": "klingon"})
        self.assertEqual(
            (done["translation"], done["from"], done["from_detected"]), ("bonjour", "english", True)
        )
        self.assertEqual(
            replies[0],
            ("/translate", {"q": "hello", "source": "auto", "target": "fr", "format": "text"}),
        )
        # the card comes back at once with the text; the translator fills it in
        self.assertEqual(
            (card["status"], card["text"], card["languages"]),
            ("pending", "hello", ["chinese", "english", "french"]),
        )
        self.assertEqual((bad.status_code, bad.json()["code"]), (400, "unknown_language"))

    def test_a_stopped_translator_says_so(self):
        async def down(*_args, **_kwargs):
            raise andromeda_translate.Unavailable("connection refused")

        andromeda_translate._LANGUAGES.update(at=0.0, url="", names=[])
        with (
            mock.patch.dict(os.environ, self.ENV),
            mock.patch.object(andromeda_translate, "_call", side_effect=down),
        ):
            response = self.client.post(
                "/api/andromeda/translate", json={"text": "hi", "to": "french"}
            )
            card = self.client.post(
                "/api/andromeda/answer", json={"query": "english to french"}
            ).json()
        self.assertEqual(
            (response.status_code, response.json()["code"]), (503, "translator_unavailable")
        )
        self.assertEqual(card["engine"], "unavailable")

    def test_a_plain_search_gets_did_you_mean(self):
        with (
            mock.patch.dict(os.environ, self.ENV),
            mock.patch.object(
                andromeda_answers, "did_you_mean", mock.AsyncMock(return_value="receive")
            ),
        ):
            card = self.client.post("/api/andromeda/answer", json={"query": "recieve"}).json()
        self.assertEqual((card["kind"], card["did_you_mean"]), (None, "receive"))

    def test_search_says_when_a_tool_answers(self):
        async def fake_search(*_args, **_kwargs):
            return {
                "status": "ok",
                "results": [{"url": "https://a.example", "title": "a", "snippet": "a"}],
            }

        with (
            mock.patch.dict(os.environ, self.ENV),
            mock.patch.object(andromeda, "normal_search", side_effect=fake_search),
        ):
            tool = self.client.post(
                "/api/andromeda/search", json={"query": "english to french"}
            ).json()
            plain = self.client.post(
                "/api/andromeda/search", json={"query": "tailscale serve"}
            ).json()
        self.assertEqual((tool["answer_kind"], tool["overview_mode"]), ("translate", "skip"))
        self.assertEqual((plain["answer_kind"], plain["overview_mode"]), (None, "ask"))


class LocalDictionaryTest(ApiTest):
    """the wiktionary copy answers definitions, spelling and did-you-mean without going online."""

    ROWS = [
        {
            "word": "receive",
            "lang_code": "en",
            "pos": "verb",
            "sounds": [{"ipa": "/ɹɪˈsiːv/"}],
            "senses": [
                {
                    "glosses": ["To take, as something that is offered."],
                    "examples": [{"text": "to receive a gift"}],
                    "synonyms": [{"word": "get"}],
                }
            ],
        },
        {
            "word": "recieve",
            "lang_code": "en",
            "pos": "verb",
            "senses": [
                {
                    "glosses": ["Misspelling of receive."],
                    "tags": ["misspelling"],
                    "alt_of": [{"word": "receive"}],
                }
            ],
        },
        {"word": "recevoir", "lang_code": "fr", "pos": "verb", "senses": [{"glosses": ["x"]}]},
    ]

    def setUp(self):
        super().setUp()
        folder = Path(tempfile.mkdtemp(prefix="alles-dictionary-"))
        self.addCleanup(lambda: shutil.rmtree(folder, ignore_errors=True))
        source = folder / "sample.jsonl"
        source.write_text("\n".join(json.dumps(row) for row in self.ROWS), encoding="utf-8")
        patcher = mock.patch.dict(os.environ, {"ALLES_DICTIONARY": str(folder / "d.sqlite")})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.assertEqual(andromeda_dictionary.build(source), 2)

    def test_lookup_spelling_and_did_you_mean_stay_local(self):
        offline = mock.AsyncMock(side_effect=AssertionError("went online"))
        with mock.patch.object(andromeda_answers, "_get_json", offline):
            word = run(andromeda_answers.resolve(detect("define receive")))
            typo = run(andromeda_answers.resolve(detect("define recieve")))
            spelling = run(andromeda_answers.resolve(detect("how to spell recieve")))
            andromeda_answers._SPELLING_CACHE.clear()
            fixed = run(andromeda_answers.did_you_mean("recieve email"))
        self.assertEqual(
            (word["status"], word["phonetic"], word["synonyms"]), ("ok", "/ɹɪˈsiːv/", ["get"])
        )
        self.assertEqual(word["meanings"][0]["definitions"][0]["example"], "to receive a gift")
        self.assertEqual((typo["status"], typo["suggestions"]), ("not_found", ["receive"]))
        self.assertEqual((spelling["correct"], spelling["suggestions"]), (False, ["receive"]))
        self.assertEqual(fixed, "receive email")


class StreamedOverviewTest(ApiTest):
    """the instant answer: prose from the result snippets, streamed word by word, cited by number."""

    def setUp(self):
        super().setUp()
        from core.database import ModelEndpoint
        from core.settings import load_settings, save_settings

        db = self.db()
        db.add(
            ModelEndpoint(
                name="local",
                base_url="http://127.0.0.1:11434/v1",
                cached_models='["overview-model"]',
                enabled=True,
            )
        )
        db.commit()
        db.close()
        andromeda._OVERVIEW_CACHE.clear()
        save_settings(
            {
                **load_settings(),
                "andromeda_overview": True,
                "andromeda_model_band": "standard",
                "andromeda_model_bands": {},
            }
        )
        flags = mock.patch.dict(os.environ, {"ALLES_AFTERLIFE_FEATURES": "afterlife_andromeda"})
        flags.start()
        self.addCleanup(flags.stop)
        self.body = {
            "query": "why is the sky blue",
            "results": [
                {
                    "url": "https://en.wikipedia.org/wiki/Sky",
                    "title": "Sky",
                    "snippet": "Rayleigh scattering makes the daytime sky look blue.",
                },
                {
                    "url": "https://spaceplace.nasa.gov/blue-sky/",
                    "title": "Why is the sky blue?",
                    "snippet": "Blue light is scattered more than other colors because it travels as shorter waves.",
                },
            ],
        }

    def events(self, text):
        return [
            json.loads(chunk[6:]) for chunk in text.split("\n\n") if chunk.startswith("data: {")
        ]

    def stream(self, words, calls):
        async def stream(*_args, **kwargs):
            calls.append(kwargs)
            for word in words:
                yield {"delta": word}

        return stream

    def test_words_stream_and_the_answer_cites_its_sources(self):
        calls = []
        words = [
            "Rayleigh ",
            "scattering ",
            "makes the sky blue. ",
            "[1]",
            "\n- Blue light ",
            "scatters most. [2]",
        ]
        with mock.patch("services.llm.stream_chat", new=self.stream(words, calls)):
            first = self.client.post("/api/andromeda/overview", json=self.body).text
            again = self.client.post("/api/andromeda/overview", json=self.body).text
        events = self.events(first)
        tokens = [event["text"] for event in events if event["type"] == "token"]
        self.assertGreater(len(tokens), 2)
        answer = events[-1]["overview"]
        self.assertEqual(
            (answer["status"], answer["mode"], answer["cited"]), ("ready", "prose", [1, 2])
        )
        self.assertEqual(
            answer["claims"][0]["citations"][0]["url"], "https://en.wikipedia.org/wiki/Sky"
        )
        self.assertEqual(answer["claims"][1]["text"], "Blue light scatters most.")
        # the prompt holds the numbered snippets, never whole pages
        prompt = calls[0]
        self.assertFalse(prompt["thinking"])
        # the same question over the same results comes back without asking the model again
        self.assertEqual(len(calls), 1)
        self.assertIn('"cached": true', again)

    def test_skip_shows_nothing_and_an_asked_answer_never_skips(self):
        calls = []
        with mock.patch("services.llm.stream_chat", new=self.stream(["SK", "IP"], calls)):
            skipped = self.events(self.client.post("/api/andromeda/overview", json=self.body).text)
        self.assertFalse([event for event in skipped if event["type"] == "token"])
        self.assertEqual(skipped[-1]["overview"]["status"], "skipped")
        seen = []

        async def capture(messages, *_args, **_kwargs):
            seen.append(messages[0]["content"])
            yield {"delta": "Rayleigh scattering. [1]"}

        with mock.patch("services.llm.stream_chat", new=capture):
            self.client.post("/api/andromeda/overview", json={**self.body, "allow_skip": False})
        self.assertNotIn("SKIP", seen[0])

    def test_when_the_answer_runs_on_its_own(self):
        modes = {
            "why is the sky blue": "full",
            "best laptops for students this year": "full",
            "tailscale serve": "ask",
            "youtube": "none",
            "github.com/astqh": "none",
            "site:reddit.com ssh keys": "none",
            "gmail login": "none",
            "english to french": "skip",
            "carbon": "brief",
        }
        for query, mode in modes.items():
            with self.subTest(query=query):
                self.assertEqual(andromeda_answers.overview_mode(detect(query), query), mode)

    def test_think_blocks_and_a_partial_skip_never_reach_the_page(self):
        self.assertIsNone(andromeda.visible_prose("SK"))
        self.assertIsNone(andromeda.visible_prose("<think>planning"))
        self.assertEqual(andromeda.visible_prose("<think>x</think>Blue light."), "Blue light.")
