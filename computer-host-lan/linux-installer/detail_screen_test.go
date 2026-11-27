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

func detailInspectFixture(t *testing.T) apiInspect {
	t.Helper()
	info, err := fixtureClient(t).inspect()
	if err != nil {
		t.Fatal(err)
	}
	return info
}

func detailBackupFixtures() []backupSummary {
	var items []backupSummary
	for i := 0; i < 32; i++ {
		b := testBackup()
		b.Name = fmt.Sprintf("snapshot-test%02d", i+1)
		b.CapturedAt -= int64(i) * 60
		items = append(items, b)
	}
	return items
}

func assertDetailBounds(t *testing.T, view string, width, height int, mono bool) {
	t.Helper()
	if lipgloss.Width(view) > width || lipgloss.Height(view) > height {
		t.Fatalf("frame exceeds %dx%d: %dx%d", width, height, lipgloss.Width(view), lipgloss.Height(view))
	}
	if mono && strings.Contains(view, "\x1b") {
		t.Fatal("monochrome frame contains escape sequences")
	}
}

func TestInspectionFrameObservationsAndScroll(t *testing.T) {
	info := detailInspectFixture(t)
	info.Installation.ServiceFile = "unsafe"
	info.Installation.PowerDropin = "unreadable"
	info.Installation.AgentServiceState = "failed"
	info.Installation.AgentServiceEnabled = "masked"
	info.Python.SelectedInterpreter = "/usr/" + strings.Repeat("x", 120)
	info.Checks = append(info.Checks, apiCheck{ID: "managed_path_integrity", Status: "blocked"})
	rows := inspectionRows(info, "0.4.7-rc.3")
	for _, mono := range []bool{false, true} {
		m := inspectionScreen{frame: detailFrame{monochrome: mono}, rows: rows}
		for _, size := range [][2]int{{64, 22}, {80, 24}, {100, 30}, {140, 50}} {
			model, _ := m.Update(tea.WindowSizeMsg{Width: size[0], Height: size[1]})
			m = model.(inspectionScreen)
			model, _ = m.Update(tea.KeyPressMsg{Code: tea.KeyHome})
			m = model.(inspectionScreen)
			view := m.View().Content
			assertDetailBounds(t, view, size[0], size[1], mono)
			// Check text separately from escape sequences.
			all := m.content()
			var text []string
			for _, row := range all {
				text = append(text, row.text)
			}
			joined := strings.Join(text, "\n")
			for _, want := range []string{"Service file: unsafe", "Power opt-in file: unreadable",
				"Agent service: failed", "Start at boot: masked", "Managed file integrity: blocked",
				"Recovery not inspected; identity/key not read or verified."} {
				if !strings.Contains(joined, want) {
					t.Fatalf("missing observation %q", want)
				}
			}
			if !strings.Contains(strings.ReplaceAll(joined, "\n", ""), info.Python.SelectedInterpreter) {
				t.Fatal("long interpreter path was truncated")
			}
			model, _ = m.Update(tea.KeyPressMsg{Code: tea.KeyEnd})
			m = model.(inspectionScreen)
			view = m.View().Content
			assertDetailBounds(t, view, size[0], size[1], mono)
			if m.offset != m.maxOffset() || !strings.Contains(view, "not read or verified.") {
				t.Fatal("last inspection page not reachable")
			}
		}
	}
}

func TestBackupFrameAllSelectionsAndResize(t *testing.T) {
	items := detailBackupFixtures()
	items[31].Name = "snapshot-" + strings.Repeat("z", 64)
	items[31].Version = strings.Repeat("v", 64)
	items[31].Power = "keep"
	for _, mono := range []bool{false, true} {
		m := backupScreen{frame: detailFrame{monochrome: mono}, backups: items,
			current: strings.Repeat("c", 64), selected: -1}
		for _, size := range [][2]int{{64, 22}, {80, 24}, {100, 30}, {140, 50}} {
			model, _ := m.Update(tea.WindowSizeMsg{Width: size[0], Height: size[1]})
			m = model.(backupScreen)
			for index := range items {
				m.cursor = index
				rows, status, _, fits := m.page()
				if !fits || len(rows) != m.frame.capacity() ||
					!strings.Contains(status, fmt.Sprintf("Backup %d of 32", index+1)) {
					t.Fatalf("selected backup %d not fully displayed at %v: fits=%t rows=%d status=%q", index+1, size, fits, len(rows), status)
				}
				var text []string
				for _, row := range rows {
					if lipgloss.Width(row.text) > m.frame.bodyWidth() {
						t.Fatalf("oversized detail: %q", row.text)
					}
					text = append(text, row.text)
				}
				joined := strings.Join(text, "")
				if !strings.Contains(joined, items[index].Name) ||
					!strings.Contains(joined, items[index].Version) ||
					strings.Contains(joined, items[index].Digest) {
					t.Fatal("selected identity incomplete or digest exposed")
				}
				assertDetailBounds(t, m.View().Content, size[0], size[1], mono)
			}
		}
		model, _ := m.Update(tea.WindowSizeMsg{Width: 60, Height: 20})
		m = model.(backupScreen)
		model, cmd := m.Update(tea.KeyPressMsg{Code: tea.KeyEnter})
		m = model.(backupScreen)
		if cmd != nil || m.selected != -1 {
			t.Fatal("invisible selection accepted")
		}
		model, _ = m.Update(tea.WindowSizeMsg{Width: 64, Height: 22})
		m = model.(backupScreen)
		model, cmd = m.Update(tea.KeyPressMsg{Code: tea.KeyEnter})
		if cmd == nil || model.(backupScreen).selected != 31 {
			t.Fatal("visible selection lost after resize")
		}
		model, cmd = m.Update(tea.KeyPressMsg{Code: tea.KeyEscape})
		if cmd == nil || model.(backupScreen).selected != -1 {
			t.Fatal("Escape did not cancel")
		}
	}
}

