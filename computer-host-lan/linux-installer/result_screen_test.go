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

func resultText(rows []detailRow) string {
	var lines []string
	for _, row := range rows {
		lines = append(lines, row.text)
	}
	return strings.Join(lines, "\n")
}

func TestResultClassification(t *testing.T) {
	failed := errors.New("private diagnostic must not be shown in the frame")
	for _, tc := range []struct {
		action string
		reply  privilegedResult
		err    error
		want   string
	}{
		{"install", privilegedResult{Status: "installed"}, nil, "Agent installation completed"},
		{"upgrade", privilegedResult{Status: "installed_cleanup_required"}, nil, "Cleanup required: run -recover"},
		{"repair", privilegedResult{Status: "error", ErrorCode: "rolled_back", WOLReviewRequired: true}, failed, "Operation rolled back"},
		{"install", privilegedResult{Status: "error", ErrorCode: "aborted", FailureStage: "plan"}, failed, "Aborted before managed changes"},
		{"uninstall", privilegedResult{Status: "error", ErrorCode: "recovery_required"}, failed, "Recovery required"},
		{"restore", privilegedResult{Status: "restored_cleanup_required"}, nil, "Restore committed; run -recover"},
		{"uninstall", privilegedResult{Status: "uninstalled_cleanup_required"}, nil, "Uninstall committed; run -recover"},
		{"recover", privilegedResult{Status: "passed", RecoveryStatus: "nothing_to_recover"}, nil, "No protected transaction needs recovery"},
		{"recover", privilegedResult{Status: "passed", RecoveryStatus: "rolled_back"}, nil, "Previous files and service state restored"},
		{"recover", privilegedResult{Status: "passed", RecoveryStatus: "aborted"}, nil, "Interrupted operation aborted before managed changes"},
		{"recover", privilegedResult{Status: "passed", RecoveryStatus: "cleaned"}, nil, "Transaction cleanup completed"},
		{"wol-remove", privilegedResult{Status: "passed", WOLStatus: "removed"}, nil, "Installer-owned Wake-on-LAN setting removed"},
		{"wol-remove", privilegedResult{Status: "passed", WOLStatus: "not_managed"}, nil, "No installer-owned setting to remove"},
		{"wol-check", privilegedResult{Status: "error", ErrorCode: "wol_review_required"}, failed, "Wake-on-LAN needs review"},
		{"backups", privilegedResult{}, failed, "Outcome not confirmed"},
		{"install", privilegedResult{Status: "installed"}, failed, "Outcome not confirmed"},
		{"install", privilegedResult{}, &authorizationUnavailableError{cause: failed}, "Not started"},
	} {
		r := operationReport{action: tc.action, reply: tc.reply, runErr: tc.err, called: true}
		rows := r.rows(tc.err)
		if got := resultText(rows); !strings.Contains(got, tc.want) || strings.Contains(got, failed.Error()) {
			t.Fatalf("%s / %s: unexpected result: %s", tc.action, tc.reply.Status, got)
		}
		if tc.err != nil {
			for _, row := range rows {
				if row.tone == "success" {
					t.Fatal("unsuccessful execution displayed a success row")
				}
			}
		}
		for _, size := range [][2]int{{64, 22}, {80, 24}, {100, 30}, {140, 50}} {
			m := inspectionScreen{frame: detailFrame{width: size[0], height: size[1], monochrome: true},
				rows: rows, title: "RESULT", statusPrefix: "Operation result", closeHelp: "Enter/Esc/Q Close"}
			for offset := 0; offset <= m.maxOffset(); offset++ {
				m.offset = offset
				view := m.View().Content
				if lipgloss.Width(view) > size[0] || lipgloss.Height(view) > size[1] {
					t.Fatalf("result does not fit %v", size)
				}
			}
		}
	}
}

func TestResultVerificationLimits(t *testing.T) {
	r := operationReport{action: "upgrade", power: "enable", wolConfigured: true,
		reply: privilegedResult{Status: "installed", IdentityPreserved: "verified", WOLStatus: "capability_unknown"}}
	got := resultText(r.rows(nil))
	for _, want := range []string{"Credential continuity: not verified", "Refresh your existing SmartThings device", "Wake-on-LAN capability unknown", "power operation not tested"} {
		if !strings.Contains(got, want) {
			t.Fatalf("missing %q: %s", want, got)
		}
	}
	if strings.Contains(got, "Wake-on-LAN configuration verified") {
		t.Fatal("unsupported observation presented as verified")
	}
	r = operationReport{action: "recover", reply: privilegedResult{Status: "passed", RecoveryStatus: "rolled_back", WOLReviewRequired: true}}
	if got := resultText(r.rows(nil)); !strings.Contains(got, "do not repeat recovery for WOL alone") || !strings.Contains(got, "Credential continuity: not verified") {
		t.Fatal(got)
	}
}

