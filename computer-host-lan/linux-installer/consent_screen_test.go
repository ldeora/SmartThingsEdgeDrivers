package main

import (
	"bytes"
	"fmt"
	"strings"
	"testing"

	tea "charm.land/bubbletea/v2"
	"charm.land/lipgloss/v2"
)

func consentEvent(m consentScreen, msg tea.Msg) consentScreen {
	next, _ := m.Update(msg)
	return next.(consentScreen)
}

func TestFramedConsentExactSubmission(t *testing.T) {
	for _, token := range []string{"INSTALL", "REUSE", "RESTORE", "RECOVER", "UNINSTALL", "REMOVE"} {
		for _, tc := range []struct {
			value string
			want  bool
		}{
			{token, true}, {" " + token + " ", true},
			{strings.ToLower(token), false}, {token + "X", false},
			{token + "\n", false}, {token + "\x1b", false},
			{strings.Repeat(" ", 128) + token, false}, {"", false},
		} {
			m := consentScreen{frame: detailFrame{width: 64, height: 22, monochrome: true}, token: token}
			m = consentEvent(m, tea.PasteMsg{Content: tc.value})
			if m.accepted() {
				t.Fatal("paste authorized without explicit submission")
			}
			m = consentEvent(m, tea.KeyPressMsg{Code: tea.KeyEnter})
			if m.done != tc.want || m.accepted() != tc.want {
				t.Fatalf("%s / %q: accepted=%t want=%t", token, tc.value, m.accepted(), tc.want)
			}
			if tc.want {
				// A queued character or clear cannot alter submitted consent.
				m = consentEvent(m, tea.KeyPressMsg{Code: 'X', Text: "X"})
				if !m.accepted() {
					t.Fatal("queued input changed submitted approval")
				}
			} else {
				m = consentEvent(m, tea.KeyPressMsg{Code: 'u', Mod: tea.ModCtrl})
				m = consentEvent(m, tea.PasteMsg{Content: token})
				m = consentEvent(m, tea.KeyPressMsg{Code: tea.KeyEnter})
				if !m.done || !m.accepted() {
					t.Fatal("corrected confirmation did not succeed")
				}
			}
		}
	}
}

func TestFramedConsentResizeEditingAndCancel(t *testing.T) {
	m := consentScreen{frame: detailFrame{width: 64, height: 22, monochrome: true}, token: "RECOVER"}
	m = consentEvent(m, tea.KeyPressMsg{Code: 'q', Text: "q"})
	if m.done || m.input != "q" {
		t.Fatal("Q is ordinary text in a consent field")
	}
	m = consentEvent(m, tea.KeyPressMsg{Code: tea.KeyBackspace})
	m = consentEvent(m, tea.PasteMsg{Content: "RECOVER"})
	m = consentEvent(m, tea.WindowSizeMsg{Width: 63, Height: 20})
	m = consentEvent(m, tea.KeyPressMsg{Code: tea.KeyEnter})
	if m.done || m.accepted() {
		t.Fatal("hidden consent accepted")
	}
	m = consentEvent(m, tea.WindowSizeMsg{Width: 64, Height: 22})
	m = consentEvent(m, tea.KeyPressMsg{Code: tea.KeyEscape})
	if !m.done || m.accepted() {
		t.Fatal("Escape accepted consent")
	}
	m = consentEvent(m, tea.KeyPressMsg{Code: tea.KeyEnter})
	if m.accepted() {
		t.Fatal("queued Enter after Escape accepted consent")
	}
}

