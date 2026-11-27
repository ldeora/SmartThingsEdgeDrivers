package main

// One alternate-screen lifetime for ordinary maintenance navigation and
// consent. A model can return an intent; privileged execution is exclusively
// outside Program.Run, after the terminal has been restored.
import (
	"fmt"
	"io"
	"os"

	tea "charm.land/bubbletea/v2"
	"charm.land/huh/v2"
)

type maintenanceApplication struct {
	menu       maintenanceScreen
	info       apiInspect
	screen     tea.Model
	window     tea.WindowSizeMsg
	prepare    func(string) (*liveSelection, error) // read-only
	nicChooser func() nicSelectionScreen
	action     string
	selection  *liveSelection
	nic        string
	err        error
	done       bool
	fromConfig bool
	pending    bool
	generation uint64
}

type preparedSetup struct {
	generation uint64
	selection  *liveSelection
	err        error
}

// Read-only preparation has no authorization capability. The generation
// identifies this visit so a late reply cannot reopen a cancelled screen.
type preparingScreen struct {
	frame detailFrame
}

func (m preparingScreen) Init() tea.Cmd { return nil }

func (m preparingScreen) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	if size, ok := msg.(tea.WindowSizeMsg); ok {
		m.frame.width, m.frame.height = size.Width, size.Height
	}
	return m, nil
}

func (m preparingScreen) View() tea.View {
	v := tea.NewView(m.frame.render("SETUP", []detailRow{
		{"Searching for SmartThings hubs...", "header"},
		{"Checking the local installation and network.", "normal"},
	}, "Preparing setup", "Esc Back | Ctrl+C Exit"))
	v.AltScreen = true
	return v
}

func (m maintenanceApplication) Init() tea.Cmd { return nil }

func (m maintenanceApplication) backToMenu() (tea.Model, tea.Cmd) {
	m.pending = false
	m.fromConfig = false
	m.selection = nil
	m.menu.chosen = ""
	return m.switchScreen(m.menu)
}

func (m maintenanceApplication) backFromTask() (tea.Model, tea.Cmd) {
	m.pending = false
	m.selection = nil
	if m.fromConfig {
		m.fromConfig = false
		return m.open("configure")
	}
	return m.backToMenu()
}

func (m maintenanceApplication) switchScreen(screen tea.Model) (tea.Model, tea.Cmd) {
	init := screen.Init()
	next, resize := screen.Update(m.window)
	m.screen = next
	return m, tea.Batch(init, resize)
}

func (m maintenanceApplication) finish(action string) (tea.Model, tea.Cmd) {
	m.action, m.done = action, true
	return m, tea.Quit
}

func (m maintenanceApplication) open(action string) (tea.Model, tea.Cmd) {
	switch action {
	case "inspect":
		return m.switchScreen(inspectionScreen{
			frame: detailFrame{monochrome: m.menu.monochrome},
			rows:  inspectionRows(m.info, m.menu.installed),
		})
	case "configure":
		screen := configurationScreen()
		screen.frame.monochrome = m.menu.monochrome
		return m.switchScreen(screen)
	case "wol":
		return m.switchScreen(m.nicChooser())
	case "recover", "uninstall":
		screen, token := recoveryScreen(), "RECOVER"
		if action == "uninstall" {
			screen, token = uninstallScreen(), "UNINSTALL"
		}
		screen.frame.monochrome = m.menu.monochrome
		return m.switchScreen(operationConsentScreen{operation: screen, token: token})
	case "restore":
		// Protected listing requires its own genuine authorization.
		return m.finish("restore")
	case "install", "upgrade", "repair":
		m.generation++
		m.pending = true
		generation, prepare := m.generation, m.prepare
		next, _ := m.switchScreen(preparingScreen{
			frame: detailFrame{monochrome: m.menu.monochrome},
		})
		return next, func() tea.Msg {
			s, err := prepare(action)
			return preparedSetup{generation: generation, selection: s, err: err}
		}
	default:
		m.err = fmt.Errorf("invalid maintenance selection")
		return m.finish("")
	}
}

