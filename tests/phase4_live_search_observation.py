"""One-off live timing observation. This is not a deterministic performance gate."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.andromeda import normal_search

QUERIES = (
    "python 3.14 release notes",
    "fastapi current release documentation",
    "sqlite latest release notes",
)


async def main() -> None:
    observations = []
    for query in QUERIES:
        result = await normal_search(query, max_results=5)
        observations.append(
            {
                "query": query,
                "status": result["status"],
                "provider": result["provider"],
                "elapsed_ms": result["elapsed_ms"],
                "results": len(result["results"]),
                "error": result["error"],
            }
        )
    print(
        json.dumps(
            {"kind": "live network observation, not a guarantee", "runs": observations}, indent=2
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
