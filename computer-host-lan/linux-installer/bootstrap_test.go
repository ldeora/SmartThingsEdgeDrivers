package main

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

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
