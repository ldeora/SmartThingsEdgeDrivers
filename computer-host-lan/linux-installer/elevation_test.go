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
	"strconv"
	"strings"
	"syscall"
	"testing"
)

func TestElevationFallbackOrderAndNoninteractiveRules(t *testing.T) {
	python := "/usr/bin/python3"
	sourceDir := "/tmp/private-handoff"
	digest := strings.Repeat("a", 64)
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
			got, err := findElevationCommand(python, sourceDir, digest, 1000, test.interactive, []byte(`{"schema_version":1,"action":"status"}`),
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
			joined := strings.Join(got.args, " ")
			if !strings.Contains(joined, test.wantArg) {
				t.Fatalf("Missing required option %s in %q", test.wantArg, got.args)
			}
			if !strings.Contains(joined, "-root-bootstrap") ||
				!strings.Contains(joined, protectedHandoffScript) {
				t.Fatalf("Provider did not invoke the fixed protected handoff: %+v", got)
			}
			if strings.Contains(joined, sourceDir) == false {
				t.Fatalf("Provider omitted the private snapshot directory: %+v", got)
			}
		})
	}
}

func TestExplicitElevationChoiceSelectsOnlyRequestedProvider(t *testing.T) {
	python, sourceDir, digest := "/usr/bin/python3", "/tmp/handoff", strings.Repeat("b", 64)
	payload := []byte(`{"schema_version":1,"action":"status"}`)
	available := func(path string) bool {
		return path == "/usr/bin/run0" || path == "/usr/bin/su"
	}
	automatic, err := chooseElevationCommand(python, sourceDir, digest, 1000, true, payload, "auto", available)
	if err != nil || automatic.method != "run0" {
		t.Fatalf("Automatic selection changed: %+v, %v", automatic, err)
	}
	chosen, err := chooseElevationCommand(python, sourceDir, digest, 1000, true, payload, "su", available)
	if err != nil || chosen.method != "su" {
		t.Fatalf("Explicit su override was ignored: %+v, %v", chosen, err)
	}
	if !strings.Contains(chosen.args[2], "-root-bootstrap") ||
		!strings.Contains(chosen.args[2], string(payload)) ||
		!strings.Contains(chosen.args[2], protectedHandoffScript) {
		t.Fatalf("Explicit su did not retain the protected handoff and bounded request: %+v", chosen)
	}
	chosen, err = chooseElevationCommand(python, sourceDir, digest, 1000, true, payload, "run0", available)
	if err != nil || chosen.method != "run0" {
		t.Fatalf("Explicit run0 did not select the requested provider: %+v, %v", chosen, err)
	}
	for _, tc := range []struct {
		name        string
		method      string
		interactive bool
	}{
		{"refuse absent sudo, do not fallback", "sudo", true},
		{"refuse absent doas, do not fallback", "doas", true},
		{"refuse su without a terminal", "su", false},
		{"reject arbitrary program name", "/tmp/malicious", true},
		{"reject shell-command method", "su;id", true},
	} {
		t.Run(tc.name, func(t *testing.T) {
			if got, err := chooseElevationCommand(python, sourceDir, digest, 1000, tc.interactive, payload, tc.method, available); err == nil {
				t.Fatalf("Unexpectedly selected provider %+v", got)
			}
		})
	}
}

func TestSuFallbackQuotesEveryProtectedHandoffArgument(t *testing.T) {
	python := "/home/test/user's python3"
	sourceDir := "/home/test/user's private handoff"
	got, err := findElevationCommand(python, sourceDir, strings.Repeat("c", 64), 1000, true,
		[]byte(`{"schema_version":1,"action":"status"}`),
		func(path string) bool { return path == "/bin/su" })
	if err != nil {
		t.Fatal(err)
	}
	if got.method != "su" || len(got.args) != 3 || got.args[0] != "root" || got.args[1] != "-c" {
		t.Fatalf("Bad su invocation: %+v", got)
	}
	if !strings.Contains(got.args[2], `'\''`) ||
		!strings.Contains(got.args[2], "'-I'") ||
		!strings.Contains(got.args[2], "-root-bootstrap") {
		t.Fatalf("Executable, snapshot path or request was not safely shell-quoted: %q", got.args[2])
	}
}

