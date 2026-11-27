package main

import (
	"os"
	"strings"

	"charm.land/huh/v2"
	"charm.land/lipgloss/v2"
)

// Shared palette for the maintenance chooser and setup wizard. The sidebar
// has its own navy background; the form body respects the terminal background.
const (
	uiNavy      = "#0D1729"
	uiPanel     = "#16283C"
	uiText      = "#E2E8F0"
	uiMuted     = "#A8BDD3"
	uiCyan      = "#7DD3FC"
	uiSelected  = "#CFFAFE"
	uiHighlight = "#164E63"
	uiTeal      = "#5EEAD4"
	uiWarning   = "#FBBF24"
)

func wizardTheme(monochrome bool) huh.Theme {
	return huh.ThemeFunc(func(dark bool) *huh.Styles {
		t := huh.ThemeBase(dark)
		plain := lipgloss.NewStyle()
		button := plain.Padding(0, 2).MarginRight(1)
		t.Focused.Title = plain.Bold(true)
		t.Focused.SelectedOption = plain.Bold(true)
		t.Focused.TextInput.Placeholder = plain
		t.Focused.FocusedButton = button.Bold(true).Reverse(true)
		t.Focused.BlurredButton = button
		t.Focused.ErrorMessage = t.Focused.ErrorMessage.Bold(true)

		// ThemeBase already contains colors in the button and placeholder
		// styles. Replace those above and the help styles below explicitly.
		helpKey, helpText := plain.Bold(true), plain
		if !monochrome {
			text, muted, accent, errorColor := uiText, uiMuted, uiCyan, uiWarning
			if !dark {
				text, muted, accent, errorColor = "#1E293B", "#475569", "#075985", "#9A3412"
			}
			t.Focused.Base = t.Focused.Base.BorderForeground(lipgloss.Color(accent))
			t.Focused.Title = t.Focused.Title.Foreground(lipgloss.Color(accent))
			t.Focused.Description = plain.Foreground(lipgloss.Color(muted))
			t.Focused.ErrorIndicator = t.Focused.ErrorIndicator.Foreground(lipgloss.Color(errorColor))
			t.Focused.ErrorMessage = t.Focused.ErrorMessage.Foreground(lipgloss.Color(errorColor))
			t.Focused.SelectSelector = t.Focused.SelectSelector.Foreground(lipgloss.Color(accent))
			t.Focused.Option = plain.Foreground(lipgloss.Color(text))
			t.Focused.UnselectedOption = t.Focused.Option
			t.Focused.SelectedOption = t.Focused.SelectedOption.Foreground(lipgloss.Color(uiSelected)).
				Background(lipgloss.Color(uiHighlight))
			t.Focused.NextIndicator = t.Focused.NextIndicator.Foreground(lipgloss.Color(accent))
			t.Focused.PrevIndicator = t.Focused.PrevIndicator.Foreground(lipgloss.Color(accent))
			t.Focused.TextInput.Text = plain.Foreground(lipgloss.Color(text))
			t.Focused.TextInput.Placeholder = plain.Foreground(lipgloss.Color(muted))
			t.Focused.TextInput.Prompt = plain.Foreground(lipgloss.Color(accent))
			t.Focused.TextInput.Cursor = plain.Foreground(lipgloss.Color(accent))
			t.Focused.FocusedButton = button.Bold(true).Foreground(lipgloss.Color(uiSelected)).
				Background(lipgloss.Color(uiHighlight))
			t.Focused.BlurredButton = button.Foreground(lipgloss.Color(uiText)).
				Background(lipgloss.Color(uiPanel))

			// Huh caches help styles on the group before detecting the
			// terminal background. Use a matched foreground/background
			// pair so the shortcuts remain readable in either case.
			helpKey = plain.Bold(true).Foreground(lipgloss.Color(uiCyan)).Background(lipgloss.Color(uiNavy))
			helpText = plain.Foreground(lipgloss.Color(uiMuted)).Background(lipgloss.Color(uiNavy))
		}
		t.Help.ShortKey, t.Help.FullKey = helpKey, helpKey
		t.Help.ShortDesc, t.Help.FullDesc = helpText, helpText
		t.Help.ShortSeparator, t.Help.FullSeparator, t.Help.Ellipsis = helpText, helpText, helpText
		t.Focused.Card = t.Focused.Base
		t.Blurred = t.Focused
		t.Blurred.Base = t.Focused.Base.BorderStyle(lipgloss.HiddenBorder())
		t.Blurred.Card = t.Blurred.Base
		t.Blurred.SelectSelector = plain.SetString("* ")
		t.Blurred.SelectedOption = t.Focused.Option.Bold(true)
		t.Blurred.NextIndicator, t.Blurred.PrevIndicator = plain, plain
		t.Group.Title = t.Focused.Title
		t.Group.Description = t.Focused.Description
		return t
	})
}

const wizardSidebarWidth = 22
const wizardSidebarMinWidth = 100

// The step indicator is derived from the actual focused Huh field. Optional
// hub-address and network-interface pages belong to their parent stages.
// It neither tracks a separate navigation counter nor influences validation.
func wizardStage(key string) int {
	switch key {
	case "welcome":
		return 0
	case "hub", "hub-address":
		return 1
	case "power", "wol", "network":
		return 2
	case "review":
		return 3
	default:
		return -1
	}
}

type wizardLayout struct {
	width      int
	monochrome bool
}

func (l *wizardLayout) GroupWidth(_ *huh.Form, _ *huh.Group, width int) int {
	l.width = width
	if width >= wizardSidebarMinWidth {
		return width - wizardSidebarWidth - 1
	}
	return width
}

func (l *wizardLayout) sidebar(stage int) string {
	style := func(s, fg, bg string, bold bool) string {
		s = maintenanceFit(s, wizardSidebarWidth)
		if l.monochrome {
			return s
		}
		return lipgloss.NewStyle().Foreground(lipgloss.Color(fg)).
			Background(lipgloss.Color(bg)).Bold(bold).Render(s)
	}
	lines := []string{
		style(" COMPUTER HOST LAN", uiCyan, uiPanel, true),
		style(" SETUP", uiMuted, uiNavy, false),
		style("", uiText, uiNavy, false),
	}
	for i, label := range []string{"Welcome", "Hub", "Power & WOL", "Review"} {
		marker, fg, bg := "  ", uiMuted, uiNavy
		if i == stage {
			marker, fg, bg = "> ", uiSelected, uiHighlight
		} else if stage >= 0 && i < stage {
			marker, fg = "* ", uiTeal
		}
		lines = append(lines, style(marker+label, fg, bg, i == stage))
	}
	return strings.Join(lines, "\n")
}

func (l *wizardLayout) View(f *huh.Form) string {
	body := huh.LayoutDefault.View(f)
	if l.width < wizardSidebarMinWidth {
		return body
	}
	// Render only the selected Huh group, including its native help and
	// validation messages. No custom clipping, key handling or scrolling.
	return lipgloss.JoinHorizontal(lipgloss.Top, l.sidebar(wizardStage(f.GetFocusedField().GetKey())), " ", body)
}

func styledLiveForm(s *liveSelection, installing bool) *huh.Form {
	monochrome := os.Getenv("NO_COLOR") != ""
	return liveFormMode(s, installing).
		WithTheme(wizardTheme(monochrome)).
		WithLayout(&wizardLayout{monochrome: monochrome})
}
