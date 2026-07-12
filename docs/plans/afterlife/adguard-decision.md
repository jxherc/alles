# adguard home decision

- **checked:** 2026-07-12
- **scope:** optional network-wide DNS filtering beside Alles
- **decision:** keep AdGuard Home external and optional; do not install or manage it in Phase 1
- **phase result:** Alles makes no DNS, DHCP, router, firewall, static-address, or port-53 change

## short answer

AdGuard Home can be useful for network-wide tracker/domain blocking and friendly local DNS rewrites. It
is not a normal Alles dependency. Making it the router's DNS server changes connectivity for every
device, normally needs a stable LAN address and port 53, can conflict with an existing resolver, and can
break name resolution when the service or host is down.

The safe Alles behavior is read-only: explain setup, check health when the owner provides an address,
and open the external admin page. Installation and router changes stay manual until a later advanced
flow proves the approval and rollback contract below.

## linked-video check

The original brainstorm linked [“what's on my home server 2026”](https://youtu.be/kwLgfYCZFto).
The reviewed section from about 6:23 to 7:08 describes AdGuard Home as the pfSense network's DNS server,
uses it to block ad/tracker domains, and uses DNS rewrites to send friendly names to Nginx Proxy Manager.

That is the useful pattern Alles should explain. Two limits matter:

- DNS rewriting and reverse proxying are separate jobs. AdGuard resolves a name to an address; the
  proxy terminates HTTPS and routes HTTP traffic.
- DNS filtering cannot remove ads that share a domain with wanted content. AdGuard's own FAQ names
  YouTube, Twitch, and social sponsored posts as examples.

## network and privilege impact

The official first-run guide lists 3000/TCP for setup, 80/TCP for the web UI, and 53/UDP for DNS. Other
DNS protocols need more ports. Binding port 53 usually needs elevated privileges; Linux can instead
grant narrow capabilities, but that is still a privileged host change. Ubuntu may already have
`systemd-resolved` on port 53.

A network-wide deployment also needs:

- a stable LAN address or reservation for the AdGuard host;
- a router/DHCP setting or a per-device DNS change;
- an authenticated admin account and an admin listener limited to the intended interface;
- a known previous DNS configuration and a way to restore it without using DNS;
- a tested answer for host reboot, service failure, and port conflict.

Alles must never guess or automatically perform those changes.

## ownership and access

| case | Alles behavior |
|---|---|
| owner already runs AdGuard Home | store only an owner-approved admin/health address, show external status and setup help, and open the admin page |
| service is missing or unhealthy | show DNS may be affected; do not restart, reinstall, edit router settings, or change the current machine's resolver |
| future Alles-installed instance | require a dedicated dual ownership marker, fixed service definition, explicit interface/port/static-IP plan, capability review, backup, and removal path |
| admin exposure | bind only to loopback or the intended LAN interface; never expose the setup/admin UI publicly by default |

The current Server service manager already refuses lifecycle control for external or mismatched
services. AdGuard stays in that external category.

## update, backup, and rollback

Native AdGuard Home can update from its UI/CLI. Its guide says the previous binary and configuration
are placed in a backup directory for rollback. Docker/Home Assistant/Snap installations do not
auto-update; their image must be updated separately.

Before any future Alles-owned update:

1. stop new mutations and record the current version;
2. copy `AdGuardHome.yaml` and the complete `data/` directory to a private backup;
3. retain the previous binary or pinned container image and service definition;
4. update, restart, validate the config, query a known allowed domain and a known blocked test domain,
   and confirm the admin listener remains private;
5. on failure, restore the old binary/image, config, and data, then repeat the DNS probes;
6. if DNS still fails, tell the owner to restore the recorded router/device DNS values.

Removal must first restore router/device DNS and prove normal resolution without AdGuard. Only then may
an owned service be stopped and removed. An external instance is never removed by Alles.

## failure isolation

Using only the AdGuard host as router DNS makes that host a network dependency. Adding a public
secondary DNS can improve availability but lets some clients bypass filtering; whether a router honors
primary/secondary order also varies. Alles therefore cannot promise redundancy from a generic second
address.

A future managed flow must show this plainly and require one tested recovery path:

- restore the previous router/DHCP DNS values;
- configure a second owner-operated AdGuard instance; or
- accept that filtering can be bypassed during failover.

The recovery instructions must be saved somewhere reachable without Alles or working DNS.

## exact approval gate for any future install

Before Alles changes anything, the owner must see and approve:

1. installation type and exact version;
2. host/interface and stable IP requirement;
3. every TCP/UDP port and any current conflict;
4. privilege/capability, service, and firewall changes;
5. admin URL, bind scope, and authentication requirement;
6. router/DHCP or per-device DNS values before and after;
7. upstream resolvers, filter lists, logging/privacy choices, and DNS rewrites;
8. backup location and secret handling;
9. health test, failure effect, rollback commands, and offline copy of them;
10. removal order that restores DNS before stopping the service.

No single **enable AdGuard** switch is safe enough.

## sources

- [linked home-server video](https://youtu.be/kwLgfYCZFto)
- [AdGuard Home overview](https://adguard-dns.io/kb/adguard-home/overview/)
- [AdGuard Home getting started, ports, devices, and updates](https://adguard-dns.io/kb/adguard-home/getting-started/)
- [AdGuard Home secure binding guidance](https://adguard-dns.io/kb/adguard-home/running-securely/)
- [AdGuard Home FAQ, port conflicts, limits, and reverse proxies](https://adguard-dns.io/kb/adguard-home/faq/)
- [AdGuard Home configuration reference](https://github.com/AdguardTeam/AdGuardHome/wiki/Configuration)

## phase decision

Phase 1 does not install AdGuard Home, claim port 53, edit router DNS, or merge DNS with reverse proxy
setup. An external AdGuard instance may appear only as read-only status/setup context. A later managed
proposal must pass the exact approval, backup, failure, and rollback rules above.
