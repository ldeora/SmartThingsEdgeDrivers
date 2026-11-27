package main

import (
	"bytes"
	"fmt"
	"os"
	"strings"
	"testing"

	tea "charm.land/bubbletea/v2"
	"charm.land/lipgloss/v2"
)

func TestOperationPagesFitMinimum(t *testing.T) {
	screens := []operationScreen{configurationScreen(), recoveryScreen(), uninstallScreen()}
	for _, m := range screens {
		for _, mono := range []bool{false, true} {
			m.frame.monochrome = mono
			for width := 64; width <= 140; width++ {
				for _, height := range []int{22, 24, 30} {
					m.frame.width, m.frame.height = width, height
					for i := range m.choices {
						m.cursor = i
						rows, fits := m.page()
						view := m.View().Content
						if !fits || len(rows) > m.frame.capacity() ||
							lipgloss.Width(view) > width || lipgloss.Height(view) > height {
							t.Fatalf("%s choice %d at %dx%d does not fit: %s", m.title, i, width, height, view)
						}
						for _, row := range rows {
							if lipgloss.Width(row.text) > m.frame.bodyWidth() {
								t.Fatalf("row too wide: %s", row.text)
							}
						}
					}
				}
			}
		}
	}
}

func TestOperationSelectionAndResize(t *testing.T) {
	for _, initial := range []operationScreen{recoveryScreen(), uninstallScreen()} {
		m := initial
		m.frame.width, m.frame.height = 64, 22
		next, cmd := m.Update(tea.KeyPressMsg{Code: tea.KeyEnter})
		want := "continue"
		if initial.title == "UNINSTALL" {
			want = ""
		}
		if cmd == nil || next.(operationScreen).chosen != want {
			t.Fatalf("unexpected default for %s", initial.title)
		}
		next, cmd = m.Update(tea.KeyPressMsg{Code: '1', Text: "1"})
		m = next.(operationScreen)
		if cmd != nil || m.chosen != "" || m.cursor != 0 {
			t.Fatal("number must only highlight")
		}
		next, _ = m.Update(tea.WindowSizeMsg{Width: 63, Height: 22})
		m = next.(operationScreen)
		next, cmd = m.Update(tea.KeyPressMsg{Code: tea.KeyEnter})
		if cmd != nil || next.(operationScreen).chosen != "" {
			t.Fatal("invisible review accepted")
		}
		next, _ = m.Update(tea.WindowSizeMsg{Width: 64, Height: 22})
		m = next.(operationScreen)
		next, cmd = m.Update(tea.KeyPressMsg{Code: tea.KeyEnter})
		if cmd == nil || next.(operationScreen).chosen != "continue" {
			t.Fatal("visible review did not advance")
		}
		next, cmd = m.Update(tea.KeyPressMsg{Code: tea.KeyEscape})
		if cmd == nil || next.(operationScreen).chosen != "" {
			t.Fatal("Escape did not cancel")
		}
	}
}

func TestConfigurationSelection(t *testing.T) {
	for i, action := range []string{"upgrade", "wol", ""} {
		m := configurationScreen()
		m.frame.width, m.frame.height = 80, 24
		m.cursor = i
		next, cmd := m.Update(tea.KeyPressMsg{Code: tea.KeyEnter})
		if cmd == nil || next.(operationScreen).chosen != action {
			t.Fatalf("wrong configuration action %d", i)
		}
	}
}

func TestRecoveryRequiresSubmittedLiteral(t *testing.T) {
	for _, input := range []string{"", "RECOVER", "recover\n", "yes\n", "RECOVER\n"} {
		var out bytes.Buffer
		calls := 0
		err := confirmRecovery(strings.NewReader(input), &out, func(req privilegedRequest) (privilegedResult, error) {
			calls++
			if req.SchemaVersion != 1 || req.Action != "recover" || req.validate() != nil {
				t.Fatalf("unexpected recovery request: %+v", req)
			}
			return privilegedResult{Status: "passed", RecoveryStatus: "nothing_to_recover"}, nil
		})
		want := 0
		if input == "RECOVER\n" {
			want = 1
		}
		if err != nil || calls != want {
			t.Fatalf("recovery consent mismatch for %q: %d / %d (%v)", input, calls, want, err)
		}
	}
}

func TestOperationScreenPTYHarness(t *testing.T) {
	mode := os.Getenv("COMPUTER_HOST_TEST_OPERATION_PTY")
	if mode == "" {
		t.Skip("external PTY harness")
	}
	var m operationScreen
	switch mode {
	case "configure":
		m = configurationScreen()
	case "recover":
		m = recoveryScreen()
	case "uninstall":
		m = uninstallScreen()
	default:
		t.Fatal("invalid PTY fixture mode")
	}
	if mode == "configure" {
		action, err := runOperationScreen(m)
		if err != nil || action != "wol" {
			t.Fatalf("configuration selection: %q, %v", action, err)
		}
		fmt.Println("PTY CONFIGURE HANDOFF wol")
	} else {
		token := "RECOVER"
		if mode == "uninstall" {
			token = "UNINSTALL"
		}
		m.frame.monochrome = true
		accepted, err := runOperationConsent(m, token)
		if err != nil || accepted {
			t.Fatalf("unexpected operation approval: %t, %v", accepted, err)
		}
		fmt.Println("PTY CONSENT CANCELLED")
	}
	fmt.Println("PTY OPERATION CLOSED")
}
