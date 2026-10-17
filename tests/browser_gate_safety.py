"""Owned-server proof and loopback-only transports for maintained browser gates.

This is a fixture boundary, not a sandbox for hostile test code. Python startup
installs it before the app/test imports. Playwright's shared implementation layer
covers both public APIs; a rejecting proxy also catches browser redirects,
service workers and Node requests that do not traverse Python sockets.
"""

from __future__ import annotations

import errno
import functools
import inspect
import ipaddress
import json
import os
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urljoin, urlsplit
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


def loopback_host(host) -> bool:
    if isinstance(host, bytes):
        host = host.decode("ascii", errors="replace")
    name = str(host or "").lower().rstrip(".").strip("[]")
    if name == "localhost" or name.endswith(".localhost"):
        return True
    try:
        address = ipaddress.ip_address(name)
        return address.is_loopback or bool(
            isinstance(address, ipaddress.IPv6Address)
            and address.ipv4_mapped
            and address.ipv4_mapped.is_loopback
        )
    except ValueError:
        return False


def loopback_url(url: str, base_url: str = "") -> bool:
    try:
        parsed = urlsplit(urljoin(base_url, url) if base_url else url)
        if parsed.netloc or parsed.scheme in {"http", "https", "ws", "wss", "ftp"}:
            return loopback_host(parsed.hostname)
        return parsed.scheme in {"about", "data", "blob", "file"}
    except ValueError:
        return False


def prepare_network_isolation(data: Path, run_id: str) -> Path:
    """Create only the owned child's trusted startup hook, never an inherited hook."""
    try:
        owned = bool(run_id) and (data / ".alles-test-owner").read_text() == run_id
    except OSError:
        owned = False
    if not owned:
        raise RuntimeError("network isolation requires an owned throwaway data root")
    directory = data / ".browser-network"
    directory.mkdir()
    # Python normally prints sitecustomize errors and continues. Fail closed if
    # either ownership verification or installation fails instead.
    source = Path(__file__).resolve()
    (directory / "sitecustomize.py").write_text(
        "import os, runpy, traceback\n"
        "try:\n"
        f"    runpy.run_path({str(source)!r})['install_network_isolation']()\n"
        "except BaseException:\n"
        "    traceback.print_exc()\n"
        "    os._exit(78)\n",
        encoding="utf-8",
    )
    return directory


