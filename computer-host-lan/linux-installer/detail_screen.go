package main

// These views display observations or select a previously validated backup.
// They have no backend, elevation, filesystem mutation or authorization
// callbacks. A selection is returned only after the terminal is restored.
import (
	"fmt"
	"io"
	"os"
	"strings"
	"time"

	tea "charm.land/bubbletea/v2"
	"charm.land/lipgloss/v2"
	"github.com/charmbracelet/x/term"
)

type detailRow struct {
	text string
	tone string
}

type detailFrame struct {
	width, height int
	monochrome    bool
}

func (f detailFrame) ready() bool {
	return f.width >= maintenanceMinWidth && f.height >= maintenanceMinHeight
}

func (f detailFrame) bodyWidth() int {
	return max(1, min(f.width, 106)-4)
}

func (f detailFrame) capacity() int {
	return max(1, min(f.height, 30)-7)
}

func (f detailFrame) render(title string, rows []detailRow, status, help string) string {
	if !f.ready() {
		return strings.TrimRight(maintenanceFit(fmt.Sprintf("Enlarge terminal to 64x22 (now %dx%d). Esc/Q exits.", f.width, f.height), f.width), " ")
	}
	width := min(f.width, 106)
	inner := width - 2
	margin := strings.Repeat(" ", (f.width-width)/2)
	palette := maintenanceScreen{monochrome: f.monochrome}
	border := func(left, mid, right string) string {
		return margin + palette.paint(left+strings.Repeat(mid, inner)+right, width, "header")
	}
	line := func(s, tone string) string {
		return margin + palette.paint("│", 1, "header") +
			palette.paint(" "+s, inner, tone) + palette.paint("│", 1, "header")
	}
	lines := []string{
		border("┌", "─", "┐"),
		line("COMPUTER HOST LAN / "+title, "header"),
		border("├", "─", "┤"),
	}
	for i := 0; i < f.capacity(); i++ {
		r := detailRow{"", "normal"}
		if i < len(rows) {
			r = rows[i]
		}
		lines = append(lines, line(r.text, r.tone))
	}
	lines = append(lines, border("├", "─", "┤"), line(status, "muted"),
		line(help, "header"), border("└", "─", "┘"))
	return strings.Join(lines, "\n")
}

// Only fixed labels and validated ASCII inspector/backup fields are passed
// here. Split even an unusually long version, name or path without losing
// any characters. The list preview can abbreviate; its selected details
// and inspection text must remain available in full.
func wrapDetail(row detailRow, width int) []detailRow {
	if row.text == "" {
		return []detailRow{row}
	}
	var result []detailRow
	var line string
	for _, word := range strings.Fields(row.text) {
		if line != "" && len(line)+1+len(word) > width {
			result = append(result, detailRow{line, row.tone})
			line = ""
		}
		for len(word) > width {
			result = append(result, detailRow{word[:width], row.tone})
			word = word[width:]
		}
		if line != "" {
			line += " "
		}
		line += word
	}
	if line != "" {
		result = append(result, detailRow{line, row.tone})
	}
	return result
}

func wrapDetailRows(rows []detailRow, width int) []detailRow {
	var result []detailRow
	for _, row := range rows {
		result = append(result, wrapDetail(row, width)...)
	}
	return result
}

func detailPreview(s string, width int) string {
	if lipgloss.Width(s) <= width {
		return s
	}
	return strings.TrimRight(maintenanceFit(s, width-1), " ") + "…"
}

func detailTerminal(accessible bool, reader io.Reader, writer io.Writer) bool {
	in, inOK := reader.(*os.File)
	out, outOK := writer.(*os.File)
	return inOK && outOK && in == os.Stdin && out == os.Stdout &&
		visualMaintenanceAllowed(accessible, term.IsTerminal(in.Fd()), term.IsTerminal(out.Fd()), os.Getenv("TERM"))
}

func observedTone(value string) string {
	switch value {
	case "active", "passed", "enabled":
		return "success"
	case "failed", "blocked", "warning", "unsafe", "unreadable", "masked":
		return "warning"
	default:
		return "normal"
	}
}

