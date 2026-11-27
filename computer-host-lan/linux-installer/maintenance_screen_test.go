package main

import (
	"bytes"
	"fmt"
	"os"
	"strings"
	"testing"

	"charm.land/lipgloss/v2"
)

func existingMenuFixture() apiInspect {
	var info apiInspect
	info.Installation.Detected = true
	info.Installation.ServiceFile = "present"
	info.Installation.AgentServiceState = "active"
	return info
}

func testMaintenanceScreen(info apiInspect) maintenanceScreen {
	m := newMaintenanceScreen(info, "0.4.6-rc.2", "0.4.7-rc.3", true)
	m.width, m.height = 100, 28
	return m
}

func TestMaintenanceVersionRecommendation(t *testing.T) {
	for _, tc := range []struct {
		installed, bundled string
		want               bool
	}{
		{"0.4.6-rc.2", "0.4.7-rc.3", true},
		{"0.4.7-rc.9", "0.4.7-rc.10", true},
		{"0.4.7-dev.1", "0.4.7-beta.1", true},
		{"0.4.7-beta.2", "0.4.7-rc.1", true},
		{"0.4.7-rc.3", "0.4.7", true},
		{"0.4.7", "0.4.7-rc.3", false},
		{"0.4.7-rc.3", "0.4.7-rc.3", false},
		{"0.4.10", "0.4.9", false},
		{"unknown", "0.4.7", false},
		{"0.4.6", "unknown", false},
		{"0.04.6", "0.4.7", false},
		{"0.4.6-rc.01", "0.4.7", false},
		{"0.4.6-custom.1", "0.4.7", false},
		{"0.4.6+build", "0.4.7", false},
		{"18446744073709551616.0.0", "0.4.7", false},
	} {
		m := newMaintenanceScreen(existingMenuFixture(), tc.installed, tc.bundled, true)
		if m.recommended != tc.want || (m.cursor == 0) != tc.want {
			t.Errorf("%s -> %s: recommended=%t cursor=%d", tc.installed, tc.bundled, m.recommended, m.cursor)
		}
	}
	info := existingMenuFixture()
	info.Installation.ServiceFile = "unsafe"
	if m := testMaintenanceScreen(info); m.recommended || m.cursor != 5 {
		t.Fatal("ambiguous service state recommended upgrade")
	}
}

func TestMaintenanceVersionStatus(t *testing.T) {
	for _, tc := range []struct {
		installed, bundled string
		want, tone         string
		recommended        bool
	}{
		{"0.4.6-rc.2", "0.4.7-rc.3", "Newer bundled version available", "success", true},
		{"0.4.7-rc.3", "0.4.7-rc.3", "Up to date (bundled version)", "success", false},
		{"0.4.7", "0.4.7-rc.3", "Installed version is newer than this installer", "warning", false},
		{"0.4.10", "0.4.9", "Installed version is newer than this installer", "warning", false},
		{"unknown", "0.4.7", "Version comparison unavailable", "muted", false},
		{"0.4.6+build", "0.4.6+build", "Version comparison unavailable", "muted", false},
	} {
		m := newMaintenanceScreen(existingMenuFixture(), tc.installed, tc.bundled, true)
		m.width, m.height = 64, 22
		view := m.render()
		if m.status != tc.want || m.statusTone != tc.tone || m.recommended != tc.recommended ||
			!strings.Contains(view, tc.want) || (m.cursor == 0) != tc.recommended {
			t.Errorf("%s -> %s: unexpected version status: %+v", tc.installed, tc.bundled, m)
		}
		for _, unwanted := range []string{"runtime not verified", "Selecting a task does not authorize", "Protected recovery status"} {
			if strings.Contains(view, unwanted) {
				t.Errorf("maintenance screen still contains %q", unwanted)
			}
		}
	}
	info := existingMenuFixture()
	info.Installation.ServiceFile = "unsafe"
	m := testMaintenanceScreen(info)
	if m.recommended || m.statusTone != "muted" || strings.Contains(m.render(), "Up to date") {
		t.Fatal("ambiguous installation state implies known version status")
	}
}

func TestMaintenanceServiceLabels(t *testing.T) {
	for state, want := range map[string]string{
		"active":       "running",
		"inactive":     "stopped",
		"failed":       "failed",
		"activating":   "starting",
		"deactivating": "stopping",
		"unknown":      "unknown",
		"":             "unknown",
	} {
		info := existingMenuFixture()
		info.Installation.AgentServiceState = state
		m := testMaintenanceScreen(info)
		if m.service != want || !strings.Contains(m.render(), "Service:   "+want) {
			t.Errorf("service %q: got %q, want %q", state, m.service, want)
		}
	}
}

