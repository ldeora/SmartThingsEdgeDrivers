package main

import (
	"bufio"
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"

	"charm.land/huh/v2"
)

// The legacy live read-only path stays untouched unless -install is
// explicitly selected. This bundled preview runner makes the new Go
// executable self-contained without executing Python as root from /tmp.
func makeEmbeddedReadOnlyAPI() (string, func(), error) {
	if err := validateEmbeddedBundle(); err != nil {
		return "", nil, err
	}
	base, err := os.MkdirTemp("", "computer-host-readonly-")
	if err != nil {
		return "", nil, err
	}
	cleanup := func() { _ = os.RemoveAll(base) }
	for _, name := range previewFiles {
		data, err := bundleRead(name)
		if err != nil {
			cleanup()
			return "", nil, err
		}
		dest := filepath.Join(base, filepath.FromSlash(name))
		if err := os.MkdirAll(filepath.Dir(dest), 0o700); err != nil {
			cleanup()
			return "", nil, err
		}
		mode := os.FileMode(0o600)
		if strings.HasSuffix(name, ".sh") {
			mode = 0o700
		}
		if err := os.WriteFile(dest, data, mode); err != nil {
			cleanup()
			return "", nil, err
		}
	}
	return filepath.Join(base, "scripts/installer-api.sh"), cleanup, nil
}

func (s *liveSelection) installationSummary() string {
	summary := s.inspectionSummary()
	return strings.Replace(summary,
		"This is an early PREVIEW: it will not install or change anything.",
		"Installation is available after explicit review and administrator authorization.", 1)
}

func (s *liveSelection) installPreview() string {
	preview := s.preview()
	preview = strings.Replace(preview,
		"Preview only — your Linux agent, SmartThings devices and settings\nwill remain unchanged. No installation or pairing will happen.",
		"After confirmation, the wizard will request administrator permission\nand install or upgrade the Linux agent. No SmartThings pairing or firewall\nchanges will happen automatically.", 1)
	return preview
}

func approvedRootRequest(s *liveSelection) (privilegedRequest, error) {
	plan, err := s.currentPlan()
	if err != nil {
		return privilegedRequest{}, errors.New("read-only installation plan failed")
	}
	if !s.inspection.Python.VersionSupported ||
		plan.SelectedPython != s.inspection.Python.SelectedInterpreter {
		return privilegedRequest{}, errors.New("compatible Python 3.10+ is required")
	}
	for _, check := range s.inspection.Checks {
		if check.Status == "blocked" {
			return privilegedRequest{}, fmt.Errorf("installation prerequisite %s needs attention", check.ID)
		}
	}
	action := "install"
	if s.inspection.Installation.Detected {
		action = "upgrade"
	}
	power := "preserve"
	if s.powerChoice == "enabled" {
		power = "enable"
	} else if s.powerChoice == "disabled" {
		power = "disable"
	}
	var nic *string
	if s.wolChoice == "pin" {
		if err := validNICName(s.wolNIC); err != nil {
			return privilegedRequest{}, errors.New("invalid network interface")
		}
		value := s.wolNIC
		nic = &value
	}
	request := privilegedRequest{
		SchemaVersion: 1, Action: action, Power: power, WOLInterface: nic,
	}
	return request, request.validate()
}

// The privileged process reads only the bounded request on stdin. sudo may
// open /dev/tty for its password prompt only after Huh has released raw mode.
// Neither the wizard nor the helper reads or stores the sudo password.
func executeAuthorizedBootstrap(request privilegedRequest, interactive bool) (privilegedResult, error) {
	payload, err := json.Marshal(request)
	if err != nil {
		return privilegedResult{}, err
	}
	binary, err := os.Executable()
	if err != nil {
		return privilegedResult{}, errors.New("cannot identify installer executable")
	}
	binary, err = filepath.EvalSymlinks(binary)
	if err != nil || !filepath.IsAbs(binary) {
		return privilegedResult{}, errors.New("cannot resolve installer executable")
	}
	sudo := ""
	for _, candidate := range []string{"/usr/bin/sudo", "/bin/sudo"} {
		if info, statErr := os.Stat(candidate); statErr == nil && info.Mode().IsRegular() &&
			info.Mode().Perm()&0o111 != 0 {
			sudo = candidate
			break
		}
	}
	if sudo == "" {
		return privilegedResult{}, errors.New("sudo is required to authorize installation")
	}
	args := []string{"--", binary, "-root-bootstrap"}
	if !interactive {
		args = append([]string{"-n"}, args...)
	}
	cmd := exec.Command(sudo, args...)
	cmd.Dir = "/"
	cmd.Stdin = bytes.NewReader(payload)
	cmd.Env = []string{
		"PATH=/usr/sbin:/usr/bin:/sbin:/bin", "HOME=/root",
		"LANG=C", "LC_ALL=C", "TERM=dumb",
	}
	cmd.WaitDelay = 2 * time.Second
	var stdout, stderr cappedBuffer
	cmd.Stdout, cmd.Stderr = &stdout, &stderr
	if err := cmd.Run(); err != nil {
		// Never copy raw sudo or privileged helper stderr into a bug report.
		return privilegedResult{}, errors.New("administrator authorization or privileged installation failed; no credentials were collected")
	}
	var response privilegedResult
	if err := json.Unmarshal(stdout.Bytes(), &response); err != nil ||
		response.SchemaVersion != 1 || response.SecretsIncluded ||
		response.Operation != request.Action {
		return privilegedResult{}, errors.New("unexpected privileged installer response")
	}
	if response.Status == "error" {
		return response, fmt.Errorf("privileged installer returned %s", response.ErrorCode)
	}
	if response.Status != "installed" && response.Status != "installed_cleanup_required" &&
		response.Status != "passed" {
		return response, errors.New("installer did not report a valid completion")
	}
	return response, nil
}