func inspectionRows(info apiInspect, installed string) []detailRow {
	python := info.Python.SelectedInterpreter
	if python == "" {
		python = "Not found"
	}
	retained := "Not detected"
	if info.Installation.RetainedStatePresent {
		retained = "Detected"
	}
	rows := []detailRow{
		{"INSTALLATION", "header"},
		{"Installed agent file: " + installed, "normal"},
		{"Service file: " + info.Installation.ServiceFile, observedTone(info.Installation.ServiceFile)},
		{"Agent service: " + menuServiceLabel(info.Installation.AgentServiceState), observedTone(info.Installation.AgentServiceState)},
		{"Start at boot: " + info.Installation.AgentServiceEnabled, observedTone(info.Installation.AgentServiceEnabled)},
		{"Retained state: " + retained, "normal"},
		{"Power opt-in file: " + info.Installation.PowerDropin, observedTone(info.Installation.PowerDropin)},
		{"NETWORK AND DISCOVERY", "header"},
		{"Avahi daemon: " + menuServiceLabel(info.Avahi.DaemonState), observedTone(info.Avahi.DaemonState)},
		{"Avahi services directory: " + info.Avahi.ServicesDirectory, "normal"},
		{"Agent advertisement file: " + info.Installation.AvahiServiceFile, observedTone(info.Installation.AvahiServiceFile)},
		{"SYSTEM REQUIREMENTS", "header"},
		{"Compatible Python: " + python, "normal"},
	}
	for _, c := range preflightChecks(info) {
		rows = append(rows, detailRow{c.ID + ": " + c.Status, observedTone(c.Status)})
	}
	return append(rows,
		detailRow{"VERIFICATION LIMITS", "header"},
		detailRow{"Runtime agent version and power/WOL operation: Not verified", "muted"},
		detailRow{"Protected recovery state: Not inspected", "muted"},
		detailRow{"Credentials and identity: Not accessed or verified", "muted"},
		detailRow{"Use Recover for an interrupted operation, or cli status.", "muted"})
}

type inspectionScreen struct {
	frame  detailFrame
	rows   []detailRow
	offset int
}

func (m inspectionScreen) Init() tea.Cmd { return nil }

func (m inspectionScreen) content() []detailRow {
	return wrapDetailRows(m.rows, m.frame.bodyWidth())
}

func (m inspectionScreen) maxOffset() int {
	return max(0, len(m.content())-m.frame.capacity())
}

func (m inspectionScreen) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	switch event := msg.(type) {
	case tea.WindowSizeMsg:
		m.frame.width, m.frame.height = event.Width, event.Height
	case tea.KeyPressMsg:
		switch event.String() {
		case "esc", "q", "ctrl+c", "enter":
			return m, tea.Quit
		}
		if m.frame.ready() {
			switch event.String() {
			case "up", "k":
				m.offset--
			case "down", "j":
				m.offset++
			case "pgup":
				m.offset -= m.frame.capacity()
			case "pgdown":
				m.offset += m.frame.capacity()
			case "home":
				m.offset = 0
			case "end":
				m.offset = m.maxOffset()
			}
		}
	}
	m.offset = min(max(0, m.offset), m.maxOffset())
	return m, nil
}

func (m inspectionScreen) View() tea.View {
	rows := m.content()
	start := min(m.offset, m.maxOffset())
	end := min(len(rows), start+m.frame.capacity())
	status := fmt.Sprintf("Read-only snapshot | Lines %d-%d of %d", start+1, end, len(rows))
	v := tea.NewView(m.frame.render("INSPECT", rows[start:end], status,
		"Up/Down Scroll | PgUp/PgDn Page | Enter/Esc/Q Close"))
	v.AltScreen = true
	return v
}

func runInspectionPresentation(accessible bool, reader io.Reader, writer io.Writer, info apiInspect) error {
	if !detailTerminal(accessible, reader, writer) {
		fmt.Fprintln(writer, info.brief())
		fmt.Fprintln(writer, "Installed agent file version (not runtime-verified):", installedAgentVersion())
		fmt.Fprintln(writer, "For protected transaction status, run cli status. Choose Recover for an interrupted operation.")
		return nil
	}
	m := inspectionScreen{
		frame: detailFrame{monochrome: os.Getenv("NO_COLOR") != ""},
		rows:  inspectionRows(info, installedAgentVersion()),
	}
	_, err := tea.NewProgram(m).Run()
	return err
}

type backupScreen struct {
	frame    detailFrame
	backups  []backupSummary
	current  string
	cursor   int
	selected int // -1 until explicit Enter on a fully displayed choice.
}

func (m backupScreen) Init() tea.Cmd { return nil }

