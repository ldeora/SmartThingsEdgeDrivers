# Linux standalone installer

For installation and maintenance, start with [Install on Linux](../docs/install-linux.md)
and [Upgrade and maintenance](../docs/upgrade.md). Use only the verified,
version-matched published executable for installation.

Contributors: see [build and test](../docs/development.md#build-and-test)
and the [protected installer engineering contract](../docs/reference/linux-installer.md).
The Go wizard and noninteractive CLI share the protected Python engine.
Changes to authoritative embedded sources require regenerating and checking
the bundle in the same commit:

```sh
python3 sync_bundle.py
python3 sync_bundle.py --check
go test ./...
```

Never elevate a development checkout or ordinary CI artifact.

## Troubleshooting discovery and connectivity

See [Firewall and Avahi](../docs/troubleshooting.md#firewall-and-avahi).
