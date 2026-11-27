// Package main is an isolated visual prototype. It is not linked into the
// installer and has no access to the installer engine or real host state.
package main

import (
	"fmt"
	"os"
	"strings"

	tea "charm.land/bubbletea/v2"
	"charm.land/lipgloss/v2"
	"github.com/charmbracelet/x/term"
)

const minWidth, minHeight = 64, 22

type screen int

const (
	menu screen = iota
	welcome
	hub
	power
	review
	progress
	finish
	inspect
	backups
	operation
)

type menuItem struct {
	key, title, detail string
}

var menuItems = []menuItem{
	{"1", "Upgrade / install", "Install the bundled agent version"},
	{"2", "Configure", "Power control and Wake-on-LAN"},
	{"3", "Repair", "Reinstall the bundled agent version"},
	{"4", "Restore", "Select an earlier local backup"},
	{"5", "Recover", "Review an interrupted operation"},
	{"6", "Inspect", "View read-only installation status"},
	{"7", "Uninstall", "Remove agent; retain private state and backups"},
	{"0", "Exit", "Leave without changes"},
}

var hubChoices = []string{
	"Example hub A (192.0.2.10)",
	"Example hub B (198.51.100.24)",
	"Choose a hub later",
}

var powerChoices = []string{"Monitoring only", "Allow shutdown, reboot and suspend"}
var wolChoices = []string{"Keep existing configuration", "Configure persistent Wake-on-LAN", "Leave WOL unchanged", "Pin interface only (advanced)"}
var backupChoices = []string{"0.4.7-rc.3  |  2026-11-27 12:56", "0.4.6-rc.2  |  2026-11-27 00:42", "0.4.5-rc.1  |  2026-11-21 20:31"}
var stages = []string{"Administrator authorization", "Inspect protected installation state", "Create recovery snapshot", "Preserve identity and credentials", "Install managed files and services", "Activate services", "Verify installation", "Complete transaction"}

type model struct {
	page                       screen
	width, height              int
	cursor, hub, power, wol    int
	focus, completed, backup   int
	monochrome                 bool
}

func (m model) Init() tea.Cmd { return nil }

func cycle(value, delta, size int) int { return (value + delta + size) % size }

// All navigation affects simulated, in-memory selections only. No command
// other than quitting the terminal program is ever returned.
func (m *model) key(key string) bool {
	if key == "ctrl+c" || key == "q" {
		return true
	}
	if key == "esc" || key == "shift+tab" {
		switch m.page {
		case menu:
			return key == "esc"
		case hub:
			m.page = welcome
		case power:
			if m.focus == 1 {
				m.focus = 0
			} else {
				m.page = hub
			}
		case review:
			m.page = power
			m.focus = 1
		case progress:
			m.page = review
			m.completed = 0
		case operation:
			if m.cursor == 3 {
				m.page = backups
			} else {
				m.page = menu
			}
		default:
			m.page = menu
		}
		return false
	}
	// Keep exit/back usable, but don't navigate invisible choices.
	if m.width < minWidth || m.height < minHeight {
		return false
	}
	delta := 0
	switch key {
	case "up", "left", "k":
		delta = -1
	case "down", "right", "j":
		delta = 1
	}
	if delta != 0 {
		switch m.page {
		case menu:
			m.cursor = cycle(m.cursor, delta, len(menuItems))
		case hub:
			m.hub = cycle(m.hub, delta, len(hubChoices))
		case power:
			if m.focus == 0 {
				m.power = cycle(m.power, delta, len(powerChoices))
			} else {
				m.wol = cycle(m.wol, delta, len(wolChoices))
			}
		case backups:
			m.backup = cycle(m.backup, delta, len(backupChoices))
		}
		return false
	}
	if m.page == menu {
		for i, item := range menuItems {
			if key == item.key {
				m.cursor = i // highlight only; Enter selects the task
				return false
			}
		}
	}
	if key == "tab" && m.page == power {
		m.focus = 1 - m.focus
		return false
	}
	if key != "enter" {
		return false
	}
	switch m.page {
	case menu:
		switch m.cursor {
		case 0, 1, 2:
			m.page, m.focus, m.completed = welcome, 0, 0
		case 3:
			m.page = backups
		case 4, 6:
			m.page = operation
		case 5:
			m.page = inspect
		case 7:
			return true
		}
	case welcome:
		m.page = hub
	case hub:
		m.page, m.focus = power, 0
	case power:
		if m.focus == 0 {
			m.focus = 1
		} else {
			m.page = review
		}
	case review:
		m.page, m.completed = progress, 0
	case progress:
		if m.completed < len(stages) {
			m.completed++
		} else {
			m.page = finish
		}
	case backups:
		m.page = operation
	case finish, inspect, operation:
		m.page = menu
	}
	return false
}

func (m model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	switch msg := msg.(type) {
	case tea.WindowSizeMsg:
		m.width, m.height = msg.Width, msg.Height
	case tea.KeyPressMsg:
		if m.key(msg.String()) {
			return m, tea.Quit
		}
	}
	return m, nil
}

