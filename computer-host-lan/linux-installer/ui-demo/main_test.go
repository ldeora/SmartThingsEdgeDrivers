package main

import (
	"strings"
	"testing"

	"charm.land/lipgloss/v2"
)

func testModel() model {
	return model{page: menu, width: 100, height: 28, power: 1, monochrome: true}
}

func TestWizardChoicesAndBack(t *testing.T) {
	m := testModel()
	for _, key := range []string{"2", "enter", "enter", "down", "enter"} {
		if m.key(key) {
			t.Fatal("unexpected quit")
		}
	}
	if m.page != power || m.cursor != 1 || m.hub != 1 {
		t.Fatalf("wrong wizard state: %+v", m)
	}
	m.key("up")
	m.key("enter")
	m.key("down")
	m.key("enter")
	if m.page != review || m.power != 0 || m.wol != 1 {
		t.Fatalf("choices lost: %+v", m)
	}
	view := m.render()
	for _, want := range []string{"DEMO ONLY", "Monitoring only", "Configure persistent Wake-on-LAN", "198.51.100.24"} {
		if !strings.Contains(view, want) {
			t.Errorf("review missing %q", want)
		}
	}
	m.key("esc")
	if m.page != power || m.focus != 1 || m.wol != 1 {
		t.Fatalf("back lost choices: %+v", m)
	}
	m.key("enter")
	m.key("enter")
	if m.page != progress || m.completed != 0 {
		t.Fatalf("unexpected demo progress: %+v", m)
	}
	for i := 0; i < len(stages); i++ {
		m.key("enter")
	}
	if m.page != progress || m.completed != len(stages) {
		t.Fatalf("wrong simulated progress: %+v", m)
	}
	m.key("enter")
	if m.page != finish || !strings.Contains(m.render(), "Nothing was installed, changed or verified.") {
		t.Fatal("missing explicit simulated completion")
	}
	m.key("enter")
	if m.page != menu {
		t.Fatal("did not return to menu")
	}
}

func TestMaintenancePreviewRoutes(t *testing.T) {
	for _, tc := range []struct {
		key  string
		want screen
	}{{"1", welcome}, {"2", welcome}, {"3", welcome}, {"4", backups}, {"5", operation}, {"6", inspect}, {"7", operation}} {
		m := testModel()
		m.key(tc.key)
		if m.page != menu {
			t.Fatal("numeric key must only highlight")
		}
		m.key("enter")
		if m.page != tc.want {
			t.Errorf("task %s: got %d, want %d", tc.key, m.page, tc.want)
		}
		if !strings.Contains(m.render(), "DEMO ONLY") {
			t.Errorf("task %s not identified as demo", tc.key)
		}
	}
	m := testModel()
	m.key("4")
	m.key("enter")
	m.key("down")
	m.key("enter")
	if m.page != operation || !strings.Contains(m.render(), "0.4.6-rc.2") {
		t.Fatal("selected example backup not shown")
	}
	m.key("esc")
	if m.page != backups || m.backup != 1 {
		t.Fatal("back lost backup choice")
	}
}

func TestRenderBoundsAndMonochrome(t *testing.T) {
	for _, size := range [][2]int{{64, 22}, {80, 24}, {88, 24}, {106, 30}, {132, 42}} {
		for page := menu; page <= operation; page++ {
			for _, mono := range []bool{false, true} {
				m := testModel()
				m.page, m.width, m.height, m.monochrome = page, size[0], size[1], mono
				m.cursor, m.completed = 3, 4
				got := m.render()
				lines := strings.Split(got, "\n")
				if len(lines) > m.height {
					t.Fatalf("page %d: height %d > %d", page, len(lines), m.height)
				}
				for _, line := range lines {
					if lipgloss.Width(line) > m.width {
						t.Fatalf("page %d: width %d > %d", page, lipgloss.Width(line), m.width)
					}
				}
				if !strings.Contains(got, "DEMO ONLY") {
					t.Fatalf("page %d: demo marker not visible", page)
				}
				if mono && strings.Contains(got, "\x1b") {
					t.Fatal("ANSI styling in monochrome content")
				}
			}
		}
	}
}

func TestSmallWindowAndExit(t *testing.T) {
	m := testModel()
	m.width, m.height = 40, 10
	m.key("enter")
	if m.page != menu || !strings.Contains(m.render(), "Resize") {
		t.Fatal("small terminal allowed invisible navigation")
	}
	if !m.key("q") {
		t.Fatal("small terminal cannot quit")
	}
	m = testModel()
	m.key("0")
	if !m.key("enter") {
		t.Fatal("exit task did not quit")
	}
}
