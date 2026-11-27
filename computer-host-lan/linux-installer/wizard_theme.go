package main

import (
	"errors"
	"fmt"
	"os"
	"strings"

	tea "charm.land/bubbletea/v2"
	"charm.land/huh/v2"
	"charm.land/lipgloss/v2"
	"github.com/charmbracelet/x/term"
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
const wizardMinWidth = 64
const wizardMinHeight = 22
const wizardMaxWidth = 106

// The step and group indicators are derived from the actual focused Huh
// field. Conditional pages belong to their parent stages.
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

func wizardGroupIndex(key string) int {
	switch key {
	case "welcome":
		return 0
	case "hub":
		return 1
	case "hub-address":
		return 2
	case "power", "wol":
		return 3
	case "network":
		return 4
	case "review":
		return 5
	default:
		return -1
	}
}

type wizardLayout struct {
	width, height int
	monochrome    bool
	installing    bool
	groups        []*huh.Group
}

func (l *wizardLayout) panelWidth() int {
	return min(l.width, wizardMaxWidth)
}

func (l *wizardLayout) wide() bool {
	return l.width >= wizardSidebarMinWidth
}

func (l *wizardLayout) GroupWidth(_ *huh.Form, _ *huh.Group, width int) int {
	l.width = width
	available := l.panelWidth() - 4 // frame and content padding
	if l.wide() {
		available -= wizardSidebarWidth + 1 // sidebar and divider
	}
	return max(1, available)
}

func (l *wizardLayout) paint(s, fg, bg string, bold bool) string {
	if l.monochrome {
		return s
	}
	return lipgloss.NewStyle().Foreground(lipgloss.Color(fg)).
		Background(lipgloss.Color(bg)).Bold(bold).Render(s)
}

func (l *wizardLayout) sidebarLine(stage, row int) string {
	label, fg, bg := "", uiMuted, uiPanel
	bold := false
	if row == 0 {
		label, fg, bold = " SETUP", uiCyan, true
	} else if row >= 2 && row < 6 {
		i := row - 2
		label = []string{"Welcome", "Hub", "Power & WOL", "Review"}[i]
		marker := "  "
		if i == stage {
			marker, fg, bg, bold = "> ", uiSelected, uiHighlight, true
		} else if stage >= 0 && i < stage {
			marker, fg = "* ", uiTeal
		}
		label = marker + label
	}
	return l.paint(maintenanceFit(label, wizardSidebarWidth), fg, bg, bold)
}

func wizardLines(s string) []string {
	if s == "" {
		return nil
	}
	return strings.Split(strings.TrimRight(s, "\n"), "\n")
}

// wizardHelp uses the active field's enabled native bindings. Navigation
// comes first; redundant yes/no shortcuts need not repeat button labels.
// Fit optional hints ourselves: Bubbles v2.0.0 ShortHelpView can exceed
// its width when there is no room left for the ellipsis.
func (l *wizardLayout) wizardHelp(f *huh.Form, width int) string {
	var primary, secondary []string
	for _, binding := range f.GetFocusedField().KeyBinds() {
		if !binding.Enabled() {
			continue
		}
		h := binding.Help()
		switch h.Key {
		case "enter":
			primary = append(primary, "Enter "+h.Desc)
		case "shift+tab":
			primary = append(primary, "Shift+Tab back")
		case "y", "n":
			// The labeled confirmation buttons already explain the choices.
		default:
			secondary = append(secondary, h.Key+" "+h.Desc)
		}
	}
	var result string
	for _, item := range append(primary, secondary...) {
		candidate := item
		if result != "" {
			candidate = result + " | " + item
		}
		if lipgloss.Width(candidate) > width {
			if lipgloss.Width(result)+2 <= width {
				result += " …"
			}
			break
		}
		result = candidate
	}
	return l.paint(result, uiMuted, uiNavy, false)
}

// render returns whether the entire active page, including native validation,
// fits. Optional keyboard hints may be shortened. Never crop a review or accept a hidden
// control. Unlike Group.View, Content is not clipped by the group viewport.
// The native fields (including their own option scrolling) remain intact.
func (l *wizardLayout) render(f *huh.Form) (string, bool) {
	if l.width < wizardMinWidth || l.height < wizardMinHeight {
		return fmt.Sprintf("Enlarge terminal to 64x22 (now %dx%d). Ctrl+C cancels.", l.width, l.height), false
	}
	key := f.GetFocusedField().GetKey()
	stage, index := wizardStage(key), wizardGroupIndex(key)
	if index < 0 || index >= len(l.groups) {
		return "Cannot display the current setup page. Ctrl+C cancels.", false
	}
	g := l.groups[index]
	body := wizardLines(g.Header())
	body = append(body, wizardLines(g.Content())...)
	// Native help is disabled only for the framed groups. Footer therefore
	// contains validation errors, which must never be treated as optional.
	body = append(body, wizardLines(g.Footer())...)
	inner := l.panelWidth() - 2
	pane := inner
	if l.wide() {
		pane -= wizardSidebarWidth + 1
	}
	for _, line := range body {
		if lipgloss.Width(line) > pane-2 {
			return "Setup content is too wide. Enlarge the terminal or use -accessible. Ctrl+C cancels.", false
		}
	}
	help := wizardLines(l.wizardHelp(f, pane-2))
	// Six frame rows. Omit the two ornamental blank rows so standard
	// pages can fit in short terminals without sacrificing review text.
	required := len(body) + len(help) + 6
	if required > l.height {
		return fmt.Sprintf("This page needs %d rows (now %d). Enlarge the terminal or use -accessible. Ctrl+C cancels.", required, l.height), false
	}
	height := max(required, min(l.height, 30))
	contentHeight := height - 6
	margin := strings.Repeat(" ", (l.width-l.panelWidth())/2)
	border := func(left, mid, right string) string {
		return margin + l.paint(left+strings.Repeat(mid, inner)+right, uiCyan, uiNavy, false)
	}
	vertical := l.paint("│", uiCyan, uiNavy, false)
	full := func(label string) string {
		return margin + vertical + l.paint(maintenanceFit(" "+label, inner), uiCyan, uiPanel, true) + vertical
	}
	mode := "SETUP PREVIEW — no changes"
	if l.installing {
		mode = "LINUX INSTALLATION"
	}
	lines := []string{
		border("┌", "─", "┐"),
		full("COMPUTER HOST LAN / " + mode),
		border("├", "─", "┤"),
	}
	helpStart := contentHeight - len(help)
	for i := 0; i < contentHeight; i++ {
		value := ""
		if i < len(body) {
			value = body[i]
		} else if i >= helpStart && len(help) > 0 {
			value = help[i-helpStart]
		}
		// Native styled strings are preserved. Padding never truncates,
		// reflows or escapes a field's text.
		value = " " + value + strings.Repeat(" ", pane-1-lipgloss.Width(value))
		if !l.monochrome {
			value = lipgloss.NewStyle().Background(lipgloss.Color(uiNavy)).Render(value)
		}
		if l.wide() {
			value = l.sidebarLine(stage, i) + vertical + value
		}
		lines = append(lines, margin+vertical+value+vertical)
	}
	lines = append(lines,
		border("├", "─", "┤"),
		full(fmt.Sprintf("Step %d of 4  |  Ctrl+C Cancel", stage+1)),
		border("└", "─", "┘"),
	)
	return strings.Join(lines, "\n"), true
}

func (l *wizardLayout) View(f *huh.Form) string {
	view, _ := l.render(f)
	return view
}

// The wrapper owns only terminal geometry and lifetime. Huh still owns
// every selection, input, conditional group, validation and review command.
// Resize messages are handled here rather than letting Huh size its group
// viewport to the entire terminal (which hides the bottom help in short
// windows). No privileged operation is reachable from this model.
type wizardScreen struct {
	form         *huh.Form
	layout       *wizardLayout
	reviewChoice *bool
}

func newWizardScreen(s *liveSelection, installing, monochrome bool) wizardScreen {
	// Continue is the default selection, not approval of any changes.
	// Keep it separate from s.finished until the form actually completes.
	reviewChoice := true
	groups := liveFormGroups(s, installing, &reviewChoice)
	for _, group := range groups {
		group.WithShowHelp(false)
	}
	layout := &wizardLayout{monochrome: monochrome, installing: installing, groups: groups}
	form := huh.NewForm(groups...).WithTheme(wizardTheme(monochrome)).WithLayout(layout)
	form.SubmitCmd = tea.Quit
	form.CancelCmd = tea.Quit
	return wizardScreen{form: form, layout: layout, reviewChoice: &reviewChoice}
}

func (m wizardScreen) Init() tea.Cmd { return m.form.Init() }

func (m wizardScreen) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	switch event := msg.(type) {
	case tea.WindowSizeMsg:
		m.layout.width, m.layout.height = event.Width, event.Height
		if event.Width >= wizardMinWidth && event.Height >= wizardMinHeight {
			m.form.WithWidth(event.Width)
		}
		return m, nil
	case tea.KeyPressMsg:
		if event.String() != "ctrl+c" {
			if _, fits := m.layout.render(m.form); !fits {
				return m, nil
			}
		}
	case tea.PasteMsg:
		if _, fits := m.layout.render(m.form); !fits {
			return m, nil
		}
	}
	_, cmd := m.form.Update(msg)
	return m, cmd
}

