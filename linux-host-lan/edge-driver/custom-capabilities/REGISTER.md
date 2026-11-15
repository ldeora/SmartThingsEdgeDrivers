# Register the Linux Host monitoring capabilities

The enhanced `linux-host-advanced` profile uses six custom capabilities under the
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
Cpu Usage` becomes `linuxCpuUsage`). The `capabilities:create` command defaults to an account-selected namespace,
which may *not* be `oceancircle09600` even if that namespace exists. Always
supply `--namespace oceancircle09600`; the JSON definition itself does not
select a namespace. Verify each returned ID before creating the presentation.

Check whether any of these capability IDs already exist:

```sh
smartthings capabilities
```

Do not create duplicates. For a capability that does not exist, run its create
command and then create its presentation. The capability ID is generated from
its `name` (for example, `Linux Host Status` becomes `linuxHostStatus`); verify
the ID returned by each create command before using it in the presentation
command. Before creating, change to the `edge-driver/` directory:

```sh
cd edge-driver
smartthings capabilities:create --namespace oceancircle09600 -i custom-capabilities/linuxHostStatus.json
smartthings capabilities:presentation:create oceancircle09600.linuxHostStatus \
  -i custom-capabilities/linuxHostStatus.presentation.json
```

Run the remaining commands from the `edge-driver/` directory:

```sh
smartthings capabilities:create --namespace oceancircle09600 -i custom-capabilities/linuxCpuUsage.json
smartthings capabilities:presentation:create oceancircle09600.linuxCpuUsage -i custom-capabilities/linuxCpuUsage.presentation.json

smartthings capabilities:create --namespace oceancircle09600 -i custom-capabilities/linuxMemoryUsage.json
smartthings capabilities:presentation:create oceancircle09600.linuxMemoryUsage -i custom-capabilities/linuxMemoryUsage.presentation.json

smartthings capabilities:create --namespace oceancircle09600 -i custom-capabilities/linuxDiskUsage.json
smartthings capabilities:presentation:create oceancircle09600.linuxDiskUsage -i custom-capabilities/linuxDiskUsage.presentation.json

smartthings capabilities:create --namespace oceancircle09600 -i custom-capabilities/linuxUptime.json
smartthings capabilities:presentation:create oceancircle09600.linuxUptime -i custom-capabilities/linuxUptime.presentation.json

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

The package contains both `linux-host` (standard-capability fallback) and
`linux-host-advanced` profiles. The advanced profile is selected by default.
Existing `Linux examplehost` devices request a profile metadata update through
`device:try_update_metadata`; they do not need to be deleted or re-paired.

Verify the resulting attributes with:

```sh
smartthings devices:status <device-id>
```

Custom capability definitions and presentations are account-level SmartThings
resources. They are not local files that the Edge hub imports from the driver ZIP.

## v0.2.9: Update existing presentations and translations (no re-registration)

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
