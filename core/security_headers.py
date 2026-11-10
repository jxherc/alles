"""baseline security headers on every http response: nosniff, the referrer policy and the
content security policy for html (the app policy, or the stricter one of a sandboxed page)."""

# scripts only from alles itself and plaid link's loader: no inline code, no eval. styles keep
# 'unsafe-inline' (style attributes are everywhere). images take any web host: markdown, book
# covers, feeds and the map tiles (plain http too, for http installs; an https page upgrades or
# blocks those itself). plaid hosts follow plaid's own csp notes for link
_CSP = "; ".join(
    (
        "default-src 'self' https://cdn.plaid.com",
        "script-src 'self' https://cdn.plaid.com",
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data: blob: https: http:",
        "font-src 'self'",
        "media-src 'self' blob:",
        "connect-src 'self' https://*.plaid.com",
        "frame-src 'self' https://cdn.plaid.com https://secure.plaid.com",
        "worker-src 'self'",
        "manifest-src 'self'",
        "object-src 'none'",
        "base-uri 'self'",
        "frame-ancestors 'self'",
        "form-action 'self'",
    )
).encode()
# the page aide's html artifacts and "run" on a code block load into. `sandbox allow-scripts`
# gives it an opaque origin (no alles cookies, storage or api), so its code may be inline and
# load from the web, like it could in the srcdoc frame it replaces (srcdoc takes the app's csp)
_SANDBOX_CSP = (
    b"sandbox allow-scripts; default-src https: data: blob: 'unsafe-inline' 'unsafe-eval'; "
    b"object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'self'"
)
# fastapi's own api pages start swagger / redoc from jsdelivr with an inline script. they only
# exist when ALLES_API_DOCS is on (a 404 otherwise, with no html), so this stays on their paths
_API_DOCS_CSP = (
    b"default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    b"style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com; "
    b"font-src 'self' https://fonts.gstatic.com; img-src 'self' data: https:; "
    b"worker-src 'self' blob:; object-src 'none'; base-uri 'self'; frame-ancestors 'self'; "
    b"form-action 'self'"
)
_PAGE_CSP = {
    "/static/sandbox.html": _SANDBOX_CSP,
    "/api/docs": _API_DOCS_CSP,
    "/api/docs/oauth2-redirect": _API_DOCS_CSP,
    "/api/redoc": _API_DOCS_CSP,
}
# not same-origin: the photos map loads openstreetmap tiles from the browser, and their tile
# policy needs a referer (same-origin is on their list of causes for the "access blocked" tile)
_REFERRER_POLICY = b"strict-origin-when-cross-origin"
# what runs in the sandbox tells nobody where it came from
_PAGE_REFERRER = {"/static/sandbox.html": b"no-referrer"}


class SecurityHeadersMiddleware:
    """Baseline headers on every http response. Pure ASGI like the others, so streams pass
    through chunk by chunk. A header a route already set wins, so the sandboxed file
    previews keep their stricter CSP; html without one gets the app policy, or its page's."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers") or [])
                have = {name.lower() for name, _ in headers}
                if b"x-content-type-options" not in have:
                    headers.append((b"x-content-type-options", b"nosniff"))
                if b"referrer-policy" not in have:
                    policy = _PAGE_REFERRER.get(scope.get("path", ""), _REFERRER_POLICY)
                    headers.append((b"referrer-policy", policy))
                if b"content-security-policy" not in have:
                    ctype = next((v for k, v in headers if k.lower() == b"content-type"), b"")
                    if ctype.split(b";")[0].strip().lower() == b"text/html":
                        csp = _PAGE_CSP.get(scope.get("path", ""), _CSP)
                        headers.append((b"content-security-policy", csp))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_headers)