func TestRestoreChooserStillRequiresExactConsentAndOriginalBinding(t *testing.T) {
	items := detailBackupFixtures()
	for _, tc := range []struct {
		index int
		input string
		calls int
	}{
		{-1, "RESTORE\n", 1},
		{32, "RESTORE\n", 1},
		{31, "NO\n", 1},
		{31, "RESTORE", 1},
		{31, "RESTORE\n", 2},
	} {
		var out bytes.Buffer
		calls := 0
		err := restoreWizardWithChooser(strings.NewReader(tc.input), &out,
			func(req privilegedRequest) (privilegedResult, error) {
				calls++
				if req.Action == "backups" {
					return privilegedResult{Status: "passed", Backups: &items}, nil
				}
				want := items[31]
				if req.Action != "restore" || req.Backup != want.Name || req.BackupDigest != want.Digest {
					t.Fatal("selected name/digest binding changed")
				}
				return privilegedResult{Status: "restored", IdentityPreserved: "verified", CredentialContinuity: "verified"}, nil
			}, "0.4.7-rc.3", func(backups []backupSummary, _ string) (int, error) {
				if len(backups) != 32 || backups[31] != items[31] {
					t.Fatal("chooser did not receive sorted list")
				}
				backups[31].Name = "snapshot-mutated"
				return tc.index, nil
			})
		if calls != tc.calls || (err != nil) != (tc.index == 32) {
			t.Fatalf("unexpected outcome: %+v calls=%d err=%v", tc, calls, err)
		}
	}
}

func TestRestoreChooserRejectsInvalidOrEmptyList(t *testing.T) {
	empty := []backupSummary{}
	for _, reply := range []privilegedResult{
		{Status: "error"},
		{Status: "passed"},
		{Status: "passed", Backups: &empty},
	} {
		var out bytes.Buffer
		err := restoreWizardWithChooser(strings.NewReader("RESTORE\n"), &out,
			func(req privilegedRequest) (privilegedResult, error) {
				if req.Action != "backups" {
					t.Fatal("unexpected action")
				}
				return reply, nil
			}, "unknown", func(_ []backupSummary, _ string) (int, error) {
				t.Fatal("invalid or empty list reached chooser")
				return -1, nil
			})
		if (err != nil) != (reply.Backups == nil) {
			t.Fatalf("unexpected result: %v", err)
		}
	}
}

// Invoked by the external PTY fixture only. No actual privilege provider
// or managed host mutation is reachable.
func TestDetailScreenPTYHarness(t *testing.T) {
	mode := os.Getenv("COMPUTER_HOST_TEST_DETAIL_PTY")
	if mode == "" {
		t.Skip("external PTY harness")
	}
	if mode == "inspect" {
		m := inspectionScreen{
			frame: detailFrame{monochrome: true},
			rows:  inspectionRows(detailInspectFixture(t), "0.4.7-rc.3"),
		}
		if _, err := tea.NewProgram(m).Run(); err != nil {
			t.Fatal(err)
		}
		fmt.Println("PTY INSPECTION CLOSED")
		return
	}
	items := detailBackupFixtures()
	calls := 0
	err := restoreWizardWithChooser(os.Stdin, os.Stdout, func(req privilegedRequest) (privilegedResult, error) {
		calls++
		if req.Action != "backups" {
			t.Fatal("mutation reached PTY fixture")
		}
		return privilegedResult{Status: "passed", Backups: &items}, nil
	}, "0.4.7-rc.3", selectBackupScreen)
	if err != nil || calls != 1 {
		t.Fatalf("unexpected restore cancellation: %v, calls=%d", err, calls)
	}
	fmt.Println("PTY RESTORE CLOSED")
}