func TestSuPassesRequestAsQuotedArgumentAndKeepsStdinForPassword(t *testing.T) {
	// Execute the constructed su -c command WITHOUT su or elevation. The
	// stub interpreter prints NUL-separated argv so even the multiline
	// fixed Python source remains one argument through the shell.
	dir := t.TempDir()
	python := filepath.Join(dir, "my user's python")
	script := "#!/bin/sh\nprintf '%s\\0' \"$@\"\n"
	if err := os.WriteFile(python, []byte(script), 0o700); err != nil {
		t.Fatal(err)
	}
	sourceDir := filepath.Join(dir, "snapshot's directory")
	nic := "enp1s0f0"
	request := privilegedRequest{
		SchemaVersion: 1, Action: "upgrade", Power: "enable",
		WOLInterface: &nic,
	}
	payload, err := json.Marshal(request)
	if err != nil {
		t.Fatal(err)
	}
	got, err := findElevationCommand(python, sourceDir, strings.Repeat("d", 64), 1000, true, payload,
		func(path string) bool { return path == "/bin/su" })
	if err != nil {
		t.Fatal(err)
	}
	output, err := exec.Command("/bin/sh", "-c", got.args[2]).Output()
	if err != nil {
		t.Fatal(err)
	}
	fields := strings.Split(strings.TrimSuffix(string(output), "\x00"), "\x00")
	if len(fields) != 11 || fields[0] != "-I" || fields[1] != "-S" || fields[2] != "-c" ||
		fields[3] != protectedHandoffScript || fields[4] != sourceDir ||
		fields[5] != strings.Repeat("d", 64) || fields[6] != "1000" ||
		fields[7] != "/run" || fields[8] != "computer-host-lan" || fields[9] != "0" {
		t.Fatalf("su did not preserve the exact protected launcher arguments: %q", fields)
	}
	var childArgs []string
	if err := json.Unmarshal([]byte(fields[10]), &childArgs); err != nil {
		t.Fatal(err)
	}
	if len(childArgs) != 3 || childArgs[0] != "-root-bootstrap" ||
		childArgs[1] != "-request" || childArgs[2] != string(payload) {
		t.Fatalf("su did not preserve the bounded request: %#v", childArgs)
	}

	terminal := strings.NewReader("simulated-password\n")
	if elevationInput("su", payload, terminal) != terminal {
		t.Fatal("su would consume the piped JSON as its root password")
	}
	for _, method := range []string{"sudo", "doas", "run0"} {
		read, err := io.ReadAll(elevationInput(method, payload, terminal))
		if err != nil || !bytes.Equal(read, payload) {
			t.Fatalf("%s no longer forwards bounded request via stdin: %v", method, err)
		}
	}
}

func TestSuStillUsesStrictBoundedDecoder(t *testing.T) {
	for _, raw := range []string{
		"", strings.Repeat("x", 4097),
		`{"schema_version":1,"action":"status","control_token":"secret"}`,
		`{"schema_version":2,"action":"reveal_power_key"}`,
		`{"schema_version":1,"action":"status","action":"upgrade"}`,
	} {
		if _, err := decodePrivilegedRequest(strings.NewReader(raw)); err == nil {
			t.Fatalf("Untrusted or oversized CLI request was accepted")
		}
	}
}

func TestTrustedSystemPythonIsRootOwnedAndIsolated(t *testing.T) {
	path, err := trustedSystemPython()
	if err != nil {
		t.Fatal(err)
	}
	if !filepath.IsAbs(path) {
		t.Fatalf("trusted Python path is not absolute: %q", path)
	}
	if err := verifyParents(filepath.Dir(path), 0); err != nil {
		t.Fatalf("trusted Python parent chain is unsafe: %v", err)
	}
	if err := protectedPath(path, 0, false); err != nil || !isExecutableFile(path) {
		t.Fatalf("trusted Python executable is unsafe: %v", err)
	}
}

