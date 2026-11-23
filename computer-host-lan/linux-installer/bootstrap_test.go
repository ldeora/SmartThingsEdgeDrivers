package main

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

// CI-only root smoke test for the actual installed-only Python entrypoint.
// Never run against a developer's host or use the installation action.
// It provisions ONLY the trusted helper bundle in an ephemeral GitHub runner.
func TestRootInstalledHelperStatusSmoke(t *testing.T) {
	if os.Getenv("GITHUB_ACTIONS") != "true" ||
		os.Getenv("COMPUTER_HOST_CI_ROOT_SMOKE") != "1" {
		t.Skip("only invoked explicitly on a disposable GitHub Actions runner")
	}
	if os.Geteuid() != 0 {
		t.Fatal("root smoke must run with the expected GitHub Actions sudo context")
	}
	if _, err := os.Lstat(trustedDir); err == nil {
		t.Fatal("refusing to overwrite a previously installed trusted helper")
	} else if !os.IsNotExist(err) {
		t.Fatal(err)
	}
	for _, suffix := range []string{".next", ".previous", ".failed"} {
		if _, err := os.Lstat(trustedDir + suffix); err == nil {
			t.Fatal("refusing to disturb an existing helper staging artifact")
		} else if !os.IsNotExist(err) {
			t.Fatal(err)
		}
	}
	t.Cleanup(func() {
		// Only the exclusive, just-created CI helper path can be removed.
		// Do not touch /var/lib/linux-host-agent or managed systemd units.
		if err := os.RemoveAll(trustedDir); err != nil {
			t.Errorf("unable to clean CI-only root helper fixture: %v", err)
		}
	})
	changed, err := prepareTrustedVersion(trustedDir, trustedLock, 0,
		func() (string, error) {
			t.Fatal("fresh root fixture must not call an old installed helper")
			return "", nil
		})
	if err != nil || changed {
		t.Fatalf("failed to stage CI root helper: changed=%t err=%v", changed, err)
	}
	request := privilegedRequest{SchemaVersion: 1, Action: "status"}
	reply, helperErr := runInstalledHelper(trustedDir, request)
	if helperErr != nil || reply.Status != "passed" ||
		reply.PrivilegedTransactionState != "none" {
		// This runner has no agent installation or protected state.
		// On failure the captured stderr is exclusively from ephemeral
		// CI helper code; never perform this diagnostic on a user's host.
		cmd := exec.Command("/bin/sh", filepath.Join(trustedDir, "installer-entry.sh"), "--request-stdin")
		cmd.Stdin = strings.NewReader(`{"schema_version":1,"action":"status"}`)
		cmd.Env = []string{"PATH=/usr/sbin:/usr/bin:/sbin:/bin", "HOME=/root", "LANG=C", "LC_ALL=C"}
		var out, stderr cappedBuffer
		cmd.Stdout, cmd.Stderr = &out, &stderr
		processErr := cmd.Run()
		t.Fatalf("root-installed read-only status failed: helperErr=%v, reply=%+v, processErr=%v, stdout=%q, stderr=%q",
			helperErr, reply, processErr, out.Bytes(), stderr.Bytes())
	}
	// Reproduce the already deployed root-owned helper that fails to select
	// Python when Gentoo reports /usr/sbin/python3. The explicit legacy
	// fallback must verify the trusted script fingerprint and query only
	// status through installer_root.py; it must not touch any agent files.
	legacy, err := os.ReadFile("testdata/installer-entry-gentoo-legacy.sh")
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(trustedDir, "installer-entry.sh"), legacy, 0o755); err != nil {
		t.Fatal(err)
	}
	status, err := legacyHelperStatusWithSystemPython(trustedDir)
	if err != nil || status.Status != "passed" ||
		status.PrivilegedTransactionState != "none" {
		t.Fatalf("Known Gentoo legacy helper status fallback failed: %+v %v", status, err)
	}
	// Exercise the safe promotion path against that known old launcher:
	// it may be replaced only after the read-only status succeeds.
	changed, err = prepareTrustedVersion(trustedDir, trustedLock, 0,
		func() (string, error) {
			resp, err := legacyHelperStatusWithSystemPython(trustedDir)
			return resp.PrivilegedTransactionState, err
		})
	if err != nil || !changed {
		t.Fatalf("Safe replacement of a recognized legacy helper failed: %+v %v", changed, err)
	}
	status, err = runInstalledHelper(trustedDir,
		privilegedRequest{SchemaVersion: 1, Action: "status"})
	if err != nil || status.Status != "passed" ||
		status.PrivilegedTransactionState != "none" {
		t.Fatalf("Corrected promoted root helper cannot report status: %+v %v", status, err)
	}
	if err := retirePreviousTrustedVersion(trustedDir, 0); err != nil {
		t.Fatal(err)
	}
}

