package main

import (
	"bytes"
	"errors"
	"fmt"
	"os"
	"strings"
	"testing"

	tea "charm.land/bubbletea/v2"
	"charm.land/lipgloss/v2"
)

func TestOperationPagesFitMinimum(t *testing.T) {
	screens := []operationScreen{configurationScreen(), recoveryScreen(), uninstallScreen()}
	for _, status := range []string{"managed", "not_managed", "review_required", "runtime_only"} {
		screens = append(screens, savedWOLScreen(strings.Repeat("n", 15),
			privilegedResult{Status: "passed", WOLStatus: status}))
	}
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
	for _, initial := range []operationScreen{recoveryScreen(), uninstallScreen(),
		savedWOLScreen("LAN0", privilegedResult{Status: "passed", WOLStatus: "managed"})} {
		m := initial
		m.frame.width, m.frame.height = 64, 22
		next, cmd := m.Update(tea.KeyPressMsg{Code: tea.KeyEnter})
		if cmd == nil || next.(operationScreen).chosen != "" {
			t.Fatal("default choice must cancel")
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

func TestFramedWOLReviewRetainsLiteralConsent(t *testing.T) {
	for _, tc := range []struct {
		status, input string
		proceed       bool
		want          int
	}{
		{"managed", "REMOVE\n", false, 1},
		{"managed", "REMOVE", true, 1},
		{"managed", "no\n", true, 1},
		{"managed", "REMOVE\n", true, 2},
		{"review_required", "REMOVE\n", false, 1},
		{"not_managed", "REMOVE\n", true, 1},
		{"runtime_only", "REMOVE\n", true, 2},
	} {
		var out bytes.Buffer
		calls, reviews := 0, 0
		err := manageWOLWithReview(strings.NewReader("LAN0\n"+tc.input), &out, false,
			func(req privilegedRequest) (privilegedResult, error) {
				calls++
				if req.validate() != nil || req.WOLInterface == nil || *req.WOLInterface != "LAN0" {
					t.Fatal("WOL interface binding lost")
				}
				if calls == 1 && req.Action == "wol-check" {
					return privilegedResult{Status: "passed", WOLStatus: tc.status}, nil
				}
				if calls == 2 && req.Action == "wol-remove" {
					return privilegedResult{Status: "passed", WOLStatus: "removed"}, nil
				}
				t.Fatal("unexpected WOL action")
				return privilegedResult{}, nil
			}, func(nic string, reply privilegedResult) (bool, error) {
				reviews++
				if nic != "LAN0" || reply.WOLStatus != tc.status {
					t.Fatal("review received wrong data")
				}
				return tc.proceed, nil
			})
		if err != nil || calls != tc.want || reviews != 1 {
			t.Fatalf("consent mismatch: %+v calls=%d reviews=%d err=%v", tc, calls, reviews, err)
		}
	}
}

func TestFailedWOLCheckCannotOpenReview(t *testing.T) {
	var out bytes.Buffer
	denied := errors.New("authorization cancelled")
	for _, failed := range []bool{false, true} {
		err := manageWOLWithReview(strings.NewReader("LAN0\nREMOVE\n"), &out, false,
			func(req privilegedRequest) (privilegedResult, error) {
				if req.Action != "wol-check" {
					t.Fatal("mutation after failed check")
				}
				if failed {
					return privilegedResult{}, denied
				}
				return privilegedResult{Status: "error"}, nil
			}, func(_ string, _ privilegedResult) (bool, error) {
				t.Fatal("failed check opened review")
				return false, nil
			})
		if err == nil {
			t.Fatal("failed WOL check was not reported")
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
	action, err := runOperationScreen(m)
	if err != nil {
		t.Fatal(err)
	}
	if action != "" && mode == "configure" {
		if action != "wol" {
			t.Fatal("wrong configuration selection")
		}
		fmt.Println("PTY CONFIGURE HANDOFF wol")
	} else if action == "continue" {
		authorize := func(req privilegedRequest) (privilegedResult, error) {
			t.Fatal("PTY cancellation reached authorization")
			return privilegedResult{}, nil
		}
		if mode == "recover" {
			err = confirmRecovery(os.Stdin, os.Stdout, authorize)
		} else {
			err = confirmUninstall(os.Stdin, os.Stdout, authorize)
		}
		if err != nil {
			t.Fatal(err)
		}
	}
	fmt.Println("PTY OPERATION CLOSED")
}