func TestOperationConsentDoesNotQuitBetweenReviewAndText(t *testing.T) {
	for _, token := range []string{"RECOVER", "UNINSTALL"} {
		screen := recoveryScreen()
		if token == "UNINSTALL" {
			screen = uninstallScreen()
		}
		screen.frame = detailFrame{width: 64, height: 22, monochrome: true}
		m := operationConsentScreen{operation: screen, token: token}
		next, cmd := m.Update(tea.KeyPressMsg{Code: '1', Text: "1"})
		m = next.(operationConsentScreen)
		if cmd != nil || m.consent != nil {
			t.Fatal("numeric highlight advanced without Enter")
		}
		next, cmd = m.Update(tea.KeyPressMsg{Code: tea.KeyEnter})
		m = next.(operationConsentScreen)
		if cmd != nil || m.consent == nil || m.consent.accepted() {
			t.Fatal("review did not transition safely")
		}
		if view := m.View().Content; !strings.Contains(view, "Type "+token+" to authorize:") ||
			lipgloss.Width(view) > 64 || lipgloss.Height(view) > 22 {
			t.Fatalf("confirmation not visible at minimum size:\n%s", view)
		}
		next, cmd = m.Update(tea.PasteMsg{Content: token})
		m = next.(operationConsentScreen)
		if cmd != nil || m.consent.accepted() {
			t.Fatal("typing alone authorized")
		}
		next, cmd = m.Update(tea.KeyPressMsg{Code: tea.KeyEnter})
		if cmd == nil || !next.(operationConsentScreen).consent.accepted() {
			t.Fatal("submitted literal not accepted")
		}
	}
}

func TestBackupConsentBindsOriginalIdentity(t *testing.T) {
	items := detailBackupFixtures()
	m := backupConsentScreen{chooser: backupScreen{
		frame: detailFrame{width: 64, height: 22, monochrome: true}, backups: items,
		current: "0.4.7-rc.3", selected: -1,
	}}
	next, _ := m.Update(tea.KeyPressMsg{Code: tea.KeyEnd})
	m = next.(backupConsentScreen)
	next, cmd := m.Update(tea.KeyPressMsg{Code: tea.KeyEnter})
	m = next.(backupConsentScreen)
	if cmd != nil || m.consent == nil || m.chooser.selected != 31 {
		t.Fatal("backup selection did not advance to confirmation")
	}
	if view := m.View().Content; !strings.Contains(view, items[31].Name) ||
		!strings.Contains(view, "Type RESTORE to authorize:") || strings.Contains(view, items[31].Digest) {
		t.Fatalf("incorrect backup confirmation:\n%s", view)
	}
	next, cmd = m.Update(tea.KeyPressMsg{Code: tea.KeyEscape})
	m = next.(backupConsentScreen)
	if cmd != nil || m.consent != nil || m.chooser.selected != -1 || m.chooser.cursor != 31 {
		t.Fatal("Escape did not return to selected backup")
	}
	for _, tc := range []struct {
		approval backupApproval
		want     int
		err      bool
	}{
		{backupApproval{}, 1, false},
		{backupApproval{index: 32, approved: true}, 1, true},
		{backupApproval{index: 31, name: items[31].Name, digest: strings.Repeat("b", 64), approved: true}, 1, true},
		{backupApproval{index: 31, name: items[31].Name, digest: items[31].Digest, approved: true}, 2, false},
	} {
		var out bytes.Buffer
		calls := 0
		err := restoreWizardWithApproval(&out, func(req privilegedRequest) (privilegedResult, error) {
			calls++
			if req.Action == "backups" {
				return privilegedResult{Status: "passed", Backups: &items}, nil
			}
			if req.Action != "restore" || req.Backup != items[31].Name || req.BackupDigest != items[31].Digest {
				t.Fatal("incorrect restore binding")
			}
			return privilegedResult{Status: "restored", IdentityPreserved: "verified", CredentialContinuity: "verified"}, nil
		}, "0.4.7-rc.3", func(_ []backupSummary, _ string) (backupApproval, error) {
			return tc.approval, nil
		})
		if calls != tc.want || (err != nil) != tc.err {
			t.Fatalf("unexpected approval result: calls=%d err=%v", calls, err)
		}
	}
}