func TestVisualMaintenanceRoutes(t *testing.T) {
	for _, info := range []apiInspect{existingMenuFixture(), {}} {
		for _, opt := range maintenanceOptions(info) {
			m := testMaintenanceScreen(info)
			if m.handleKey(opt.key) || m.chosen != "" {
				t.Fatal("numeric key dispatched a task without Enter")
			}
			if !m.handleKey("enter") {
				t.Fatalf("available task %s did not exit chooser", opt.key)
			}
			want := opt.action
			if want == "exit" {
				want = ""
			}
			if m.chosen != want {
				t.Fatalf("key %s routed to %q, want %q", opt.key, m.chosen, want)
			}
		}
	}
	var retained apiInspect
	retained.Installation.RetainedStatePresent = true
	retained.Installation.ServiceFile = "absent"
	m := testMaintenanceScreen(retained)
	if m.cursor != 0 || m.recommended {
		t.Fatal("unexpected retained-state default")
	}
	for _, key := range []string{"3", "7"} {
		if m.handleKey(key) || m.handleKey("enter") || m.chosen != "" {
			t.Fatalf("disabled task %s dispatched", key)
		}
		if m.choices[m.cursor].enabled || m.choices[m.cursor].detail == "" {
			t.Fatal("disabled task lacks explanation")
		}
	}
	for _, key := range []string{"q", "esc", "ctrl+c"} {
		m = testMaintenanceScreen(existingMenuFixture())
		m.handleKey("7")
		if !m.handleKey(key) || m.chosen != "" {
			t.Fatalf("%s failed to cancel without dispatch", key)
		}
	}
}

func TestVisualMaintenanceBoundsAndFallback(t *testing.T) {
	m := testMaintenanceScreen(existingMenuFixture())
	for _, size := range [][2]int{{64, 22}, {80, 24}, {100, 28}, {132, 42}} {
		m.width, m.height = size[0], size[1]
		for _, mono := range []bool{false, true} {
			m.monochrome = mono
			view := m.render()
			lines := strings.Split(view, "\n")
			if len(lines) > m.height {
				t.Fatal("menu exceeds terminal height")
			}
			for _, line := range lines {
				if lipgloss.Width(line) > m.width {
					t.Fatal("menu exceeds terminal width")
				}
			}
			for _, want := range []string{"0.4.6-rc.2", "0.4.7-rc.3", "recommended", "Service:   running", "Newer bundled version available", "Esc/Q Exit"} {
				if !strings.Contains(view, want) {
					t.Errorf("missing %q", want)
				}
			}
			if mono && strings.Contains(view, "\x1b") {
				t.Fatal("ANSI styling in monochrome content")
			}
		}
	}
	m.width, m.height = 60, 20
	if !strings.Contains(m.render(), "Enlarge terminal to 64x22 (now 60x20). Q quits.") || m.handleKey("enter") || m.chosen != "" || !m.handleKey("q") {
		t.Fatal("small terminal allowed invisible navigation or could not exit")
	}
	for _, tc := range []struct {
		accessible, in, out bool
		term                string
		want                bool
	}{
		{false, true, true, "xterm-256color", true},
		{true, true, true, "xterm-256color", false},
		{false, false, true, "xterm-256color", false},
		{false, true, false, "xterm-256color", false},
		{false, true, true, "dumb", false},
		{false, true, true, "", false},
	} {
		if visualMaintenanceAllowed(tc.accessible, tc.in, tc.out, tc.term) != tc.want {
			t.Errorf("incorrect presentation gate: %+v", tc)
		}
	}
	for _, accessible := range []bool{false, true} {
		var out bytes.Buffer
		calls := 0
		err := runMaintenancePresentation(accessible, strings.NewReader("6\n"), &out, existingMenuFixture(), func(choice string) error {
			calls++
			if choice != "inspect" {
				t.Fatal("wrong plain route")
			}
			return nil
		})
		if err != nil || calls != 1 || strings.Contains(out.String(), "\x1b") {
			t.Fatal("plain fallback changed")
		}
	}
}

// Executed only by the external PTY test. The injected dispatcher consumes
// a harmless line of text; no real installer, host inspection or elevation.
func TestMaintenanceScreenPTYHarness(t *testing.T) {
	if os.Getenv("COMPUTER_HOST_TEST_MAINTENANCE_PTY") != "1" {
		t.Skip("external PTY harness")
	}
	m := newMaintenanceScreen(existingMenuFixture(), "0.4.6-rc.2", "0.4.7-rc.3", true)
	err := runMaintenanceScreen(m, os.Stdout, func(choice string) error {
		fmt.Printf("PTY HANDOFF %s\n", choice)
		line, err := readConfirmationLine(os.Stdin)
		if err != nil {
			return err
		}
		if line != "Q typed into ordinary prompt" {
			return fmt.Errorf("unexpected plain input")
		}
		fmt.Println("PTY INPUT PRESERVED")
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
}
