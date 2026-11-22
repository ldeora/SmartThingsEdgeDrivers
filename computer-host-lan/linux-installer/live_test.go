package main

import (
	"bytes"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	tea "charm.land/bubbletea/v2"
	"charm.land/huh/v2"
)

const fixtureInspect = `{"schema_version":1,"operation":"inspect","mode":"read_only","checks":[{"id":"linux","status":"passed"},{"id":"python_3_10_plus","status":"passed"},{"id":"avahi_discovery","status":"passed"}],"python":{"selected_interpreter":"/usr/bin/python3.11","version_supported":true},"avahi":{"services_directory":"present","daemon_state":"active"},"installation":{"detected":true,"service_file":"present","power_dropin":"present","avahi_service_file":"absent","agent_service_state":"active","agent_service_enabled":"enabled"},"privileged_transaction_state":"unknown","identity_preserved":"not_verified","secrets_included":false}`

const fixturePlan = `{"schema_version":1,"operation":"plan","mode":"read_only","changes":[{"path":"/opt/linux-host-agent/linux_host_agent.py","action":"replace"},{"path":"/etc/systemd/system/linux-host-agent.service","action":"replace"}],"selected_python":"/usr/bin/python3.11","power_option":"%s","wol_interface_requested":%s,"privileged_transaction_state":"unknown","runtime_verified":false,"changes_applied":false,"secrets_included":false}`

// Explicit test doubles, not the real system's launcher or service files.
func scriptClient(t *testing.T, source string) apiClient {
	t.Helper()
	path := filepath.Join(t.TempDir(), "api.sh")
	if err := os.WriteFile(path, []byte(source), 0o755); err != nil {
		t.Fatal(err)
	}
	client, err := newAPIClient(path)
	if err != nil {
		t.Fatal(err)
	}
	return client
}

func fixtureClient(t *testing.T) apiClient {
	t.Helper()
	// No systemctl, sudo, installation or network access. Arguments are
	// inspected in this fixture to check which options are sent to Python.
	source := `#!/bin/sh
case "$1" in
  inspect)
    cat <<'JSON'
` + fixtureInspect + `
JSON
    ;;
  plan)
    shift
    power=preserve
    wol=false
    while [ "$#" -gt 0 ]; do
      case "$1" in
        --enable-power) power=enable ;;
        --disable-power) power=disable ;;
        --wol-interface)
          wol=true
          shift
          [ "$1" = "enp1s0f0" ] || [ "$1" = "LAN0" ] || exit 2
          ;;
        *) exit 2 ;;
      esac
      shift
    done
    printf '` + fixturePlan + `\n' "$power" "$wol"
    ;;
  *) exit 2 ;;
esac
`
	return scriptClient(t, source)
}

func TestLiveBackendInspectAndPlanAreActualTypedData(t *testing.T) {
	client := fixtureClient(t)
	info, err := client.inspect()
	if err != nil {
		t.Fatal(err)
	}
	if !info.Installation.Detected || info.Installation.AgentServiceEnabled != "enabled" ||
		info.Avahi.DaemonState != "active" || !strings.Contains(info.brief(), "Privileged transaction/recovery status: UNKNOWN") {
		t.Fatalf("real state not reflected, or protected state falsely claimed: %+v", info)
	}
	for _, test := range []struct {
		opt   planOptions
		power string
		wol   bool
	}{
		{planOptions{power: "keep"}, "preserve", false},
		{planOptions{power: "enabled"}, "enable", false},
		{planOptions{power: "disabled", wolNIC: "enp1s0f0"}, "disable", true},
	} {
		p, err := client.plan(test.opt)
		if err != nil {
			t.Fatal(err)
		}
		if p.PowerOption != test.power || p.WOLInterfaceRequested != test.wol ||
			p.ChangesApplied || p.RuntimeVerified || p.SecretsIncluded {
			t.Fatalf("unexpected plan result: %+v", p)
		}
	}
	if !strings.Contains(info.brief(), "Agent active: active; enabled: enabled") {
		t.Fatalf("service state lost: %s", info.brief())
	}
}