func backupTime(b backupSummary) string {
	return time.Unix(b.CapturedAt, 0).Local().Format("2006-01-02 15:04")
}

func backupDetails(b backupSummary) []detailRow {
	coverage, tone := "Complete optional-file coverage", "normal"
	if b.Coverage == "partial" {
		coverage, tone = "Partial optional-file coverage; unrecorded settings kept", "warning"
	}
	return []detailRow{
		{"SELECTED BACKUP", "header"},
		{"Agent version: " + b.Version, "normal"},
		{"Snapshot: " + b.Name, "normal"},
		{fmt.Sprintf("Saved running: %t | Start at boot: %t | Power: %s", b.AgentActive, b.AgentEnabled, b.Power), "normal"},
		{coverage, tone},
	}
}

// Return all rows for the current page; the selected name and version are
// always shown in full, even when their list preview is shortened.
func (m backupScreen) page() ([]detailRow, string, int, bool) {
	if len(m.backups) == 0 || m.cursor < 0 || m.cursor >= len(m.backups) {
		return nil, "No suitable backups", 0, false
	}
	width := m.frame.bodyWidth()
	header := wrapDetailRows([]detailRow{
		{"Installed agent file: " + m.current, "normal"},
		{"HISTORICAL BACKUPS (newest first)", "header"},
	}, width)
	details := wrapDetailRows(backupDetails(m.backups[m.cursor]), width)
	available := m.frame.capacity() - len(header) - len(details)
	if available < 1 {
		return nil, "Enlarge the terminal to see all selected backup details.", 0, false
	}
	first := max(0, min(m.cursor-available+1, len(m.backups)-available))
	last := min(len(m.backups), first+available)
	rows := append([]detailRow(nil), header...)
	for i := first; i < last; i++ {
		b := m.backups[i]
		marker, tone, latest := "  ", "normal", ""
		if i == m.cursor {
			marker, tone = "> ", "selected"
		}
		if i == 0 {
			latest = " (Latest)"
		}
		label := fmt.Sprintf("%s%2d. %s%s | %s", marker, i+1, backupTime(b), latest, b.Version)
		rows = append(rows, detailRow{detailPreview(label, width), tone})
	}
	for len(rows) < m.frame.capacity()-len(details) {
		rows = append(rows, detailRow{"", "normal"})
	}
	rows = append(rows, details...)
	status := fmt.Sprintf("Backup %d of %d | Enter opens review, not restore", m.cursor+1, len(m.backups))
	return rows, status, available, true
}

func (m backupScreen) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	switch event := msg.(type) {
	case tea.WindowSizeMsg:
		m.frame.width, m.frame.height = event.Width, event.Height
	case tea.KeyPressMsg:
		switch event.String() {
		case "q", "esc", "ctrl+c":
			m.selected = -1
			return m, tea.Quit
		}
		if !m.frame.ready() {
			return m, nil
		}
		_, _, pageSize, fits := m.page()
		switch event.String() {
		case "enter":
			if fits {
				m.selected = m.cursor
				return m, tea.Quit
			}
		case "up", "k":
			m.cursor--
		case "down", "j":
			m.cursor++
		case "pgup":
			m.cursor -= max(1, pageSize)
		case "pgdown":
			m.cursor += max(1, pageSize)
		case "home":
			m.cursor = 0
		case "end":
			m.cursor = len(m.backups) - 1
		}
		m.cursor = min(max(0, m.cursor), max(0, len(m.backups)-1))
	}
	return m, nil
}

func (m backupScreen) View() tea.View {
	rows, status, _, fits := m.page()
	if !fits {
		rows = []detailRow{{status, "warning"}}
	}
	v := tea.NewView(m.frame.render("RESTORE", rows, status,
		"Up/Down Select | PgUp/PgDn Page | Enter Review | Esc/Q Exit"))
	v.AltScreen = true
	return v
}

func selectBackupScreen(backups []backupSummary, current string) (int, error) {
	m := backupScreen{
		frame:    detailFrame{monochrome: os.Getenv("NO_COLOR") != ""},
		backups:  append([]backupSummary(nil), backups...),
		current:  current,
		selected: -1,
	}
	result, err := tea.NewProgram(m).Run()
	if err != nil {
		return -1, err
	}
	final, ok := result.(backupScreen)
	if !ok || final.selected < -1 || final.selected >= len(backups) {
		return -1, fmt.Errorf("invalid backup selection")
	}
	return final.selected, nil
}