func (m wizardScreen) View() tea.View {
	v := tea.NewView(m.form.View())
	v.AltScreen = true
	return v
}

func runStyledLiveWizard(s *liveSelection, installing bool) error {
	if !visualMaintenanceAllowed(false, term.IsTerminal(os.Stdin.Fd()), term.IsTerminal(os.Stdout.Fd()), os.Getenv("TERM")) {
		return liveFormMode(s, installing).Run()
	}
	m := newWizardScreen(s, installing, os.Getenv("NO_COLOR") != "")
	_, err := runFramedProgram(m)
	if errors.Is(err, tea.ErrInterrupted) || m.form.State == huh.StateAborted {
		return huh.ErrUserAborted
	}
	if err != nil {
		return err
	}
	// Only the native form's completed state can reach the existing
	// confirmation caller. An unexpected program exit fails closed.
	if m.form.State != huh.StateCompleted {
		return huh.ErrUserAborted
	}
	s.finished = *m.reviewChoice
	return nil
}

// The normal setup model and its original validators own Review. Only
// a completed positive Review may transition to literal confirmation.
// No privilege provider is invoked while the Bubble Tea program is alive.
type installConsentWizard struct {
	wizard  wizardScreen
	state   *liveSelection
	consent *consentScreen
}

// Native Huh commands belong to the form instance that produced them.
// Late messages from a superseded form cannot advance a reopened review.
type wizardCommandMsg struct {
	form *huh.Form
	msg  tea.Msg
}