func TestLivePreviewUsesRealBackendWithoutTTY(t *testing.T) {
	client := fixtureClient(t)
	var result bytes.Buffer
	if err := runLive(true, false, client.executable, strings.NewReader(""), &result); err != nil {
		t.Fatal(err)
	}
	body := result.String()
	for _, want := range []string{"REAL HOST", "existing installation", "Power setting: preserve",
		"replace: /opt/linux-host-agent/linux_host_agent.py",
		"No runtime check", "Privileged transaction/recovery status: UNKNOWN"} {
		if !strings.Contains(body, want) {
			t.Errorf("live preview omitted %q: %s", want, body)
		}
	}
	if strings.Contains(body, "DEMO ONLY") || strings.Contains(body, "\x1b") {
		t.Fatalf("live preview included simulated or ANSI output: %s", body)
	}
}

func TestLiveAccessibleModeAndBack(t *testing.T) {
	client := fixtureClient(t)
	var result bytes.Buffer
	// Change the default power selection, go back, restore preserve;
	// leave WOL unchanged, review, finish.
	input := "y\nback\nk\nk\ny\n"
	if err := runLive(true, true, client.executable, strings.NewReader(""), &result); err != nil {
		t.Fatal(err)
	}
	result.Reset()
	if err := runLive(false, true, client.executable, strings.NewReader(input), &result); err != nil {
		t.Fatal(err)
	}
	body := result.String()
	for _, want := range []string{"READ-ONLY, ANSI-FREE", "Power setting: preserve", "READ-ONLY REVIEW COMPLETE"} {
		if !strings.Contains(body, want) {
			t.Errorf("accessible output missing %q: %s", want, body)
		}
	}
	if strings.Contains(body, "\x1b") || strings.Contains(body, "DEMO ONLY") {
		t.Fatalf("unexpected ANSI or demo output: %q", body)
	}
}

func TestLiveMissingBackendAndInvalidNamesFailClosed(t *testing.T) {
	if _, err := newAPIClient(filepath.Join(t.TempDir(), "missing")); err == nil {
		t.Fatal("missing API was silently accepted")
	}
	for _, name := range []string{"", ".", "..", "foo/bar", "lo;rm", "very-long-interface-name"} {
		if validNICName(name) == nil {
			t.Errorf("should reject NIC %q", name)
		}
	}
	if validNICName("enp1s0f0") != nil {
		t.Fatal("valid NIC refused")
	}
	client := fixtureClient(t)
	_, err := client.plan(planOptions{power: "enabled", wolNIC: "foo/bar"})
	if err == nil || !strings.Contains(err.Error(), "invalid_argument") {
		t.Fatalf("invalid NIC did not fail closed: %v", err)
	}
}

func TestLiveBackendRejectsUnknownFieldsOrUnexpectedChanges(t *testing.T) {
	for _, change := range []struct {
		name    string
		inspect string
		plan    string
	}{
		{"secret-tag", strings.Replace(fixtureInspect, `"secrets_included":false`, `"secrets_included":true`, 1), ""},
		{"unknown-inspect", strings.Replace(fixtureInspect, `"schema_version":1`, `"unexpected_private_token":"should-never-be-printed","schema_version":1`, 1), ""},
		{"unexpected-file", "", strings.Replace(fmt.Sprintf(fixturePlan, "preserve", "false"), "/opt/linux-host-agent/linux_host_agent.py", "/var/lib/linux-host-agent/control-token", 1)},
		{"claims-apply", "", strings.Replace(fmt.Sprintf(fixturePlan, "preserve", "false"), `"changes_applied":false`, `"changes_applied":true`, 1)},
		{"wrong-schema", "", strings.Replace(fmt.Sprintf(fixturePlan, "preserve", "false"), `"schema_version":1`, `"schema_version":2`, 1)},
	} {
		t.Run(change.name, func(t *testing.T) {
			reply := change.plan
			op := "plan"
			if change.inspect != "" {
				reply = change.inspect
				op = "inspect"
			}
			client := scriptClient(t, "#!/bin/sh\nif [ \"$1\" != \""+op+"\" ]; then exit 2; fi\ncat <<'JSON'\n"+reply+"\nJSON\n")
			var err error
			if op == "plan" {
				_, err = client.plan(planOptions{power: "keep"})
			} else {
				_, err = client.inspect()
			}
			if err == nil || !strings.Contains(err.Error(), "invalid_response") {
				t.Fatalf("unsafe backend %s accepted: %v", change.name, err)
			}
			if strings.Contains(err.Error(), "should-never-be-printed") || strings.Contains(err.Error(), "control-token") {
				t.Fatalf("backend leaked sensitive text: %v", err)
			}
		})
	}
}

