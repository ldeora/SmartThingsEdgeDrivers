package main

import (
	"fmt"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"syscall"
)

// Read only the fixed installed agent file; never execute historical code,
// access private credentials, query the network or imply runtime verification.
const installedAgentFile = "/opt/linux-host-agent/linux_host_agent.py"

var installedProtocol = regexp.MustCompile(`(?m)^PROTOCOL = "computer-host-agent"[ \t]*$`)

func installedAgentVersion() string {
	return readInstalledAgentVersion(installedAgentFile, 0)
}

func readInstalledAgentVersion(path string, owner uint32) string {
	for dir := filepath.Dir(path); ; dir = filepath.Dir(dir) {
		info, err := os.Lstat(dir)
		if err != nil || !info.IsDir() || info.Mode().Perm()&0o022 != 0 {
			return "unknown"
		}
		st, ok := info.Sys().(*syscall.Stat_t)
		if !ok || st.Uid != owner {
			return "unknown"
		}
		if dir == "/" {
			break
		}
	}
	f, err := os.OpenFile(path, os.O_RDONLY|syscall.O_NOFOLLOW|syscall.O_NONBLOCK|syscall.O_CLOEXEC, 0)
	if err != nil {
		return "unknown"
	}
	defer f.Close()
	info, err := f.Stat()
	if err != nil || !info.Mode().IsRegular() || info.Mode().Perm()&0o022 != 0 || info.Size() > 1<<20 {
		return "unknown"
	}
	st, ok := info.Sys().(*syscall.Stat_t)
	if !ok || st.Uid != owner || st.Nlink != 1 {
		return "unknown"
	}
	data, err := io.ReadAll(io.LimitReader(f, (1<<20)+1))
	if err != nil || len(data) > 1<<20 {
		return "unknown"
	}
	return agentVersionFromSource(data)
}

func agentVersionFromSource(data []byte) string {
	if len(installedProtocol.FindAll(data, 2)) != 1 {
		return "unknown"
	}
	versions := bundledAgentVersion.FindAllSubmatch(data, 2)
	if len(versions) != 1 || !backupVersionPattern.Match(versions[0][1]) {
		return "unknown"
	}
	return string(versions[0][1])
}

func maintenanceNeeded(info apiInspect) bool {
	return info.Installation.Detected || info.Installation.RetainedStatePresent ||
		info.Installation.ServiceFile != "absent"
}

type maintenanceOption struct {
	key, action, label string
}

// Fixed keys are identical across supported layouts. Missing actions are
// rejected, rather than silently remapped to a different operation.
func maintenanceOptions(info apiInspect) []maintenanceOption {
	options := []maintenanceOption{{"1", "install", "Install / reinstall the agent"}}
	if info.Installation.Detected {
		options = []maintenanceOption{
			{"1", "upgrade", "Upgrade / install the bundled agent version"},
			{"2", "configure", "Configure — power control and Wake-on-LAN"},
			{"3", "repair", "Repair using the bundled agent version"},
		}
	} else {
		options = append(options, maintenanceOption{"2", "wol", "Configure — check or remove saved Wake-on-LAN"})
	}
	options = append(options,
		maintenanceOption{"4", "restore", "Restore an earlier backup"},
		maintenanceOption{"5", "recover", "Recover an interrupted operation"},
		maintenanceOption{"6", "inspect", "Inspect installation status"})
	if info.Installation.Detected {
		options = append(options, maintenanceOption{"7", "uninstall", "Uninstall the agent (keep private state and backups)"})
	}
	return append(options, maintenanceOption{"0", "exit", "Exit without changes"})
}

func runMaintenanceMenu(reader io.Reader, writer io.Writer, info apiInspect, dispatch func(string) error) error {
	fmt.Fprintln(writer, "Computer Host LAN — Maintenance")
	if info.Installation.Detected {
		fmt.Fprintln(writer, "Existing installation detected.")
	} else if info.Installation.RetainedStatePresent {
		fmt.Fprintln(writer, "Retained installation data detected.")
	} else {
		fmt.Fprintln(writer, "Installation state needs attention.")
	}
	fmt.Fprintln(writer, "Selecting a task does not authorize changes. Each operation has its own confirmation.")
	options := maintenanceOptions(info)
	for _, opt := range options {
		fmt.Fprintf(writer, "  [%s] %s\n", opt.key, opt.label)
	}
	for {
		fmt.Fprint(writer, "Choose a task (Enter to exit): ")
		line, err := readConfirmationLine(reader)
		if err == io.EOF || err == io.ErrUnexpectedEOF {
			fmt.Fprintln(writer, "Exited without changes.")
			return nil
		}
		if err != nil {
			return err
		}
		switch strings.ToLower(strings.TrimSpace(line)) {
		case "", "0", "quit", "exit", "q":
			fmt.Fprintln(writer, "Exited without changes.")
			return nil
		}
		for _, opt := range options {
			if strings.TrimSpace(line) == opt.key {
				return dispatch(opt.action)
			}
		}
		fmt.Fprintln(writer, "Choose one of the listed tasks.")
	}
}

func configureMaintenance(reader io.Reader, writer io.Writer, dispatch func(string) error) error {
	fmt.Fprintln(writer, "Configure Computer Host LAN")
	fmt.Fprintln(writer, "  [1] Change power or WOL settings (rerun setup using the bundled agent version)")
	fmt.Fprintln(writer, "  [2] Check or remove installer-owned Wake-on-LAN")
	fmt.Fprint(writer, "Choose a task (Enter to exit): ")
	line, err := readConfirmationLine(reader)
	if err == io.EOF || err == io.ErrUnexpectedEOF {
		return nil
	}
	if err != nil {
		return err
	}
	switch strings.ToLower(strings.TrimSpace(line)) {
	case "1":
		return dispatch("upgrade")
	case "2":
		return dispatch("wol")
	case "", "0", "q", "quit", "exit":
		return nil
	default:
		return fmt.Errorf("choose 1 or 2")
	}
}

func dispatchMaintenance(choice string, accessible bool, apiPath string, reader io.Reader, writer io.Writer, method string, info apiInspect) error {
	switch choice {
	case "install", "upgrade", "repair":
		return runInstallingWizardMode(accessible, apiPath, reader, writer, method, false, choice)
	case "configure":
		return configureMaintenance(reader, writer, func(action string) error {
			return dispatchMaintenance(action, accessible, apiPath, reader, writer, method, info)
		})
	case "inspect":
		fmt.Fprintln(writer, info.brief())
		fmt.Fprintln(writer, "Installed agent file version (not runtime-verified):", installedAgentVersion())
		fmt.Fprintln(writer, "For protected transaction status, run cli status. Choose Recover for an interrupted operation.")
		return nil
	case "restore", "wol", "recover", "uninstall":
		if !stdinIsTerminal() {
			return fmt.Errorf("this maintenance task requires a terminal")
		}
		switch choice {
		case "restore":
			return runRestoreWizard(reader, writer, method)
		case "wol":
			return runWOLManagement(reader, writer, method, false)
		case "recover":
			return runRecoveryWizard(reader, writer, method)
		case "uninstall":
			return runUninstallWizard(reader, writer, method)
		}
	}
	return fmt.Errorf("unknown maintenance task")
}
