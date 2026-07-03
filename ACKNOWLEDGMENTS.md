# Acknowledgments

aide was inspired by and built on the ideas of
**[Odysseus](https://github.com/pewdiepie-archdaemon/odysseus)**
by pewdiepie-archdaemon.

The concept of a self-hosted personal AI assistant with memory, research mode,
shell access, MCP integration, and a multi-provider LLM backend originates from
that project. aide is an independent reimplementation written from scratch, but
Odysseus is where the idea came from and deserves full credit for it.

Go give that repo a star.

## Third-party components

alles bundles or builds on these open-source projects, with thanks:

- **[CodeMirror 6](https://codemirror.net)** (MIT) — vendored as `static/vendor/cm6.bundle.js`;
  powers the docs editor's live-preview markdown editing.
- **[Leaflet](https://leafletjs.com)** (BSD-2-Clause) — vendored under `static/vendor/leaflet/`;
  powers the gallery "places" map view.
- **Map tiles © [OpenStreetMap](https://www.openstreetmap.org/copyright) contributors**
  ([ODbL](https://opendatacommons.org/licenses/odbl/)) — the tiles shown in the places map come
  from OpenStreetMap; the attribution is displayed on the map as required.
- **City data © [GeoNames](https://www.geonames.org)** ([CC BY 4.0](https://creativecommons.org/licenses/by/4.0/))
  — the `cities15000` + country list bundled as `services/places_cities.csv` /
  `services/places_countries.csv`; powers the gallery's offline reverse-geocoding (Places view).
- **[OpenAI CLIP](https://github.com/openai/CLIP)** (MIT) via **[Immich's ONNX export](https://huggingface.co/immich-app/ViT-B-32__openai)**
  — the optional `ViT-B-32` model powering the gallery's "smart" semantic search, run locally with
  **[ONNX Runtime](https://onnxruntime.ai)** (MIT) + **[Hugging Face tokenizers](https://github.com/huggingface/tokenizers)**
  (Apache-2.0). Models are downloaded by the user into `models/clip/`, not bundled.
- **[InsightFace](https://github.com/deepinsight/insightface)** (MIT) — the optional `buffalo_l`
  face detection + ArcFace recognition models powering the gallery's "people" view (face grouping),
  run locally on CPU via ONNX Runtime. The models auto-download into `models/faces/`, not bundled.
- And the rest of the stack: [FastAPI](https://fastapi.tiangolo.com), [Uvicorn](https://www.uvicorn.org),
  [SQLAlchemy](https://www.sqlalchemy.org), [httpx](https://www.python-httpx.org),
  [fastembed](https://github.com/qdrant/fastembed), [KaTeX](https://katex.org),
  [Mermaid](https://mermaid.js.org), [Pillow](https://python-pillow.org),
  [python-docx](https://python-docx.readthedocs.io), [pypdf](https://pypdf.readthedocs.io),
  and [cryptography](https://cryptography.io).
