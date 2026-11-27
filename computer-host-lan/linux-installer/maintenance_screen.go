package main

// The full-screen maintenance chooser owns the terminal only while choosing
// a task. It returns a selection to the existing dispatcher, never invokes
// installer logic from a Bubble Tea callback, and does not authorize changes.
import (
	"fmt"
	"io"
	"os"
	"regexp"
	"strconv"
	"strings"

	tea "charm.land/bubbletea/v2"
	"charm.land/lipgloss/v2"
	"github.com/charmbracelet/x/term"
)

const maintenanceMinWidth, maintenanceMinHeight = 64, 22

// Compare only canonical versions in the project's supported release scheme.
// Unknown or unusual versions are not grounds for recommending an upgrade.
var menuVersionPattern = regexp.MustCompile(`^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-(dev|beta|rc)\.(0|[1-9][0-9]*))?$`)

func menuVersion(s string) ([5]uint64, bool) {
	var v [5]uint64
	m := menuVersionPattern.FindStringSubmatch(s)
	if m == nil {
		return v, false
	}
	for i := 0; i < 3; i++ {
		n, err := strconv.ParseUint(m[i+1], 10, 64)
		if err != nil {
			return v, false
		}
		v[i] = n
	}
	switch m[4] {
	case "dev":
		v[3] = 0
	case "beta":
		v[3] = 1
	case "rc":
		v[3] = 2
	default:
		v[3] = 3
	}
	if m[5] != "" {
		n, err := strconv.ParseUint(m[5], 10, 64)
		if err != nil {
			return v, false
		}
		v[4] = n
	}
	return v, true
}

func menuNewerVersion(installed, bundled string) bool {
	a, okA := menuVersion(installed)
	b, okB := menuVersion(bundled)
	if !okA || !okB {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return a[i] < b[i]
		}
	}
	return false
}

type visualMaintenanceChoice struct {
	key, action, title, detail string
	enabled                    bool
}

type maintenanceScreen struct {
	choices                    []visualMaintenanceChoice
	installed, bundled, status string
	service                    string
	width, height, cursor      int
	recommended, monochrome    bool
	chosen                     string
}

func newMaintenanceScreen(info apiInspect, installed, bundled string, monochrome bool) maintenanceScreen {
	// Only existing available routes can become enabled. In particular,
	// retained data must not accidentally enable Repair or Uninstall.
	allowed := make(map[string]string)
	for _, opt := range maintenanceOptions(info) {
		allowed[opt.key] = opt.action
	}
	choice := func(key, title, detail string) visualMaintenanceChoice {
		action, ok := allowed[key]
		return visualMaintenanceChoice{key, action, title, detail, ok}
	}
	first, second := "Install / reinstall", "Configure saved Wake-on-LAN"
	if info.Installation.Detected {
		first, second = "Upgrade / install", "Configure power and Wake-on-LAN"
	}
	m := maintenanceScreen{
		installed: installed, bundled: bundled, monochrome: monochrome,
		status:  "Installation state needs attention",
		service: info.Installation.AgentServiceState,
		choices: []visualMaintenanceChoice{
			choice("1", first, "Review setup using the bundled version."),
			choice("2", second, "Review power or network settings."),
			choice("3", "Repair", "Reinstall managed files using the bundled version."),
			choice("4", "Restore", "Backups are checked after administrator authorization."),
			choice("5", "Recover", "Review an interrupted operation."),
			choice("6", "Inspect", "Read-only installation status."),
			choice("7", "Uninstall", "Remove agent; retain identity, key and backups."),
			choice("0", "Exit", "Leave without changes."),
		},
		cursor: 5, // Inspection is the conservative default for unknown state.
	}
	if info.Installation.Detected {
		m.status = "Existing installation detected"
	} else if info.Installation.RetainedStatePresent {
		m.status = "Retained installation data detected"
	}
	if !m.choices[2].enabled {
		m.choices[2].detail = "Install an agent before repairing."
	}
	if !m.choices[6].enabled {
		m.choices[6].detail = "No existing installation detected."
	}
	// The installed version is an observed file version, not a runtime
	// result. Do not recommend changes on ambiguous service-file state.
	if info.Installation.Detected && info.Installation.ServiceFile == "present" {
		if menuNewerVersion(installed, bundled) {
			m.recommended = true
			m.cursor = 0
		}
	} else if !info.Installation.Detected && info.Installation.RetainedStatePresent && info.Installation.ServiceFile == "absent" {
		m.cursor = 0
	}
	return m
}

func (m maintenanceScreen) Init() tea.Cmd { return nil }

func (m *maintenanceScreen) handleKey(key string) bool {
	switch key {
	case "q", "esc", "ctrl+c":
		m.chosen = ""
		return true
	}
	if m.width < maintenanceMinWidth || m.height < maintenanceMinHeight {
		return false
	}
	switch key {
	case "up", "k":
		m.cursor = (m.cursor + len(m.choices) - 1) % len(m.choices)
	case "down", "j":
		m.cursor = (m.cursor + 1) % len(m.choices)
	case "enter":
		c := m.choices[m.cursor]
		if !c.enabled {
			return false
		}
		if c.action != "exit" {
			m.chosen = c.action
		}
		return true
	default:
		for i, c := range m.choices {
			if key == c.key {
				m.cursor = i // Numeric shortcuts only highlight.
				break
			}
		}
	}
	return false
}

func (m maintenanceScreen) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	switch msg := msg.(type) {
	case tea.WindowSizeMsg:
		m.width, m.height = msg.Width, msg.Height
	case tea.KeyPressMsg:
		if m.handleKey(msg.String()) {
			return m, tea.Quit
		}
	}
	return m, nil
}

