package main

// Full-screen literal consent. This model never invokes a backend or a
// privilege provider. A submitted, matching value is necessary, but the
// caller must still validate and execute the original protected request.
import (
	"fmt"
	"strings"

	tea "charm.land/bubbletea/v2"
)

const confirmationLimit = 127 // readConfirmationLine accepts at most 127 bytes.

type consentScreen struct {
	frame     detailFrame
	title     string
	review    []detailRow
	token     string
	prompt    string // Optional non-authorization field label.
	input     string
	invalid   bool
	submitted bool
	done      bool
}

func (m consentScreen) Init() tea.Cmd { return nil }

func (m consentScreen) accepted() bool {
	return m.submitted && !m.invalid && len(m.input) <= confirmationLimit &&
		m.token != "" && strings.TrimSpace(m.input) == m.token
}

func (m consentScreen) page() ([]detailRow, bool) {
	if !m.frame.ready() {
		return nil, false
	}
	width := m.frame.bodyWidth()
	rows := wrapDetailRows(m.review, width)
	prompt := m.prompt
	if prompt == "" {
		prompt = "Type " + m.token + " to authorize:"
	}
	rows = append(rows, detailRow{prompt, "header"})
	// A bounded, append-only editor; show all entered characters without
	// interpreting terminal escapes. Reserve the cursor cell on each line.
	text := m.input
	for len(text) > width-3 {
		rows = append(rows, detailRow{"> " + text[:width-3], "selected"})
		text = text[width-3:]
	}
	rows = append(rows, detailRow{"> " + text + "_", "selected"})
	if m.invalid {
		rows = append(rows, detailRow{"Invalid or too long input. Ctrl+U clears.", "warning"})
	}
	return rows, len(rows) <= m.frame.capacity()
}

// Reject the entire invalid insertion (including multiline pastes), not
// a prefix that could accidentally become the literal authorization word.
func (m *consentScreen) insert(value string) {
	if len(m.input)+len(value) > confirmationLimit {
		m.invalid = true
		return
	}
	for _, c := range value {
		if c < 32 || c > 126 {
			m.invalid = true
			return
		}
	}
	m.input += value
}

func (m consentScreen) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	if m.done {
		return m, nil
	}
	switch event := msg.(type) {
	case tea.WindowSizeMsg:
		m.frame.width, m.frame.height = event.Width, event.Height
	case tea.KeyPressMsg:
		switch event.String() {
		case "esc", "ctrl+c":
			m.done = true
			m.submitted = false
			return m, tea.Quit
		case "ctrl+u":
			m.input, m.invalid = "", false
			return m, nil
		case "backspace":
			if len(m.input) > 0 {
				m.input = m.input[:len(m.input)-1]
			}
			return m, nil
		}
		if _, fits := m.page(); !fits {
			return m, nil
		}
		if event.String() == "enter" {
			m.done = true
			m.submitted = true
			return m, tea.Quit
		}
		if event.Text != "" {
			m.insert(event.Text)
		}
	case tea.PasteMsg:
		if _, fits := m.page(); fits {
			m.insert(event.Content)
		}
	}
	return m, nil
}

func (m consentScreen) View() tea.View {
	rows, fits := m.page()
	status := "Exact word required; any other submission cancels"
	if m.prompt != "" {
		status = "Enter submits the interface name"
	}
	if !fits {
		rows = []detailRow{{"Enlarge the terminal to see the full confirmation.", "warning"}}
		status = "Resize required"
	}
	v := tea.NewView(m.frame.render(m.title, rows, status,
		"Enter Submit | Ctrl+U Clear | Esc/Ctrl+C Cancel"))
	v.AltScreen = true
	return v
}

// Integrate the review and text entry in one Bubble Tea lifetime. The
// underlying operation model still owns numeric and arrow navigation.
type operationConsentScreen struct {
	operation operationScreen
	consent   *consentScreen
	token     string
}

func (m operationConsentScreen) Init() tea.Cmd { return nil }

func (m operationConsentScreen) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	if m.consent != nil {
		next, cmd := m.consent.Update(msg)
		value := next.(consentScreen)
		m.consent = &value
		return m, cmd
	}
	next, cmd := m.operation.Update(msg)
	m.operation = next.(operationScreen)
	if m.operation.chosen == "continue" {
		rows := append([]detailRow(nil), m.operation.review...)
		if len(rows) > 0 && strings.HasPrefix(rows[len(rows)-1].text, "Next: type ") {
			rows = rows[:len(rows)-1]
		}
		if m.token == "UNINSTALL" {
			rows = append(rows,
				detailRow{"Also keeps ownership record, linuxhost account and", "normal"},
				detailRow{"the trusted recovery helper. Not a full purge.", "normal"})
		}
		if m.token == "RECOVER" {
			rows = append(rows, detailRow{"Protected state has not yet been checked.", "muted"})
		}
		m.consent = &consentScreen{
			frame: m.operation.frame, title: m.operation.title,
			review: rows, token: m.token,
		}
		// Consume the review's Quit: advance to the text field instead.
		return m, nil
	}
	return m, cmd
}

func (m operationConsentScreen) View() tea.View {
	if m.consent != nil {
		return m.consent.View()
	}
	return m.operation.View()
}

func runOperationConsent(m operationScreen, token string) (bool, error) {
	result, err := runFramedProgram(operationConsentScreen{operation: m, token: token})
	if err != nil {
		return false, err
	}
	final, ok := result.(operationConsentScreen)
	if !ok {
		return false, fmt.Errorf("unexpected confirmation result")
	}
	return final.consent != nil && final.consent.accepted(), nil
}
