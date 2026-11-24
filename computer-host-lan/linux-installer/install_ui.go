package main

import (
	"bufio"
	"bytes"
	"context"
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

// This is a bounded, read-only service-state probe. It never invokes
// firewall-cmd, modifies rules, restarts networking or opens sockets.
func firewalldRunning() bool {
	var binary string
	for _, path := range []string{"/usr/bin/systemctl", "/bin/systemctl"} {
		if isExecutableFile(path) {
			binary = path
			break
		}
	}
	if binary == "" {
		return false // Unknown is not proof that a firewall is enabled.
	}
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	cmd := exec.CommandContext(ctx, binary, "is-active", "--quiet", "firewalld.service")
	cmd.Env = []string{"PATH=/usr/sbin:/usr/bin:/sbin:/bin", "LANG=C", "LC_ALL=C"}
	return cmd.Run() == nil
}

// Preflight evidence only: a passed Avahi check is not proof of an
// advertised service or hub reachability. A negative firewalld probe
// is not proof that it is inactive or that the firewall allows access.
type networkObservation struct {
	AvahiPrerequisites string `json:"avahi_prerequisites"`
	Firewalld           string `json:"firewalld"`
}

func observeNetwork(info apiInspect, firewallActive bool) networkObservation {
	result := networkObservation{AvahiPrerequisites: "not_verified", Firewalld: "not_verified"}
	for _, check := range info.Checks {
		if check.ID == "avahi_discovery" {
			if check.Status == "passed" {
				result.AvahiPrerequisites = "passed"
			}
			break
		}
	}
	if firewallActive {
		result.Firewalld = "active"
	}
	return result
}

func (s *liveSelection) networkWarnings() []string {
	var warnings []string
	observed := observeNetwork(s.inspection, s.firewalldActive)
	if observed.AvahiPrerequisites != "passed" {
		warnings = append(warnings,
			"Avahi discovery is not confirmed. SmartThings Scan nearby may not find this computer until avahi-daemon is running and the agent's _computerhost._tcp service is advertised.")
	}
	if observed.Firewalld == "active" {
		warnings = append(warnings,
			"firewalld is active. Incoming TCP 8765 may be blocked for the SmartThings hub. Check or explicitly configure a hub-scoped rule before relying on connectivity; this wizard has not changed firewall rules.")
	}
	return warnings
}

func (s *liveSelection) showNetworkWarnings(w io.Writer) {
	for _, warning := range s.networkWarnings() {
		fmt.Fprintln(w, "WARNING:", warning)
	}
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
	for _, warning := range s.networkWarnings() {
		preview += "\n\nWARNING: " + warning
	}
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

// Every privilege provider receives the same bounded JSON on stdin.
// Its own authentication must use the controlling TTY/polkit agent, never
// the JSON pipe. Do not attempt another provider after a declined prompt:
// switching identities automatically after a refusal would be surprising.
type elevationCommand struct {
	method string
	path   string
	args   []string
}

func findElevationCommand(binary string, interactive bool, payload []byte, available func(string) bool) (elevationCommand, error) {
	if !filepath.IsAbs(binary) {
		return elevationCommand{}, errors.New("installer executable must have an absolute path")
	}
	find := func(names ...string) string {
		for _, name := range names {
			if available(name) {
				return name
			}
		}
		return ""
	}
	if sudo := find("/usr/bin/sudo", "/bin/sudo"); sudo != "" {
		args := []string{"--", binary, "-root-bootstrap"}
		if !interactive {
			args = append([]string{"-n"}, args...)
		}
		return elevationCommand{"sudo", sudo, args}, nil
	}
	if doas := find("/usr/bin/doas", "/bin/doas"); doas != "" {
		args := []string{"--", binary, "-root-bootstrap"}
		if !interactive {
			args = append([]string{"-n"}, args...)
		}
		return elevationCommand{"doas", doas, args}, nil
	}
	if run0 := find("/usr/bin/run0", "/bin/run0"); run0 != "" {
		args := []string{"--pipe", "--", binary, "-root-bootstrap"}
		if !interactive {
			args = append([]string{"--no-ask-password"}, args...)
		}
		return elevationCommand{"run0", run0, args}, nil
	}
	// util-linux su/PAM may read the root password from standard input,
	// unlike sudo/doas. Never pipe the JSON request into su: attach the
	// user's terminal and supply only the non-secret schema-v1 options
	// via a shell-quoted -request argument to the same Go root decoder.
	if interactive {
		if su := find("/usr/bin/su", "/bin/su"); su != "" {
			command := "exec " + quotePOSIXShell(binary) +
				" -root-bootstrap -request " + quotePOSIXShell(string(payload))
			return elevationCommand{"su", su, []string{"root", "-c", command}}, nil
		}
	}
	return elevationCommand{}, errors.New("no supported administrator authorization method is available (sudo, doas, run0 or interactive su)")
}

// An explicit provider is important for remote SSH sessions where run0's
// polkit authorization can be unavailable even when su root works.
// Never retry another provider after failure or quietly weaken selection.
func validElevationChoice(method string) bool {
	switch method {
	case "auto", "sudo", "doas", "run0", "su":
		return true
	}
	return false
}

func chooseElevationCommand(binary string, interactive bool, payload []byte,
	method string, available func(string) bool) (elevationCommand, error) {
	if !validElevationChoice(method) {
		return elevationCommand{}, errors.New("invalid administrator authorization method")
	}
	if method == "auto" {
		return findElevationCommand(binary, interactive, payload, available)
	}
	if method == "su" && !interactive {
		return elevationCommand{}, errors.New("su requires an interactive terminal for root password authentication")
	}
	selected, err := findElevationCommand(binary, interactive, payload,
		func(candidate string) bool {
			return filepath.Base(candidate) == method && available(candidate)
		})
	if err != nil {
		return elevationCommand{}, fmt.Errorf("requested administrator authorization method %s is not available", method)
	}
	if selected.method != method {
		return elevationCommand{}, errors.New("requested administrator authorization method mismatch")
	}
	return selected, nil
}

func quotePOSIXShell(s string) string {
	return "'" + strings.ReplaceAll(s, "'", "'\\''") + "'"
}

func isExecutableFile(path string) bool {
	info, err := os.Stat(path)
	return err == nil && info.Mode().IsRegular() && info.Mode().Perm()&0o111 != 0
}

func validatedPrivilegedReply(data []byte, action string) (privilegedResult, error) {
	var reply privilegedResult
	if len(data) == 0 || len(data) > maxAPIBytes || json.Unmarshal(data, &reply) != nil ||
		reply.SchemaVersion != 1 || reply.SecretsIncluded ||
		(reply.Operation != "" && reply.Operation != action) ||
		!validAbortedFailureStage(reply.ErrorCode, reply.FailureStage) {
		return privilegedResult{}, errors.New("invalid privileged installer reply")
	}
	if reply.Operation == "" && reply.Status == "error" {
		// Python error envelopes deliberately omit operation. Only the
		// explicit, already validated caller action supplies that value.
		reply.Operation = action
	}
	if reply.Operation != action {
		return privilegedResult{}, errors.New("privileged helper action mismatch")
	}
	switch reply.Status {
	case "error":
		if !knownPrivilegedError(reply.ErrorCode) {
			return privilegedResult{}, errors.New("unrecognized privileged failure code")
		}
	case "installed", "installed_cleanup_required":
		if action != "install" && action != "upgrade" && action != "repair" {
			return privilegedResult{}, errors.New("unexpected installation outcome")
		}
	case "uninstalled", "uninstalled_cleanup_required":
		if action != "uninstall" {
			return privilegedResult{}, errors.New("unexpected uninstall outcome")
		}
		if reply.IdentityPreserved != "verified" && reply.IdentityPreserved != "not_verified" {
			return privilegedResult{}, errors.New("invalid uninstall identity outcome")
		}
	case "passed":
		if action != "status" && action != "recover" {
			return privilegedResult{}, errors.New("unexpected status outcome")
		}
	default:
		return privilegedResult{}, errors.New("unrecognized privileged result")
	}
	// Every string that can be relayed across the privileged boundary
	// must be a fixed enum, including optional legacy response fields.
	if reply.Status != "error" && reply.ErrorCode != "" {
		return privilegedResult{}, errors.New("unexpected error code in success reply")
	}
	switch reply.IdentityPreserved {
	case "", "verified", "not_verified":
	default:
		return privilegedResult{}, errors.New("invalid identity outcome")
	}
	switch reply.PrivilegedTransactionState {
	case "", "none", "in_progress", "incomplete", "recovery_required":
	default:
		return privilegedResult{}, errors.New("invalid transaction state")
	}
	switch reply.RecoveryStatus {
	case "", "aborted", "rolled_back", "cleaned", "nothing_to_recover":
	default:
		return privilegedResult{}, errors.New("invalid recovery outcome")
	}
	switch reply.RecoveryOperation {
	case "", "install", "upgrade", "repair", "uninstall":
	default:
		return privilegedResult{}, errors.New("invalid recovery operation")
	}
	if reply.RecoveryOperation != "" && (action != "recover" || reply.Status != "passed" ||
		reply.RecoveryStatus == "" || reply.RecoveryStatus == "nothing_to_recover") {
		return privilegedResult{}, errors.New("unexpected recovery operation")
	}
	return reply, nil
}

// Restrict privileged diagnostics to fixed, non-sensitive enum values.
// An absent stage is accepted for older helpers and Go bootstrap failures.
func validAbortedFailureStage(code, stage string) bool {
	if stage == "" {
		return true
	}
	if code != "aborted" {
		return false
	}
	switch stage {
	case "payload", "existing_state", "plan", "snapshot":
		return true
	}
	return false
}

func knownPrivilegedError(code string) bool {
	switch code {
	case "invalid_request", "installation_busy", "aborted", "rolled_back",
		"recovery_required", "unsupported_environment", "adoption_required",
		"unsupported_python", "untrusted_root_launcher",
		"invalid_trusted_manifest", "duplicate_key", "bootstrap_failed",
		"unsafe_lock", "not_installed":
		return true
	}
	return false
}

func userFacingPrivilegeFailure(reply privilegedResult) error {
	switch reply.ErrorCode {
	case "installation_busy":
		return errors.New("another installation or recovery is in progress. Finish that operation before retrying")
	case "unsafe_lock":
		return errors.New("an installer lock is unsafe. After confirming no installation or recovery is running, ask an administrator to inspect /run/lock/linux-host-agent-install.lock and /run/computer-host-lan/bootstrap.lock; do not delete lock files during an active installation")
	case "rolled_back":
		if reply.Operation == "uninstall" {
			return errors.New("uninstall was undone; previous files and service state were restored. Check prerequisites and run -uninstall again if desired")
		}
		return errors.New("installation could not complete; previous files and service state were restored. Check prerequisites and retry")
	case "recovery_required":
		return errors.New("installer transaction requires recovery. Run this wizard with -recover before retrying; preserve the protected journal and backup")
	case "adoption_required":
		return errors.New("retained agent state needs v2 verification. Use the manual Linux installer with --adopt-retained-state after confirming its provenance")
	case "unsupported_python":
		return errors.New("a system Python 3.10 or newer is required; install a compatible interpreter without changing the system default")
	case "not_installed":
		return errors.New("no installed Linux agent was found; nothing to uninstall. Retained state and recovery files have not been removed")
	case "unsupported_environment":
		return errors.New("the existing installation or operating environment needs attention. Check the read-only inspection before retrying")
	case "aborted":
		if reply.Operation == "uninstall" {
			return errors.New("uninstall was aborted before applying changes; inspect the existing installation and snapshot prerequisites before retrying")
		}
		switch reply.FailureStage {
		case "payload":
			return errors.New("installation aborted before applying changes (payload verification/staging); check protected payload staging prerequisites")
		case "existing_state":
			return errors.New("installation aborted before applying changes (existing agent/service state); inspect service and protected identity prerequisites")
		case "plan":
			return errors.New("installation aborted before applying changes (installation plan); inspect managed paths and systemd templates")
		case "snapshot":
			return errors.New("installation aborted before applying changes (backup snapshot); inspect the existing backup directory and available storage")
		default:
			return errors.New("installation was aborted safely before applying changes; inspect prerequisites before retrying")
		}
	case "untrusted_root_launcher", "invalid_trusted_manifest":
		return errors.New("the installed privileged helper or its trusted manifest is invalid; reinstall the verified wizard before retrying")
	case "bootstrap_failed":
		return errors.New("the elevated helper could not complete preparation or cleanup. Check the installer status and preserved recovery files before retrying")
	default:
		return fmt.Errorf("privileged installer refused the operation (%s)", reply.ErrorCode)
	}
}

// Parse an authenticated helper reply BEFORE checking the elevation process
// exit code. Python returns nonzero for many normal, recoverable failures.
func interpretPrivilegedExecution(stdout []byte, runErr error, action string) (privilegedResult, error) {
	reply, decodeErr := validatedPrivilegedReply(stdout, action)
	if decodeErr == nil {
		if reply.Status == "error" {
			return reply, userFacingPrivilegeFailure(reply)
		}
		if runErr != nil {
			return reply, errors.New("privileged helper returned success data but exited unsuccessfully; check recovery state")
		}
		return reply, nil
	}
	if runErr != nil {
		// Includes password refusal, missing policy authorization, and
		// failure before the root helper could return a valid reply.
		return privilegedResult{}, errors.New("administrator authorization or privileged bootstrap failed; no valid installer result was received")
	}
	return privilegedResult{}, errors.New("privileged helper returned an invalid or incomplete response")
}

// The root helper decodes the same bounded schema-v1 request in both cases:
// sudo/doas/run0 pass it through stdin; su receives it as a non-secret,
// shell-quoted argument while keeping stdin on the terminal for PAM.
func elevationInput(method string, payload []byte, terminal io.Reader) io.Reader {
	if method == "su" {
		return terminal
	}
	return bytes.NewReader(payload)
}

// authorizationUnavailableError means the authorization provider process
// did not start. It is intentionally distinct from any failure after Start,
// including a nonzero provider exit or lost/invalid helper response. Keep
// the existing human-readable error for the wizard.
type authorizationUnavailableError struct {
	cause error
}

func (e *authorizationUnavailableError) Error() string { return e.cause.Error() }
func (e *authorizationUnavailableError) Unwrap() error { return e.cause }

func runElevationProcess(cmd *exec.Cmd) error {
	if err := cmd.Start(); err != nil {
		return &authorizationUnavailableError{cause: err}
	}
	return cmd.Wait()
}

func executeAuthorizedBootstrap(request privilegedRequest, interactive bool, method string) (privilegedResult, error) {
	if err := request.validate(); err != nil {
		return privilegedResult{}, &authorizationUnavailableError{cause: err}
	}
	payload, err := json.Marshal(request)
	if err != nil {
		return privilegedResult{}, &authorizationUnavailableError{cause: err}
	}
	binary, err := os.Executable()
	if err != nil {
		return privilegedResult{}, &authorizationUnavailableError{cause: errors.New("cannot identify installer executable")}
	}
	binary, err = filepath.EvalSymlinks(binary)
	if err != nil || !filepath.IsAbs(binary) {
		return privilegedResult{}, &authorizationUnavailableError{cause: errors.New("cannot resolve installer executable")}
	}
	elevate, err := chooseElevationCommand(binary, interactive, payload, method, isExecutableFile)
	if err != nil {
		return privilegedResult{}, &authorizationUnavailableError{cause: err}
	}
	cmd := exec.Command(elevate.path, elevate.args...)
	cmd.Dir = "/"
	cmd.Stdin = elevationInput(elevate.method, payload, os.Stdin)
	cmd.Env = []string{
		"PATH=/usr/sbin:/usr/bin:/sbin:/bin", "HOME=/root",
		"LANG=C", "LC_ALL=C", "TERM=dumb",
	}
	cmd.WaitDelay = 2 * time.Second
	var stdout, stderr cappedBuffer
	cmd.Stdout = &stdout
	if elevate.method == "su" {
		// PAM writes its Password: prompt to stderr on some distributions.
		// Leave it visible to the user; never parse or copy stderr into
		// the structured error response.
		cmd.Stderr = os.Stderr
	} else {
		cmd.Stderr = &stderr
	}
	runErr := runElevationProcess(cmd)
	var unavailable *authorizationUnavailableError
	if errors.As(runErr, &unavailable) {
		// A failed Start cannot have produced a privileged reply.
		return privilegedResult{}, &authorizationUnavailableError{
			cause: errors.New("administrator authorization or privileged bootstrap failed; no valid installer result was received"),
		}
	}
	return interpretPrivilegedExecution(stdout.Bytes(), runErr, request.Action)
}

func installSelection(s *liveSelection, w io.Writer, interactive bool, method string) error {
	req, err := approvedRootRequest(s)
	if err != nil {
		return err
	}
	fmt.Fprintf(w, "\nAuthorizing %s of Computer Host LAN. This changes agent files and systemd services.\n", req.Action)
	if method != "auto" {
		fmt.Fprintln(w, "Administrator authorization method explicitly selected:", method)
	}
	result, err := executeAuthorizedBootstrap(req, interactive, method)
	if err != nil {
		return err
	}
	showInstallationOutcome(w, s, req, result)
	return nil
}

// The same fixed onboarding choice is exposed by the CLI without
// asserting that the SmartThings device or control key was inspected.
func onboardingMode(result privilegedResult) string {
	if result.IdentityPreserved == "verified" {
		return "check_existing_device"
	}
	return "check_or_discover"
}

func showInstallationOutcome(w io.Writer, s *liveSelection, req privilegedRequest, result privilegedResult) {
	fmt.Fprintln(w, "\nComputer Host LAN:", result.Status)
	if onboardingMode(result) == "check_existing_device" {
		fmt.Fprintln(w, "Existing agent identity verified.")
		fmt.Fprintln(w, "Open your existing SmartThings computer device and refresh it first. Rediscovery is normally unnecessary.")
		fmt.Fprintln(w, "Only if no device is registered, install the Computer Host LAN Edge driver if needed, then Add device → Scan nearby.")
	} else {
		fmt.Fprintln(w, "Previous agent identity was not verified.")
		fmt.Fprintln(w, "If you already have a SmartThings computer device, check and refresh it first.")
		fmt.Fprintln(w, "For first-time onboarding, install the Computer Host LAN Edge driver, then Add device → Scan nearby.")
	}
	s.showNetworkWarnings(w)
	fmt.Fprintln(w, "If discovery or connectivity warnings appear above, resolve those conditions before relying on Scan nearby.")
	fmt.Fprintln(w, "Automatic hub pairing, firewall changes and persistent WOL configuration were not performed.")
	switch req.Power {
	case "enable":
		fmt.Fprintln(w, "For remote power, enable allowPower and configure controlKey in the SmartThings device if needed.")
		fmt.Fprintln(w, "If the retained control key is unchanged and already configured, no key update is normally needed. Identity verification alone does not verify key equality.")
		fmt.Fprintln(w, "The control key is not shown here.")
	case "preserve":
		fmt.Fprintln(w, "Current/default power choice was retained. If remote power is enabled, an unchanged and already configured control key normally needs no update.")
	case "disable":
		fmt.Fprintln(w, "Remote power was disabled on the computer; no control key setup is needed for monitoring.")
	}
	if result.Status == "installed_cleanup_required" {
		fmt.Fprintln(w, "Installation committed, but helper cleanup is pending. Run -recover before another installation.")
	}
}

func runInstallingWizard(accessible bool, apiPath string, reader io.Reader, writer io.Writer, method string) error {
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
		// Accessible/plain-text mode can still run inside a real terminal.
		// Only use sudo -n when there is no TTY; otherwise allow sudo's
		// usual /dev/tty password prompt after the plain form completes.
		stdinInfo, statErr := os.Stdin.Stat()
		hasTTY := statErr == nil && stdinInfo.Mode()&os.ModeCharDevice != 0
		return runLiveAccessibleWithHubsMode(reader, writer, api, info, hubs,
			true, func(s *liveSelection) error {
				return installSelection(s, writer, hasTTY, method)
			})
	}
	state, err := os.Stdin.Stat()
	if err != nil || state.Mode()&os.ModeCharDevice == 0 {
		return errors.New("interactive installation needs a terminal; use -accessible")
	}
	s := newLiveSelection(api, info, hubs)
	s.firewalldActive = firewalldRunning()
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
	return installSelection(s, writer, true, method)
}

// Read only the submitted line, not subsequent input that may belong
// to PAM (su). Bound the confirmation length and reject EOF without a
// newline; unlike bufio.Reader this cannot prefetch the next line.
func readConfirmationLine(reader io.Reader) (string, error) {
	var line strings.Builder
	var next [1]byte
	for line.Len() < 128 {
		if _, err := io.ReadFull(reader, next[:]); err != nil {
			return "", err
		}
		if next[0] == '\n' {
			return line.String(), nil
		}
		line.WriteByte(next[0])
	}
	return "", errors.New("confirmation line too long")
}

// Plain text is intentional: uninstall uses the same accessible review
// and literal confirmation on every terminal, without a default Yes action.
func confirmUninstall(reader io.Reader, writer io.Writer,
	authorize func(privilegedRequest) (privilegedResult, error)) error {
	fmt.Fprintln(writer, "COMPUTER HOST LAN — LINUX UNINSTALL")
	fmt.Fprintln(writer, "Removes the managed agent files, systemd units/drop-ins and Avahi service.")
	fmt.Fprintln(writer, "Stops and disables the agent and power socket, and stops the power helper.")
	fmt.Fprintln(writer, "Retains the private installation ID and control key, v2 ownership record,")
	fmt.Fprintln(writer, "linuxhost account, historical recovery snapshots and trusted recovery helper.")
	fmt.Fprintln(writer, "External Wake-on-LAN/network policies and firewall rules are unchanged.")
	fmt.Fprintln(writer, "The SmartThings device will go offline; remove it manually if no longer needed.")
	fmt.Fprintln(writer, "A later reinstall can reuse the retained identity. This is not a full purge.")
	fmt.Fprint(writer, "Type UNINSTALL to authorize removal (anything else cancels): ")
	raw, err := readConfirmationLine(reader)
	if err != nil && err != io.EOF {
		return err
	}
	// EOF without an actual submitted line is not confirmation.
	if err == io.EOF || strings.TrimSpace(raw) != "UNINSTALL" {
		fmt.Fprintln(writer, "Uninstall cancelled. No changes made.")
		return nil
	}
	fmt.Fprintln(writer, "Authorizing uninstall. This can take several minutes.")
	reply, err := authorize(privilegedRequest{SchemaVersion: 2, Action: "uninstall"})
	if err != nil {
		return err
	}
	switch reply.Status {
	case "uninstalled":
		fmt.Fprintln(writer, "Computer Host LAN: uninstalled.")
	case "uninstalled_cleanup_required":
		fmt.Fprintln(writer, "Computer Host LAN: uninstalled; installer cleanup is still required.")
		fmt.Fprintln(writer, "Run this wizard with -recover to finish any pending transaction cleanup.")
	default:
		return errors.New("unexpected uninstall outcome")
	}
	if reply.IdentityPreserved == "verified" {
		fmt.Fprintln(writer, "Retained installation identity verified.")
	} else {
		fmt.Fprintln(writer, "No saved installation identity could be verified.")
	}
	fmt.Fprintln(writer, "Private state, recovery snapshots and the recovery helper are retained.")
	fmt.Fprintln(writer, "The SmartThings device is not automatically removed.")
	return nil
}

func runUninstallWizard(reader io.Reader, writer io.Writer, method string) error {
	if os.Geteuid() == 0 {
		return errors.New("run the wizard as your normal user; administrator authorization follows confirmation")
	}
	info, err := os.Stdin.Stat()
	if err != nil || info.Mode()&os.ModeCharDevice == 0 {
		return errors.New("interactive uninstall needs a terminal")
	}
	return confirmUninstall(reader, writer, func(request privilegedRequest) (privilegedResult, error) {
		return executeAuthorizedBootstrap(request, true, method)
	})
}

func showRecoveryOutcome(writer io.Writer, response privilegedResult) {
	fmt.Fprintln(writer, "Recovery outcome:", response.RecoveryStatus)
	switch response.RecoveryStatus {
	case "rolled_back":
		if response.RecoveryOperation == "uninstall" {
			fmt.Fprintln(writer, "Interrupted uninstall was undone. Previous files and services were restored; run -uninstall again if desired.")
		} else {
			fmt.Fprintln(writer, "Previous files and service state were restored; retry the intended operation explicitly.")
		}
	case "aborted":
		fmt.Fprintln(writer, "Interrupted operation was aborted before managed changes. Retry explicitly if desired.")
	case "cleaned":
		fmt.Fprintln(writer, "Finished transaction cleanup. No uninstall or installation was resumed.")
	}
}

func runRecoveryWizard(reader io.Reader, writer io.Writer, method string) error {
	if os.Geteuid() == 0 {
		return errors.New("run the wizard as your normal user; sudo is requested after confirmation")
	}
	info, err := os.Stdin.Stat()
	if err != nil || info.Mode()&os.ModeCharDevice == 0 {
		return errors.New("interactive recovery needs a terminal")
	}
	fmt.Fprintln(writer, "Computer Host LAN — recover a previously interrupted installer operation.")
	fmt.Fprintln(writer, "This rolls back an interrupted operation or finishes terminal cleanup; it never resumes deletion.")
	fmt.Fprint(writer, "Type RECOVER to authorize the existing trusted helper: ")
	raw, err := readConfirmationLine(reader)
	if err != nil && err != io.EOF {
		return err
	}
	if err == io.EOF || strings.TrimSpace(raw) != "RECOVER" {
		fmt.Fprintln(writer, "Recovery cancelled. No changes made.")
		return nil
	}
	response, err := executeAuthorizedBootstrap(
		privilegedRequest{SchemaVersion: 1, Action: "recover"}, true, method)
	if err != nil {
		return err
	}
	showRecoveryOutcome(writer, response)
	return nil
}