class BrowserNetworkGuard:
    def __init__(self, artifacts: Path):
        self.artifacts = artifacts
        self._patches = []
        self._proxy = None
        self._proxy_thread = None

    def _record(self, kind: str, host="") -> None:
        # Store host names only, never URLs, credentials, query strings or bodies.
        self.artifacts.mkdir(parents=True, exist_ok=True)
        with (self.artifacts / "outbound-blocks.jsonl").open("a", encoding="utf-8") as log:
            log.write(json.dumps({"kind": kind, "host": str(host), "pid": os.getpid()}) + "\n")

    def _deny(self, kind: str, host) -> None:
        self._record(kind, host)
        raise OSError(errno.ENETUNREACH, "browser fixtures allow loopback network access only")

    def _replace(self, owner, name, replacement) -> None:
        self._patches.append((owner, name, getattr(owner, name, None)))
        setattr(owner, name, replacement)

    def _host(self, host, kind: str, family=socket.AF_INET):
        if not loopback_host(host):
            self._deny(kind, host)
        name = host.decode("ascii") if isinstance(host, bytes) else str(host)
        name = name.lower().rstrip(".").strip("[]")
        if name == "localhost" or name.endswith(".localhost"):
            return "::1" if family == socket.AF_INET6 else "127.0.0.1"
        return name

    def _address(self, address, kind, family):
        if isinstance(address, tuple):
            return (self._host(address[0], kind, family), *address[1:])
        return address  # Unix-domain sockets are local and used by child transports.

    def install(self) -> None:
        if self._patches:
            return
        dns = socket.getaddrinfo
        connect = socket.socket.connect
        connect_ex = socket.socket.connect_ex
        sendto = socket.socket.sendto
        sendmsg = getattr(socket.socket, "sendmsg", None)
        byname = socket.gethostbyname
        byname_ex = socket.gethostbyname_ex
        byaddr = socket.gethostbyaddr
        nameinfo = socket.getnameinfo

        def getaddrinfo(host, port, family=0, *args, **kwargs):
            # None is the local bind address, not a remote lookup.
            target = None if host is None else self._host(host, "python-dns", family)
            return dns(target, port, family, *args, **kwargs)

        def guarded_connect(sock, address):
            return connect(sock, self._address(address, "python-connect", sock.family))

        def guarded_connect_ex(sock, address):
            try:
                address = self._address(address, "python-connect-ex", sock.family)
            except OSError:
                return errno.ENETUNREACH
            return connect_ex(sock, address)

        def guarded_sendto(sock, data, *args):
            address = self._address(args[-1], "python-datagram", sock.family)
            return sendto(sock, data, *args[:-1], address)

        def guarded_sendmsg(sock, buffers, *args):
            if len(args) == 3:  # ancillary data, flags, optional destination
                address = self._address(args[2], "python-datagram", sock.family)
                args = (*args[:2], address)
            return sendmsg(sock, buffers, *args)

        def getnameinfo(address, flags):
            family = socket.AF_INET6 if len(address) == 4 else socket.AF_INET
            return nameinfo(self._address(address, "python-dns", family), flags)

        self._replace(socket, "getaddrinfo", getaddrinfo)
        self._replace(socket, "gethostbyname", lambda host: byname(self._host(host, "python-dns")))
        self._replace(
            socket, "gethostbyname_ex", lambda host: byname_ex(self._host(host, "python-dns"))
        )
        self._replace(socket, "gethostbyaddr", lambda host: byaddr(self._host(host, "python-dns")))
        self._replace(socket, "getnameinfo", getnameinfo)
        self._replace(socket.socket, "connect", guarded_connect)
        self._replace(socket.socket, "connect_ex", guarded_connect_ex)
        self._replace(socket.socket, "sendto", guarded_sendto)
        if sendmsg is not None:
            self._replace(socket.socket, "sendmsg", guarded_sendmsg)
        self._install_playwright()
        self._replace(socket, "_alles_loopback_only", True)

    def close(self) -> None:
        if self._proxy:
            self._proxy.shutdown()
            self._proxy.server_close()
            self._proxy_thread.join(timeout=2)
        for owner, name, original in reversed(self._patches):
            if original is None:
                delattr(owner, name)
            else:
                setattr(owner, name, original)
        self._patches.clear()

    def _proxy_settings(self) -> dict:
        if self._proxy is None:
            guard = self

            class RejectOutbound(BaseHTTPRequestHandler):
                def reject(self):
                    target = self.path if "://" in self.path else "//" + self.path
                    try:
                        host = urlsplit(target).hostname or ""
                    except ValueError:
                        host = "invalid proxy target"
                    guard._record("playwright-proxy", host)
                    self.send_response(403, "fixture outbound access blocked")
                    self.send_header("Content-Length", "0")
                    self.send_header("Connection", "close")
                    self.end_headers()
                    self.close_connection = True

                do_CONNECT = do_GET = do_HEAD = do_POST = do_PUT = reject
                do_PATCH = do_DELETE = do_OPTIONS = reject

                def log_message(self, *_args):
                    pass

            self._proxy = ThreadingHTTPServer(("127.0.0.1", 0), RejectOutbound)
            self._proxy_thread = threading.Thread(target=self._proxy.serve_forever, daemon=True)
            self._proxy_thread.start()
        return {
            "server": f"http://127.0.0.1:{self._proxy.server_port}",
            "bypass": "127.0.0.1,localhost,*.localhost,[::1]",
        }

    @staticmethod
    def _arguments(original, instance, args, kwargs):
        return inspect.signature(original).bind(instance, *args, **kwargs)

    def _guard_url(self, url, kind, base_url=""):
        if not loopback_url(url, base_url):
            try:
                host = urlsplit(urljoin(base_url, url)).hostname or "unresolved URL"
            except ValueError:
                host = "invalid URL"
            self._deny(kind, host)

    def _install_playwright(self) -> None:
        try:
            from playwright._impl._browser import Browser
            from playwright._impl._browser_type import BrowserType
            from playwright._impl._fetch import APIRequest, APIRequestContext
            from playwright._impl._network import Route
        except ModuleNotFoundError as exc:
            if exc.name == "playwright":
                return  # Backend-only installations still receive the socket boundary.
            raise

        def context_factory(owner, method, *, launch=False, persistent=False, api=False):
            original = getattr(owner, method)

            @functools.wraps(original)
            async def guarded(instance, *args, **kwargs):
                bound = self._arguments(original, instance, args, kwargs)
                bound.arguments["proxy"] = self._proxy_settings()
                if launch and instance.name == "chromium":
                    flags = list(bound.arguments.get("args") or [])
                    flags.extend(
                        [
                            "--host-resolver-rules=MAP *.localhost 127.0.0.1, MAP localhost 127.0.0.1, EXCLUDE 127.0.0.1, EXCLUDE [::1], MAP * ~NOTFOUND",
                            "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
                        ]
                    )
                    bound.arguments["args"] = flags
                result = await original(*bound.args, **bound.kwargs)
                base = bound.arguments.get("baseURL") or ""
                if api:
                    result._alles_guard_base_url = base
                elif not launch or persistent:
                    # The rejecting proxy guards browser traffic without a route
                    # callback. Impl callbacks use different sync/async dispatch
                    # contracts; registering an async handler here breaks sync
                    # Playwright. Fixture-owned public routes remain untouched.
                    result.request._alles_guard_base_url = base
                return result

            self._replace(owner, method, guarded)

        context_factory(BrowserType, "launch", launch=True)
        context_factory(BrowserType, "launch_persistent_context", launch=True, persistent=True)
        # Browser.new_page calls this implementation directly; patching only the
        # generated sync/async Browser.new_context wrappers misses that path.
        context_factory(Browser, "new_context")
        context_factory(APIRequest, "new_context", api=True)
        fetch = APIRequestContext._inner_fetch

        @functools.wraps(fetch)
        async def guarded_fetch(instance, *args, **kwargs):
            bound = self._arguments(fetch, instance, args, kwargs)
            request = bound.arguments.get("request")
            url = bound.arguments.get("url") or (request.url if request else "")
            self._guard_url(url, "playwright-api", getattr(instance, "_alles_guard_base_url", ""))
            return await fetch(*bound.args, **bound.kwargs)

        self._replace(APIRequestContext, "_inner_fetch", guarded_fetch)
        proceed = Route.continue_

        @functools.wraps(proceed)
        async def guarded_continue(instance, *args, **kwargs):
            bound = self._arguments(proceed, instance, args, kwargs)
            url = bound.arguments.get("url") or instance.request.url
            if not loopback_url(url):
                self._record("browser-continue", urlsplit(url).hostname)
                return await instance.abort("blockedbyclient")
            return await proceed(*bound.args, **bound.kwargs)

        self._replace(Route, "continue_", guarded_continue)


_network_guard = None


def install_network_isolation() -> None:
    global _network_guard
    if _network_guard is not None:
        return
    data = Path(os.environ.get("ALLES_DATA", ""))
    run_id = os.environ.get("ALLES_TEST_RUN_ID", "")
    if (
        os.environ.get("ALLES_TEST_DATA") != "1"
        or not run_id
        or (data / ".alles-test-owner").read_text() != run_id
    ):
        raise RuntimeError("network isolation requires an owned throwaway data root")
    artifacts = Path(os.environ["ALLES_BROWSER_ARTIFACTS"])
    guard = BrowserNetworkGuard(artifacts)
    guard.install()
    _network_guard = guard
    artifacts.mkdir(parents=True, exist_ok=True)
    with (artifacts / "network-isolation.jsonl").open("a", encoding="utf-8") as log:
        log.write(
            json.dumps({"pid": os.getpid(), "run_id": run_id, "mode": "loopback-only"}) + "\n"
        )