func TestTrustedHelperMissingPythonErrorIsSanitized(t *testing.T) {
	request := privilegedRequest{SchemaVersion: 1, Action: "status"}
	cmd := exec.Command("/bin/sh", "-c",
		"printf '%s\\n' 'Python 3.10+ is required (install a compatible system Python interpreter).' >&2; exit 2")
	if _, err := runTrustedHelperCommand(cmd, request); !errors.Is(err, errUnavailablePython) {
		t.Fatalf("Legacy Python selection failure was not recognized safely: %v", err)
	}
	cmd = exec.Command("/bin/sh", "-c", "printf 'unrelated sensitive stderr\\n' >&2; exit 2")
	if _, err := runTrustedHelperCommand(cmd, request); !errors.Is(err, errInvalidHelperResponse) {
		t.Fatalf("Untrusted stderr was incorrectly interpreted as a known error: %v", err)
	}
	var out bytes.Buffer
	if err := relayBootstrapFailure(&out, "upgrade", errUnavailablePython); err == nil {
		t.Fatal("Missing system Python must be a failed bootstrap")
	}
	var reply privilegedResult
	if err := json.Unmarshal(out.Bytes(), &reply); err != nil ||
		reply.ErrorCode != "unsupported_python" || reply.SecretsIncluded ||
		reply.Operation != "upgrade" {
		t.Fatalf("Safe missing-Python envelope corrupted: %+v, %v", reply, err)
	}
}

func TestGentooSystemPythonPathAndExactLegacyLauncherRecognition(t *testing.T) {
	launcher, err := os.ReadFile("../scripts/installer-entry.sh")
	if err != nil {
		t.Fatal(err)
	}
	for _, directory := range []string{"/usr/sbin/*", "/usr/bin/*", "/sbin/*", "/bin/*"} {
		if !bytes.Contains(launcher, []byte(directory)) {
			t.Fatalf("Installed launcher does not accept fixed trusted system directory %s", directory)
		}
	}
	legacy, err := os.ReadFile("testdata/installer-entry-gentoo-legacy.sh")
	if err != nil {
		t.Fatal(err)
	}
	if !knownGentooLauncherBug(legacy) {
		t.Fatal("The reviewed legacy-launcher checksum no longer matches the fixture")
	}
	if knownGentooLauncherBug(launcher) {
		t.Fatal("The corrected launcher must not be accepted as the legacy defective version")
	}
	corrupted := append([]byte{}, legacy...)
	corrupted[len(corrupted)-1] ^= 1
	if knownGentooLauncherBug(corrupted) {
		t.Fatal("A modified launcher must not trigger the narrow recovery path")
	}
}

func TestEmbeddedFilesMatchAuthoritativeRepository(t *testing.T) {
	if err := validateEmbeddedBundle(); err != nil {
		t.Fatal(err)
	}
	for _, name := range append(append([]string{}, payloadFiles...), append(installedHelpers, "installer-api.sh", "installer_api.py", "python-selector.sh")...) {
		source := name
		if !strings.Contains(name, "/") {
			source = "scripts/" + name
		}
		got, err := bundleRead(source)
		if err != nil {
			t.Fatal(err)
		}
		expected, err := os.ReadFile(filepath.Join("..", filepath.FromSlash(source)))
		if err != nil {
			t.Fatal(err)
		}
		if !bytes.Equal(got, expected) {
			t.Errorf("Embedded %s differs from the reviewed source of truth", source)
		}
	}
}

