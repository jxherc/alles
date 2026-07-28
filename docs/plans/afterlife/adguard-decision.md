# adguard home decision

- **checked:** 2026-07-26
- **scope:** optional Alles-owned network-wide DNS filtering
- **decision:** ship AdGuard Home as a pinned, independently licensed managed companion
- **image:** `adguard/adguardhome:v0.107.78`

## product boundary

Alles may prepare the pinned image and private data when Docker Compose is available. Preparation never
starts the service or claims a network listener. Activation is a separate recent-owner action with an
exact interface, TCP/UDP port checks, a typed confirmation phrase, a private admin credential, a
configuration snapshot, a health probe, and automatic rollback on failure.

Alles does not change router, DHCP, firewall, or operating-system DNS settings. The owner must make
those network changes separately after the isolated activation has been tested. Removal and rollback
retain the service data and restore the previous listener/configuration files.

## native surface

Server shows lifecycle and health, daily query and blocked counts, bounded recent DNS activity,
filtering state, and DNS rewrites through AdGuard Home's published API. Filtering and rewrite changes
are typed Alles operations with audit records. Aide receives the same typed operations; its model never
receives the stored admin password.

The generated password is sealed with Alles's machine-local credential key. The AdGuard configuration
contains only its bcrypt digest. The credential file is included in credential inventory, rotation,
backup validation, and recovery dependency checks.

## ownership and failure rules

- only the exact Alles Compose definition and matching dual ownership markers permit lifecycle control;
- a modified Compose file, environment, symlink, or ownership marker disables control;
- DNS cannot bind to a wildcard interface through this flow;
- port 53 is checked for both TCP and UDP before activation;
- setup/admin remains on loopback port 3000;
- activation failure restores the previous environment and AdGuard configuration, then stops the stack;
- external AdGuard instances are never claimed or modified.

## verification boundary

Unit and API tests prove definition pinning, secret handling, preflight, activation failure, rollback,
typed dashboard calls, filtering, rewrites, and Aide scopes. A real port-53 activation remains an
isolated-network or disposable-VM scenario. It must not be run on the owner's active network as a test.

## sources

- [AdGuard Home repository and GPL-3.0 license](https://github.com/AdguardTeam/AdGuardHome)
- [AdGuard Home OpenAPI](https://github.com/AdguardTeam/AdGuardHome/blob/master/openapi/openapi.yaml)
- [AdGuard Home configuration reference](https://github.com/AdguardTeam/AdGuardHome/wiki/Configuration)
