package main

import (
	"bytes"
	"errors"
	"strings"
	"testing"
)

func TestMaintenanceMenuRoutingAndCancellation(t *testing.T) {
	info := apiInspect{}
	info.Installation.Detected = true
	info.Installation.ServiceFile = "present"
	for _, tc := range []struct {
		input string
		want  string
	}{
		{"1\n", "upgrade"},
		{"2\n", "configure"},
		{"3\n", "repair"},
		{"4\n", "restore"},
		{"5\n", "recover"},
		{"6\n", "inspect"},
		{"7\n", "uninstall"},
		{"9\n3\n", "repair"},
		{"0\n", ""},
		{"\n", ""},
		{"quit\n", ""},
		{"7", ""},
		{"", ""},
	} {
		var out bytes.Buffer
		calls := 0
		err := runMaintenanceMenu(strings.NewReader(tc.input), &out, info, func(action string) error {
			calls++
			if action != tc.want || tc.want == "" {
				t.Fatalf("Wrong route %q for %q", action, tc.input)
			}
			return nil
		})
		if err != nil || (calls == 1) != (tc.want != "") || calls > 1 {
			t.Fatalf("Unexpected menu result for %q: %v, %d", tc.input, err, calls)
		}
		if strings.Contains(out.String(), "\x1b") {
			t.Fatal("Maintenance menu is not plain text")
		}
	}
}

func TestMaintenanceLayoutChoices(t *testing.T) {
	info := apiInspect{}
	info.Installation.ServiceFile = "absent"
	if maintenanceNeeded(info) {
		t.Fatal("Clean host should continue directly to setup")
	}
	info.Installation.RetainedStatePresent = true
	if !maintenanceNeeded(info) {
		t.Fatal("Retained state needs maintenance")
	}
	var out bytes.Buffer
	calls := 0
	err := runMaintenanceMenu(strings.NewReader("7\n3\n1\n"), &out, info, func(action string) error {
		calls++
		if action != "install" {
			t.Fatalf("Unsafe retained-state route: %s", action)
		}
		return nil
	})
	if err != nil || calls != 1 || strings.Contains(out.String(), "Uninstall the agent") {
		t.Fatalf("Incorrect retained-state menu: %v %s", err, out.String())
	}
	info.Installation.RetainedStatePresent = false
	info.Installation.ServiceFile = "unreadable"
	if !maintenanceNeeded(info) {
		t.Fatal("Ambiguous service state must not be presented as clean")
	}
}

func TestConfigureMenuDispatchesOnlyExplicitChoice(t *testing.T) {
	for _, tc := range []struct {
		input string
		want  string
	}{
		{"1\n", "upgrade"},
		{"2\n", "wol"},
		{"\n", ""},
		{"2", ""},
		{"quit\n", ""},
	} {
		calls := 0
		var out bytes.Buffer
		err := configureMaintenance(strings.NewReader(tc.input), &out, func(action string) error {
			calls++
			if tc.want == "" || action != tc.want {
				t.Fatalf("Unexpected Configure route: %s", action)
			}
			return nil
		})
		if err != nil || (calls == 1) != (tc.want != "") || calls > 1 {
			t.Fatalf("Wrong Configure result: %v, %d", err, calls)
		}
	}
}

func TestMenuRepairRequiresExistingConfirmationAndPreservesInput(t *testing.T) {
	client := fixtureClient(t)
	info, err := client.inspect()
	if err != nil {
		t.Fatal(err)
	}
	reader := strings.NewReader("3\ns\nk\nk\nINSTALL\nnext-line\n")
	var out bytes.Buffer
	called := false
	err = runMaintenanceMenu(reader, &out, info, func(action string) error {
		s := newLiveSelectionWithNIC(client, info, nil, func(string) string { return "LAN0" })
		s.requestedAction = action
		return runLiveAccessibleSelection(reader, &out, s, true, func(s *liveSelection) error {
			called = true
			req, err := approvedRootRequest(s)
			if err != nil || req.Action != "repair" || req.Power != "preserve" ||
				req.WOLInterface != nil || req.ReuseRetained || req.WOLPlanDigest != "" {
				t.Fatalf("Wrong repair request: %+v (%v)", req, err)
			}
			if reader.Len() != len("next-line\n") {
				t.Fatal("Input was consumed before authorization")
			}
			return nil
		})
	})
	if err != nil || !called || !strings.Contains(out.String(), "Action: Repair using the bundled agent version") {
		t.Fatalf("Repair not reviewed: %v %s", err, out.String())
	}
	s := newLiveSelectionWithNIC(client, info, nil, func(string) string { return "LAN0" })
	s.requestedAction = "install"
	if _, err := approvedRootRequest(s); err == nil {
		t.Fatal("Stale installation intent accepted")
	}
	s.requestedAction = "repair"
	called = false
	if err := runLiveAccessibleSelection(strings.NewReader("s\nk\nk\nquit\n"), &out, s, true, func(*liveSelection) error {
		called = true
		return errors.New("unexpected authorization")
	}); err != nil || called {
		t.Fatal("Cancelled repair reached authorization")
	}
}

func TestInstalledVersionUsesOnlyExpectedProtocolAndVersion(t *testing.T) {
	data, err := bundleRead("agent/linux_host_agent.py")
	if err != nil {
		t.Fatal(err)
	}
	version := agentVersionFromSource(data)
	if version == "unknown" || !backupVersionPattern.MatchString(version) {
		t.Fatal("Bundled v2 agent version not detected")
	}
	for _, data := range []string{
		"VERSION = \"0.4.6\"\n",
		"PROTOCOL = \"linux-host-agent\"\nVERSION = \"0.4.6\"\n",
		"PROTOCOL = \"computer-host-agent\"\nVERSION = \"0.4.6\"\nVERSION = \"other\"\n",
		"PROTOCOL = \"computer-host-agent\"\nVERSION = \"private value\"\n",
	} {
		if got := agentVersionFromSource([]byte(data)); got != "unknown" {
			t.Fatalf("Unexpected source accepted: %s", got)
		}
	}
}
