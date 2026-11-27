package main

import (
	"fmt"
	"io"
	"os"
	"sort"
	"strings"

	tea "charm.land/bubbletea/v2"
)

// Read-only candidates use the same physical Ethernet heuristic as setup.
// The protected backend, not the chooser, establishes actual WOL support.
func wiredCandidatesAt(sysfs string) []string {
	entries, err := os.ReadDir(sysfs)
	if err != nil {
		return nil
	}
	var result []string
	for _, entry := range entries {
		if wiredInterfaceAt(sysfs, entry.Name()) {
			result = append(result, entry.Name())
		}
	}
	sort.Strings(result)
	return result
}

type nicSelectionScreen struct {
	frame      detailFrame
	candidates []string
	suggested  string
	cursor     int
	first      int
	chosen     string
	manual     *consentScreen
	done       bool
	optional   bool
}

func newNICSelection(candidates []string, suggested string, optional bool) nicSelectionScreen {
	m := nicSelectionScreen{candidates: append([]string(nil), candidates...), suggested: suggested, optional: optional}
	// Other is the default when no unique recommendation exists. On
	// optional post-uninstall entry, default to Keep/Cancel instead.
	m.cursor = len(candidates)
	for i, nic := range candidates {
		if nic == suggested {
			m.cursor = i
			break
		}
	}
	if optional {
		m.cursor = len(candidates) + 1
	}
	return m
}

func (m nicSelectionScreen) Init() tea.Cmd { return nil }

func (m nicSelectionScreen) pageSize() int { return max(1, m.frame.capacity()-3) }

func (m nicSelectionScreen) start() int {
	size := m.pageSize()
	first := min(max(0, m.first), max(0, len(m.candidates)+2-size))
	if m.cursor < first {
		first = m.cursor
	} else if m.cursor >= first+size {
		first = m.cursor - size + 1
	}
	return max(0, first)
}

func (m nicSelectionScreen) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	if m.done {
		return m, nil
	}
	if m.manual != nil {
		next, cmd := m.manual.Update(msg)
		v := next.(consentScreen)
		m.manual = &v
		if v.done {
			if v.submitted && (v.invalid || !wiredNICName(strings.TrimSpace(v.input))) {
				// Keep invalid manual names in the editor, never call the backend.
				v.done, v.submitted, v.invalid = false, false, true
				m.manual = &v
				return m, nil
			}
			m.done = true
			if v.submitted {
				m.chosen = strings.TrimSpace(v.input)
			}
			return m, tea.Quit
		}
		return m, cmd
	}
	switch event := msg.(type) {
	case tea.WindowSizeMsg:
		m.frame.width, m.frame.height = event.Width, event.Height
	case tea.KeyPressMsg:
		switch event.String() {
		case "esc", "q", "ctrl+c":
			m.done = true
			return m, tea.Quit
		}
		if !m.frame.ready() {
			return m, nil
		}
		switch event.String() {
		case "up", "k":
			m.cursor--
		case "down", "j":
			m.cursor++
		case "pgup":
			m.cursor -= m.pageSize()
		case "pgdown":
			m.cursor += m.pageSize()
		case "home":
			m.cursor = 0
		case "end":
			m.cursor = len(m.candidates) + 1
		case "enter":
			if m.cursor < len(m.candidates) {
				if wiredNICName(m.candidates[m.cursor]) {
					m.chosen = m.candidates[m.cursor]
				}
				m.done = true
				return m, tea.Quit
			}
			if m.cursor == len(m.candidates) {
				m.manual = &consentScreen{
					frame: m.frame, title: "WAKE-ON-LAN",
					review: []detailRow{{"Enter a wired Ethernet interface name.", "normal"},
						{"Only installer-owned settings can be removed.", "muted"}},
					prompt: "Interface name:",
				}
				return m, nil
			}
			m.done = true
			return m, tea.Quit
		}
		m.cursor = min(max(0, m.cursor), len(m.candidates)+1)
	}
	m.first = m.start()
	return m, nil
}

func (m nicSelectionScreen) View() tea.View {
	if m.manual != nil {
		return m.manual.View()
	}
	title := "Select the wired interface"
	if m.optional {
		title = "Agent removed. Optional Wake-on-LAN cleanup"
	}
	rows := []detailRow{{title, "header"},
		{"Administrator authorization checks the saved policy.", "normal"},
		{"No network settings change during the check.", "muted"}}
	first := m.start()
	for i := first; i < min(len(m.candidates)+2, first+m.pageSize()); i++ {
		label := "Cancel / keep settings"
		if i < len(m.candidates) {
			label = m.candidates[i]
			if label == m.suggested {
				label += " (suggested)"
			}
		} else if i == len(m.candidates) {
			label = "Other interface (enter name)"
		}
		marker, tone := "  ", "normal"
		if i == m.cursor {
			marker, tone = "> ", "selected"
		}
		rows = append(rows, detailRow{marker + label, tone})
	}
	status := fmt.Sprintf("Choice %d of %d | Enter checks saved WOL", m.cursor+1, len(m.candidates)+2)
	v := tea.NewView(m.frame.render("WAKE-ON-LAN", rows, status,
		"Up/Down Select | PgUp/PgDn Page | Enter | Esc/Q Cancel"))
	v.AltScreen = true
	return v
}