func TestEmbeddedManifestMatchesPayloadBytes(t *testing.T) {
	raw, err := manifestFromEmbedded()
	if err != nil {
		t.Fatal(err)
	}
	var parsed struct {
		SchemaVersion int               `json:"schema_version"`
		AgentVersion  string            `json:"agent_version"`
		Files         map[string]string `json:"files"`
	}
	if err := json.Unmarshal(raw, &parsed); err != nil {
		t.Fatal(err)
	}
	if parsed.SchemaVersion != 1 || parsed.AgentVersion == "" ||
		len(parsed.Files) != len(payloadFiles) {
		t.Fatalf("Unexpected embedded manifest: %#v", parsed)
	}
	for _, name := range payloadFiles {
		file, err := bundleRead(name)
		if err != nil {
			t.Fatal(err)
		}
		hash := sha256.Sum256(file)
		if parsed.Files[name] != hex.EncodeToString(hash[:]) {
			t.Errorf("Digest mismatch for %s", name)
		}
	}
}

func TestEmbeddedRootHelperStageHasExpectedContentAndModes(t *testing.T) {
	temp := filepath.Join(t.TempDir(), "trusted-helper.next")
	if err := os.Mkdir(temp, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := writeEmbeddedSet(temp); err != nil {
		t.Fatal(err)
	}
	for _, name := range installedHelpers {
		info, err := os.Stat(filepath.Join(temp, name))
		if err != nil {
			t.Fatal(err)
		}
		mode := os.FileMode(0o644)
		if strings.HasSuffix(name, ".sh") {
			mode = 0o755
		}
		if info.Mode().Perm() != mode {
			t.Errorf("Incorrect installed mode %s: %o", name, info.Mode().Perm())
		}
	}
	for _, name := range payloadFiles {
		location := filepath.Join(temp, "payload", filepath.FromSlash(name))
		info, err := os.Stat(location)
		if err != nil {
			t.Fatal(err)
		}
		if info.Mode().Perm() != 0o600 {
			t.Errorf("Embedded payload %s mode: %o", name, info.Mode().Perm())
		}
	}
	manifest, err := os.ReadFile(filepath.Join(temp, "trusted-payload.json"))
	if err != nil {
		t.Fatal(err)
	}
	expected, err := manifestFromEmbedded()
	if err != nil || !bytes.Equal(manifest, expected) {
		t.Fatal("Trusted manifest differs from embedded payload")
	}
}

func TestPrivilegedRequestDoesNotAllowUserChosenSourcesOrShell(t *testing.T) {
	normal := privilegedRequest{SchemaVersion: 1, Action: "install", Power: "preserve"}
	marshalled, err := json.Marshal(normal)
	if err != nil {
		t.Fatal(err)
	}
	got, err := decodePrivilegedRequest(bytes.NewReader(marshalled))
	if err != nil {
		t.Fatal(err)
	}
	python, err := pythonRequest(got)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Contains(python, []byte(trustedDir+"/payload")) {
		t.Fatal("Python source must be fixed to the installed embedded payload")
	}
	for _, bad := range []string{
		`{"schema_version":1,"action":"install","power":"preserve","source":"/tmp/bad"}`,
		`{"schema_version":1,"action":"install","power":"preserve","command":"id"}`,
		`{"schema_version":1,"action":"install","power":"preserve","wol_interface":"eth0;id"}`,
		`{"schema_version":1,"action":"uninstall"}`,
		`{"schema_version":1,"action":"install","power":"preserve","python":"/tmp/python"}`,
	} {
		t.Run(bad, func(t *testing.T) {
			if _, err := decodePrivilegedRequest(strings.NewReader(bad)); err == nil {
				t.Fatal("Unexpectedly accepted unsafe privileged request")
			}
		})
	}
	long := strings.NewReader(strings.Repeat("X", 4097))
	if _, err := decodePrivilegedRequest(long); err == nil {
		t.Fatal("Oversized privileged request accepted")
	}
	if _, err := decodePrivilegedRequest(io.LimitReader(strings.NewReader(""), 0)); err == nil {
		t.Fatal("Empty privileged request accepted")
	}
}

func TestBootstrapLifetimeLockBlocksConcurrentVersionReplacement(t *testing.T) {
	if os.Geteuid() == 0 {
		t.Skip("non-root lock fixture only")
	}
	path := filepath.Join(t.TempDir(), "bootstrap.lock")
	first, err := lockInstaller(path, os.Geteuid())
	if err != nil {
		t.Fatal(err)
	}
	if second, err := lockInstaller(path, os.Geteuid()); err == nil {
		second.Close()
		t.Fatal("Second installer acquired bootstrap lifetime lock concurrently")
	}
	if err := first.Close(); err != nil {
		t.Fatal(err)
	}
	again, err := lockInstaller(path, os.Geteuid())
	if err != nil {
		t.Fatalf("Released bootstrap lock could not be reused: %v", err)
	}
	again.Close()
}

func TestRepeatedFailedUpgradeDiscardsOnlyOldRootOwnedFailedBundle(t *testing.T) {
	parent := t.TempDir()
	root := filepath.Join(parent, "computer-host-lan")
	previous := root + ".previous"
	failed := root + ".failed"
	for _, path := range []string{root, previous, failed} {
		if err := os.Mkdir(path, 0o700); err != nil {
			t.Fatal(err)
		}
	}
	_ = os.WriteFile(filepath.Join(root, "new"), []byte("new"), 0o600)
	_ = os.WriteFile(filepath.Join(previous, "old"), []byte("old"), 0o600)
	_ = os.WriteFile(filepath.Join(failed, "stale"), []byte("stale"), 0o600)
	if err := restorePreviousTrustedVersion(root, os.Geteuid()); err != nil {
		t.Fatal(err)
	}
	if content, err := os.ReadFile(filepath.Join(root, "old")); err != nil || string(content) != "old" {
		t.Fatalf("Previous helper was not restored: %v", err)
	}
	if _, err := os.Stat(filepath.Join(failed, "stale")); !os.IsNotExist(err) {
		t.Fatal("Stale failed helper was not removed before the second restore")
	}
	if content, err := os.ReadFile(filepath.Join(failed, "new")); err != nil || string(content) != "new" {
		t.Fatalf("Failed live helper was not safely moved aside: %v", err)
	}
}

func TestFailedHelperSymlinkIsNotRemovedOnRestore(t *testing.T) {
	parent := t.TempDir()
	root := filepath.Join(parent, "computer-host-lan")
	previous := root + ".previous"
	failed := root + ".failed"
	if err := os.Mkdir(root, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.Mkdir(previous, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(t.TempDir(), failed); err != nil {
		t.Fatal(err)
	}
	if err := restorePreviousTrustedVersion(root, os.Geteuid()); err == nil {
		t.Fatal("Symlinked failed helper was incorrectly removed")
	}
	if _, err := os.Lstat(failed); err != nil {
		t.Fatal("Refused symlink should remain untouched", err)
	}
}

func TestTrustedHelperVersionReplacementFixture(t *testing.T) {
	if os.Geteuid() == 0 {
		t.Skip("temporary non-root test fixture; never redirect a live root installation")
	}
	parent := t.TempDir()
	root := filepath.Join(parent, "computer-host-lan")
	lock := filepath.Join(parent, "install.lock")
	checked := false
	status := func() (string, error) {
		checked = true
		return "none", nil
	}
	changed, err := prepareTrustedVersion(root, lock, os.Geteuid(), status)
	if err != nil || changed || checked {
		t.Fatalf("Unexpected fresh bootstrap: changed=%v checked=%v err=%v", changed, checked, err)
	}
	if _, err := os.Stat(filepath.Join(root, "installer_root.py")); err != nil {
		t.Fatal(err)
	}
	changed, err = prepareTrustedVersion(root, lock, os.Geteuid(), status)
	if err != nil || !changed || !checked {
		t.Fatalf("Unexpected upgrade bootstrap: changed=%v checked=%v err=%v", changed, checked, err)
	}
	if _, err := os.Stat(root + ".previous"); err != nil {
		t.Fatal("previous trusted version must be retained", err)
	}
	if err := retirePreviousTrustedVersion(root, os.Geteuid()); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(root + ".previous"); !os.IsNotExist(err) {
		t.Fatal("old helper should be retired after verified completion")
	}
}

func TestTrustedHelperReconcilesInterruptedPromotion(t *testing.T) {
	if os.Geteuid() == 0 {
		t.Skip("temporary non-root bootstrap fixture")
	}
	parent := t.TempDir()
	root := filepath.Join(parent, "computer-host-lan")
	lock := filepath.Join(parent, "install.lock")
	status := func() (string, error) { return "none", nil }
	if _, err := prepareTrustedVersion(root, lock, os.Geteuid(), status); err != nil {
		t.Fatal(err)
	}
	if err := os.Rename(root, root+".previous"); err != nil {
		t.Fatal(err)
	}
	if err := os.Mkdir(root+".next", 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root+".next", "partial"), []byte("discard"), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := prepareTrustedVersion(root, lock, os.Geteuid(), status); err != nil {
		t.Fatalf("Crash between old/new directory swap was not recovered: %v", err)
	}
	if _, err := os.Stat(filepath.Join(root, "installer_root.py")); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(root + ".next"); !os.IsNotExist(err) {
		t.Fatal("interrupted stage must not block future upgrades")
	}
}

func TestTrustedHelperReconcilesPreviousWithCurrentWhenJournalClean(t *testing.T) {
	if os.Geteuid() == 0 {
		t.Skip("temporary non-root bootstrap fixture")
	}
	parent := t.TempDir()
	root := filepath.Join(parent, "computer-host-lan")
	lock := filepath.Join(parent, "install.lock")
	status := func() (string, error) { return "none", nil }
	if _, err := prepareTrustedVersion(root, lock, os.Geteuid(), status); err != nil {
		t.Fatal(err)
	}
	if _, err := prepareTrustedVersion(root, lock, os.Geteuid(), status); err != nil {
		t.Fatal(err)
	}
	if _, err := prepareTrustedVersion(root, lock, os.Geteuid(), status); err != nil {
		t.Fatalf("Old helper left after a successful swap blocked next install: %v", err)
	}
	if _, err := os.Stat(filepath.Join(root, "trusted-payload.json")); err != nil {
		t.Fatal(err)
	}
}

func TestTrustedHelperRefusesUpgradeWithPendingTransaction(t *testing.T) {
	if os.Geteuid() == 0 {
		t.Skip("temporary non-root test fixture")
	}
	parent := t.TempDir()
	root := filepath.Join(parent, "computer-host-lan")
	lock := filepath.Join(parent, "install.lock")
	_, err := prepareTrustedVersion(root, lock, os.Geteuid(), func() (string, error) {
		t.Fatal("first install must not call old status")
		return "", nil
	})
	if err != nil {
		t.Fatal(err)
	}
	changed, err := prepareTrustedVersion(root, lock, os.Geteuid(),
		func() (string, error) { return "recovery_required", nil })
	if err == nil || changed {
		t.Fatal("upgrade must refuse a pending protected transaction")
	}
	if _, err := os.Stat(root + ".previous"); !os.IsNotExist(err) {
		t.Fatal("transaction guard must run before replacing the old helper")
	}
}

func TestEmbeddedReadOnlyAPIContainsNoWritableRootHelper(t *testing.T) {
	api, cleanup, err := makeEmbeddedReadOnlyAPI()
	if err != nil {
		t.Fatal(err)
	}
	defer cleanup()
	if !strings.HasSuffix(api, "/scripts/installer-api.sh") {
		t.Fatal("Wrong read-only entrypoint")
	}
	if info, err := os.Stat(api); err != nil || info.Mode().Perm() != 0o700 {
		t.Fatal("Read-only launcher missing or has unexpected mode")
	}
	if _, err := os.Stat(filepath.Join(filepath.Dir(api), "installer_root.py")); !os.IsNotExist(err) {
		t.Fatal("Privileged root helper must not be extracted for read-only preview")
	}
}