func scopedWizardCommand(form *huh.Form, cmd tea.Cmd) tea.Cmd {
	if cmd == nil {
		return nil
	}
	return func() tea.Msg {
		msg := cmd()
		if batch, ok := msg.(tea.BatchMsg); ok {
			var scoped []tea.Cmd
			for _, child := range batch {
				if child != nil {
					scoped = append(scoped, scopedWizardCommand(form, child))
				}
			}
			return tea.BatchMsg(scoped)
		}
		return wizardCommandMsg{form: form, msg: msg}
	}
}

func (m installConsentWizard) Init() tea.Cmd {
	return scopedWizardCommand(m.wizard.form, m.wizard.Init())
}

// A completed Huh form cannot be reopened. Reconstruct the native form
// from the existing selections and navigate to Review, not through a new
// submission. The review validator still runs on the next Continue.
func (m installConsentWizard) reopenReview() (tea.Model, tea.Cmd) {
	frame := m.consent.frame
	m.consent = nil
	m.wizard = newWizardScreen(m.state, true, frame.monochrome)
	next, _ := m.wizard.Update(tea.WindowSizeMsg{Width: frame.width, Height: frame.height})
	m.wizard = next.(wizardScreen)
	var cmd tea.Cmd
	for i := 0; i < 6 && m.wizard.form.GetFocusedField().GetKey() != "review"; i++ {
		cmd = m.wizard.form.NextGroup()
	}
	if m.wizard.form.State != huh.StateNormal || m.wizard.form.GetFocusedField().GetKey() != "review" {
		return m, tea.Quit
	}
	return m, scopedWizardCommand(m.wizard.form, cmd)
}

func (m installConsentWizard) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	if event, ok := msg.(wizardCommandMsg); ok {
		if event.form != m.wizard.form || m.consent != nil {
			return m, nil
		}
		msg = event.msg
	}
	if m.consent != nil {
		if key, ok := msg.(tea.KeyPressMsg); ok && key.String() == "esc" && !m.consent.done {
			return m.reopenReview()
		}
		next, cmd := m.consent.Update(msg)
		value := next.(consentScreen)
		m.consent = &value
		return m, cmd
	}
	if key, ok := msg.(tea.KeyPressMsg); ok && key.String() == "esc" {
		if m.wizard.form.GetFocusedField().GetKey() == "welcome" {
			return m, tea.Quit
		}
		msg = huh.PrevField()
	}
	next, cmd := m.wizard.Update(msg)
	m.wizard = next.(wizardScreen)
	if m.wizard.form.State == huh.StateCompleted && *m.wizard.reviewChoice {
		token := m.state.installConfirmation()
		rows := []detailRow{
			{"Confirm your reviewed installation plan", "header"},
			{"Agent files and services will change.", "normal"},
			{"Next: administrator authorization (password if needed).", "muted"},
		}
		if token == "REUSE" {
			rows = append(rows, detailRow{"Reuse the retained installation identity and key.", "warning"})
		}
		m.consent = &consentScreen{
			frame: detailFrame{
				width: m.wizard.layout.width, height: m.wizard.layout.height,
				monochrome: m.wizard.layout.monochrome,
			},
			title: "INSTALLATION", review: rows, token: token,
		}
		return m, nil // Consume the native form's completion Quit.
	}
	if m.wizard.form.State != huh.StateNormal {
		return m, cmd
	}
	return m, scopedWizardCommand(m.wizard.form, cmd)
}

func (m installConsentWizard) View() tea.View {
	if m.consent != nil {
		return m.consent.View()
	}
	return m.wizard.View()
}

func runInstallConsentWizard(s *liveSelection) (bool, error) {
	m := installConsentWizard{
		wizard: newWizardScreen(s, true, os.Getenv("NO_COLOR") != ""), state: s,
	}
	result, err := runFramedProgram(m)
	if errors.Is(err, tea.ErrInterrupted) {
		return false, nil
	}
	if err != nil {
		return false, err
	}
	final, ok := result.(installConsentWizard)
	if !ok {
		return false, fmt.Errorf("unexpected installation confirmation result")
	}
	// Recheck the required word against the same reviewed plan before the
	// original request builder runs. Never convert INSTALL into REUSE.
	accepted := final.wizard.form.State == huh.StateCompleted && *final.wizard.reviewChoice &&
		final.consent != nil && final.consent.accepted() && final.consent.token == s.installConfirmation()
	s.finished = accepted
	return accepted, nil
}
