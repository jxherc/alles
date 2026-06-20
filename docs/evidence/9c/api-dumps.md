# Vault API Audit Dumps — 9c
Server: python app.py PORT=8801 ALLES_DATA=.tmp_audit9c AUTH_ENABLED=false

## POST /api/vault/unlock (first unlock — sets master password)
Request: {"password":"masterpw1"}
Response 200: {"token":"JO8MCCoh89ko3gp9fJIeYA","vault_id":"default"}
NOTE: vault_id:"default" is already in the response — 9c stub field.

## GET /api/vault (immediately after first unlock)
X-Vault-Token: <token>
Response 200: []

## POST /api/vault — login entry
{"name":"GitHub","type":"login","username":"jxherc","fields":{"password":"Sup3r$ecr3t!99","url":"https://github.com","notes":"main account"}}
Response 200: {"id":"4226a107-f4f1-40b7-87b5-03f8fc93f1e6","name":"GitHub","category":"general","type":"login"}
NOTE: category defaults to "general" even for typed entries.

## POST /api/vault — credit card entry
{"name":"Visa Infinite","type":"card","fields":{"cardholder":"John X Herc","number":"4242424242424242","expiry":"12/27","cvv":"123","notes":"travel card"}}
Response 200: {"id":"20032fd5-02ea-426b-ac09-9731aa8d9751","name":"Visa Infinite","category":"general","type":"card"}

## POST /api/vault — API key entry
{"name":"OpenAI Key","type":"apikey","fields":{"apikey":"sk-real-key-abc123xyz","endpoint":"https://api.openai.com/v1","notes":"prod key"}}
Response 200: {"id":"d3a665ad-3946-4fb2-b3c1-bcd466d4b6cd","name":"OpenAI Key","category":"general","type":"apikey"}

## POST /api/vault — secure note
{"name":"Recovery Codes","type":"note","fields":{"notes":"code1: ABCD-1234\ncode2: EFGH-5678\ncode3: IJKL-9012"}}
Response 200: {"id":"4827f376-9489-4838-9253-15077062a37f","name":"Recovery Codes","category":"general","type":"note"}

## GET /api/vault (list with 4 entries)
Response 200: [
  {"id":"4827f376...","name":"Recovery Codes","username":"","category":"general","type":"note","created_at":"2026-06-19T18:20:18.560184"},
  {"id":"d3a665ad...","name":"OpenAI Key","username":"","category":"general","type":"apikey","created_at":"2026-06-19T18:20:18.496659"},
  {"id":"20032fd5...","name":"Visa Infinite","username":"","category":"general","type":"card","created_at":"2026-06-19T18:20:18.437396"},
  {"id":"4226a107...","name":"GitHub","username":"jxherc","category":"general","type":"login","created_at":"2026-06-19T18:20:18.377192"}
]
NOTE: ordered by created_at DESC (newest first).

## GET /api/vault/{id}/reveal — login entry
Response 200: {"type":"login","fields":{"password":"Sup3r$ecr3t!99","url":"https://github.com","notes":"main account"},"value":"Sup3r$ecr3t!99"}
NOTE: username stored in DB column, NOT in fields dict (not returned in fields here).

## GET /api/vault/{id}/reveal — card entry
Response 200: {"type":"card","fields":{"cardholder":"John X Herc","number":"4242424242424242","expiry":"12/27","cvv":"123","notes":"travel card"},"value":"","card":{"brand":"Visa","last4":"4242","masked":"••••••••••••4242","valid":true}}
NOTE: value="" for card. Luhn valid. masked uses Unicode bullet chars.

## GET /api/vault/{id}/reveal — apikey entry
Response 200: {"type":"apikey","fields":{"apikey":"sk-real-key-abc123xyz","endpoint":"https://api.openai.com/v1","notes":"prod key"},"value":""}
NOTE: value="" for apikey type — the key lives in fields.apikey not fields.password.

## GET /api/vault/{id}/reveal — secure note
Response 200: {"type":"note","fields":{"notes":"code1: ABCD-1234\ncode2: EFGH-5678\ncode3: IJKL-9012"},"value":""}

## GET /api/vault/categories
Response 200: {
  "categories":["api key","card","general","note","password"],
  "schemas":{
    "api key":{"fields":["password","url","notes"]},
    "card":{"fields":["cardholder","number","expiry","cvv","address","notes"]},
    "general":{"fields":["password","notes"]},
    "note":{"fields":["notes"]},
    "password":{"fields":["username","password","url","notes"]}
  }
}
NOTE: no "login","apikey","identity","bank","ssh","license" — old vocabulary, new JS types not reflected.

## GET /api/vault/watchtower (after seeding WeakSite/123456 + SiteA+SiteB sharing ReusedPass!77)
Response 200: {
  "weak":[{"id":"2a1767a6...","name":"WeakSite"}],
  "reused":[{"ids":["9be27142...","405038a7..."],"names":["SiteA","SiteB"]}],
  "breached":[{"id":"2a1767a6...","name":"WeakSite","count":210318957}],
  "counts":{"weak":1,"reused":1,"breached":1}
}
NOTE: watchtower only scans fields.password — apikey field NOT scanned.

## POST /api/vault/lock
Response 200: {"ok":true}
NOTE: _unlock_tokens.clear() — global nuke, all sessions locked at once.

## GET /api/vault after lock
Response 403: {"detail":"vault locked"} — correct.

## POST /api/vault/unlock (wrong password)
{"password":"wrongpw"}
Response 401 — correct.

## POST /api/vault/unlock (correct password, re-unlock)
Response 200: {"token":"-rCEJv4hRY-UydKO1AH4ew","vault_id":"default"}

## POST /api/vault/strength
{"password":"123456"} → {"score":0,"entropy":10.0,"label":"very weak","warning":"this is a commonly used password"}
{"password":"Sup3r$ecr3t!99"} → {"score":4,"entropy":91.8,"label":"very strong","warning":""}

## GET /api/vault/generate?length=20
→ {"password":"GiDLUTg4yK_#xc3_J$Wj","strength":{"score":4,"entropy":131.1,"label":"very strong","warning":""}}

## Category pollution test
POST with category="Login" (as JS sends) then GET /api/vault/categories:
→ "Login" appears alongside "password" as separate categories. Both exist, causing duplication.
