package main

import (
	"reflect"
	"strings"
	"testing"

	tea "charm.land/bubbletea/v2"
	"charm.land/huh/v2"
	"charm.land/lipgloss/v2"
)

func TestWizardStages(t *testing.T) {
	for key, want := range map[string]int{
		"welcome": 0, "hub": 1, "hub-address": 1,
		"power": 2, "wol": 2, "network": 2, "review": 3,
		"": -1, "unknown": -1,
	} {
		if got := wizardStage(key); got != want {
			t.Errorf("field %q: stage %d, want %d", key, got, want)
		}
	}
}

func TestWizardThemeMonochromeAndHelpContrast(t *testing.T) {
	plain := lipgloss.NewStyle()
	for _, dark := range []bool{false, true} {
		mono := wizardTheme(true).Theme(dark)
		for _, style := range []lipgloss.Style{
			mono.Focused.Title, mono.Focused.SelectedOption,
			mono.Focused.FocusedButton, mono.Focused.BlurredButton,
			mono.Focused.TextInput.Placeholder, mono.Help.ShortKey,
			mono.Help.ShortDesc, mono.Help.ShortSeparator,
		} {
			if !reflect.DeepEqual(style.GetForeground(), plain.GetForeground()) ||
				!reflect.DeepEqual(style.GetBackground(), plain.GetBackground()) {
				t.Fatal("monochrome wizard contains an explicit color")
			}
		}
		color := wizardTheme(false).Theme(dark)
		for _, style := range []lipgloss.Style{color.Help.ShortKey, color.Help.ShortDesc, color.Help.ShortSeparator} {
			if !reflect.DeepEqual(style.GetBackground(), lipgloss.Color(uiNavy)) {
				t.Fatal("help text lost its matched background")
			}
		}
	}
}

// The terminal may report a light background or never answer the query.
// Neither case should make the dark application panel unreadable.
func TestWizardThemeUsesMatchedColorsRegardlessOfBackgroundReport(t *testing.T) {
	for _, dark := range []bool{false, true} {
		styles := wizardTheme(false).Theme(dark)
		for _, tc := range []struct {
			style lipgloss.Style
			fg    string
			bg    string
		}{
			{styles.Group.Title, uiCyan, uiNavy},
			{styles.Focused.Title, uiCyan, uiNavy},
			{styles.Focused.Description, uiMuted, uiNavy},
			{styles.Blurred.Description, uiMuted, uiNavy},
			{styles.Focused.UnselectedOption, uiText, uiNavy},
			{styles.Focused.SelectedOption, uiSelected, uiHighlight},
			{styles.Blurred.SelectSelector, uiCyan, uiNavy},
			{styles.Focused.TextInput.Text, uiText, uiNavy},
			{styles.Focused.TextInput.Placeholder, uiMuted, uiNavy},
			{styles.Focused.ErrorMessage, uiWarning, uiNavy},
		} {
			if !reflect.DeepEqual(tc.style.GetForeground(), lipgloss.Color(tc.fg)) ||
				!reflect.DeepEqual(tc.style.GetBackground(), lipgloss.Color(tc.bg)) {
				t.Errorf("background report %t: expected paired colors %s on %s", dark, tc.fg, tc.bg)
			}
		}
	}
}

func fixtureWizard(t *testing.T, monochrome bool) (wizardScreen, *liveSelection) {
	t.Helper()
	client := fixtureClient(t)
	ins, err := client.inspect()
	if err != nil {
		t.Fatal(err)
	}
	s := &liveSelection{api: client, inspection: ins, hubChoice: "skip", powerChoice: "keep", wolChoice: "keep"}
	s.recordHubChoice("skip")
	return newWizardScreen(s, false, monochrome), s
}

