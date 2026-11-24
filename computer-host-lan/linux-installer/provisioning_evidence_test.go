package main

import (
	"bytes"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"syscall"
	"testing"
)

func TestMissingHelperProvisioningEvidence(t *testing.T) {
	if os.Geteuid() == 0 {
		t.Skip("non-root helper provisioning fixture")
	}
	for _, tc := range []struct {
		name  string
		kind  string
		clean bool
	}{
		{"absent", "", true}, {"empty", "empty", true}, {"lock only", "lock", true},
		{"journal", "journal.json", false}, {"partial journal", ".wizard-journal-0123456789abcdef0123456789abcdef", false},
		{"stage", "ready-payload", false}, {"fence", "schema-2-fence", false},
		{"stage temp", ".stage-tmp", false}, {"unknown", "unknown", false},
		{"unsafe journal ancestor", "ancestor-link", false}, {"unsafe staging ancestor", "stage-link", false},
		{"public journal", "public", false}, {"public staging", "stage-public", false},
		{"unreadable", "unreadable", false}, {"nondirectory", "nondirectory", false},
		{"lock symlink", "lock-link", false}, {"lock hardlink", "lock-hardlink", false},
		{"lock fifo", "lock-fifo", false}, {"lock nonempty", "lock-data", false}, {"lock permissions", "lock-mode", false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			base := t.TempDir()
			root := filepath.Join(base, "helper")
			manual := filepath.Join(base, "install.lock")
			journal := filepath.Join(base, "var/backups/linux-host-agent/wizard-transactions")
			stage := filepath.Join(base, "var/lib/computer-host-installer/staging")
			mkdir := func(path string) {
				t.Helper()
				if err := os.MkdirAll(path, 0o700); err != nil {
					t.Fatal(err)
				}
			}
			write := func(path, data string, mode os.FileMode) {
				t.Helper()
				if err := os.WriteFile(path, []byte(data), mode); err != nil {
					t.Fatal(err)
				}
			}
			must := func(err error) {
				t.Helper()
				if err != nil {
					t.Fatal(err)
				}
			}
			if tc.kind != "" {
				mkdir(journal)
				mkdir(stage)
			}
			switch tc.kind {
			case "", "empty":
			case "lock":
				write(filepath.Join(journal, "lock"), "", 0o600)
				write(filepath.Join(stage, "stage.lock"), "", 0o600)
			case "ancestor-link":
				must(os.Remove(journal))
				must(os.Symlink("missing", journal))
			case "stage-link":
				must(os.Remove(stage))
				must(os.Symlink("missing", stage))
			case "public":
				must(os.Chmod(journal, 0o755))
			case "stage-public":
				must(os.Chmod(stage, 0o755))
			case "unreadable":
				must(os.Chmod(journal, 0))
				t.Cleanup(func() { _ = os.Chmod(journal, 0o700) })
			case "nondirectory":
				must(os.Remove(journal))
				write(journal, "", 0o600)
			case "lock-link":
				must(os.Symlink("missing", filepath.Join(journal, "lock")))
			case "lock-hardlink":
				write(filepath.Join(journal, "lock"), "", 0o600)
				must(os.Link(filepath.Join(journal, "lock"), filepath.Join(base, "alias")))
			case "lock-fifo":
				must(syscall.Mkfifo(filepath.Join(stage, "stage.lock"), 0o600))
			case "lock-data":
				write(filepath.Join(stage, "stage.lock"), "evidence", 0o600)
			case "lock-mode":
				write(filepath.Join(journal, "lock"), "", 0o644)
			case "ready-payload", "schema-2-fence", ".stage-tmp":
				mkdir(filepath.Join(stage, tc.kind))
			default:
				write(filepath.Join(journal, tc.kind), "evidence", 0o600)
			}
			// Even a pre-existing next helper must not be discarded on refusal.
			if !tc.clean {
				mkdir(root + ".next")
				write(filepath.Join(root+".next", "marker"), "keep", 0o600)
			}
			changed, err := prepareTrustedVersion(root, manual, os.Geteuid(), func() (string, error) { t.Fatal("missing helper must not execute status"); return "", nil })
			if changed || (tc.clean && err != nil) || (!tc.clean && !errors.Is(err, errRecoveryHelperMissing)) {
				t.Fatalf("changed=%v err=%v", changed, err)
			}
			if tc.clean {
				if _, err := os.Stat(filepath.Join(root, "installer_root.py")); err != nil {
					t.Fatal(err)
				}
			} else {
				if _, err := os.Lstat(root); !os.IsNotExist(err) {
					t.Fatal("helper promoted despite evidence")
				}
				if data, err := os.ReadFile(filepath.Join(root+".next", "marker")); err != nil || string(data) != "keep" {
					t.Fatal("existing stage was changed", err)
				}
			}
		})
	}
}

func TestMissingHelperUninstallEvidencePrecedesMissingAgent(t *testing.T) {
	if os.Geteuid() == 0 {
		t.Skip("non-root helper provisioning fixture")
	}
	base := t.TempDir()
	stage := filepath.Join(base, "var/lib/computer-host-installer/staging/schema-2-fence")
	if err := os.MkdirAll(stage, 0o700); err != nil {
		t.Fatal(err)
	}
	changed, err := prepareTrustedVersionForAction(filepath.Join(base, "helper"), filepath.Join(base, "manual.lock"), os.Geteuid(), func() (string, error) { t.Fatal("no helper"); return "", nil }, filepath.Join(base, "missing-agent"))
	if changed || !errors.Is(err, errRecoveryHelperMissing) {
		t.Fatalf("changed=%v err=%v", changed, err)
	}
	if _, err := os.Stat(stage); err != nil {
		t.Fatal("evidence not preserved", err)
	}
}

func TestMissingRecoveryHelperDiagnostic(t *testing.T) {
	var out bytes.Buffer
	if err := relayBootstrapFailure(&out, "upgrade", errRecoveryHelperMissing); !errors.Is(err, errRecoveryHelperMissing) {
		t.Fatal(err)
	}
	reply, err := validatedPrivilegedReply(out.Bytes(), "upgrade")
	if err != nil || reply.ErrorCode != "recovery_helper_missing" {
		t.Fatalf("unexpected reply %+v %v", reply, err)
	}
	message := userFacingPrivilegeFailure(reply).Error()
	if !strings.Contains(message, "verified compatible recovery helper") || !strings.Contains(message, "Preserve") {
		t.Fatal(message)
	}
}
