package main

import (
	"fmt"
	"os"
	"strings"
	"testing"
	"time"

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
	m, _ = appEvent(m, tea.KeyPressMsg{Code: tea.KeyEscape})
	if _, ok := m.screen.(maintenanceScreen); !ok || m.done {
		t.Fatal("Configure Escape did not return to menu")
	}
	m, _ = appKey(m, '2')
	m, _ = appEvent(m, tea.KeyPressMsg{Code: tea.KeyEnter})
	m, _ = appKey(m, '2')
	m, _ = appEvent(m, tea.KeyPressMsg{Code: tea.KeyEnter})
	if _, ok := m.screen.(nicSelectionScreen); !ok || m.done {
		t.Fatal("WOL selection left the application before interface selection")
	}
	m, _ = appEvent(m, tea.KeyPressMsg{Code: tea.KeyEscape})
	if _, ok := m.screen.(operationScreen); !ok || m.done {
		t.Fatal("WOL Escape did not return to Configure")
	}
	m, _ = appKey(m, '2')
	m, _ = appEvent(m, tea.KeyPressMsg{Code: tea.KeyEnter})
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
			if !accept {
				if m.done || cmd != nil || m.action != "" || !strings.Contains(m.View().Content, "exactly") {
					t.Fatal("wrong word did not remain in the editor")
				}
				m, _ = appEvent(m, tea.KeyPressMsg{Code: tea.KeyEscape})
				if screen, ok := m.screen.(operationConsentScreen); !ok || screen.consent != nil || m.done {
					t.Fatal("Escape did not return to review")
				}
				m, _ = appEvent(m, tea.KeyPressMsg{Code: tea.KeyEscape})
				if _, ok := m.screen.(maintenanceScreen); !ok || m.done {
					t.Fatal("Escape did not return to menu")
				}
			} else if !m.done || cmd == nil || m.action != tc.want {
				t.Fatalf("unexpected application intent %q, want %q", m.action, tc.want)
			}
		}
	}
}

func TestApplicationSetupRequiresLiteralAfterNativeReview(t *testing.T) {
	for _, accepted := range []bool{false, true} {
		m := fixtureApplication(t)
		m, _ = appEvent(m, tea.WindowSizeMsg{Width: 110, Height: 40})
		m, _ = appKey(m, '1')
		m, prepare := appEvent(m, tea.KeyPressMsg{Code: tea.KeyEnter})
		if prepare == nil || !strings.Contains(m.View().Content, "Searching for SmartThings hubs") {
			t.Fatal("setup preparation is not a visible command")
		}
		m, _ = appEvent(m, prepare())
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
		// Native Huh delivers a next-group command before StateCompleted.
		m = drainApplicationCommands(t, m, cmd)
		if m.done || !strings.Contains(m.View().Content, "Type INSTALL to authorize:") {
			t.Fatal("native Review did not stay in full-screen confirmation")
		}
		word := "NO"
		if accepted {
			word = "INSTALL"
		}
		m, _ = appEvent(m, tea.PasteMsg{Content: word})
		m, cmd = appEvent(m, tea.KeyPressMsg{Code: tea.KeyEnter})
		if !accepted {
			if m.done || cmd != nil || m.action != "" || m.selection.finished {
				t.Fatal("wrong installation word did not remain retryable")
			}
			m, _ = appEvent(m, tea.KeyPressMsg{Code: tea.KeyEscape})
			reopened, ok := m.screen.(installConsentWizard)
			if !ok || reopened.consent != nil || reopened.wizard.form.GetFocusedField().GetKey() != "review" || m.done {
				t.Fatal("Escape did not reopen native review")
			}
			if reopened.wizard.form.State != huh.StateNormal || reopened.state != wizard.state {
				t.Fatal("review did not preserve the original choices")
			}
			// A delayed navigation message from the old completed form is ignored.
			m, cmd = appEvent(m, wizardCommandMsg{form: wizard.wizard.form, msg: huh.NextField()})
			if cmd != nil || m.done || m.screen.(installConsentWizard).consent != nil {
				t.Fatal("stale form command advanced reopened Review")
			}
			// A second approval must run through native Review again.
			m, cmd = appEvent(m, huh.NextField())
			m = drainApplicationCommands(t, m, cmd)
			if !strings.Contains(m.View().Content, "Type INSTALL to authorize:") || m.done {
				t.Fatal("second review did not reach confirmation")
			}
			m, _ = appEvent(m, tea.PasteMsg{Content: "INSTALL"})
			m, cmd = appEvent(m, tea.KeyPressMsg{Code: tea.KeyEnter})
		}
		if !m.done || cmd == nil || m.action != "install-reviewed" || !m.selection.finished {
			t.Fatalf("unexpected installation approval: %q, finished=%t", m.action, m.selection.finished)
		}
	}
}

// Drain the same command/message chain Bubble Tea runs. Do not expect
// Huh's native field transition to complete the form synchronously.
func drainApplicationCommands(t *testing.T, m maintenanceApplication, first tea.Cmd) maintenanceApplication {
	t.Helper()
	queue := []tea.Cmd{first}
	for steps := 0; len(queue) > 0; steps++ {
		if steps >= 300 {
			t.Fatal("application command chain did not settle")
		}
		cmd := queue[0]
		queue = queue[1:]
		if cmd == nil {
			continue
		}
		msg := cmd()
		if batch, ok := msg.(tea.BatchMsg); ok {
			queue = append(queue, batch...)
			continue
		}
		var next tea.Cmd
		m, next = appEvent(m, msg)
		if w, ok := m.screen.(installConsentWizard); ok && w.consent != nil {
			return m
		}
		queue = append(queue, next)
	}
	return m
}

func TestPreparationBackDiscardsStaleResult(t *testing.T) {
	m := fixtureApplication(t)
	m, _ = appEvent(m, tea.WindowSizeMsg{Width: 100, Height: 30})
	m, _ = appKey(m, '1')
	m, old := appEvent(m, tea.KeyPressMsg{Code: tea.KeyEnter})
	m, _ = appEvent(m, tea.KeyPressMsg{Code: tea.KeyEscape})
	if _, ok := m.screen.(maintenanceScreen); !ok || m.done || m.pending {
		t.Fatal("Escape did not cancel pending preparation")
	}
	m, _ = appKey(m, '1')
	m, fresh := appEvent(m, tea.KeyPressMsg{Code: tea.KeyEnter})
	m, _ = appEvent(m, old())
	if _, ok := m.screen.(preparingScreen); !ok || !m.pending {
		t.Fatal("stale reply reopened the wizard")
	}
	m, _ = appEvent(m, fresh())
	if _, ok := m.screen.(installConsentWizard); !ok || m.pending {
		t.Fatal("current preparation did not open the wizard")
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
	m := fixtureApplication(t)
	prepare := m.prepare
	m.prepare = func(action string) (*liveSelection, error) {
		// Make the read-only preparation screen observable in the PTY.
		time.Sleep(300 * time.Millisecond)
		return prepare(action)
	}
	result, err := runFramedProgram(m)
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