func TestInspectionOverviewDoesNotImplyRuntimeVerification(t *testing.T) {
	info := detailInspectFixture(t)
	info.Installation.Detected = true
	info.Installation.ServiceFile = "present"
	info.Installation.AgentServiceState = "active"
	info.Installation.AgentServiceEnabled = "enabled"
	info.Installation.PowerDropin = "present"
	info.Installation.AvahiServiceFile = "absent"
	rows := inspectionSummary(info, "0.4.7-rc.3")
	if rows[1].text != "Agent: running, starts at boot" ||
		rows[3].text != "Power control: Configured on" ||
		rows[4].text != "Hub discovery: Advertisement file missing" || rows[4].tone != "warning" {
		t.Fatalf("unexpected installed summary: %+v", rows)
	}
	info.Installation.AvahiServiceFile = "present"
	info.Avahi.ServicesDirectory = "present"
	info.Avahi.DaemonState = "active"
	rows = inspectionSummary(info, "0.4.7-rc.3")
	if rows[4].text != "Hub discovery: Advertisement configured" {
		t.Fatal("configured advertisement was not described accurately")
	}
	info.Avahi.DaemonState = "inactive"
	info.Installation.PowerDropin = "unreadable"
	rows = inspectionSummary(info, "unknown")
	if rows[3].text != "Power control: Unknown" || rows[3].tone != "warning" || rows[4].tone != "warning" {
		t.Fatal("uncertain power or discovery state was presented as healthy")
	}
	info.Installation.Detected = false
	info.Installation.ServiceFile = "absent"
	info.Installation.AvahiServiceFile = "absent"
	if inspectionSummary(info, "unknown")[4].tone == "warning" {
		t.Fatal("expected missing advertisement on an uninstalled host")
	}
}

func TestMaintenanceHubReturnsOnlyAfterInspection(t *testing.T) {
	for _, actions := range [][]string{{"inspect", "inspect", ""}, {"inspect", "restore"}, {"upgrade"}, {""}} {
		calls := 0
		var dispatched []string
		err := runMaintenanceHub(func(dispatch func(string) error) error {
			if calls >= len(actions) {
				t.Fatal("unexpected menu reopen")
			}
			action := actions[calls]
			calls++
			if action == "" {
				return nil
			}
			return dispatch(action)
		}, func(action string) error {
			dispatched = append(dispatched, action)
			return nil
		})
		if err != nil || calls != len(actions) {
			t.Fatalf("unexpected navigation: %v, %d", err, calls)
		}
		if len(dispatched) != len(actions)-1 && actions[len(actions)-1] == "" {
			t.Fatal("exit dispatched an operation")
		}
	}
}

func TestBackupViewportRemainsStableWhileMovingUp(t *testing.T) {
	m := backupScreen{
		frame:   detailFrame{width: 80, height: 24, monochrome: true},
		backups: detailBackupFixtures(), current: "0.4.7-rc.3", selected: -1,
	}
	model, _ := m.Update(tea.KeyPressMsg{Code: tea.KeyEnd})
	m = model.(backupScreen)
	first := m.first
	if first == 0 || m.cursor != 31 {
		t.Fatal("End did not scroll to the final entry")
	}
	model, _ = m.Update(tea.KeyPressMsg{Code: tea.KeyUp})
	m = model.(backupScreen)
	if m.first != first || m.cursor != 30 {
		t.Fatal("viewport moved even though selection remained visible")
	}
	model, _ = m.Update(tea.KeyPressMsg{Code: tea.KeyHome})
	m = model.(backupScreen)
	if m.first != 0 || m.cursor != 0 {
		t.Fatal("Home did not restore first page")
	}
}

func TestBackupPlainLanguage(t *testing.T) {
	b := testBackup()
	for _, tc := range []struct {
		power, want string
	}{{"enabled", "on"}, {"disabled", "off"}, {"keep", "keep current"}} {
		b.Power = tc.power
		rows := backupDetails(b)
		if !strings.Contains(rows[4].text, "Running: yes | Starts at boot: yes | Power: "+tc.want) ||
			rows[5].tone != "warning" {
			t.Fatalf("unexpected backup details: %+v", rows)
		}
	}
}

func TestBackupListingAuthorizationFailureDoesNotOpenChooser(t *testing.T) {
	var out bytes.Buffer
	calls := 0
	denied := fmt.Errorf("authorization cancelled")
	err := restoreWizardWithChooser(strings.NewReader("RESTORE\n"), &out,
		func(req privilegedRequest) (privilegedResult, error) {
			calls++
			if req.Action != "backups" {
				t.Fatal("unexpected action")
			}
			return privilegedResult{}, denied
		}, "unknown", func(_ []backupSummary, _ string) (int, error) {
			t.Fatal("failed authorization opened chooser")
			return -1, nil
		})
	if err != denied || calls != 1 {
		t.Fatalf("unexpected authorization result: %v, %d", err, calls)
	}
}
