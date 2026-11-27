package main

// Presentation only: an operation screen can return a choice, but it
// cannot read private state, request elevation or execute an operation.
import (
	"fmt"
	"io"
	"os"

	tea "charm.land/bubbletea/v2"
)

type operationChoice struct {
	key, action, label string
}

type operationScreen struct {
	frame   detailFrame
	title   string
	review  []detailRow
	choices []operationChoice
	cursor  int
	chosen  string
}

func (m operationScreen) Init() tea.Cmd { return nil }

func (m operationScreen) page() ([]detailRow, bool) {
	if !m.frame.ready() {
		return nil, false
	}
	width := m.frame.bodyWidth()
	rows := wrapDetailRows(m.review, width)
	rows = append(rows, detailRow{"", "normal"})
	for i, choice := range m.choices {
		marker, tone := "  ", "normal"
		if i == m.cursor {
			marker, tone = "> ", "selected"
		}
		label := marker + "[" + choice.key + "] " + choice.label
		// Preserve the two-space unselected marker for aligned choices.
		if len(label) <= width {
			rows = append(rows, detailRow{label, tone})
		} else {
			rows = append(rows, wrapDetail(detailRow{label, tone}, width)...)
		}
	}
	return rows, len(rows) <= m.frame.capacity()
}

func (m operationScreen) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	switch event := msg.(type) {
	case tea.WindowSizeMsg:
		m.frame.width, m.frame.height = event.Width, event.Height
	case tea.KeyPressMsg:
		switch event.String() {
		case "esc", "q", "ctrl+c":
			m.chosen = ""
			return m, tea.Quit
		}
		if _, fits := m.page(); !fits || len(m.choices) == 0 {
			return m, nil
		}
		switch event.String() {
		case "up", "k":
			m.cursor = (m.cursor + len(m.choices) - 1) % len(m.choices)
		case "down", "j":
			m.cursor = (m.cursor + 1) % len(m.choices)
		case "enter":
			m.chosen = m.choices[m.cursor].action
			return m, tea.Quit
		default:
			for i, choice := range m.choices {
				if event.String() == choice.key {
					m.cursor = i
					break
				}
			}
		}
	}
	return m, nil
}

func (m operationScreen) View() tea.View {
	rows, fits := m.page()
	status := "Select a task"
	if !fits {
		rows = []detailRow{{"Enlarge the terminal to see the full review.", "warning"}}
		status = "Resize required"
	}
	v := tea.NewView(m.frame.render(m.title, rows, status,
		"Up/Down Navigate | Enter Select | Esc/Q Cancel"))
	v.AltScreen = true
	return v
}

func runOperationScreen(m operationScreen) (string, error) {
	m.frame.monochrome = os.Getenv("NO_COLOR") != ""
	result, err := tea.NewProgram(m).Run()
	if err != nil {
		return "", err
	}
	final, ok := result.(operationScreen)
	if !ok {
		return "", fmt.Errorf("unexpected operation screen result")
	}
	if final.chosen == "" {
		return "", nil
	}
	for _, choice := range m.choices {
		if final.chosen == choice.action {
			return final.chosen, nil
		}
	}
	return "", fmt.Errorf("invalid operation selection")
}

func configurationScreen() operationScreen {
	return operationScreen{
		title: "CONFIGURE",
		review: []detailRow{
			{"Choose what to configure", "header"},
			{"Power and WOL: review setup using the bundled agent.", "normal"},
			{"Saved WOL: check or remove installer-owned policy.", "normal"},
			{"Other network settings and firewall rules are unchanged.", "muted"},
		},
		choices: []operationChoice{
			{"1", "upgrade", "Change power or Wake-on-LAN settings"},
			{"2", "wol", "Check or remove saved Wake-on-LAN"},
			{"0", "", "Cancel"},
		},
	}
}

// Continue is the default for non-removal reviews. For removal, select
// Cancel. In both cases the later literal token is the authorization.
func confirmationScreen(title string, rows []detailRow, removal bool) operationScreen {
	cursor := 0
	if removal {
		cursor = 1
	}
	return operationScreen{
		title:  title,
		review: rows,
		choices: []operationChoice{
			{"1", "continue", "Continue to typed confirmation"},
			{"0", "", "Cancel"},
		},
		cursor: cursor,
	}
}

func recoveryScreen() operationScreen {
	return confirmationScreen("RECOVER", []detailRow{
		{"Recover an interrupted operation", "header"},
		{"Undo an interrupted change or finish transaction cleanup.", "normal"},
		{"Recovery never resumes an interrupted deletion.", "normal"},
		{"Next: type RECOVER, then authorize as administrator.", "muted"},
	}, false)
}

func uninstallScreen() operationScreen {
	return confirmationScreen("UNINSTALL", []detailRow{
		{"Remove Computer Host LAN", "header"},
		{"Removes the agent and its services.", "warning"},
		{"Keeps your computer's identity, key and backups.", "normal"},
		{"Reinstall can reconnect the same SmartThings device.", "normal"},
		{"Keeps Wake-on-LAN and firewall settings by default.", "normal"},
		{"The SmartThings device goes offline; it is not deleted.", "normal"},
		{"Next: type UNINSTALL, then authorize as administrator.", "muted"},
	}, true)
}

// The normal terminal is restored before the existing literal prompt.
func operationReview(accessible bool, reader io.Reader, writer io.Writer, m operationScreen) (bool, error) {
	if !detailTerminal(accessible, reader, writer) {
		return true, nil
	}
	action, err := runOperationScreen(m)
	return action == "continue", err
}

func configurePresentation(accessible bool, reader io.Reader, writer io.Writer, dispatch func(string) error) error {
	if !detailTerminal(accessible, reader, writer) {
		return configureMaintenance(reader, writer, dispatch)
	}
	action, err := runOperationScreen(configurationScreen())
	if err != nil || action == "" {
		return err
	}
	return dispatch(action)
}
