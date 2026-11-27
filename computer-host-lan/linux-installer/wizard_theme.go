package main

import (
	"os"
	"strings"

	"charm.land/huh/v2"
	"charm.land/lipgloss/v2"
)

// Shared palette for the maintenance chooser and setup wizard. The sidebar
// and form use matched foreground/background pairs, independent of the
// terminal's reported (or missing) background color.
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
			// A terminal may never answer the background-color query. Huh's
			// initial dark flag is false, which is not evidence of a light
			// terminal. Pair each visible text color with our own background.
			pair := func(style lipgloss.Style, fg string) lipgloss.Style {
				return style.Foreground(lipgloss.Color(fg)).Background(lipgloss.Color(uiNavy))
			}
			t.Focused.Base = t.Focused.Base.Background(lipgloss.Color(uiNavy)).
				BorderForeground(lipgloss.Color(uiCyan)).BorderBackground(lipgloss.Color(uiNavy))
			t.Focused.Title = pair(t.Focused.Title, uiCyan)
			t.Focused.Description = pair(plain, uiMuted)
			t.Focused.ErrorIndicator = pair(t.Focused.ErrorIndicator, uiWarning)
			t.Focused.ErrorMessage = pair(t.Focused.ErrorMessage, uiWarning)
			t.Focused.SelectSelector = pair(t.Focused.SelectSelector, uiCyan)
			t.Focused.Option = pair(plain, uiText)
			t.Focused.UnselectedOption = t.Focused.Option
			t.Focused.SelectedOption = t.Focused.SelectedOption.Foreground(lipgloss.Color(uiSelected)).
				Background(lipgloss.Color(uiHighlight))
			t.Focused.NextIndicator = pair(t.Focused.NextIndicator, uiCyan)
			t.Focused.PrevIndicator = pair(t.Focused.PrevIndicator, uiCyan)
			t.Focused.TextInput.Text = pair(plain, uiText)
			t.Focused.TextInput.Placeholder = pair(plain, uiMuted)
			t.Focused.TextInput.Prompt = pair(plain, uiCyan)
			t.Focused.TextInput.Cursor = plain.Foreground(lipgloss.Color(uiCyan))
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
		t.Blurred.SelectSelector = t.Focused.SelectSelector.SetString("* ")
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
	// Render only the selected Huh group, including its native help and
	// validation messages. No custom clipping, key handling or scrolling.
	if l.width >= wizardSidebarMinWidth {
		sidebar := l.sidebar(wizardStage(f.GetFocusedField().GetKey()))
		body = lipgloss.JoinHorizontal(lipgloss.Top, sidebar, " ", body)
	}
	if !l.monochrome {
		// Fill the gaps and native viewport padding as well as styled text.
		// Do not impose a width/height that could wrap or clip review content.
		body = lipgloss.NewStyle().Background(lipgloss.Color(uiNavy)).Render(body)
	}
	return body
}

func styledLiveForm(s *liveSelection, installing bool) *huh.Form {
	monochrome := os.Getenv("NO_COLOR") != ""
	return liveFormMode(s, installing).
		WithTheme(wizardTheme(monochrome)).
		WithLayout(&wizardLayout{monochrome: monochrome})
}
