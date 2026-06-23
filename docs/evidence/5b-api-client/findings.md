# stage 5b - typed API client + response validation - audit findings (2026-06-23)

## current state
- every frontend module hand-rolls `fetch('/api/...')` + `.then(r => r.json())` with ad-hoc error
  handling and zero response-shape checking. a backend field rename silently yields `undefined` in the
  UI with no signal.
- there's no single client with named methods, query-string building, consistent error throwing, or a
  lightweight shape validator (FastAPI already serves /openapi.json from 3h's note, but nothing consumes
  it).

## scope (testable core)
a typed API client module: request/get/post/patch/del + query building + consistent errors + a tiny
runtime response-shape validator. DEFERRED: full OpenAPI codegen + the widget factory library (dropdown/
dialog/chip-input already exist as shared widgets; unifying them is a frontend refactor, not new logic).

## fix - new `static/js/apiclient.js` (vanilla ESM, injectable fetch so it's node-testable)
- `createClient({ base='', fetchFn=fetch })` -> `{ request, get, post, patch, del }`.
- `request(method, path, { params, body, shape })`: builds the query string, sends/parses JSON, throws
  an Error carrying `.status` on a non-2xx, and (when `shape` given) validates the response.
- `validate(data, shape)` -> { ok, errors }: shape is `{ field: 'string'|'number'|'boolean'|'array'|
  'object', field2: '?string' (optional) }`; reports missing + wrong-typed fields.

tested with a fake fetch: get builds url + parses, query params appended, post sends body, non-ok throws
with status, validate ok/missing/wrong-type/optional, request+shape rejects a bad response.
