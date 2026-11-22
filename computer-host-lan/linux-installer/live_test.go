package main

import (
	"bytes"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"

	tea "charm.land/bubbletea/v2"
	"charm.land/huh/v2"
)

const fixtureInspect = `{"schema_version":1,"operation":"inspect","mode":"read_only","checks":[{"id":"linux","status":"passed"},{"id":"python_3_10_plus","status":"passed"},{"id":"avahi_discovery","status":"passed"}],"python":{"selected_interpreter":"/usr/bin/python3.11","version_supported":true},"avahi":{"services_directory":"present","daemon_state":"active"},"installation":{"detected":true,"service_file":"present","power_dropin":"present","avahi_service_file":"absent","agent_service_state":"active","agent_service_enabled":"enabled"},"privileged_transaction_state":"unknown","identity_preserved":"not_verified","secrets_included":false}`

const fixturePlan = `{"schema_version":1,"operation":"plan","mode":"read_only","changes":[{"path":"/opt/linux-host-agent/linux_host_agent.py","action":"replace"},{"path":"/etc/systemd/system/linux-host-agent.service","action":"replace"}],"selected_python":"/usr/bin/python3.11","power_option":"%s","wol_interface_requested":%s,"privileged_transaction_state":"unknown","runtime_verified":false,"changes_applied":false,"secrets_included":false}`

// Explicit test doubles, not the real system's launcher or service files.
func scriptClient(t *testing.T, source string) apiClient {
	t.Helper()
	path := filepath.Join(t.TempDir(), "api.sh")
	if err := os.WriteFile(path, []byte(source), 0o755); err != nil { t.Fatal(err) }
	client, err := newAPIClient(path)
	if err != nil { t.Fatal(err) }
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
          [ "$1" = "enp1s0f0" ] || exit 2
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
	if err != nil { t.Fatal(err) }
	if !info.Installation.Detected || info.Installation.AgentServiceEnabled != "enabled" ||
		info.Avahi.DaemonState != "active" || !strings.Contains(info.brief(), "Privileged transaction/recovery status: UNKNOWN") {
		t.Fatalf("real state not reflected, or protected state falsely claimed: %+v", info)
	}
	for _, test := range []struct{
		opt planOptions
		power string
		wol bool
	}{
		{planOptions{power:"keep"}, "preserve", false},
		{planOptions{power:"enabled"}, "enable", false},
		{planOptions{power:"disabled", wolNIC:"enp1s0f0"}, "disable", true},
	} {
		p, err := client.plan(test.opt)
		if err != nil { t.Fatal(err) }
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
	for _, want := range []string{"REAL HOST", "Existing installation", "Power setting: preserve",
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
		if !strings.Contains(body, want) { t.Errorf("accessible output missing %q: %s", want, body) }
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
		if validNICName(name) == nil { t.Errorf("should reject NIC %q", name) }
	}
	if validNICName("enp1s0f0") != nil { t.Fatal("valid NIC refused") }
	client := fixtureClient(t)
	_, err := client.plan(planOptions{power: "enabled", wolNIC:"foo/bar"})
	if err == nil || !strings.Contains(err.Error(), "invalid_argument") {
		t.Fatalf("invalid NIC did not fail closed: %v", err)
	}
}

func TestLiveBackendRejectsUnknownFieldsOrUnexpectedChanges(t *testing.T) {
	for _, change := range []struct{
		name string
		inspect string
		plan string
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
			if change.inspect != "" { reply = change.inspect; op = "inspect" }
			client := scriptClient(t, "#!/bin/sh\nif [ \"$1\" != \""+op+"\" ]; then exit 2; fi\ncat <<'JSON'\n"+reply+"\nJSON\n")
			var err error
			if op == "plan" { _, err = client.plan(planOptions{power:"keep"}) } else { _, err = client.inspect() }
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
		_, err := client.plan(planOptions{power:"keep"})
		if err == nil { t.Fatal("backend unexpectedly accepted failure") }
		if strings.Contains(err.Error(), "SHOULD_NOT_LEAK") || strings.Contains(err.Error(), "send_secret") {
			t.Fatalf("raw backend error escaped: %v", err)
		}
	}
}

func TestLiveReviewDescriptionInvalidatesWhenSelectionChanges(t *testing.T) {
	client := fixtureClient(t)
	ins, err := client.inspect()
	if err != nil { t.Fatal(err) }
	s := liveSelection{api:client, inspection:ins, powerChoice:"keep", wolChoice:"keep"}
	form := liveForm(&s).WithWidth(110).WithHeight(40)
	// Welcome (1 field), options (2 fields), hidden NIC: three NextField
	// events reach the Review page.
	for i := 0; i < 3; i++ { deliverFormMessage(t, form, huh.NextField()) }
	initial := form.View()
	if !strings.Contains(initial, "Power setting: preserve") {
		t.Fatalf("initial live Review was not rendered: %s", initial)
	}
	s.powerChoice = "enabled"
	deliverFormMessage(t, form, tea.WindowSizeMsg{Width:110, Height:40})
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
