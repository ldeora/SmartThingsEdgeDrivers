# Register the Computer Host monitoring capabilities

The Linux profile `computer-host-linux` uses five shared capabilities and the Linux-specific `linuxLoad` capability under the
expected developer namespace `oceancircle09600`. The capability definitions and
presentations are version 1. They must be registered in the SmartThings developer
account **before** packaging/installing the advanced Edge Driver.

In the complete integration archive, this guide is at
`edge-driver/custom-capabilities/REGISTER.md`. If you extracted the standalone
capability bundle, it preserves the same `edge-driver/custom-capabilities/`
subdirectory layout; run the CLI registration commands from that `edge-driver/`
directory, then switch to the complete integration or Edge Driver project to
package the driver.

The namespace is account-owned. Confirm it first:

```sh
smartthings capabilities:namespaces
```

The account used for the existing `oceancircle09600.vtempset` and related custom
capabilities should report `oceancircle09600`. The definition names are chosen
so SmartThings generates the IDs expected by the driver (for example, `Linux
Cpu Usage` becomes `computerCpuUsage`). The `capabilities:create` command defaults to an account-selected namespace,
which may *not* be `oceancircle09600` even if that namespace exists. Always
supply `--namespace oceancircle09600`; the JSON definition itself does not
select a namespace. Verify each returned ID before creating the presentation.

Check whether any of these capability IDs already exist:

```sh
smartthings capabilities
```

Do not create duplicates. For a capability that does not exist, run its create
command and then create its presentation. The capability ID is generated from
its `name` (for example, `Computer Host Status` becomes `computerHostStatus`); verify
the ID returned by each create command before using it in the presentation
command. Before creating, change to the `edge-driver/` directory:

```sh
cd edge-driver
smartthings capabilities:create --namespace oceancircle09600 -i custom-capabilities/computerHostStatus.json
smartthings capabilities:presentation:create oceancircle09600.computerHostStatus \
  -i custom-capabilities/computerHostStatus.presentation.json
```

Run the remaining commands from the `edge-driver/` directory:

```sh
smartthings capabilities:create --namespace oceancircle09600 -i custom-capabilities/computerCpuUsage.json
smartthings capabilities:presentation:create oceancircle09600.computerCpuUsage -i custom-capabilities/computerCpuUsage.presentation.json

smartthings capabilities:create --namespace oceancircle09600 -i custom-capabilities/computerMemoryUsage.json
smartthings capabilities:presentation:create oceancircle09600.computerMemoryUsage -i custom-capabilities/computerMemoryUsage.presentation.json

smartthings capabilities:create --namespace oceancircle09600 -i custom-capabilities/computerDiskUsage.json
smartthings capabilities:presentation:create oceancircle09600.computerDiskUsage -i custom-capabilities/computerDiskUsage.presentation.json

smartthings capabilities:create --namespace oceancircle09600 -i custom-capabilities/computerUptime.json
smartthings capabilities:presentation:create oceancircle09600.computerUptime -i custom-capabilities/computerUptime.presentation.json

smartthings capabilities:create --namespace oceancircle09600 -i custom-capabilities/linuxLoad.json
smartthings capabilities:presentation:create oceancircle09600.linuxLoad -i custom-capabilities/linuxLoad.presentation.json
```

For an already-existing capability, inspect it with `smartthings capabilities <id>`
and its presentation with `smartthings capabilities:presentation <id>`. If its
schema differs from these files, update it deliberately with
`smartthings capabilities:update <id> -i <definition.json>` and
`smartthings capabilities:presentation:update <id> -i <presentation.json>`.
Do not overwrite a capability that is used by another driver without checking
its current schema and consumers first.

After all six capabilities and presentations have been created or verified,
return to the complete integration root and package/install the Edge Driver:

```sh
cd ..
smartthings edge:drivers:package edge-driver/ --install
```

If you used the standalone capability bundle, this final packaging command must
instead be run from the extracted complete integration directory (or use the
separate Edge Driver ZIP after registration).

The package contains `computer-host` (standard-capability fallback),
`computer-host-linux`, and `computer-host-windows` profiles. The advanced profile is selected by default.
This development build uses a new device identity; delete the old Linux Host device and install the new agent/driver together. No migration is provided.

Verify the resulting attributes with:

```sh
smartthings devices:status <device-id>
```

Custom capability definitions and presentations are account-level SmartThings
resources. They are not local files that the Edge hub imports from the driver ZIP.

## Additive disk capacity attribute (post-beta)

The proposed `diskTotalGiB` field is an **account-level capability schema change**
to the existing `oceancircle09600.computerDiskUsage` capability. Do not assume
that packaging the Edge Driver or running `publish-presentations.sh` applies
the schema. Review and follow the staged registration, translation, presentation
and agent rollout in [DISK-CAPACITY-ROLLOUT.md](../../docs/development/DISK-CAPACITY-ROLLOUT.md).
Do **not** run `capabilities:create` again or update the public channel
before verifying the live schema and presentation on the test hub.

## Development v0.4.0: Create new generic capabilities, then update presentations

If all six capabilities already exist in `oceancircle09600`, DO NOT run
`capabilities:create` again. New localization and label changes modify
**account-level resources**; they are NOT applied by Edge driver installation.

From the full-integration root:

```sh
./scripts/publish-presentations.sh          # dry run only
./scripts/publish-presentations.sh --apply  # 12 translations, 6 presentations
```

The second command runs `smartthings capabilities:translations:upsert` for
`en` and `de`, followed by `smartthings capabilities:presentation:update` for
each of the six existing capability IDs. Inspect and back up existing
presentations before applying this cloud-wide change, because another device
using the same capability could also change appearance. Do not edit the six
capability definitions/attribute types; this release does not require them to
be updated. If any API call fails, stop and inspect it rather than attempting
to delete/recreate capabilities.

The standard `temperatureMeasurement` and `momentary` UI presentations are
owned by SmartThings, not this driver. We retain them unchanged to avoid
breaking those shared standard capabilities; more specialized button labels
and a CPU-specific temperature card remain a future device-presentation task.