func actualNICSelection(optional bool) nicSelectionScreen {
	m := newNICSelection(wiredCandidatesAt("/sys/class/net"), suggestedNIC(""), optional)
	m.frame.monochrome = os.Getenv("NO_COLOR") != ""
	return m
}

func selectWOLInterface(optional bool) (string, error) {
	result, err := runFramedProgram(actualNICSelection(optional))
	if err != nil {
		return "", err
	}
	final, ok := result.(nicSelectionScreen)
	if !ok {
		return "", fmt.Errorf("unexpected interface selection")
	}
	if !final.done || final.chosen == "" {
		return "", nil
	}
	if !wiredNICName(final.chosen) {
		return "", fmt.Errorf("invalid wired interface")
	}
	return final.chosen, nil
}

func wolRemovalReview(nic string, reply privilegedResult) operationScreen {
	rows := []detailRow{{"Interface: " + nic, "header"}}
	switch reply.WOLStatus {
	case "managed":
		rows = append(rows, detailRow{"Installer-owned Wake-on-LAN policy is recorded.", "normal"})
	case "runtime_only":
		rows = append(rows,
			detailRow{"Persistent policy was not changed by the installer.", "normal"},
			detailRow{"Removal may restore the recorded runtime WOL setting.", "normal"})
	case "review_required":
		rows = append(rows,
			detailRow{"Saved policy could not be verified.", "warning"},
			detailRow{"Retry removal only if intended; ownership is rechecked.", "warning"},
			detailRow{"If verification fails, keep the record for manual review.", "muted"})
	case "not_managed":
		rows = append(rows, detailRow{"No installer-owned setting for this interface.", "normal"})
		return operationScreen{title: "WAKE-ON-LAN", review: rows,
			choices: []operationChoice{{"0", "", "Close"}}}
	}
	rows = append(rows, detailRow{"Restore recorded settings only if the helper verifies them.", "normal"},
		detailRow{"The agent is unchanged. Administrator policy is protected.", "muted"})
	return confirmationScreen("WAKE-ON-LAN", rows, true)
}

// A fresh protected check precedes informed consent. A second request is
// separately authorized; no session, password or privilege is retained.
func manageWOLSelected(writer io.Writer, nic string,
	authorize func(privilegedRequest) (privilegedResult, error),
	review func(string, privilegedResult) (bool, error)) error {
	if !wiredNICName(nic) {
		return fmt.Errorf("invalid wired interface")
	}
	reply, err := authorize(privilegedRequest{SchemaVersion: 2, Action: "wol-check", WOLInterface: &nic})
	if err != nil {
		return err
	}
	if reply.Status != "passed" || !validWOLStatus(reply, "wol-check") {
		return fmt.Errorf("invalid Wake-on-LAN status")
	}
	accepted, err := review(nic, reply)
	if err != nil {
		return err
	}
	if !accepted || reply.WOLStatus == "not_managed" {
		return nil
	}
	reply, err = authorize(privilegedRequest{SchemaVersion: 2, Action: "wol-remove", WOLInterface: &nic})
	if err != nil {
		return err
	}
	if reply.Status != "passed" || !validWOLStatus(reply, "wol-remove") {
		return fmt.Errorf("invalid Wake-on-LAN removal result")
	}
	showWOLStatus(writer, reply)
	return nil
}

func runSelectedWOL(writer io.Writer, method, nic string) error {
	return manageWOLSelected(writer, nic, func(req privilegedRequest) (privilegedResult, error) {
		return executeAuthorizedBootstrap(req, true, method)
	}, func(nic string, reply privilegedResult) (bool, error) {
		m := wolRemovalReview(nic, reply)
		m.frame.monochrome = os.Getenv("NO_COLOR") != ""
		if reply.WOLStatus == "not_managed" {
			_, err := runOperationScreen(m)
			return false, err
		}
		return runOperationConsent(m, "REMOVE")
	})
}

func runWOLPresentation(accessible bool, reader io.Reader, writer io.Writer, method string, optional bool) error {
	if !detailTerminal(accessible, reader, writer) {
		return manageWOL(reader, writer, optional, func(req privilegedRequest) (privilegedResult, error) {
			return executeAuthorizedBootstrap(req, true, method)
		})
	}
	nic, err := selectWOLInterface(optional)
	if err != nil || nic == "" {
		return err
	}
	return runSelectedWOL(writer, method, nic)
}