func installSelection(s *liveSelection, w io.Writer, interactive bool) error {
	req, err := approvedRootRequest(s)
	if err != nil {
		return err
	}
	fmt.Fprintf(w, "\nAuthorizing %s of Computer Host LAN. This changes agent files and systemd services.\n", req.Action)
	result, err := executeAuthorizedBootstrap(req, interactive)
	if err != nil {
		return err
	}
	fmt.Fprintln(w, "\nComputer Host LAN:", result.Status)
	if result.IdentityPreserved == "verified" {
		fmt.Fprintln(w, "Existing agent identity verified.")
	} else if req.Action != "install" {
		fmt.Fprintln(w, "Existing identity was not verified because the agent was intentionally stopped.")
	} else {
		fmt.Fprintln(w, "A new agent was installed; there is no previous identity to compare.")
	}
	fmt.Fprintln(w, "Open SmartThings, install the Computer Host LAN Edge driver, then Add device → Scan nearby.")
	fmt.Fprintln(w, "Automatic hub pairing, firewall changes and persistent WOL configuration were not performed.")
	if req.Power == "enable" {
		fmt.Fprintln(w, "For remote power, configure the SmartThings device's controlKey and allowPower preferences.")
		fmt.Fprintln(w, "The guarded key display is planned for the schema v2 wizard; it is not shown here.")
	}
	return nil
}

func runInstallingWizard(accessible bool, apiPath string, reader io.Reader, writer io.Writer) error {
	if os.Geteuid() == 0 {
		return errors.New("run the wizard as your normal user; sudo is requested only after review")
	}
	if apiPath == "" {
		var cleanup func()
		var err error
		apiPath, cleanup, err = makeEmbeddedReadOnlyAPI()
		if err != nil {
			return err
		}
		defer cleanup()
	}
	api, err := newAPIClient(apiPath)
	if err != nil {
		return err
	}
	info, err := api.inspect()
	if err != nil {
		return err
	}
	hubs := discoverHubs()
	if accessible {
		// The plain-text form includes a literal INSTALL confirmation on
		// its final page; no extra raw-terminal/sudo prompt is mixed in.
		return runLiveAccessibleWithHubsMode(reader, writer, api, info, hubs,
			true, func(s *liveSelection) error {
				return installSelection(s, writer, false)
			})
	}
	state, err := os.Stdin.Stat()
	if err != nil || state.Mode()&os.ModeCharDevice == 0 {
		return errors.New("interactive installation needs a terminal; use -accessible")
	}
	s := newLiveSelection(api, info, hubs)
	fmt.Fprintln(writer, "COMPUTER HOST LAN — LINUX INSTALLATION")
	fmt.Fprintln(writer, "The agent will not be changed until you approve the final confirmation.")
	if err := liveFormMode(s, true).Run(); err != nil {
		if errors.Is(err, huh.ErrUserAborted) {
			fmt.Fprintln(writer, "Cancelled. No changes made.")
			return nil
		}
		return err
	}
	if !s.finished {
		fmt.Fprintln(writer, "Exited without changes.")
		return nil
	}
	// At this point Huh has exited; the terminal is no longer in raw mode.
	fmt.Fprint(writer, "\nType INSTALL to authorize system changes (anything else cancels): ")
	line, err := bufio.NewReader(reader).ReadString('\n')
	if err != nil && err != io.EOF {
		return err
	}
	if strings.TrimSpace(line) != "INSTALL" {
		fmt.Fprintln(writer, "Cancelled. No changes made.")
		return nil
	}
	return installSelection(s, writer, true)
}

func runRecoveryWizard(reader io.Reader, writer io.Writer) error {
	if os.Geteuid() == 0 {
		return errors.New("run the wizard as your normal user; sudo is requested after confirmation")
	}
	info, err := os.Stdin.Stat()
	if err != nil || info.Mode()&os.ModeCharDevice == 0 {
		return errors.New("interactive recovery needs a terminal")
	}
	fmt.Fprintln(writer, "Computer Host LAN — recover a previously interrupted installation.")
	fmt.Fprintln(writer, "This restores the last managed-file snapshot and previous service state.")
	fmt.Fprint(writer, "Type RECOVER to authorize the existing trusted helper: ")
	raw, err := bufio.NewReader(reader).ReadString('\n')
	if err != nil && err != io.EOF {
		return err
	}
	if strings.TrimSpace(raw) != "RECOVER" {
		fmt.Fprintln(writer, "Recovery cancelled. No changes made.")
		return nil
	}
	response, err := executeAuthorizedBootstrap(
		privilegedRequest{SchemaVersion: 1, Action: "recover"}, true)
	if err != nil {
		return err
	}
	fmt.Fprintln(writer, "Recovery outcome:", response.RecoveryStatus)
	return nil
}