func TestResultObserverAndPresentationPreserveExecution(t *testing.T) {
	var out bytes.Buffer
	var report operationReport
	calls, screens := 0, 0
	secret := strings.Repeat("a", 64)
	run := report.observe(&out, func(req privilegedRequest) (privilegedResult, error) {
		calls++
		if req.Action == "backups" {
			return privilegedResult{Status: "passed"}, nil
		}
		if req.Action != "restore" || req.BackupDigest != secret {
			t.Fatal("request altered")
		}
		return privilegedResult{Status: "restored", CredentialContinuity: "verified"}, nil
	})
	show := func(m inspectionScreen) (string, error) {
		screens++
		if strings.Contains(resultText(m.rows), secret) {
			t.Fatal("digest leaked")
		}
		return "", errors.New("terminal unavailable")
	}
	_, err := run(privilegedRequest{Action: "backups"})
	if err != nil || report.presentWith(&out, err, show) != nil || screens != 0 {
		t.Fatal("successful read-only check unexpectedly presented a result")
	}
	_, err = run(privilegedRequest{Action: "restore", BackupDigest: secret})
	if err != nil || report.presentWith(&out, err, show) != nil || !report.screenFailed || calls != 2 || screens != 1 {
		t.Fatal("render failure altered committed operation result")
	}
	original := errors.New("operation failure")
	report.runErr = original
	if report.presentWith(&out, original, show) != original || calls != 2 || screens != 2 {
		t.Fatal("result rendering retried operation or changed the original error")
	}
	if !strings.Contains(out.String(), "No intermediate progress is reported.") {
		t.Fatal("missing honest waiting message")
	}
}

func TestResultScreenPTYHarness(t *testing.T) {
	mode := os.Getenv("COMPUTER_HOST_TEST_RESULT_PTY")
	if mode == "" {
		t.Skip("external PTY harness")
	}
	var report operationReport
	calls := 0
	run := report.observe(os.Stdout, func(req privilegedRequest) (privilegedResult, error) {
		calls++
		if req.Action != "upgrade" {
			t.Fatal("wrong request")
		}
		if mode == "result-failure" {
			return privilegedResult{Status: "error", ErrorCode: "rolled_back"}, errors.New("fixture failure")
		}
		return privilegedResult{Status: "installed_cleanup_required", CredentialContinuity: "verified"}, nil
	})
	_, original := run(privilegedRequest{Action: "upgrade", Power: "preserve"})
	err := report.present(os.Stdout, original)
	if err != original || calls != 1 || report.screenFailed {
		t.Fatal("unexpected result presentation")
	}
	fmt.Println("PTY RESULT CLOSED")
	line, err := readConfirmationLine(os.Stdin)
	if err != nil || line != "ordinary terminal input" {
		t.Fatal("terminal input not preserved")
	}
	fmt.Println("PTY RESULT INPUT PRESERVED")
}

func TestResultCloseIsReadOnly(t *testing.T) {
	m := inspectionScreen{frame: detailFrame{width: 64, height: 22}, rows: []detailRow{{"Outcome", "normal"}}, title: "RESULT"}
	_, cmd := m.Update(tea.KeyPressMsg{Code: tea.KeyEnter})
	if cmd == nil {
		t.Fatal("result did not close")
	}
	if _, ok := cmd().(tea.QuitMsg); !ok {
		t.Fatal("result close does not quit")
	}
}

func TestUninstallResultOptionalWOLRequiresExplicitContinue(t *testing.T) {
	for _, status := range []string{"uninstalled", "uninstalled_cleanup_required"} {
		for _, key := range []string{"enter", "esc", "q", "ctrl+c", ""} {
			for _, failed := range []bool{false, true} {
				var out bytes.Buffer
				report := operationReport{action: "uninstall", called: true, reply: privilegedResult{Status: status}}
				err := report.presentWith(&out, nil, func(m inspectionScreen) (string, error) {
					if failed {
						return key, errors.New("display failure")
					}
					return key, nil
				})
				want := status == "uninstalled" && key == "enter" && !failed
				if err != nil || report.continueWOL != want {
					t.Fatalf("unexpected continuation: %s %q failure=%t", status, key, failed)
				}
			}
		}
	}
}