func (m maintenanceApplication) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
	if m.done {
		return m, nil
	}
	switch event := msg.(type) {
	case preparedSetup:
		if !m.pending || event.generation != m.generation {
			return m, nil
		}
		m.pending = false
		if event.err != nil || event.selection == nil {
			m.err = event.err
			if m.err == nil {
				m.err = fmt.Errorf("setup preparation returned no selection")
			}
			return m.finish("")
		}
		m.selection = event.selection
		return m.switchScreen(installConsentWizard{
			wizard: newWizardScreen(event.selection, true, m.menu.monochrome), state: event.selection,
		})
	case tea.WindowSizeMsg:
		m.window = event
	case tea.KeyPressMsg:
		if event.String() == "ctrl+c" {
			return m.finish("")
		}
		if event.String() == "esc" {
			switch screen := m.screen.(type) {
			case preparingScreen, operationScreen:
				return m.backFromTask()
			case operationConsentScreen:
				if screen.consent == nil {
					return m.backFromTask()
				}
			case nicSelectionScreen:
				if screen.manual == nil {
					return m.backFromTask()
				}
			case installConsentWizard:
				if screen.consent == nil && screen.wizard.form.GetFocusedField().GetKey() == "welcome" {
					return m.backFromTask()
				}
			}
		}
	}
	next, cmd := m.screen.Update(msg)
	m.screen = next
	switch current := next.(type) {
	case maintenanceScreen:
		if cmd == nil {
			return m, nil
		}
		if current.chosen == "" {
			return m.finish("")
		}
		for _, c := range m.menu.choices {
			if c.enabled && c.action == current.chosen && c.action != "exit" {
				return m.open(current.chosen)
			}
		}
		m.err = fmt.Errorf("invalid maintenance selection")
		return m.finish("")
	case inspectionScreen:
		if cmd != nil {
			return m.backToMenu()
		}
	case operationScreen:
		if cmd != nil {
			switch current.chosen {
			case "upgrade", "wol":
				m.fromConfig = true
				return m.open(current.chosen)
			case "":
				return m.backToMenu()
			default:
				m.err = fmt.Errorf("invalid configuration selection")
				return m.finish("")
			}
		}
	case operationConsentScreen:
		if current.consent != nil && current.consent.done {
			if current.consent.accepted() {
				switch current.token {
				case "RECOVER":
					return m.finish("recover")
				case "UNINSTALL":
					return m.finish("uninstall")
				}
			}
			return m.finish("")
		}
		if current.consent == nil && cmd != nil {
			return m.backFromTask()
		}
	case nicSelectionScreen:
		if current.done {
			if wiredNICName(current.chosen) {
				m.nic = current.chosen
				return m.finish("wol")
			}
			return m.backFromTask()
		}
	case installConsentWizard:
		if current.wizard.form.State == huh.StateAborted {
			return m.finish("")
		}
		if current.wizard.form.State == huh.StateCompleted && !*current.wizard.reviewChoice {
			return m.backFromTask()
		}
		if current.consent != nil && current.consent.done {
			if current.consent.accepted() &&
				current.wizard.form.State == huh.StateCompleted && *current.wizard.reviewChoice &&
				current.consent.token == current.state.installConfirmation() {
				current.state.finished = true
				m.selection = current.state
				return m.finish("install-reviewed")
			}
			return m.finish("")
		}
	}
	return m, cmd
}

func (m maintenanceApplication) View() tea.View { return m.screen.View() }

func newMaintenanceApplication(menu maintenanceScreen, info apiInspect, prepare func(string) (*liveSelection, error), nicChooser func() nicSelectionScreen) maintenanceApplication {
	return maintenanceApplication{menu: menu, info: info, screen: menu, prepare: prepare, nicChooser: nicChooser}
}

func runMaintenanceApplication(api apiClient, info apiInspect, reader io.Reader, writer io.Writer, method string) error {
	bundled := "unknown"
	if data, err := bundleRead("agent/linux_host_agent.py"); err == nil {
		bundled = agentVersionFromSource(data)
	}
	menu := newMaintenanceScreen(info, installedAgentVersion(), bundled, os.Getenv("NO_COLOR") != "")
	m := newMaintenanceApplication(menu, info, func(action string) (*liveSelection, error) {
		// Match the old dispatcher's fresh inspection before setup.
		fresh, err := api.inspect()
		if err != nil {
			return nil, err
		}
		if (action == "install") == fresh.Installation.Detected {
			return nil, fmt.Errorf("installation state changed; start setup again")
		}
		s := newLiveSelection(api, fresh, discoverHubs())
		s.requestedAction = action
		s.firewalldActive = firewalldRunning()
		return s, nil
	}, func() nicSelectionScreen { return actualNICSelection(false) })
	result, err := runFramedProgram(m)
	if err != nil {
		return err
	}
	final, ok := result.(maintenanceApplication)
	if !ok {
		return fmt.Errorf("unexpected maintenance application result")
	}
	if final.err != nil {
		return final.err
	}
	if !final.done || final.action == "" {
		fmt.Fprintln(writer, "Exited without changes.")
		return nil
	}
	// The renderer and input loop have exited. Only now may an existing
	// privileged action run. No credential input enters the application.
	switch final.action {
	case "install-reviewed":
		if final.selection == nil || !final.selection.finished {
			return fmt.Errorf("missing installation approval")
		}
		return installSelection(final.selection, writer, true, method)
	case "restore":
		return runRestorePresentation(false, reader, writer, method)
	case "recover":
		return executeConfirmedRecovery(writer, func(req privilegedRequest) (privilegedResult, error) {
			return executeAuthorizedBootstrap(req, true, method)
		})
	case "uninstall":
		return finishUninstall(false, reader, writer, method, true)
	case "wol":
		return runSelectedWOL(writer, method, final.nic)
	default:
		return fmt.Errorf("invalid maintenance application action")
	}
}
