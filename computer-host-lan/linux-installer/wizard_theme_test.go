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

func TestStyledLiveWizardTracksActualFields(t *testing.T) {
	t.Setenv("NO_COLOR", "1")
	t.Setenv("TERM", "xterm-256color")
	client := fixtureClient(t)
	ins, err := client.inspect()
	if err != nil {
		t.Fatal(err)
	}
	s := liveSelection{api: client, inspection: ins, hubChoice: "skip", powerChoice: "keep", wolChoice: "keep"}
	s.recordHubChoice("skip")
	form := styledLiveForm(&s, false).WithWidth(110).WithHeight(40)
	for i, want := range []string{"welcome", "hub", "power", "wol", "review"} {
		if i > 0 {
			deliverFormMessage(t, form, huh.NextField())
		}
		if key := form.GetFocusedField().GetKey(); key != want {
			t.Fatalf("step %d: field %q, want %q", i, key, want)
		}
		view := form.View()
		label := []string{"Welcome", "Hub", "Power & WOL", "Review"}[wizardStage(want)]
		if !strings.Contains(view, "> "+label) || !strings.Contains(view, "COMPUTER HOST LAN") {
			t.Fatalf("sidebar lost active field %q:\n%s", want, view)
		}
		if lipgloss.Width(view) > 110 {
			t.Fatalf("wide layout exceeds terminal width: %d", lipgloss.Width(view))
		}
	}
	if !strings.Contains(form.View(), "Power control: Keep power control enabled") {
		t.Fatal("styled review lost actual plan")
	}

	// Changing a selection must still invalidate the native Huh description.
	s.powerChoice = "disabled"
	deliverFormMessage(t, form, tea.WindowSizeMsg{Width: 110, Height: 40})
	if view := form.View(); !strings.Contains(view, "Power control: Monitoring only (power control off)") ||
		strings.Contains(view, "Power control: Keep power control enabled") {
		t.Fatalf("styled review kept stale plan:\n%s", view)
	}

	// Explicit width changes model the layout's wide/compact sizing contract.
	form.WithWidth(80)
	deliverFormMessage(t, form, tea.WindowSizeMsg{Width: 80, Height: 40})
	if view := form.View(); strings.Contains(view, "COMPUTER HOST LAN") ||
		!strings.Contains(view, "Review your choices") || lipgloss.Width(view) > 80 {
		t.Fatalf("compact review lost content or retained sidebar:\n%s", view)
	}
	form.WithWidth(110)
	deliverFormMessage(t, form, tea.WindowSizeMsg{Width: 110, Height: 40})
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
		want := size
		if size >= wizardSidebarMinWidth {
			want -= wizardSidebarWidth + 1
		}
		if got != want || l.width != size {
			t.Errorf("width %d: got %d, want %d", size, got, want)
		}
		if lipgloss.Width(l.sidebar(2)) != wizardSidebarWidth {
			t.Fatal("sidebar width changed")
		}
	}
}
