# reverse-proxy decision

- **checked:** 2026-07-26
- **scope:** optional Alles-owned visual reverse-proxy service
- **decision:** ship Nginx Proxy Manager as a pinned managed companion; leave Caddy owner-managed
- **image:** `jc21/nginx-proxy-manager:2.15.1`

## product boundary

Alles may prepare the pinned image, `/data`, and `/etc/letsencrypt` volumes when Docker Compose is
available. Preparation downloads the image but does not start it. Activation requires exact HTTP and
HTTPS bind addresses and ports, a passing preflight, a typed confirmation phrase, a health probe, and a
tested rollback path. The admin interface stays on loopback port 8181.

Alles does not change DNS, router, firewall, or public exposure settings. It never claims an existing
owner-managed proxy stack. Only matching Alles ownership markers and the unchanged pinned Compose
definition permit lifecycle control.

## credentials and native surface

Nginx Proxy Manager 2.15.1's legacy `INITIAL_ADMIN_PASSWORD` setup path writes the supplied password to
container logs. Alles therefore does not use that path. The owner creates the first administrator in
the loopback-only setup wizard, then connects Server to the local API. The login password is exchanged
once and discarded; only the API token is sealed with the machine-local Alles credential key.

Server then shows proxy hosts and certificate state and can create a typed proxy host with explicit
domains, scheme, destination, port, certificate, and HTTPS choice. Aide receives the same credential-
free typed read and create operations. The private Nginx admin link remains available for unsupported
advanced functions and two-factor login.

## ownership and rollback

- the admin listener is always `127.0.0.1:8181`;
- wildcard network binds are rejected;
- port 80 and 443 conflicts block activation;
- the prepared environment is snapshotted before activation;
- a failed start or health probe restores the environment and stops the stack;
- uninstall removes only Alles's ownership claim and keeps proxy/certificate data recoverable;
- external proxy stacks remain read-only and unmanaged.

## verification boundary

Unit and API tests prove version pinning, preparation without start, secret exclusion from Docker,
encrypted token storage, proxy/certificate reads, typed host creation, ownership failure, and rollback.
A real port-80/443 activation and public certificate issuance remain disposable-VM or isolated-network
scenarios requiring test domains. They are not safe verification actions on the owner's active server.

## sources

- [Nginx Proxy Manager repository and MIT license](https://github.com/NginxProxyManager/nginx-proxy-manager)
- [Nginx Proxy Manager guide](https://nginxproxymanager.com/guide/)
- [Nginx Proxy Manager 2.15.1 token route](https://github.com/NginxProxyManager/nginx-proxy-manager/blob/v2.15.1/backend/routes/tokens.js)
- [Nginx Proxy Manager 2.15.1 setup behavior](https://github.com/NginxProxyManager/nginx-proxy-manager/blob/v2.15.1/backend/setup.js)
