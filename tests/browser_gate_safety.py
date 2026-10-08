"""Server-binding proof shared by destructive browser gates."""

from __future__ import annotations

from urllib.parse import urljoin
from urllib.request import HTTPRedirectHandler, Request, build_opener


class _NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, _request, _file_pointer, _code, _message, _headers, _new_url):
        return None


def _open_without_redirects(request: Request):
    return build_opener(_NoRedirects).open(request, timeout=10)


def require_server_ownership(base_url: str, run_id: str) -> None:
    """Refuse mutations unless the target server owns this exact throwaway run."""
    request = Request(
        urljoin(base_url.rstrip("/") + "/", "health"),
        headers={"Cache-Control": "no-store"},
    )
    try:
        with _open_without_redirects(request) as response:
            if response.geturl() != request.full_url:
                raise RuntimeError("isolated Alles server ownership probe was redirected")
            server_run_id = response.headers.get("X-Alles-Test-Run-ID", "").strip()
    except OSError as exc:
        raise RuntimeError("could not verify the isolated Alles server") from exc
    if not run_id or server_run_id != run_id:
        raise RuntimeError(
            "target server does not match this browser run's owned throwaway data root"
        )
