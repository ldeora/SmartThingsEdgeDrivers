# Computer Host LAN — visual prototype

This is a standalone **inert demonstration**, not the
real installer, and is not included in the production installer executable.
It uses only example data and in-memory navigation. It does not inspect the
host, discover or contact the hub, access credentials or backup files, launch
subprocesses, request elevation, or perform installation operations. The
example progress advances only on a key press, not a transaction event.
The production installer and its accessible and CLI paths are untouched.

From a trusted checkout, with the repository's normal Go toolchain:

```sh
cd computer-host-lan/linux-installer
go test ./ui-demo
CGO_ENABLED=0 go run ./ui-demo
```

For a monochrome preview:

```sh
NO_COLOR=1 CGO_ENABLED=0 go run ./ui-demo
```

Use a terminal at least 64 columns by 22 rows (100x28 or larger for the
sidebar layout). Arrow keys or number keys highlight maintenance tasks;
Enter selects. Tab moves between power and WOL choices. Shift+Tab or Esc
goes back; Q or Ctrl+C exits. The sample upgrade/configure/repair flow
has a welcome, hub selection, power/WOL, review, manually advanced simulated
progress, and completion. Inspect, backup selection and other operations
have sample views only. The hub examples use reserved TEST-NET addresses;
no manual address entry or real authorization is connected.

## Review checklist

- [ ] Visual identity, contrast, density, keyboard navigation and footer.
- [ ] Sidebar at 88+ columns, compact layout below that threshold.
- [ ] Resize during each screen; small-window handling and exit.
- [ ] Monochrome selection still clear; light/dark terminals and 256 colors.
- [ ] Terminal restored after normal exit, Escape and Ctrl+C.
- [ ] No changes to the running agent, device or private state.

This inert demo is not evidence of live installer acceptance. See the
[production engineering contract](../../docs/reference/linux-installer.md).
