# ui-3p — export fidelity (tables / links / code) + live ≈ HTML/PDF

Audit finding: export already builds from the same `mdToHtml` render the user sees
(`_exportDoc` wraps `$('wiki-preview').innerHTML`), and the export stylesheet already styles tables, links,
code, callouts and images — so tables/links/code survive `.html` / `.pdf` / `.docx` faithfully. The ui-3c–3g
live-preview work also brought the live editor's tables/callouts/code/images in line with that HTML render,
so **live ≈ export** now holds. No code change was needed beyond confirming + locking it with tests.

Tests: `tests/test_docs.py::ExportFidelityTests` (2: export CSS covers table borders / link colour / pre /
callout / img; export derives from the rendered preview) + `docs/evidence/ui-3p/verify.py` (downloads the
actual exported HTML and asserts it keeps the table, the link+href, fenced + inline code, the callout, images,
and the styling — 10 checks).
