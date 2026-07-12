# kopia backup-engine spike

- **checked:** 2026-07-12
- **tested version:** Kopia CLI 0.23.1, macOS arm64
- **release asset SHA-256:** `19e6ed637221f4dfd46a46e978ec4c509c386b522d746db2cd6762b217478111`
- **scope:** use Kopia behind the existing encrypted `.alles-backup` format and staged restore rules
- **decision:** do not add Kopia to Alles now; keep the portable encrypted archive as the backup engine

## short answer

Kopia itself worked. The proposed layering did not.

The spike created two real encrypted Alles backups from almost the same 12.6 MB synthetic source. Kopia
restored the second artifact byte-for-byte after the original install and local Kopia client state were
deleted. Alles then decrypted it with the separately held recovery key, staged it, and passed two boot
and migration probes.

But the second encrypted artifact added essentially its full size to the Kopia repository. Fresh outer
encryption changes the ciphertext, so Kopia cannot find the unchanged chunks inside it. Adopting Kopia
this way would add a binary, repository password, configuration, maintenance, and another restore step
without delivering useful incremental backup.

## measured result

| proof | result |
|---|---|
| official release integrity | downloaded Kopia 0.23.1 from its official GitHub release and matched the published SHA-256 |
| local provider | `repository validate-provider` passed against a throwaway filesystem repository |
| repository encryption | reported `AES256-GCM-HMAC-SHA256`; synthetic password, marker text, and recovery-key document were absent from repository/config bytes |
| first encrypted artifact | 12,605,912 bytes; repository content became 12,607,670 bytes |
| second near-identical source | encrypted artifact was 12,605,916 bytes |
| incremental result | second snapshot added 12,607,022 bytes, or `1.0001×` the second artifact size |
| credential failure | a clean client with the wrong repository password was rejected |
| source-loss recovery | original install and artifact were deleted; a clean client reconnected and restored the exact SHA-256 |
| Alles restore contract | separate recovery key decrypted the artifact; staging restored the newest marker and passed two boot/migration probes |
| target surface | the tested CLI exposes filesystem, S3, and WebDAV repository commands; official docs list all three |

The `1.0001×` number includes small snapshot metadata, which is why it is slightly above one. It still
shows that wrapping independently encrypted Alles artifacts provides no meaningful cross-backup
deduplication.

## why not snapshot live data directly

Kopia can deduplicate ordinary files. Pointing it at live `ALLES_DATA` would bypass the rules Alles just
proved:

- SQLite must be snapshotted consistently instead of copying live WAL files.
- the keyring, Settings, connector configs, managed files, and manifest must all come from one frozen
  point in time;
- every known credential must be authenticated before the backup is accepted;
- restores must pass manifest/path/checksum limits, stage offline, migrate, boot, and keep rollback;
- the recovery key must remain separate from the lost server.

Using Kopia below the `.alles-backup` encryption layer could preserve deduplication, but then Kopia would
become a new backup format and recovery dependency. That needs a separate design for frozen plaintext
staging, repository-password recovery, binary installation/upgrades, cross-version compatibility,
maintenance, remote credential reuse, and fallback when Kopia is missing. Phase 1 does not weaken the
portable restore path to gain that complexity.

## target support checked

Kopia's current official repository documentation lists local filesystems, S3-compatible storage, and
WebDAV. The 0.23.1 CLI also exposes create/connect commands for each.

- [Kopia repositories and supported storage](https://kopia.io/docs/repositories/)
- [Kopia encryption](https://kopia.io/docs/advanced/encryption/)
- [Kopia command reference](https://kopia.io/docs/reference/command-line/common/)
- [Kopia installation and release verification](https://kopia.io/docs/installation/)
- [Kopia official releases](https://github.com/kopia/kopia/releases)

Only the local filesystem provider was exercised with real writes because this decision does not ship
Kopia for any destination. The existing Alles WebDAV and S3-compatible targets keep their own full
source-deletion recovery gates.

## reproduce

Download the official Kopia CLI, verify it against the release checksum, then run:

```bash
python scripts/kopia_spike.py --kopia /absolute/path/to/kopia
```

The script uses temporary synthetic data only. It disables file logging, update checks, Keychain use,
and credential persistence. It removes the temporary repository and clients when the run ends.

## phase decision

The Kopia spike is complete, and Kopia remains unavailable in Alles. This is the safe fallback required
by the Afterlife design. Local, WebDAV, and S3-compatible backup continue to use the same portable,
encrypted, manifest-checked artifact and the same offline staged restore path.

Revisit Kopia only if a later plan proves all of these without weakening that path:

1. snapshot the frozen recovery tree below outer encryption and keep plaintext staging private;
2. recover after losing the original install, Kopia client config, and cached state;
3. restore with a clean supported Kopia version and a separately saved repository password;
4. pass the full manifest, credential, staging, repeat-boot, and rollback gates;
5. pass live local, WebDAV, and S3 provider validation plus interruption tests;
6. define installation, signed updates, compatibility support, maintenance, removal, and fallback.