func TestNICSelectionAndSeparateWOLConsent(t *testing.T) {
	m := newNICSelection([]string{"LAN0", "LAN1"}, "LAN1", false)
	m.frame = detailFrame{width: 64, height: 22, monochrome: true}
	next, cmd := m.Update(tea.KeyPressMsg{Code: tea.KeyEnter})
	if cmd == nil || next.(nicSelectionScreen).chosen != "LAN1" {
		t.Fatal("suggested interface not selected")
	}
	m = newNICSelection(nil, "", false)
	m.frame = detailFrame{width: 64, height: 22, monochrome: true}
	next, cmd = m.Update(tea.KeyPressMsg{Code: tea.KeyEnter})
	m = next.(nicSelectionScreen)
	if cmd != nil || m.manual == nil {
		t.Fatal("manual interface selection not available")
	}
	next, cmd = m.Update(tea.KeyPressMsg{Code: tea.KeyEscape})
	m = next.(nicSelectionScreen)
	if cmd != nil || m.manual != nil || m.done {
		t.Fatal("Escape did not return to interface list")
	}
	next, _ = m.Update(tea.KeyPressMsg{Code: tea.KeyEnter})
	m = next.(nicSelectionScreen)
	next, _ = m.Update(tea.PasteMsg{Content: "LAN0"})
	m = next.(nicSelectionScreen)
	next, cmd = m.Update(tea.KeyPressMsg{Code: tea.KeyEnter})
	if cmd == nil || next.(nicSelectionScreen).chosen != "LAN0" {
		t.Fatal("manual interface not bound")
	}
	for _, status := range []string{"managed", "not_managed", "review_required", "runtime_only", "error"} {
		for _, approve := range []bool{false, true} {
			var out bytes.Buffer
			calls, reviews := 0, 0
			err := manageWOLSelected(&out, "LAN0", func(req privilegedRequest) (privilegedResult, error) {
				calls++
				if req.WOLInterface == nil || *req.WOLInterface != "LAN0" || req.validate() != nil {
					t.Fatal("invalid interface binding")
				}
				if req.Action == "wol-check" {
					if status == "error" {
						return privilegedResult{}, fmt.Errorf("authorization cancelled")
					}
					return privilegedResult{Status: "passed", WOLStatus: status}, nil
				}
				if req.Action != "wol-remove" {
					t.Fatal("unexpected WOL action")
				}
				return privilegedResult{Status: "passed", WOLStatus: "removed"}, nil
			}, func(nic string, reply privilegedResult) (bool, error) {
				reviews++
				if nic != "LAN0" || reply.WOLStatus != status {
					t.Fatal("incorrect WOL review")
				}
				return approve, nil
			})
			want, wantReviews := 1, 1
			if status == "error" {
				wantReviews = 0
			} else if approve && status != "not_managed" {
				want = 2
			}
			if calls != want || reviews != wantReviews || (err != nil) != (status == "error") {
				t.Fatalf("WOL status=%s approve=%t calls=%d reviews=%d err=%v", status, approve, calls, reviews, err)
			}
		}
	}
}

func TestConsentRejectedPasteCanBeCorrected(t *testing.T) {
	m := consentScreen{frame: detailFrame{width: 64, height: 22, monochrome: true}, token: "INSTALL"}
	m = consentEvent(m, tea.PasteMsg{Content: "INSTALL\n"})
	m = consentEvent(m, tea.KeyPressMsg{Code: tea.KeyEnter})
	if m.done || !m.invalid || m.input != "" {
		t.Fatal("invalid paste was not rejected atomically")
	}
	m = consentEvent(m, tea.PasteMsg{Content: "INSTAL"})
	m = consentEvent(m, tea.KeyPressMsg{Code: tea.KeyEnter})
	if m.done || m.invalid || !m.mistyped {
		t.Fatal("mistyped word did not remain editable")
	}
	m = consentEvent(m, tea.KeyPressMsg{Code: 'L', Text: "L"})
	m = consentEvent(m, tea.KeyPressMsg{Code: tea.KeyEnter})
	if !m.accepted() {
		t.Fatal("corrected word did not authorize")
	}
	m = consentScreen{frame: m.frame, token: "INSTALL"}
	m = consentEvent(m, tea.PasteMsg{Content: "INSTALLX"})
	m = consentEvent(m, tea.PasteMsg{Content: "\n"})
	m = consentEvent(m, tea.KeyPressMsg{Code: tea.KeyBackspace})
	m = consentEvent(m, tea.KeyPressMsg{Code: tea.KeyEnter})
	if !m.accepted() {
		t.Fatal("Backspace did not clear the rejected-input flag")
	}
}