// Values are either fixed labels, validated inspector enums, or agent file
// versions validated by agentVersionFromSource. Never render raw backend text.
func maintenanceFit(s string, width int) string {
	if width <= 0 {
		return ""
	}
	var b strings.Builder
	used := 0
	for _, r := range s {
		n := lipgloss.Width(string(r))
		if used+n > width {
			break
		}
		b.WriteRune(r)
		used += n
	}
	return b.String() + strings.Repeat(" ", width-used)
}

func (m maintenanceScreen) paint(s string, width int, kind string) string {
	s = maintenanceFit(s, width)
	if m.monochrome {
		return s
	}
	fg, bg, bold := "#E2E8F0", "#0D1729", false
	switch kind {
	case "header":
		fg, bg, bold = "#7DD3FC", "#16283C", true
	case "selected":
		fg, bg, bold = "#CFFAFE", "#164E63", true
	case "muted":
		fg = "#A8BDD3"
	case "disabled":
		fg = "#8296AB"
	case "success":
		fg = "#5EEAD4"
	case "warning":
		fg = "#FBBF24"
	}
	return lipgloss.NewStyle().
		Foreground(lipgloss.Color(fg)).
		Background(lipgloss.Color(bg)).
		Bold(bold).Render(s)
}

func (m maintenanceScreen) render() string {
	if m.width < maintenanceMinWidth || m.height < maintenanceMinHeight {
		return strings.TrimRight(maintenanceFit("Enlarge terminal to 64x22. Q quits.", m.width), " ")
	}
	width := min(m.width, 106)
	inner := width - 2
	margin := strings.Repeat(" ", (m.width-width)/2)
	border := func(left, mid, right string) string {
		return margin + m.paint(left+strings.Repeat(mid, inner)+right, width, "header")
	}
	line := func(s, kind string) string {
		return margin + m.paint("│", 1, "header") + m.paint(" "+s, inner, kind) + m.paint("│", 1, "header")
	}
	lines := []string{
		border("┌", "─", "┐"),
		line("COMPUTER HOST LAN   /   LINUX INSTALLER", "header"),
		line("Installed file: "+m.installed, "normal"),
		line("Bundled agent:  "+m.bundled, "normal"),
		line(m.status, "muted"),
		line("Agent service: "+m.service+" (observed; runtime not verified)", "muted"),
		border("├", "─", "┤"),
		line("MAINTENANCE", "header"),
	}
	for i, c := range m.choices {
		marker, kind := "  ", "normal"
		if i == m.cursor {
			marker, kind = "> ", "selected"
		}
		label := marker + "[" + c.key + "] " + c.title
		if !c.enabled {
			kind = "disabled"
			label += " — " + c.detail
		} else if i == 0 && m.recommended {
			label += " (recommended)"
		}
		lines = append(lines, line(label, kind))
	}
	detailKind := "muted"
	if !m.choices[m.cursor].enabled {
		detailKind = "warning"
	}
	lines = append(lines,
		border("├", "─", "┤"),
		line(m.choices[m.cursor].detail, detailKind),
		line("Selecting a task does not authorize system changes.", "muted"),
		line("Protected recovery status: unknown (not inspected).", "muted"),
		line("Up/Down Navigate | 0-7 Highlight | Enter Select | Esc Exit", "header"),
		border("└", "─", "┘"),
	)
	return strings.Join(lines, "\n")
}

func (m maintenanceScreen) View() tea.View {
	v := tea.NewView(m.render())
	v.AltScreen = true
	return v
}

// Use the plain, ANSI-free path for accessible mode, non-terminal streams,
// redirected output and terminals that do not support full-screen rendering.
func visualMaintenanceAllowed(accessible, inputTTY, outputTTY bool, terminal string) bool {
	return !accessible && inputTTY && outputTTY && terminal != "" && terminal != "dumb"
}

func runMaintenancePresentation(accessible bool, reader io.Reader, writer io.Writer, info apiInspect, dispatch func(string) error) error {
	in, inOK := reader.(*os.File)
	out, outOK := writer.(*os.File)
	if !inOK || !outOK || in != os.Stdin || out != os.Stdout ||
		!visualMaintenanceAllowed(accessible, term.IsTerminal(in.Fd()), term.IsTerminal(out.Fd()), os.Getenv("TERM")) {
		return runMaintenanceMenu(reader, writer, info, dispatch)
	}
	bundled := "unknown"
	if data, err := bundleRead("agent/linux_host_agent.py"); err == nil {
		bundled = agentVersionFromSource(data)
	}
	m := newMaintenanceScreen(info, installedAgentVersion(), bundled, os.Getenv("NO_COLOR") != "")
	return runMaintenanceScreen(m, writer, dispatch)
}

func runMaintenanceScreen(m maintenanceScreen, writer io.Writer, dispatch func(string) error) error {
	result, err := tea.NewProgram(m).Run()
	if err != nil {
		return err
	}
	final, ok := result.(maintenanceScreen)
	if !ok {
		return fmt.Errorf("unexpected maintenance screen result")
	}
	if final.chosen == "" {
		fmt.Fprintln(writer, "Exited without changes.")
		return nil
	}
	// The full-screen program has returned and restored the terminal.
	// All subsequent prompts and mutations stay in the existing dispatcher.
	for _, c := range m.choices {
		if c.enabled && c.action == final.chosen && c.action != "exit" {
			return dispatch(final.chosen)
		}
	}
	return fmt.Errorf("invalid maintenance selection")
}
