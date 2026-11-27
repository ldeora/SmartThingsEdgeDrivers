package main

import (
	"fmt"
	"os"
	"strings"
	"testing"

	tea "charm.land/bubbletea/v2"
	"charm.land/huh/v2"
)

func fixtureApplication(t *testing.T) maintenanceApplication {
	t.Helper()
	info := detailInspectFixture(t)
	menu := newMaintenanceScreen(info, "0.4.6-rc.2", "0.4.7-rc.3", true)
	return newMaintenanceApplication(menu, info, func(action string) (*liveSelection, error) {
		_, s := fixtureWizard(t, true)
		s.requestedAction = action
		return s, nil
	}, func() nicSelectionScreen {
		m := newNICSelection([]string{"LAN0", "LAN1"}, "LAN1", false)
		m.frame.monochrome = true
		return m
	})
}

func appEvent(m maintenanceApplication, msg tea.Msg) (maintenanceApplication, tea.Cmd) {
	next, cmd := m.Update(msg)
	return next.(maintenanceApplication), cmd
}

func appKey(m maintenanceApplication, key rune) (maintenanceApplication, tea.Cmd) {
	return appEvent(m, tea.KeyPressMsg{Code: key, Text: string(key)})
}

func TestApplicationNavigationAndApproval(t *testing.T) {
	m := fixtureApplication(t)
	m, _ = appEvent(m, tea.WindowSizeMsg{Width: 100, Height: 30})
	m, _ = appKey(m, '6')
	m, _ = appEvent(m, tea.KeyPressMsg{Code: tea.KeyEnter})
	if _, ok := m.screen.(inspectionScreen); !ok || m.done {
		t.Fatal("Inspect left the application")
	}
	m, _ = appEvent(m, tea.KeyPressMsg{Code: tea.KeyEscape})
	if _, ok := m.screen.(maintenanceScreen); !ok || m.done {
		t.Fatal("Inspect did not return to maintenance")
	}
	m, _ = appKey(m, '2')
	m, _ = appEvent(m, tea.KeyPressMsg{Code: tea.KeyEnter})
	if _, ok := m.screen.(operationScreen); !ok || m.done {
		t.Fatal("Configure left the application")
	}
	m, _ = appKey(m, '2')
	m, _ = appEvent(m, tea.KeyPressMsg{Code: tea.KeyEnter})
	if _, ok := m.screen.(nicSelectionScreen); !ok || m.done {
		t.Fatal("WOL selection left the application before interface selection")
	}
	m, cmd := appEvent(m, tea.KeyPressMsg{Code: tea.KeyEnter})
	if !m.done || cmd == nil || m.action != "wol" || m.nic != "LAN1" {
		t.Fatal("selected interface not returned for authorized check")
	}

	for _, tc := range []struct {
		key   rune
		token string
		want  string
	}{{'5', "RECOVER", "recover"}, {'7', "UNINSTALL", "uninstall"}} {
		for _, accept := range []bool{false, true} {
			m = fixtureApplication(t)
			m, _ = appEvent(m, tea.WindowSizeMsg{Width: 64, Height: 22})
			m, _ = appKey(m, tc.key)
			m, _ = appEvent(m, tea.KeyPressMsg{Code: tea.KeyEnter})
			m, _ = appKey(m, '1')
			m, cmd = appEvent(m, tea.KeyPressMsg{Code: tea.KeyEnter})
			if m.done || cmd != nil || !strings.Contains(m.View().Content, "Type "+tc.token+" to authorize:") {
				t.Fatal("review exited before confirmation")
			}
			value := "NO"
			if accept {
				value = tc.token
			}
			m, _ = appEvent(m, tea.PasteMsg{Content: value})
			if m.done || m.action != "" {
				t.Fatal("typing alone returned a privileged intent")
			}
			m, cmd = appEvent(m, tea.KeyPressMsg{Code: tea.KeyEnter})
			want := ""
			if accept {
				want = tc.want
			}
			if !m.done || cmd == nil || m.action != want {
				t.Fatalf("unexpected application intent %q, want %q", m.action, want)
			}
		}
	}
}

func TestApplicationSetupRequiresLiteralAfterNativeReview(t *testing.T) {
	for _, accepted := range []bool{false, true} {
		m := fixtureApplication(t)
		m, _ = appEvent(m, tea.WindowSizeMsg{Width: 110, Height: 40})
		m, _ = appKey(m, '1')
		m, _ = appEvent(m, tea.KeyPressMsg{Code: tea.KeyEnter})
		wizard, ok := m.screen.(installConsentWizard)
		if !ok || m.done {
			t.Fatal("setup left the application")
		}
		for i := 0; i < 4; i++ {
			deliverFormMessage(t, wizard.wizard.form, huh.NextField())
		}
		if wizard.wizard.form.GetFocusedField().GetKey() != "review" {
			t.Fatal("did not reach native Review")
		}
		m, cmd := appEvent(m, huh.NextField())
		if m.done || cmd != nil || !strings.Contains(m.View().Content, "Type INSTALL to authorize:") {
			t.Fatal("native Review did not stay in full-screen confirmation")
		}
		word := "NO"
		if accepted {
			word = "INSTALL"
		}
		m, _ = appEvent(m, tea.PasteMsg{Content: word})
		m, cmd = appEvent(m, tea.KeyPressMsg{Code: tea.KeyEnter})
		want := ""
		if accepted {
			want = "install-reviewed"
		}
		if !m.done || cmd == nil || m.action != want || m.selection.finished != accepted {
			t.Fatalf("unexpected installation approval: %q, finished=%t", m.action, m.selection.finished)
		}
	}
}

// A real terminal with fake read-only data, no actual elevation or managed
// file writes. The normal terminal line read is intentionally retained to
// verify that the application input loop no longer owns stdin.
func TestMaintenanceApplicationPTYHarness(t *testing.T) {
	mode := os.Getenv("COMPUTER_HOST_TEST_APP_PTY")
	if mode == "" {
		t.Skip("external PTY harness")
	}
	result, err := runFramedProgram(fixtureApplication(t))
	if err != nil {
		t.Fatal(err)
	}
	final, ok := result.(maintenanceApplication)
	want := map[string]string{"app-recover": "recover", "app-wol": "wol", "app-install": "install-reviewed"}[mode]
	if !ok || !final.done || final.action != want || want == "" {
		t.Fatalf("unexpected application result: %v", final.action)
	}
	fmt.Printf("PTY APP HANDOFF %s\n", final.action)
	line, err := readConfirmationLine(os.Stdin)
	if err != nil || line != "ordinary terminal input" {
		t.Fatalf("terminal input not preserved: %v", err)
	}
	fmt.Println("PTY APP INPUT PRESERVED")
}
