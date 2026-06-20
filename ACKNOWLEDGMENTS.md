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
- And the rest of the stack: [FastAPI](https://fastapi.tiangolo.com), [Uvicorn](https://www.uvicorn.org),
  [SQLAlchemy](https://www.sqlalchemy.org), [httpx](https://www.python-httpx.org),
  [fastembed](https://github.com/qdrant/fastembed), [KaTeX](https://katex.org),
  [Mermaid](https://mermaid.js.org), [Pillow](https://python-pillow.org),
  [python-docx](https://python-docx.readthedocs.io), [pypdf](https://pypdf.readthedocs.io),
  and [cryptography](https://cryptography.io).