func TestLiveBackendReportsOnlyAllowlistedErrorCodes(t *testing.T) {
	for _, input := range []string{
		`{"schema_version":1,"operation":"plan","mode":"read_only","error":{"code":"unsafe_managed_path"}}`,
		`SHOULD_NOT_LEAK_CONTROL_TOKEN=private`,
		`{"schema_version":1,"operation":"plan","mode":"read_only","error":{"code":"send_secret"}}`,
	} {
		client := scriptClient(t, "#!/bin/sh\ncat <<'JSON' >&2\n"+input+"\nJSON\nexit 2\n")
		_, err := client.plan(planOptions{power: "keep"})
		if err == nil {
			t.Fatal("backend unexpectedly accepted failure")
		}
		if strings.Contains(err.Error(), "SHOULD_NOT_LEAK") || strings.Contains(err.Error(), "send_secret") {
			t.Fatalf("raw backend error escaped: %v", err)
		}
	}
}

func TestLiveReviewDescriptionInvalidatesWhenSelectionChanges(t *testing.T) {
	client := fixtureClient(t)
	ins, err := client.inspect()
	if err != nil {
		t.Fatal(err)
	}
	s := liveSelection{api: client, inspection: ins, powerChoice: "keep", wolChoice: "keep"}
	form := liveForm(&s).WithWidth(110).WithHeight(40)
	// Welcome (1 field), options (2 fields), hidden NIC: three NextField
	// events reach the Review page.
	for i := 0; i < 3; i++ {
		deliverFormMessage(t, form, huh.NextField())
	}
	initial := form.View()
	if !strings.Contains(initial, "Power setting: preserve") {
		t.Fatalf("initial live Review was not rendered: %s", initial)
	}
	s.powerChoice = "enabled"
	deliverFormMessage(t, form, tea.WindowSizeMsg{Width: 110, Height: 40})
	if current := form.View(); !strings.Contains(current, "Power setting: enable") ||
		strings.Contains(current, "Power setting: preserve") {
		t.Fatalf("live Review cached outdated plan after changing power: %s", current)
	}
}

func TestLiveDoesNotAcceptUnknownOrMutatingOperations(t *testing.T) {
	client := fixtureClient(t)
	if _, err := client.call("install"); err == nil {
		t.Fatal("a mutating backend verb was accepted")
	}
}

func TestLiveReviewPlanCacheConcurrentDescriptionAndValidation(t *testing.T) {
	// Huh runs DescriptionFunc as a background command and may run Validate
	// on the UI goroutine before the first subprocess completes. This test
	// intentionally overlaps 32 lookups and must pass under go test -race.
	dir := t.TempDir()
	counter := filepath.Join(dir, "plan-calls")
	payload := fmt.Sprintf(fixturePlan, "preserve", "false")
	script := "#!/bin/sh\n" +
		"if [ \"$1\" != \"plan\" ]; then exit 2; fi\n" +
		"printf x >> " + counter + "\n" +
		"sleep 0.1\n" +
		"cat <<'JSON'\n" + payload + "\nJSON\n"
	client := scriptClient(t, script)
	s := liveSelection{api: client, powerChoice: "keep", wolChoice: "keep"}
	s.inspection.Python.SelectedInterpreter = "/usr/bin/python3.11"
	const readers = 32
	var wg sync.WaitGroup
	start := make(chan struct{})
	failures := make(chan error, readers)
	for i := 0; i < readers; i++ {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			<-start
			if i%2 == 0 {
				// DescriptionFunc path: preview() -> currentPlan().
				if !strings.Contains(s.preview(), "Power setting: preserve") {
					failures <- fmt.Errorf("preview failed for reader %d", i)
				}
			} else {
				// Validate path: currentPlan() returns a complete local value.
				plan, err := s.currentPlan()
				if err != nil || plan.SelectedPython != "/usr/bin/python3.11" {
					failures <- fmt.Errorf("concurrent plan failed for reader %d: %v", i, err)
				}
			}
		}(i)
	}
	close(start)
	wg.Wait()
	close(failures)
	for failure := range failures {
		t.Error(failure)
	}
	b, err := os.ReadFile(counter)
	if err != nil {
		t.Fatal(err)
	}
	if string(b) != "x" {
		t.Fatalf("expected one backend plan execution, got %d", len(b))
	}
}

