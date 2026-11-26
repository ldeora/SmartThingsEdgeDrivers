package main

import (
	"bytes"
	"encoding/json"
	"strings"
	"testing"
)

func testBackup() backupSummary {
	return backupSummary{Name: "snapshot-abcdefgh", Version: "0.4.6-rc.2",
		Digest: strings.Repeat("a", 64), CapturedAt: 1795680000,
		AgentActive: true, AgentEnabled: true, Power: "enabled", Coverage: "partial"}
}

func TestRestoreWizardRequiresExactSelectionConsent(t *testing.T) {
	b := testBackup()
	items := []backupSummary{b}
	for _, tc := range []struct {
		input string
		want  int
	}{
		{"quit\n", 1},
		{"1\nNO\n", 1},
		{"1\nRESTORE", 1},
		{"1\nRESTORE\n", 2},
	} {
		calls := 0
		var out bytes.Buffer
		err := restoreWizard(strings.NewReader(tc.input), &out, func(req privilegedRequest) (privilegedResult, error) {
			calls++
			if req.validate() != nil {
				t.Fatalf("Invalid request: %+v", req)
			}
			if calls == 1 && req.Action == "backups" {
				return privilegedResult{Status: "passed", Backups: &items}, nil
			}
			if calls == 2 && req.Action == "restore" && req.Backup == b.Name && req.BackupDigest == b.Digest {
				return privilegedResult{Status: "restored", IdentityPreserved: "verified", CredentialContinuity: "verified"}, nil
			}
			t.Fatalf("Unexpected request: %+v", req)
			return privilegedResult{}, nil
		}, "0.4.7-rc.3")
		if err != nil || calls != tc.want {
			t.Fatalf("Consent mismatch: calls=%d err=%v output=%s", calls, err, out.String())
		}
	}
}

func TestBackupReplyAndCLIContracts(t *testing.T) {
	b := testBackup()
	items := []backupSummary{b}
	reply := privilegedResult{SchemaVersion: 1, Operation: "backups", Status: "passed", Backups: &items}
	raw, _ := json.Marshal(reply)
	if _, err := validatedPrivilegedReply(raw, "backups"); err != nil {
		t.Fatal(err)
	}
	for _, invalid := range []backupSummary{
		{Name: "../bad", Version: b.Version, Digest: b.Digest},
		{Name: b.Name, Version: "private\ntext", Digest: b.Digest},
	} {
		items[0] = invalid
		raw, _ := json.Marshal(reply)
		if _, err := validatedPrivilegedReply(raw, "backups"); err == nil {
			t.Fatal("Unsafe backup summary accepted")
		}
	}
	for _, args := range [][]string{
		{"restore", "--backup", b.Name, "--backup-digest", b.Digest},
		{"restore", "--backup", "/tmp/bad", "--backup-digest", b.Digest, "--confirm", "RESTORE"},
		{"restore", "--backup", b.Name, "--confirm", "RESTORE"},
		{"backups", "--confirm", "BACKUPS"},
	} {
		if _, err := parseCLI(args); err == nil {
			t.Fatalf("Invalid CLI accepted: %v", args)
		}
	}
	opts, err := parseCLI([]string{"restore", "--backup", b.Name, "--backup-digest", b.Digest, "--confirm", "RESTORE"})
	if err != nil {
		t.Fatal(err)
	}
	prepared, err := prepareCLIRequest(opts)
	if err != nil || prepared.request.Action != "restore" || prepared.request.Backup != b.Name || prepared.request.BackupDigest != b.Digest {
		t.Fatalf("Selection lost: %+v (%v)", prepared, err)
	}
	wire, err := pythonRequest(prepared.request)
	if err != nil || !bytes.Contains(wire, []byte(b.Digest)) {
		t.Fatalf("Selection lost crossing boundary: %s (%v)", wire, err)
	}
}

func TestRestoreSuccessRequiresCredentialContinuity(t *testing.T) {
	reply := privilegedResult{SchemaVersion: 1, Operation: "restore", Status: "restored", IdentityPreserved: "verified"}
	raw, _ := json.Marshal(reply)
	if _, err := validatedPrivilegedReply(raw, "restore"); err == nil {
		t.Fatal("Unverified credential continuity accepted")
	}
	reply.InstallationIDContinuity, reply.ControlTokenContinuity, reply.CredentialContinuity = "verified", "verified", "verified"
	raw, _ = json.Marshal(reply)
	if _, err := validatedPrivilegedReply(raw, "restore"); err != nil {
		t.Fatal(err)
	}
}

func TestRestoreShowsLatestEligibleBackupAndCurrentVersion(t *testing.T) {
	older := testBackup()
	newer := older
	newer.Name = "snapshot-newer123"
	newer.Version = "0.4.7-rc.3"
	newer.CapturedAt++
	newer.Digest = strings.Repeat("b", 64)
	items := []backupSummary{older, newer}
	var out bytes.Buffer
	calls := 0
	err := restoreWizard(strings.NewReader("1\nRESTORE\n"), &out, func(req privilegedRequest) (privilegedResult, error) {
		calls++
		if req.Action == "backups" {
			return privilegedResult{Status: "passed", Backups: &items}, nil
		}
		if req.Action != "restore" || req.Backup != newer.Name || req.BackupDigest != newer.Digest {
			t.Fatalf("Displayed selection changed: %+v", req)
		}
		return privilegedResult{Status: "restored", IdentityPreserved: "verified", CredentialContinuity: "verified"}, nil
	}, "0.4.8")
	if err != nil || calls != 2 {
		t.Fatalf("Unexpected outcome: %v, %d", err, calls)
	}
	output := out.String()
	if !strings.Contains(output, "Installed agent file version (not runtime-verified): 0.4.8") ||
		strings.Count(output, "(Latest backup)") != 1 ||
		strings.Index(output, "(Latest backup)") > strings.Index(output, older.Name) ||
		items[0] != older {
		t.Fatal(output)
	}
}
