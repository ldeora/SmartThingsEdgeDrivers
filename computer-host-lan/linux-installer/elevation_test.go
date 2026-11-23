package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"strings"
	"testing"
)

func TestElevationFallbackOrderAndNoninteractiveRules(t *testing.T) {
	cases := []struct {
		name        string
		available   []string
		interactive bool
		wantMethod  string
		wantArg     string
	}{
		{"sudo preferred", []string{"/usr/bin/sudo", "/usr/bin/doas", "/usr/bin/run0", "/usr/bin/su"}, true, "sudo", "--"},
		{"sudo no tty", []string{"/usr/bin/sudo"}, false, "sudo", "-n"},
		{"doas fallback", []string{"/usr/bin/doas", "/usr/bin/run0"}, true, "doas", "--"},
		{"doas no tty", []string{"/bin/doas"}, false, "doas", "-n"},
		{"run0 fallback", []string{"/usr/bin/run0", "/usr/bin/su"}, true, "run0", "--pipe"},
		{"run0 no tty", []string{"/bin/run0"}, false, "run0", "--no-ask-password"},
		{"su fallback", []string{"/usr/bin/su"}, true, "su", "root"},
		{"su needs tty", []string{"/usr/bin/su"}, false, "", ""},
		{"none available", nil, true, "", ""},
	}
	for _, test := range cases {
		t.Run(test.name, func(t *testing.T) {
			found := make(map[string]bool)
			for _, entry := range test.available {
				found[entry] = true
			}
			got, err := findElevationCommand("/home/user/installer", test.interactive,
				func(path string) bool { return found[path] })
			if test.wantMethod == "" {
				if err == nil {
					t.Fatalf("Unexpected authorization method: %+v", got)
				}
				return
			}
			if err != nil {
				t.Fatal(err)
			}
			if got.method != test.wantMethod {
				t.Fatalf("Selected %s, expected %s", got.method, test.wantMethod)
			}
			if !strings.Contains(strings.Join(got.args, " "), test.wantArg) {
				t.Fatalf("Missing required option %s in %q", test.wantArg, got.args)
			}
			if !strings.Contains(strings.Join(got.args, " "), "-root-bootstrap") {
				t.Fatalf("Did not invoke only the root bootstrap: %+v", got)
			}
		})
	}
}

func TestSuFallbackQuotesTheFixedGoExecutablePath(t *testing.T) {
	available := func(path string) bool { return path == "/bin/su" }
	got, err := findElevationCommand("/home/test/user's/wizard", true, available)
	if err != nil {
		t.Fatal(err)
	}
	if got.method != "su" || len(got.args) != 3 || got.args[0] != "root" || got.args[1] != "-c" {
		t.Fatalf("Bad su invocation: %+v", got)
	}
	if !strings.Contains(got.args[2], `'\''`) ||
		!strings.HasSuffix(got.args[2], " -root-bootstrap") {
		t.Fatalf("Executable shell path was not safely quoted: %q", got.args[2])
	}
}

func TestPrivilegedHelperErrorsSurviveNonzeroElevationExit(t *testing.T) {
	cases := []struct {
		code string
		help string
	}{
		{"recovery_required", "-recover"},
		{"adoption_required", "--adopt-retained-state"},
		{"rolled_back", "restored"},
		{"installation_busy", "another installation"},
		{"unsupported_python", "Python 3.10"},
		{"bootstrap_failed", "elevated helper"},
	}
	for _, tc := range cases {
		t.Run(tc.code, func(t *testing.T) {
			// The Python root helper intentionally omits the operation
			// field on failure. The Go bootstrap supplies the known action.
			pyReply := []byte(`{"schema_version":1,"status":"error","error_code":"` +
				tc.code + `","secrets_included":false}`)
			parsed, err := interpretPrivilegedExecution(pyReply, errors.New("exit status 3"), "upgrade")
			if err == nil || !strings.Contains(err.Error(), tc.help) {
				t.Fatalf("Lost recoverable error details: reply=%+v err=%v", parsed, err)
			}
			if parsed.Status != "error" || parsed.Operation != "upgrade" || parsed.ErrorCode != tc.code {
				t.Fatalf("Root helper error reply not preserved: %+v", parsed)
			}
		})
	}
}

func TestNoValidReplyMeansAuthorizationOrBootstrapFailure(t *testing.T) {
	for _, output := range []string{
		"",
		"Permission denied\n",
		`{"schema_version":1,"status":"error","error_code":"private-token","secrets_included":false}`,
		`{"schema_version":1,"status":"error","error_code":"recovery_required","secrets_included":true}`,
	} {
		_, err := interpretPrivilegedExecution([]byte(output), errors.New("exit status 1"), "install")
		if err == nil || !strings.Contains(err.Error(), "no valid installer result") {
			t.Fatalf("Expected generic auth failure for invalid reply: %v", err)
		}
	}
	ok := []byte(`{"schema_version":1,"status":"installed","operation":"install","secrets_included":false}`)
	if _, err := interpretPrivilegedExecution(ok, nil, "install"); err != nil {
		t.Fatalf("Valid successful reply rejected: %v", err)
	}
	if _, err := interpretPrivilegedExecution(ok, errors.New("exit status 1"), "install"); err == nil {
		t.Fatal("Success JSON with nonzero process exit should not claim success")
	}
}

func TestRootBootstrapRelaysHelperFailureAsJSONWithNonzeroExit(t *testing.T) {
	var out bytes.Buffer
	result := privilegedResult{SchemaVersion: 1, Status: "error", ErrorCode: "recovery_required"}
	err := relayHelperResponse(&out, "upgrade", result, errors.New("python exited 3"))
	if err == nil {
		t.Fatal("Root helper failure incorrectly reported as success")
	}
	var parsed privilegedResult
	if err := json.Unmarshal(out.Bytes(), &parsed); err != nil {
		t.Fatal(err)
	}
	if parsed.SchemaVersion != 1 || parsed.ErrorCode != "recovery_required" ||
		parsed.Operation != "upgrade" || parsed.SecretsIncluded {
		t.Fatalf("Error envelope corrupted: %+v", parsed)
	}
	for _, tc := range []struct {
		err  error
		want string
	}{
		{errInstallerBusy, "installation_busy"},
		{errInstallerRecoveryPending, "recovery_required"},
		{errors.New("root helper write failed"), "bootstrap_failed"},
	} {
		out.Reset()
		if err := relayBootstrapFailure(&out, "install", tc.err); err == nil {
			t.Fatal("Bootstrap failure must exit nonzero")
		}
		if err := json.Unmarshal(out.Bytes(), &parsed); err != nil {
			t.Fatal(err)
		}
		if parsed.ErrorCode != tc.want || parsed.Status != "error" ||
			parsed.Operation != "install" {
			t.Fatalf("Unexpected bootstrap envelope: %+v", parsed)
		}
	}
}
