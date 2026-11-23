package main

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"syscall"
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
	// Exercise ordinary reviewed-helper upgrades, without retaining a
	// root-only compatibility path for an unmerged draft launcher.
	changed, err = prepareTrustedVersion(trustedDir, trustedLock, 0,
		func() (string, error) {
			resp, err := runInstalledHelper(trustedDir,
				privilegedRequest{SchemaVersion: 1, Action: "status"})
			return resp.PrivilegedTransactionState, err
		})
	if err != nil || !changed {
		t.Fatalf("Safe replacement of current helper failed: changed=%t err=%v", changed, err)
	}
	status, err := runInstalledHelper(trustedDir,
		privilegedRequest{SchemaVersion: 1, Action: "status"})
	if err != nil || status.Status != "passed" ||
		status.PrivilegedTransactionState != "none" {
		t.Fatalf("Promoted helper cannot report status: %+v %v", status, err)
	}
	if err := retirePreviousTrustedVersion(trustedDir, 0); err != nil {
		t.Fatal(err)
	}
}

func TestAbortedPrivilegedFailureStageIsBoundedAndActionable(t *testing.T) {
	for _, tc := range []struct {
		stage string
		part  string
	}{
		{"payload", "payload verification/staging"},
		{"existing_state", "existing agent/service state"},
		{"plan", "installation plan"},
		{"snapshot", "backup snapshot"},
		{"", "before applying changes"},
	} {
		t.Run(tc.stage, func(t *testing.T) {
			reply := privilegedResult{
				SchemaVersion: 1, Operation: "upgrade", Status: "error",
				ErrorCode: "aborted", FailureStage: tc.stage,
			}
			wire, err := json.Marshal(reply)
			if err != nil {
				t.Fatal(err)
			}
			got, err := validatedPrivilegedReply(wire, "upgrade")
			if err != nil || got.FailureStage != tc.stage {
				t.Fatalf("Valid fixed aborted stage rejected: %+v %v", got, err)
			}
			_, userErr := interpretPrivilegedExecution(wire, errors.New("helper refused"),
				"upgrade")
			if userErr == nil || !strings.Contains(userErr.Error(), tc.part) {
				t.Fatalf("No safe stage-specific error: %v", userErr)
			}
		})
	}
	for _, tc := range []struct{ code, stage string }{
		{"aborted", "/etc/shadow"},
		{"aborted", "free-form internal exception"},
		{"invalid_request", "payload"},
		{"recovery_required", "snapshot"},
		{"rolled_back", "existing_state"},
	} {
		reply := privilegedResult{
			SchemaVersion: 1, Operation: "upgrade", Status: "error",
			ErrorCode: tc.code, FailureStage: tc.stage,
		}
		wire, err := json.Marshal(reply)
		if err != nil {
			t.Fatal(err)
		}
		if _, err := validatedPrivilegedReply(wire, "upgrade"); err == nil {
			t.Fatalf("Untrusted failure stage was accepted: %+v", tc)
		}
		var stdout bytes.Buffer
		if err := relayHelperResponse(&stdout, "upgrade", reply, errors.New("refused")); err == nil {
			t.Fatalf("Root bootstrap leaked untrusted stage: %+v", tc)
		}
		if stdout.Len() != 0 {
			t.Fatal("Root bootstrap must not serialize a malformed stage")
		}
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

func TestGentooSystemPythonPathsAccepted(t *testing.T) {
	launcher, err := os.ReadFile("../scripts/installer-entry.sh")
	if err != nil {
		t.Fatal(err)
	}
	for _, directory := range []string{"/usr/sbin/*", "/usr/bin/*", "/sbin/*", "/bin/*"} {
		if !bytes.Contains(launcher, []byte(directory)) {
			t.Fatalf("Installed launcher does not accept fixed trusted system directory %s", directory)
		}
	}
}

func TestInstalledHelperCommandTimeoutPolicy(t *testing.T) {
	root := t.TempDir()
	for _, action := range []string{"install", "upgrade", "repair", "recover"} {
		cmd, cancel := installedHelperCommand(root, action)
		if cmd.Cancel != nil {
			t.Errorf("Mutation %s must not be SIGKILLed by Go's context deadline", action)
		}
		cancel()
	}
	cmd, cancel := installedHelperCommand(root, "status")
	defer cancel()
	if cmd.Cancel == nil {
		t.Fatal("Read-only status request must retain its bounded timeout")
	}
}

func TestInterruptedHelperReportsRecoveryNeeded(t *testing.T) {
	sentinel := errors.New("privileged helper exited without JSON")
	for _, state := range []string{"recovery_required", "incomplete", "in_progress"} {
		status := privilegedResult{
			SchemaVersion: 1, Operation: "status", Status: "passed",
			PrivilegedTransactionState: state,
		}
		if !errors.Is(classifyInterruptedHelper(sentinel, status, nil),
			errInstallerRecoveryPending) {
			t.Fatalf("Interrupted helper with state %s must report recovery", state)
		}
	}
	for _, tc := range []struct {
		status privilegedResult
		err    error
	}{
		{privilegedResult{SchemaVersion: 1, Operation: "status", Status: "passed",
			PrivilegedTransactionState: "none"}, nil},
		{privilegedResult{SchemaVersion: 1, Operation: "status", Status: "passed",
			PrivilegedTransactionState: "recovery_required"}, errors.New("status unavailable")},
		{privilegedResult{SchemaVersion: 1, Operation: "status", Status: "error",
			PrivilegedTransactionState: "recovery_required"}, nil},
		{privilegedResult{SchemaVersion: 1, Operation: "upgrade", Status: "passed",
			PrivilegedTransactionState: "recovery_required"}, nil},
		{privilegedResult{SchemaVersion: 1, Operation: "status", Status: "passed",
			PrivilegedTransactionState: "recovery_required", SecretsIncluded: true}, nil},
	} {
		if !errors.Is(classifyInterruptedHelper(sentinel, tc.status, tc.err), sentinel) {
			t.Fatal("Untrusted or clean status must not override original error")
		}
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

func TestInstallerLockRefusesSymlinkHardlinkAndFIFO(t *testing.T) {
	// /run/lock may be sticky and world-writable. A user must not steer
	// root's lock open through a symlink or a non-regular inode.
	root := t.TempDir()
	target := filepath.Join(root, "target")
	if err := os.WriteFile(target, []byte("KEEP"), 0o600); err != nil {
		t.Fatal(err)
	}
	lock := filepath.Join(root, "install.lock")
	if err := os.Symlink(target, lock); err != nil {
		t.Fatal(err)
	}
	if f, err := lockInstaller(lock, os.Geteuid()); err == nil {
		f.Close()
		t.Fatal("Symlinked lock unexpectedly accepted")
	}
	data, err := os.ReadFile(target)
	if err != nil || string(data) != "KEEP" {
		t.Fatalf("Lock target modified: %q %v", data, err)
	}
	if err := os.Remove(lock); err != nil {
		t.Fatal(err)
	}
	if err := os.Link(target, lock); err != nil {
		t.Fatal(err)
	}
	if f, err := lockInstaller(lock, os.Geteuid()); err == nil {
		f.Close()
		t.Fatal("Hardlinked lock unexpectedly accepted")
	}
	if err := os.Remove(lock); err != nil {
		t.Fatal(err)
	}
	if err := syscall.Mkfifo(lock, 0o600); err != nil {
		t.Fatal(err)
	}
	if f, err := lockInstaller(lock, os.Geteuid()); err == nil {
		f.Close()
		t.Fatal("FIFO lock unexpectedly accepted")
	}
	if err := os.Remove(lock); err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(target, 0o666); err != nil {
		t.Fatal(err)
	}
	if f, err := lockInstaller(target, os.Geteuid()); err == nil {
		f.Close()
		t.Fatal("Group/world-writable lock unexpectedly accepted")
	}
}

func TestDirectoryAtInstallerLockPathGetsFixedUnsafeLock(t *testing.T) {
	lock := filepath.Join(t.TempDir(), "install.lock")
	if err := os.Mkdir(lock, 0o700); err != nil {
		t.Fatal(err)
	}
	if file, err := lockInstaller(lock, os.Geteuid()); err == nil ||
		!errors.Is(err, errUnsafeInstallerLock) {
		if file != nil {
			file.Close()
		}
		t.Fatalf("Nonregular lock must produce fixed unsafe_lock: %v", err)
	}
}

func TestUnixSocketAtLockPathProducesFixedUnsafeLock(t *testing.T) {
	lock := filepath.Join(t.TempDir(), "install.lock")
	server, err := net.Listen("unix", lock)
	if err != nil {
		t.Fatal(err)
	}
	defer server.Close()

	if f, err := lockInstaller(lock, os.Geteuid()); err == nil ||
		!errors.Is(err, errUnsafeInstallerLock) {
		if f != nil {
			f.Close()
		}
		t.Fatalf("Unix socket at lock path must be unsafe_lock: %v", err)
	}
}

func TestInstallerLockAcceptsExisting0644WithoutChangingMode(t *testing.T) {
	lock := filepath.Join(t.TempDir(), "manual.lock")
	if err := os.WriteFile(lock, nil, 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(lock, 0o644); err != nil {
		t.Fatal(err)
	}
	guard, err := lockInstaller(lock, os.Geteuid())
	if err != nil {
		t.Fatal(err)
	}
	guard.Close()
	info, err := os.Stat(lock)
	if err != nil || info.Mode().Perm() != 0o644 {
		t.Fatalf("Existing legacy lock mode changed: %v %v", info, err)
	}
}

func TestPrivateBootstrapLockDirRequiresOwnerAndMode0700(t *testing.T) {
	if bootstrapLock != "/run/computer-host-lan/bootstrap.lock" {
		t.Fatal("Bootstrap lock must not be in world-writable /run/lock")
	}
	root := t.TempDir()
	directory := filepath.Join(root, "computer-host-lan")
	uid := os.Geteuid()
	if err := ensurePrivateBootstrapLockDir(directory, uid); err != nil {
		t.Fatal(err)
	}
	info, err := os.Lstat(directory)
	if err != nil || !info.IsDir() || info.Mode().Perm() != 0o700 {
		t.Fatalf("Private bootstrap directory not 0700: %v, %v", info, err)
	}
	if err := ensurePrivateBootstrapLockDir(directory, uid); err != nil {
		t.Fatal("Existing private directory must be reusable:", err)
	}
	guard, err := lockInstaller(filepath.Join(directory, "bootstrap.lock"), uid)
	if err != nil {
		t.Fatal(err)
	}
	guard.Close()

	if err := os.Chmod(directory, 0o755); err != nil {
		t.Fatal(err)
	}
	if !errors.Is(ensurePrivateBootstrapLockDir(directory, uid), errUnsafeInstallerLock) {
		t.Fatal("Unsafe existing directory permissions must fail closed")
	}
	if err := os.Chmod(directory, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.Remove(filepath.Join(directory, "bootstrap.lock")); err != nil {
		t.Fatal(err)
	}
	if err := os.Remove(directory); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(root, directory); err != nil {
		t.Fatal(err)
	}
	if !errors.Is(ensurePrivateBootstrapLockDir(directory, uid), errUnsafeInstallerLock) {
		t.Fatal("Existing symlink must not be accepted as private directory")
	}
}

func TestUnsafeInstallerLockIsFixedAndActionable(t *testing.T) {
	root := t.TempDir()
	lock := filepath.Join(root, "manual.lock")
	if err := os.WriteFile(lock, nil, 0o600); err != nil {
		t.Fatal(err)
	}
	// A user-owned lock is not acceptable to a privileged installer. No
	// chown needed: fixture owner mismatches the simulated required UID.
	if f, err := lockInstaller(lock, os.Geteuid()+1); err == nil ||
		!errors.Is(err, errUnsafeInstallerLock) {
		if f != nil {
			f.Close()
		}
		t.Fatalf("Foreign-owner lock must produce fixed error, got %v", err)
	}
	var output bytes.Buffer
	if err := relayBootstrapFailure(&output, "upgrade", errUnsafeInstallerLock); err == nil {
		t.Fatal("Unsafe lock must cause failure")
	}
	reply, err := validatedPrivilegedReply(output.Bytes(), "upgrade")
	if err != nil || reply.ErrorCode != "unsafe_lock" || reply.SecretsIncluded {
		t.Fatalf("Unsafe lock code must be fixed and redacted: %+v, %v", reply, err)
	}
	_, userErr := interpretPrivilegedExecution(output.Bytes(), errUnsafeInstallerLock, "upgrade")
	if userErr == nil || !strings.Contains(userErr.Error(), "/run/lock/linux-host-agent-install.lock") ||
		!strings.Contains(userErr.Error(), "/run/computer-host-lan/bootstrap.lock") ||
		!strings.Contains(userErr.Error(), "no installation or recovery is running") {
		t.Fatalf("Unsafe lock message not actionable: %v", userErr)
	}
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
