# reverse-proxy decision

- **checked:** 2026-07-12
- **scope:** HTTPS entry point for a self-hosted, single-user Alles server
- **decision:** propose Caddy as a future Alles-managed native default; keep Nginx Proxy Manager as an
  owner-managed visual/Compose option
- **phase result:** no proxy is installed or changed in Phase 1

## short answer

Nginx Proxy Manager is a good choice when the owner already uses Docker and wants a visual screen for
many services. It is not the smallest default for Alles: its official setup adds a container, persistent
application state, a certificate directory, and an admin UI on port 81.

Caddy is the better future managed default for a normal native Alles install. It can be one binary plus
one small config, handles HTTPS automatically, supports WebSocket tunnels, and runs as a normal service
on Linux. macOS has an official static binary and a community Homebrew package. It has no public admin
dashboard; its powerful admin API stays on localhost by default and should use a permissioned Unix
socket if Alles ever controls it.

This is a recommendation, not permission to install anything. Alles still needs an explicit owner
approval flow before it can claim ports 80/443, alter a firewall/router, request certificates, or expose
a hostname.

## linked-video check

The original brainstorm linked [“what's on my home server 2026”](https://youtu.be/kwLgfYCZFto).
The reviewed section from about 5:27 to 7:08 shows this pattern:

- Nginx Proxy Manager maps friendly local domain names to internal service addresses and supplies SSL;
- AdGuard Home answers local DNS and uses rewrites so those names reach the proxy;
- the example is a personal pfSense/home-lab setup with a purchased domain.

That demonstrates the desired convenience. It is not an installation or safety proof: it does not
cover Alles ownership markers, forwarded-proxy trust, rollback, backup, port conflicts, or what happens
when DNS/proxy service fails. Those remain required below.

## comparison

| concern | Caddy native | Nginx Proxy Manager |
|---|---|---|
| normal fit | small native service and text config | visual management for a Docker/Compose home lab |
| macOS/Linux | official static binary; official Linux packages/service units; community Homebrew | official project path is a pre-built Docker image, so native Alles would also need Docker |
| Compose | official Caddy image and documented persistent config/data volumes | primary documented setup; ports 80, 81, and 443 plus `data` and `letsencrypt` volumes |
| HTTPS | automatic certificates and renewal for qualifying hostnames | Let's Encrypt or custom certificates through the UI |
| WebSockets/streams | explicitly supported by `reverse_proxy` | must pass a real Alles streaming test before managed use; the current project guide does not document the exact Alles behavior |
| forwarded headers | explicit trusted-proxy CIDRs; Alles must trust only the exact proxy IP | generated Nginx config must be tested against Alles's exact trusted-proxy rules |
| wildcard hosts | supported; public wildcard certificates require a DNS challenge/plugin | certificate and routing behavior must be proven with the owner's DNS provider before use |
| admin surface | API defaults to `localhost:2019`; future managed use should prefer a permissioned Unix socket | authenticated visual admin UI on port 81; keep it private and never publish it by default |
| runtime cost | one proxy process; no numeric claim until measured on reference hardware | proxy plus Node application/admin state and Docker; no numeric claim until measured |
| updates | signed/official binary or distro package; validate config, snapshot, replace, restart/reload, health-check, rollback binary/config | snapshot volumes/database and Compose file, pin image, `docker compose pull` then `up -d`, health-check, roll back image and volumes |
| backup | Caddyfile/JSON plus Caddy data/config storage, including certificate state | Compose file, `/data`, `/etc/letsencrypt`, and external database/secret files when configured |
| ownership | controllable only with Alles's dual ownership marker and reviewed service definition | user-managed stacks stay read-only; an Alles-created stack would need the same dual marker and fixed Compose project |

## future Alles-managed Caddy contract

This is the minimum proof before Caddy can become an install option:

1. Show the exact domains, listener addresses, ports, certificate method, upstream, and network impact.
2. Require owner confirmation before any install, port 80/443 bind, firewall/router advice, DNS token,
   or public exposure.
3. Validate the generated config before first start and every update.
4. Proxy a real Alles health request and long streaming response; verify host, scheme, client IP, SSE,
   cookies, upload limits, and cleartext-to-HTTPS behavior.
5. Add only exact proxy CIDRs to Alles. Never trust all forwarded headers.
6. Keep the admin API on a permissioned local socket and never expose it through Alles or the proxy.
7. Store an ownership marker, binary/config hashes, service definition, and exact version.
8. Back up the config and required Caddy state before changes; retain the previous binary/config.
9. On failed health, restore the prior config/binary and leave the loopback Alles server usable.
10. Removal stops only the owned proxy, removes its service/config after confirmation, and never deletes
    an owner-managed proxy or certificate store.

## Nginx Proxy Manager path

If the owner already runs Nginx Proxy Manager, Alles should provide read-only health, setup guidance,
and an admin link. The owner creates the proxy host and certificate. Alles explains the required
upstream (`127.0.0.1` for native proxying or the Alles service name inside an explicitly shared Docker
network) and the exact trusted proxy IP/CIDR.

Alles does not log in to that dashboard, edit its database, pull images, expose port 81, or control the
stack. A future Alles-owned Compose option must independently pass the contract above before it ships.

## sources

- [Nginx Proxy Manager guide](https://nginxproxymanager.com/guide/)
- [Nginx Proxy Manager advanced configuration](https://nginxproxymanager.com/advanced-config/)
- [Nginx Proxy Manager upgrades](https://nginxproxymanager.com/upgrading/)
- [Caddy installation](https://caddyserver.com/docs/install)
- [Caddy service and Compose operation](https://caddyserver.com/docs/running)
- [Caddy automatic HTTPS](https://caddyserver.com/docs/automatic-https)
- [Caddy reverse proxy and WebSockets](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy)
- [Caddy admin API](https://caddyserver.com/docs/api)

## phase decision

Phase 1 ships no proxy installer, proxy credentials, network mutation, or privileged-port action. Server
may identify an externally managed proxy as external and show read-only status only. A future managed
slice starts with Caddy and the contract above; Nginx Proxy Manager remains the visual Compose choice
for owners who deliberately choose that larger setup.
