package main

import (
	"bytes"
	"encoding/json"
	"strings"
	"testing"
)

func TestCredentialContinuityReply(t *testing.T) {
	for _, tc := range []struct {
		name   string
		reply  privilegedResult
		valid  bool
		id     string
		token  string
		reason string
	}{
		{"legacy upgrade", privilegedResult{Operation: "upgrade", Status: "installed"}, true, "not_verified", "not_verified", ""},
		{"legacy recover", privilegedResult{Operation: "recover", Status: "passed", RecoveryStatus: "rolled_back"}, true, "not_verified", "not_verified", "continuity_unverified_after_interruption"},
		{"verified", privilegedResult{Operation: "upgrade", Status: "installed", InstallationIDContinuity: "verified", ControlTokenContinuity: "verified", CredentialContinuity: "verified"}, true, "verified", "verified", ""},
		{"mixed", privilegedResult{Operation: "install", Status: "installed", InstallationIDContinuity: "verified", ControlTokenContinuity: "newly_present", CredentialContinuity: "not_verified"}, true, "verified", "newly_present", ""},
		{"false aggregate", privilegedResult{Operation: "upgrade", Status: "installed", InstallationIDContinuity: "verified", ControlTokenContinuity: "absent", CredentialContinuity: "verified"}, false, "", "", ""},
		{"partial", privilegedResult{Operation: "upgrade", Status: "installed", InstallationIDContinuity: "verified"}, false, "", "", ""},
		{"private enum", privilegedResult{Operation: "upgrade", Status: "installed", InstallationIDContinuity: "private-value", ControlTokenContinuity: "verified", CredentialContinuity: "verified"}, false, "", "", ""},
		{"recovery cannot verify", privilegedResult{Operation: "recover", Status: "passed", RecoveryStatus: "rolled_back", InstallationIDContinuity: "verified", ControlTokenContinuity: "verified", CredentialContinuity: "verified"}, false, "", "", ""},
		{"mismatch", privilegedResult{Operation: "uninstall", Status: "error", ErrorCode: "recovery_required", InstallationIDContinuity: "not_verified", ControlTokenContinuity: "not_verified", CredentialContinuity: "not_verified", ContinuityReason: "credential_continuity_unverified"}, true, "not_verified", "not_verified", "credential_continuity_unverified"},
		{"success with failure", privilegedResult{Operation: "upgrade", Status: "installed", InstallationIDContinuity: "not_verified", ControlTokenContinuity: "not_verified", CredentialContinuity: "not_verified", ContinuityReason: "credential_continuity_unverified"}, false, "", "", ""},
		{"rollback verified", privilegedResult{Operation: "upgrade", Status: "error", ErrorCode: "rolled_back", InstallationIDContinuity: "verified", ControlTokenContinuity: "verified", CredentialContinuity: "verified"}, true, "verified", "verified", ""},
	} {
		t.Run(tc.name, func(t *testing.T) {
			tc.reply.SchemaVersion = 1
			wire, err := json.Marshal(tc.reply)
			if err != nil {
				t.Fatal(err)
			}
			got, err := validatedPrivilegedReply(wire, tc.reply.Operation)
			if (err == nil) != tc.valid {
				t.Fatalf("valid=%t, err=%v", tc.valid, err)
			}
			if tc.valid && (got.InstallationIDContinuity != tc.id || got.ControlTokenContinuity != tc.token || got.ContinuityReason != tc.reason) {
				t.Fatalf("unexpected result: %+v", got)
			}
			var out bytes.Buffer
			if err := relayHelperResponse(&out, tc.reply.Operation, tc.reply, nil); (err == nil) != tc.valid || (out.Len() != 0) != tc.valid {
				t.Fatal("root relay differed from UI validation")
			}
		})
	}
}

func TestCredentialContinuityDisplay(t *testing.T) {
	var out bytes.Buffer
	showCredentialContinuity(&out, privilegedResult{InstallationIDContinuity: "verified", ControlTokenContinuity: "newly_present"})
	if !strings.Contains(out.String(), "metadata unchanged") || !strings.Contains(out.String(), "no prior credential") {
		t.Fatal(out.String())
	}
	out.Reset()
	showCredentialContinuity(&out, privilegedResult{ContinuityReason: "continuity_unverified_after_interruption"})
	if !strings.Contains(out.String(), "not verified after the interruption") || strings.Contains(out.String(), "metadata unchanged") {
		t.Fatal(out.String())
	}
	out.Reset()
	showCredentialContinuity(&out, privilegedResult{ControlTokenContinuity: "private-value"})
	if strings.Contains(out.String(), "private-value") || !strings.Contains(out.String(), "not verified") {
		t.Fatal(out.String())
	}
}

func TestCredentialContinuityAbortGuidance(t *testing.T) {
	message := userFacingPrivilegeFailure(privilegedResult{ErrorCode: "aborted", ContinuityReason: "credential_continuity_unverified"}).Error()
	for _, expected := range []string{"before applying changes", "ownership, permissions and hard links", "Do not delete or reset credentials"} {
		if !strings.Contains(message, expected) {
			t.Fatal(message)
		}
	}
}