func TestRunningExecutableSnapshotIsPrivateAndDigestBound(t *testing.T) {
	if os.Geteuid() == 0 {
		t.Skip("the wizard must run as an ordinary user")
	}
	snapshot, err := snapshotRunningExecutable()
	if err != nil {
		t.Fatal(err)
	}
	defer snapshot.cleanup()
	if !filepath.IsAbs(snapshot.directory) || !sha256Pattern.MatchString(snapshot.digest) {
		t.Fatalf("invalid snapshot result: %+v", snapshot)
	}
	dirInfo, err := os.Lstat(snapshot.directory)
	if err != nil || !dirInfo.IsDir() || dirInfo.Mode().Perm() != 0o700 {
		t.Fatalf("snapshot directory is not private: %v %v", dirInfo, err)
	}
	path := filepath.Join(snapshot.directory, "installer")
	info, err := os.Lstat(path)
	if err != nil || !info.Mode().IsRegular() || info.Mode().Perm() != 0o600 {
		t.Fatalf("snapshot file is not private: %v %v", info, err)
	}
	st, ok := info.Sys().(*syscall.Stat_t)
	if !ok || int(st.Uid) != os.Getuid() || st.Nlink != 1 {
		t.Fatalf("snapshot file identity is unsafe: %+v", st)
	}
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	sum := sha256.Sum256(data)
	if hex.EncodeToString(sum[:]) != snapshot.digest {
		t.Fatal("snapshot digest does not match copied executable")
	}
}

func testPythonInterpreter(t *testing.T) string {
	t.Helper()
	path, err := exec.LookPath("python3")
	if err != nil {
		t.Skip("Python 3 is required for the protected handoff fixture")
	}
	abs, err := filepath.Abs(path)
	if err != nil {
		t.Fatal(err)
	}
	return abs
}

func runProtectedHandoffFixture(t *testing.T, snapshot executableSnapshot, tamper bool) ([]byte, error, string) {
	t.Helper()
	python := testPythonInterpreter(t)
	if tamper {
		if err := os.WriteFile(filepath.Join(snapshot.directory, "installer"), []byte("tampered"), 0o600); err != nil {
			t.Fatal(err)
		}
	}
	parent := t.TempDir()
	if err := os.Chmod(parent, 0o700); err != nil {
		t.Fatal(err)
	}
	childArgs, err := json.Marshal([]string{"-test.run=^TestProtectedHandoffChild$", "-test.v"})
	if err != nil {
		t.Fatal(err)
	}
	uid := strconv.Itoa(os.Getuid())
	args := []string{
		"-I", "-S", "-c", protectedHandoffScript,
		snapshot.directory, snapshot.digest, uid, parent,
		"computer-host-lan", uid, string(childArgs),
	}
	cmd := exec.Command(python, args...)
	cmd.Dir = "/"
	cmd.Env = []string{"PATH=/usr/bin:/bin", "HOME=" + os.Getenv("HOME"), "LANG=C", "LC_ALL=C"}
	output, runErr := cmd.CombinedOutput()
	return output, runErr, filepath.Join(parent, "computer-host-lan")
}

func TestProtectedHandoffScriptExecutesTheDigestMatchedCopy(t *testing.T) {
	if os.Geteuid() == 0 {
		t.Skip("fixture uses an unprivileged caller")
	}
	snapshot, err := snapshotRunningExecutable()
	if err != nil {
		t.Fatal(err)
	}
	defer snapshot.cleanup()
	output, runErr, root := runProtectedHandoffFixture(t, snapshot, false)
	if runErr != nil || !bytes.Contains(output, []byte("TestProtectedHandoffChild")) {
		t.Fatalf("protected copy did not execute: err=%v output=%q", runErr, output)
	}
	entries, err := os.ReadDir(root)
	if err != nil || len(entries) != 0 {
		t.Fatalf("root handoff directory was not cleaned: entries=%v err=%v", entries, err)
	}
}

func TestProtectedHandoffScriptRefusesTamperedSnapshot(t *testing.T) {
	if os.Geteuid() == 0 {
		t.Skip("fixture uses an unprivileged caller")
	}
	snapshot, err := snapshotRunningExecutable()
	if err != nil {
		t.Fatal(err)
	}
	defer snapshot.cleanup()
	output, runErr, root := runProtectedHandoffFixture(t, snapshot, true)
	if runErr == nil || bytes.Contains(output, []byte("TestProtectedHandoffChild")) {
		t.Fatalf("tampered executable was run: err=%v output=%q", runErr, output)
	}
	entries, err := os.ReadDir(root)
	if err != nil || len(entries) != 0 {
		t.Fatalf("failed handoff left a protected executable: entries=%v err=%v", entries, err)
	}
}