type tone int

const (
	normal tone = iota
	muted
	accent
	selected
	success
	warning
)

type row struct {
	text string
	tone tone
}

func plain(s string) row { return row{s, normal} }
func info(s string) row  { return row{s, muted} }
func heading(s string) row { return row{s, accent} }
func choice(label string, active, focus bool) row {
	if active && focus {
		return row{"> " + label, selected}
	}
	if active {
		return row{"* " + label, success}
	}
	return plain("  " + label)
}

// Every visible row has a known width, including its padding. Content here
// is static demo text, not untrusted host strings or terminal escape input.
func fit(s string, width int) string {
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

func (m model) paint(s string, width int, kind tone) string {
	s = fit(s, width)
	if m.monochrome {
		return s
	}
	fg, bg, bold := "#E2E8F0", "#0D1729", false
	switch kind {
	case muted:
		fg = "#A8BDD3"
	case accent:
		fg, bg, bold = "#7DD3FC", "#16283C", true
	case selected:
		fg, bg, bold = "#CFFAFE", "#164E63", true
	case success:
		fg = "#5EEAD4"
	case warning:
		fg, bold = "#FBBF24", true
	}
	return lipgloss.NewStyle().
		Foreground(lipgloss.Color(fg)).
		Background(lipgloss.Color(bg)).
		Bold(bold).Render(s)
}

func (m model) content() (string, []row, string) {
	switch m.page {
	case menu:
		rows := []row{row{"* Agent running (example)   |   Existing installation", success}, plain("")}
		for i, item := range menuItems {
			rows = append(rows, choice("["+item.key+"] "+item.title, i == m.cursor, true))
		}
		rows = append(rows, plain(""), heading(menuItems[m.cursor].detail), info("Selecting a task never authorizes changes."))
		return "MAINTENANCE", rows, "Up/Down Navigate  |  0-7 Highlight  |  Enter Select  |  Esc Exit"
	case welcome:
		return "1. WELCOME", []row{
			heading("Welcome to Computer Host LAN"), plain(""),
			plain("Example installed agent: 0.4.7-rc.3"),
			row{"* Agent running (simulated)", success}, plain(""),
			info("This prototype does not inspect your computer."),
			info("Real setup will require explicit authorization."), plain(""),
			choice("Continue", true, true),
		}, "Enter Continue  |  Esc Back  |  Q Quit"
	case hub:
		rows := []row{heading("Which SmartThings hub do you use?"), plain(""), info("Example addresses only; no discovery or contact."), plain("")}
		for i, item := range hubChoices {
			rows = append(rows, choice(item, i == m.hub, true))
		}
		return "2. SMARTTHINGS HUB", rows, "Up/Down Select  |  Enter Next  |  Esc Back  |  Q Quit"
	case power:
		rows := []row{heading("Remote power management"), info("Monitoring works without power control."), plain("")}
		for i, item := range powerChoices {
			rows = append(rows, choice(item, i == m.power, m.focus == 0))
		}
		rows = append(rows, plain(""), heading("Wake-on-LAN"), info("Keep existing policy for upgrades."), plain(""))
		for i, item := range wolChoices {
			rows = append(rows, choice(item, i == m.wol, m.focus == 1))
		}
		return "3. POWER CONTROL", rows, "Up/Down Select  |  Tab Switch field  |  Enter Next  |  Esc Back"
	case review:
		return "4. REVIEW", []row{
			heading("Review your example choices"), plain(""),
			info("Action: "+menuItems[m.cursor].title),
			plain("Hub: "+hubChoices[m.hub]),
			plain("Power: "+powerChoices[m.power]),
			plain("WOL: "+wolChoices[m.wol]), plain(""),
			row{"No changes or administrator requests will occur.", warning},
			choice("Show simulated installation progress", true, true),
		}, "Enter Show demo  |  Esc Back  |  Q Quit"
	case progress:
		rows := []row{row{"SIMULATED PROGRESS - no real transaction", warning}, plain("")}
		for i, stage := range stages {
			status := "PENDING"
			kind := muted
			if i < m.completed {
				status, kind = "DONE", success
			} else if i == m.completed {
				status, kind = "NEXT", selected
			}
			rows = append(rows, row{fmt.Sprintf("%-8s %s", status, stage), kind})
		}
		rows = append(rows, plain(""), plain("["+strings.Repeat("#", m.completed*3)+strings.Repeat("-", (len(stages)-m.completed)*3)+"]"),
			info(fmt.Sprintf("%d of %d example stages; Enter advances the demo.", m.completed, len(stages))))
		return "5. INSTALLATION DEMO", rows, "Enter Advance  |  Esc Back  |  Q Quit"
	case finish:
		return "6. COMPLETION DEMO", []row{
			row{"* Example installation successful", success}, plain(""),
			plain("Agent version: 0.4.7-rc.3 (simulated)"),
			plain("Service: running / enabled (simulated)"),
			plain("Power: "+powerChoices[m.power]),
			plain("WOL: "+wolChoices[m.wol]),
			plain("Credentials: example preserved (not verified)"), plain(""),
			heading("Next step in the real installer"),
			plain("Refresh the existing SmartThings computer device."),
			row{"Nothing was installed, changed or verified.", warning},
			choice("Return to maintenance", true, true),
		}, "Enter Menu  |  Esc Back  |  Q Quit"
	case inspect:
		return "READ-ONLY INSPECTION DEMO", []row{
			heading("Services"), plain("Agent: active / enabled (example)"),
			plain("Avahi: active (example)"), plain(""),
			heading("System requirements"), plain("Linux / systemd / Python: example only"), plain(""),
			heading("Recovery and identity"),
			row{"Privileged transaction state: UNKNOWN", warning},
			plain("Credentials: not accessed or verified"),
			plain("Installed file version: example 0.4.7-rc.3"),
			info("No runtime verification or host inspection occurred."),
		}, "Enter Menu  |  Esc Back  |  Q Quit"
	case backups:
		rows := []row{heading("Example historical snapshots"), info("No real backup directory has been accessed."), plain("")}
		for i, item := range backupChoices {
			rows = append(rows, choice(item, i == m.backup, true))
		}
		rows = append(rows, plain(""), info("The real installer separately authorizes listing"),
			info("and restoration of a selected local backup."))
		return "RESTORE DEMO", rows, "Up/Down Select  |  Enter Review  |  Esc Back  |  Q Quit"
	case operation:
		rows := []row{heading(menuItems[m.cursor].title+" - layout preview"), plain("")}
		if m.cursor == 3 {
			rows = append(rows, plain("Example backup: "+backupChoices[m.backup]))
		}
		rows = append(rows, info("No live action is connected to this screen."), plain(""),
			row{"Real operations retain their typed confirmation.", warning},
			choice("Return to maintenance", true, true))
		return "OPERATION REVIEW DEMO", rows, "Enter Menu  |  Esc Back  |  Q Quit"
	default:
		return "DEMO", nil, "Q Quit"
	}
}

func (m model) render() string {
	if m.width < minWidth || m.height < minHeight {
		return strings.TrimRight(fit("Resize to 64x22; Q quits.", m.width), " ")
	}
	width := min(m.width, 106)
	height := min(m.height, 30)
	margin := strings.Repeat(" ", (m.width-width)/2)
	inner := width - 2
	bodyWidth := inner - 2
	title, rows, footer := m.content()

	border := func(left, mid, right string) string {
		return margin + m.paint(left+strings.Repeat(mid, inner)+right, width, accent)
	}
	line := func(content string) string {
		return margin + m.paint("│", 1, accent) + content + m.paint("│", 1, accent)
	}
	full := func(text string, kind tone) string {
		return line(m.paint(" "+text, inner, kind))
	}
	lines := []string{
		border("┌", "─", "┐"),
		full("COMPUTER HOST LAN   /   LINUX INSTALLER", accent),
		full("DEMO ONLY  |  SIMULATED DATA  |  NO CHANGES", warning),
		border("├", "─", "┤"),
		full(title, accent),
	}

	// Add a persistent step sidebar on wide terminals. Compact terminals
	// retain the same choices, focus and footer in a single column.
	wizard := m.page >= welcome && m.page <= finish
	steps := []string{"Welcome", "SmartThings hub", "Power control", "Review", "Install", "Finish"}
	sidebar := wizard && width >= 88
	for i := 0; i < height-8; i++ {
		r := plain("")
		if i < len(rows) {
			r = rows[i]
		}
		if sidebar {
			label, kind := "", muted
			if i < len(steps) {
				label = fmt.Sprintf("  %d. %s", i+1, steps[i])
				if int(m.page)-1 == i {
					kind = selected
				} else if int(m.page)-1 > i {
					kind = success
				}
			}
			left := m.paint(label, 22, kind)
			right := m.paint(" "+r.text, inner-23, r.tone)
			lines = append(lines, line(left+m.paint("│", 1, accent)+right))
		} else {
			lines = append(lines, line(m.paint(" "+fit(r.text, bodyWidth)+" ", inner, r.tone)))
		}
	}
	lines = append(lines, border("├", "─", "┤"), full(footer, muted), border("└", "─", "┘"))
	return strings.Join(lines, "\n")
}

func (m model) View() tea.View {
	v := tea.NewView(m.render())
	v.AltScreen = true
	return v
}

func main() {
	if !term.IsTerminal(os.Stdin.Fd()) || !term.IsTerminal(os.Stdout.Fd()) || os.Getenv("TERM") == "dumb" {
		fmt.Fprintln(os.Stderr, "Visual demo requires an interactive terminal. No host checks or changes performed.")
		os.Exit(2)
	}
	_, monochrome := os.LookupEnv("NO_COLOR")
	m := model{page: menu, width: 80, height: 24, power: 1, monochrome: monochrome}
	if _, err := tea.NewProgram(m).Run(); err != nil {
		fmt.Fprintln(os.Stderr, "Visual demo:", err)
		os.Exit(1)
	}
}