func TestLiveAccessiblePreservesCaseSensitiveNIC(t *testing.T) {
	client := fixtureClient(t) // Accepts LAN0; explicitly rejects lan0.
	var out bytes.Buffer
	// Use an uppercase interface spelling that a udev .link rule may create.
	if err := runLive(false, true, client.executable, strings.NewReader("k\np\nLAN0\ny\n"), &out); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(out.String(), "READ-ONLY REVIEW COMPLETE") {
		t.Fatalf("case-sensitive NIC was changed/rejected: %s", out.String())
	}
}

func TestLiveRejectsGroupWritableAndSymlinkLaunchers(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "api.sh")
	if err := os.WriteFile(path, []byte("#!/bin/sh\nexit 2\n"), 0o755); err != nil {
		t.Fatal(err)
	}
	// os.WriteFile permissions are masked by the process umask.
	if err := os.Chmod(path, 0o775); err != nil {
		t.Fatal(err)
	}
	if _, err := newAPIClient(path); err == nil {
		t.Fatal("group-writable launcher accepted")
	}
	if err := os.Chmod(path, 0o757); err != nil {
		t.Fatal(err)
	}
	if _, err := newAPIClient(path); err == nil {
		t.Fatal("world-writable launcher accepted")
	}
	if err := os.Chmod(path, 0o755); err != nil {
		t.Fatal(err)
	}
	if _, err := newAPIClient(path); err != nil {
		t.Fatalf("owner-writable launcher rejected: %v", err)
	}
	link := filepath.Join(dir, "api-symlink")
	if err := os.Symlink(path, link); err != nil {
		t.Fatal(err)
	}
	if _, err := newAPIClient(link); err == nil {
		t.Fatal("symlink launcher accepted")
	}
	if _, err := newAPIClient(""); err == nil {
		t.Fatal("live mode without explicit -api accepted")
	}
}

func TestLiveWaitDelayBoundsInheritedPipes(t *testing.T) {
	// A detached child inheriting stdout/stderr must not hold the parent
	// forever after the API launcher has exited.
	client := scriptClient(t, "#!/bin/sh\nsleep 5 &\nexit 0\n")
	start := time.Now()
	_, err := client.call("inspect")
	if err == nil || time.Since(start) > 4*time.Second {
		t.Fatalf("inherited pipe was not bounded: err=%v, duration=%s", err, time.Since(start))
	}
}


func TestLiveNICInputAcceptsTypedCharactersAndValidation(t *testing.T) {
	// The full-screen journey is exercised separately under a PTY. This
	// isolates Huh's text input and checks the exact value that Blur validates
	// without executing its repeating cursor-blink timer commands.
	name := ""
	input := huh.NewInput().Validate(validateNICInput).Value(&name)
	input.WithWidth(90)
	input.Focus() // Ignore asynchronous cursor blink commands.
	for _, ch := range "enp1s0f0" {
		input.Update(tea.KeyPressMsg{Code: ch, Text: string(ch)})
	}
	input.Blur()
	if name != "enp1s0f0" || input.Error() != nil {
		t.Fatalf("typed NIC failed Huh input validation: value=%q err=%v", name, input.Error())
	}
}

func TestLiveNICInputDisplaysUsefulValidationErrors(t *testing.T) {
	name := ""
	input := huh.NewInput().Validate(validateNICInput).Value(&name)
	input.WithWidth(90)
	input.Focus()
	input.Blur()
	err := input.Error()
	if err == nil || !strings.Contains(err.Error(), "interface name") ||
		!strings.Contains(err.Error(), "1–15") ||
		strings.Contains(err.Error(), "read-only backend: invalid_argument") {
		t.Fatalf("unexpected empty-NIC validation: %v", err)
	}
}
