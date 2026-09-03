# DEX Core Deployment Notes

DEX is currently a core framework only. No vendor is operationally supported
and no phone configuration files are generated.

## Encryption key

DEX secret fields require a stable Fernet key supplied outside the source tree
and SQLite. Configure exactly one of:

```text
DEX_ENCRYPTION_KEY=<44-character URL-safe Fernet key>
```

or:

```text
DEX_ENCRYPTION_KEY_FILE=/etc/asterisk/rcm_dex.key
```

The key file must already exist, contain one valid Fernet key, and have mode
`0600` or stricter. DEX does not generate a replacement key. If no key is
available, saving a DEX secret fails safely.

For URL-bearing normalized settings, configure an explicit comma-separated
allowlist before saving values:

```text
DEX_ALLOWED_URL_HOSTS=provisioning.example.invalid,firmware.example.invalid
```

Private or loopback URL targets are rejected unless a future controlled policy
explicitly permits them.

## Discovery policy

Only private CIDR ranges are accepted by default. Additional approved ranges
must be supplied through:

```text
DEX_ALLOWED_CIDRS=10.0.0.0/8,192.168.0.0/16
```

Discovery is limited to 256 hosts, 32 concurrent probes, bounded per-host
timeouts, and a 300-second total timeout. It uses no device credentials and
does not modify devices.

## Migration

The additive DEX migration runs from `db.init_db()` using the DEX-safe SQLite
connection. It records version 1 in `dex_schema_versions` and is idempotent.
Back up `rcm_7021.db` before deployment.

## Rollback

To disable DEX code, remove the DEX blueprint registration and DEX sidebar
integration from the deployed application version, then restart the service.
The migration is intentionally non-destructive; retain DEX tables for a later
re-enable or remove them only through a separately reviewed maintenance
procedure after a verified database backup.

