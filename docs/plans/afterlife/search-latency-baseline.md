# Afterlife Phase 0 — current search latency baseline

- **Status:** measured on 2026-07-11 at 21:35 CST
- **Scope:** the shipped `services.research.search.search_chain` path that will be the search input to
  Andromeda. The future Andromeda UI and AI summary are still feature-flagged off, so they are not part
  of this number.
- **Privacy rule:** public test queries and an empty throwaway `ALLES_DATA` were used. No private
  settings, saved query, API key, hostname, serial number, UUID, IP address, or network name was read or
  recorded.

## Reference hardware

| Item | Value |
| --- | --- |
| Computer | MacBook Air (`MacBookAir10,1`) |
| Chip | Apple M1 |
| Memory | 8 GB |
| Operating system | macOS 27.0, build `26A5378j` |
| Python | 3.14.6 |
| Search library | `ddgs` 9.14.4 |
| HTTP library | `httpx` 0.28.1 |
| Workspace base | Git `b6ab007824be`, with the current Phase 0 working-tree changes |

## Method

- Started Python with an empty environment, temporary home folder, and temporary `ALLES_DATA`.
- Set `PYTHON_DOTENV_DISABLED=1`; the temporary settings file did not exist.
- Confirmed that no supported search-provider credential variable was present.
- Called `search_chain(query, override="duckduckgo", max_results=10)` seven times in one process.
- Rotated three public queries: FastAPI dependency injection docs, Python `asyncio` task-group docs, and
  SQLite write-ahead logging docs.
- Measured wall-clock time with `time.perf_counter()` around the complete `search_chain` call.
- Run 1 is the first-process call (cold). Runs 2–7 are process-warm calls. The implementation creates a
  new provider/client call each time, so “warm” does not promise a reused network connection.
- The public internet connection was not controlled. These are reference observations, not a provider
  speed guarantee.

## Results

| Run | State | Query | Time | Provider used | Results | Error |
| ---: | --- | ---: | ---: | --- | ---: | --- |
| 1 | cold | 1 | 2,933.9 ms | DuckDuckGo | 10 | none |
| 2 | warm | 2 | 2,512.7 ms | DuckDuckGo | 10 | none |
| 3 | warm | 3 | 2,928.7 ms | DuckDuckGo | 10 | none |
| 4 | warm | 1 | 6,203.4 ms | DuckDuckGo | 10 | none |
| 5 | warm | 2 | 2,472.7 ms | DuckDuckGo | 10 | none |
| 6 | warm | 3 | 5,299.8 ms | DuckDuckGo | 10 | none |
| 7 | warm | 1 | 5,300.7 ms | DuckDuckGo | 10 | none |

| Summary | Time |
| --- | ---: |
| All-run minimum | 2,472.7 ms |
| All-run median | 2,933.9 ms |
| All-run nearest-rank p95 | 6,203.4 ms |
| All-run maximum | 6,203.4 ms |
| Warm minimum | 2,472.7 ms |
| Warm median | 4,114.2 ms |
| Warm maximum | 6,203.4 ms |

All 7 calls returned 10 results from DuckDuckGo with no reported error or Wikipedia fallback. The large
spread is real public-provider/network variation. This baseline measures search retrieval only; page
reading and AI answer generation need separate budgets when Andromeda is enabled.