func TestStyledLiveWizardTracksActualFields(t *testing.T) {
	m, s := fixtureWizard(t, true)
	m.Update(tea.WindowSizeMsg{Width: 110, Height: 40})
	form := m.form
	for i, want := range []string{"welcome", "hub", "power", "wol", "review"} {
		if i > 0 {
			deliverFormMessage(t, form, huh.NextField())
		}
		if key := form.GetFocusedField().GetKey(); key != want {
			t.Fatalf("step %d: field %q, want %q", i, key, want)
		}
		view, fits := m.layout.render(form)
		label := []string{"Welcome", "Hub", "Power & WOL", "Review"}[wizardStage(want)]
		if !fits || !strings.Contains(view, "> "+label) || !strings.Contains(view, "COMPUTER HOST LAN") ||
			!strings.Contains(view, "Ctrl+C Cancel") {
			t.Fatalf("frame lost active field %q:\n%s", want, view)
		}
		if lipgloss.Width(view) > 110 || lipgloss.Height(view) > 40 {
			t.Fatalf("wide layout exceeds terminal: %dx%d", lipgloss.Width(view), lipgloss.Height(view))
		}
	}
	if !strings.Contains(form.View(), "Power control: Keep power control enabled") {
		t.Fatal("styled review lost actual plan")
	}

	// The native Review description must still update after changes.
	s.powerChoice = "disabled"
	deliverFormMessage(t, form, tea.WindowSizeMsg{Width: 110, Height: 40})
	if view := form.View(); !strings.Contains(view, "Power control: Monitoring only (power control off)") ||
		strings.Contains(view, "Power control: Keep power control enabled") {
		t.Fatalf("styled review kept stale plan:\n%s", view)
	}

	m.Update(tea.WindowSizeMsg{Width: 80, Height: 40})
	if view, fits := m.layout.render(form); !fits || strings.Contains(view, "> Review") ||
		!strings.Contains(view, "Review your choices") || lipgloss.Width(view) > 80 {
		t.Fatalf("compact review lost content or retained sidebar:\n%s", view)
	}
	m.Update(tea.WindowSizeMsg{Width: 110, Height: 40})
	if !strings.Contains(form.View(), "> Review") {
		t.Fatal("sidebar did not return after widening")
	}
	deliverFormMessage(t, form, huh.PrevField())
	if form.GetFocusedField().GetKey() != "wol" || !strings.Contains(form.View(), "> Power & WOL") {
		t.Fatal("sidebar did not follow native back navigation")
	}
}

func TestWizardLayoutWidth(t *testing.T) {
	l := &wizardLayout{monochrome: true}
	for _, size := range []int{64, 80, 99, 100, 110, 132} {
		got := l.GroupWidth(nil, nil, size)
		want := min(size, wizardMaxWidth) - 4
		if size >= wizardSidebarMinWidth {
			want -= wizardSidebarWidth + 1
		}
		if got != want || l.width != size {
			t.Errorf("width %d: got %d, want %d", size, got, want)
		}
		if lipgloss.Width(l.sidebarLine(2, 4)) != wizardSidebarWidth {
			t.Fatal("sidebar width changed")
		}
	}
}

func TestWizardFrameResizeAndCancel(t *testing.T) {
	for _, mono := range []bool{false, true} {
		m, _ := fixtureWizard(t, mono)
		m.Update(tea.WindowSizeMsg{Width: 60, Height: 18})
		if view, fits := m.layout.render(m.form); fits || !strings.Contains(view, "60x18") {
			t.Fatal("undersized terminal did not show resize notice")
		}
		m.Update(tea.KeyPressMsg{Code: tea.KeyEnter})
		if m.form.GetFocusedField().GetKey() != "welcome" || m.form.State != huh.StateNormal {
			t.Fatal("invisible page accepted Enter")
		}
		m.Update(tea.WindowSizeMsg{Width: 110, Height: 22})
		if view, fits := m.layout.render(m.form); !fits || lipgloss.Height(view) > 22 ||
			!strings.Contains(view, "Ctrl+C Cancel") {
			t.Fatalf("22-row welcome cannot be displayed:\n%s", view)
		}
		m.Update(tea.WindowSizeMsg{Width: 110, Height: 18})
		m.Update(tea.KeyPressMsg{Code: 'c', Mod: tea.ModCtrl})
		if m.form.State != huh.StateAborted {
			t.Fatal("Ctrl+C cannot cancel an undersized terminal")
		}
	}
}
