package main

import (
	"errors"
	"os"
	"path/filepath"
	"testing"
)

func TestExistingActionRestoresPreviousOnlyOnRecover(t *testing.T) {
	if os.Geteuid() == 0 {
		t.Skip("non-root fixture")
	}
	base := protectedEvidenceFixture(t)
	root, lock := filepath.Join(base, "helper"), filepath.Join(base, "manual.lock")
	if err := os.Mkdir(root+".previous", 0o700); err != nil {
		t.Fatal(err)
	}
	launcher := filepath.Join(root+".previous", "installer-entry.sh")
	if err := os.WriteFile(launcher, []byte("#!/bin/sh\nprintf '%s\\n' '{\"schema_version\":1,\"status\":\"passed\",\"operation\":\"recover\",\"recovery_status\":\"nothing_to_recover\"}'\n"), 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.Mkdir(root+".next", 0o700); err != nil {
		t.Fatal(err)
	}
	reply, err := prepareExistingHelperAction(root, lock, os.Geteuid(), "status")
	if err != nil || reply.PrivilegedTransactionState != "recovery_required" {
		t.Fatalf("%+v %v", reply, err)
	}
	if _, err := os.Lstat(root); !os.IsNotExist(err) {
		t.Fatal("status changed helper")
	}
	reply, err = prepareExistingHelperAction(root, lock, os.Geteuid(), "recover")
	if err != nil || reply.SchemaVersion != 0 {
		t.Fatalf("%+v %v", reply, err)
	}
	if _, err := os.Stat(root + ".next"); err != nil {
		t.Fatal("next not preserved", err)
	}
	if _, err := os.Lstat(root + ".previous"); !os.IsNotExist(err) {
		t.Fatal("previous not restored")
	}
	reply, err = runInstalledHelper(root, privilegedRequest{SchemaVersion: 1, Action: "recover"})
	if err != nil || reply.RecoveryStatus != "nothing_to_recover" {
		t.Fatalf("%+v %v", reply, err)
	}
}

func TestExistingActionRefusesUnsafePrevious(t *testing.T) {
	if os.Geteuid() == 0 {
		t.Skip("non-root fixture")
	}
	base := protectedEvidenceFixture(t)
	root, lock := filepath.Join(base, "helper"), filepath.Join(base, "manual.lock")
	if err := os.Symlink(base, root+".previous"); err != nil {
		t.Fatal(err)
	}
	for _, action := range []string{"status", "recover"} {
		if _, err := prepareExistingHelperAction(root, lock, os.Geteuid(), action); err == nil {
			t.Fatal("unsafe helper accepted")
		}
	}
	if _, err := os.Lstat(root); !os.IsNotExist(err) {
		t.Fatal("unsafe helper moved")
	}
}

func TestRetireFailedHelperOnlyAfterCleanStatus(t *testing.T) {
	if os.Geteuid() == 0 {
		t.Skip("non-root fixture")
	}
	base := protectedEvidenceFixture(t)
	root, lock := filepath.Join(base, "helper"), filepath.Join(base, "manual.lock")
	for _, path := range []string{root, root + ".previous"} {
		if err := os.Mkdir(path, 0o700); err != nil {
			t.Fatal(err)
		}
	}
	if err := restorePreviousTrustedVersion(root, os.Geteuid()); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(root + ".failed"); err != nil {
		t.Fatal(err)
	}
	// Simulate subsequent successful promotion, and ensure cleanup is locked.
	if err := os.Mkdir(root+".previous", 0o700); err != nil {
		t.Fatal(err)
	}
	state := "recovery_required"
	status := func() (privilegedResult, error) {
		guard, err := lockInstaller(lock, os.Geteuid())
		if err == nil {
			guard.Close()
			t.Fatal("missing lock")
		}
		if !errors.Is(err, errInstallerBusy) {
			t.Fatal(err)
		}
		return privilegedResult{SchemaVersion: 1, Operation: "status", Status: "passed", PrivilegedTransactionState: state}, nil
	}
	if err := completeTrustedVersionLocked(root, lock, os.Geteuid(), false, status); err == nil {
		t.Fatal("pending evidence retired")
	}
	for _, suffix := range []string{".previous", ".failed"} {
		if _, err := os.Stat(root + suffix); err != nil {
			t.Fatal(err)
		}
	}
	state = "none"
	if err := completeTrustedVersionLocked(root, lock, os.Geteuid(), false, status); err != nil {
		t.Fatal(err)
	}
	for _, suffix := range []string{".previous", ".failed"} {
		if _, err := os.Lstat(root + suffix); !os.IsNotExist(err) {
			t.Fatal("obsolete artifact retained", suffix, err)
		}
	}
	if err := os.Symlink(base, root+".failed"); err != nil {
		t.Fatal(err)
	}
	if err := completeTrustedVersionLocked(root, lock, os.Geteuid(), false, status); err == nil {
		t.Fatal("unsafe failed artifact accepted")
	}
	if info, err := os.Lstat(root + ".failed"); err != nil || info.Mode()&os.ModeSymlink == 0 {
		t.Fatal("unsafe artifact changed", err)
	}
}

func TestUninstallRefusesNonV2BeforeHelperPromotion(t *testing.T) {
	if os.Geteuid() == 0 {
		t.Skip("non-root fixture")
	}
	for _, tc := range []struct {
		name, agent, avahi string
		allowed            bool
	}{
		{"v1", "PROTOCOL = 'linux-host-agent'\n", "", false},
		{"unknown", "# unknown\n", "", false},
		{"mixed markers", "PROTOCOL = 'linux-host-agent'\nPROTOCOL = 'computer-host-agent'\n", "", false},
		{"mixed advertisement", "PROTOCOL = 'computer-host-agent'\n", "_linuxhost._tcp", false},
		{"v2 without owner record", "PROTOCOL = 'computer-host-agent'\n", "", true},
		{"v2 with advertisement", "PROTOCOL = 'computer-host-agent'\n", "_computerhost._tcp", true},
	} {
		t.Run(tc.name, func(t *testing.T) {
			base := protectedEvidenceFixture(t)
			root, lock, agent := filepath.Join(base, "helper"), filepath.Join(base, "lock"), filepath.Join(base, "agent.py")
			if err := os.WriteFile(agent, []byte(tc.agent), 0o600); err != nil {
				t.Fatal(err)
			}
			if tc.avahi != "" {
				path := filepath.Join(base, "etc/avahi/services/linux-host-agent.service")
				if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
					t.Fatal(err)
				}
				if err := os.WriteFile(path, []byte(tc.avahi), 0o600); err != nil {
					t.Fatal(err)
				}
			}
			_, err := prepareTrustedVersionForAction(root, lock, os.Geteuid(), func() (string, error) { t.Fatal("missing helper called"); return "", nil }, agent)
			if (tc.allowed && err != nil) || (!tc.allowed && !errors.Is(err, errUnsupportedUninstall)) {
				t.Fatal(err)
			}
			if !tc.allowed {
				for _, suffix := range []string{"", ".next", ".previous", ".failed"} {
					if _, err := os.Lstat(root + suffix); !os.IsNotExist(err) {
						t.Fatal("unexpected helper artifact", suffix, err)
					}
				}
			}
		})
	}
}