func TestProtectedHandoffExecutablePathRequiresPrivateShape(t *testing.T) {
	if os.Geteuid() == 0 {
		t.Skip("non-root fixture")
	}
	base := t.TempDir()
	root := filepath.Join(base, "computer-host-lan")
	if err := os.Mkdir(root, 0o700); err != nil {
		t.Fatal(err)
	}
	dir := filepath.Join(root, "handoff-"+strings.Repeat("a", 32))
	if err := os.Mkdir(dir, 0o700); err != nil {
		t.Fatal(err)
	}
	executable := filepath.Join(dir, "installer")
	if err := os.WriteFile(executable, []byte("fixture"), 0o700); err != nil {
		t.Fatal(err)
	}
	if err := validateProtectedHandoffExecutablePath(executable, root, os.Getuid()); err != nil {
		t.Fatal(err)
	}
	for _, bad := range []string{
		filepath.Join(root, "installer"),
		filepath.Join(root, "handoff-nothex", "installer"),
		filepath.Join(dir, "other"),
	} {
		if err := validateProtectedHandoffExecutablePath(bad, root, os.Getuid()); err == nil {
			t.Fatalf("unsafe handoff path accepted: %s", bad)
		}
	}
	if err := os.Chmod(dir, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := validateProtectedHandoffExecutablePath(executable, root, os.Getuid()); err == nil {
		t.Fatal("non-private handoff directory accepted")
	}
}

func TestProtectedHandoffArgumentsAreStrict(t *testing.T) {
	if _, err := protectedHandoffArguments("/usr/bin/python3", "/tmp/snapshot",
		strings.Repeat("e", 64), 1000, []string{"-root-bootstrap"}); err != nil {
		t.Fatalf("valid handoff arguments rejected: %v", err)
	}
	for _, tc := range []struct {
		python, source, digest string
		uid                    int
		child                  []string
	}{
		{"python3", "/tmp/snapshot", strings.Repeat("e", 64), 1000, []string{"-root-bootstrap"}},
		{"/usr/bin/python3", "/tmp/snapshot", "bad", 1000, []string{"-root-bootstrap"}},
		{"/usr/bin/python3", "/tmp/snapshot", strings.Repeat("e", 64), 0, []string{"-root-bootstrap"}},
		{"/usr/bin/python3", "/tmp/snapshot", strings.Repeat("e", 64), 1000, []string{"-root-bootstrap", "-live"}},
	} {
		if _, err := protectedHandoffArguments(tc.python, tc.source, tc.digest, tc.uid, tc.child); err == nil {
			t.Fatalf("invalid handoff arguments accepted: %+v", tc)
		}
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
		t.Fatal("Root helper failure must exit nonzero")
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
		{errUntrustedRootHandoff, "untrusted_root_launcher"},
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

func TestRootBootstrapRequiresProtectedHandoffExecutable(t *testing.T) {
	if err := requireProtectedHandoffExecutable(); !errors.Is(err, errUntrustedRootHandoff) {
		t.Fatalf("ordinary test executable unexpectedly passed root handoff validation: %v", err)
	}
}

func TestUntrustedRootHandoffDiagnosticIsActionable(t *testing.T) {
	err := userFacingPrivilegeFailure(privilegedResult{
		SchemaVersion: 1, Status: "error", ErrorCode: "untrusted_root_launcher",
	})
	if err == nil || !strings.Contains(err.Error(), "protected handoff") ||
		!strings.Contains(err.Error(), "ordinary user") ||
		!strings.Contains(err.Error(), "-root-bootstrap") {
		t.Fatalf("untrusted handoff diagnostic is incomplete: %v", err)
	}
}

func TestElevationProcessDistinguishesStartFailureFromExitFailure(t *testing.T) {
	missing := filepath.Join(t.TempDir(), "missing-provider")
	err := runElevationProcess(exec.Command(missing))
	var unavailable *authorizationUnavailableError
	if !errors.As(err, &unavailable) {
		t.Fatalf("missing executable not classified as unavailable: %v", err)
	}
	cmd := exec.Command("/bin/sh", "-c", "exit 1")
	err = runElevationProcess(cmd)
	unavailable = nil
	if err == nil || errors.As(err, &unavailable) || cmd.ProcessState == nil {
		t.Fatalf("started process failure misclassified: %v", err)
	}
	if err := runElevationProcess(exec.Command("/bin/sh", "-c", "exit 0")); err != nil {
		t.Fatal(err)
	}
}

// This test is executed only by the protected handoff script, from the
// root-private copy of the current Go test executable.
func TestProtectedHandoffChild(t *testing.T) {}
