package main

import (
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
	Firewalld          string `json:"firewalld"`
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

func (s *liveSelection) networkWarnings(completed bool) []string {
	var warnings []string
	observed := observeNetwork(s.inspection, s.firewalldActive)
	if observed.AvahiPrerequisites != "passed" {
		timing := "Install and start Avahi if needed before installing the agent.\n" +
			"After installation, check the advertisement:"
		if completed {
			timing = "If Avahi is missing or stopped, install or start it as needed.\n" +
				"Now check the advertisement:"
		}
		warnings = append(warnings,
			"Avahi discovery is not confirmed.\n"+
				"SmartThings Scan nearby may not find this computer.\n"+
				"Check: systemctl is-active avahi-daemon.service\n"+
				timing+"\n"+
				"  avahi-browse -rt _computerhost._tcp\n"+
				"Install the Avahi browsing tool if missing.\n"+
				"If Avahi was installed later, rerun the verified installer\n"+
				"to add the managed service advertisement (resolve pending recovery first).")
	}
	if observed.Firewalld == "active" {
		warnings = append(warnings,
			"firewalld is active. Incoming TCP 8765 may be blocked for the hub\n"+
				"(use your configured agent port if different).\n"+
				"As administrator, inspect:\n"+
				"  firewall-cmd --get-active-zones\n"+
				"  firewall-cmd --zone=ZONE --list-all\n"+
				"(replace ZONE with the hub-facing zone).\n"+
				"Allow the agent port only from the trusted hub as needed.\n"+
				"Check local mDNS (UDP 5353) separately.\n"+
				"Do not disable the firewall or open the agent port to all sources.\n"+
				"This wizard has not changed firewall rules.")
	}
	return warnings
}

func (s *liveSelection) showNetworkWarnings(w io.Writer) {
	for _, warning := range s.networkWarnings(true) {
		fmt.Fprintln(w, "WARNING:", warning)
	}
}

func (s *liveSelection) installationSummary() string {
	summary := s.inspectionSummary()
	if s.requestedAction == "repair" {
		summary += "\nRepair reinstalls the bundled agent version, retaining identity and key."
	}
	return strings.Replace(summary,
		"This is an early PREVIEW: it will not install or change anything.",
		"Installation is available after explicit review and administrator authorization.", 1)
}

func (s *liveSelection) installPreview() string {
	preview := s.preview()
	preview = strings.Replace(preview,
		"Preview only — your Linux agent, SmartThings devices and settings\nwill remain unchanged. No installation or pairing will happen.",
		"After confirmation, the wizard will request administrator permission\nand install or upgrade the Linux agent. No SmartThings pairing or firewall\nchanges will happen automatically.", 1)
	if s.requestedAction == "repair" {
		preview = "Action: Repair using the bundled agent version\n\n" + preview
	} else if s.requestedAction == "upgrade" {
		preview = "Action: Install the bundled agent version (upgrade or configuration change)\n\n" + preview
	}
	for _, warning := range s.networkWarnings(false) {
		preview += "\n\nWARNING: " + warning
	}
	return preview
}

const retainedReuseNotice = "Retained installation data found. If this is your previous Computer Host LAN v2 installation, reuse its identity and control key to keep your SmartThings device. Root will check the retained files and v2 backup; nothing is reset. Type REUSE only if you recognize this installation."

func (s *liveSelection) installConfirmation() string {
	plan, err := s.currentPlan()
	if err == nil && plan.RetainedStateCandidate {
		return "REUSE"
	}
	return "INSTALL"
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
	if s.requestedAction != "" {
		if s.requestedAction != action && !(s.requestedAction == "repair" && action == "upgrade") {
			return privilegedRequest{}, errors.New("installation state changed; start setup again")
		}
		action = s.requestedAction
	}
	power := "preserve"
	if s.powerChoice == "enabled" {
		power = "enable"
	} else if s.powerChoice == "disabled" {
		power = "disable"
	}
	var nic *string
	if !plan.WOLPreviewSkipped && (s.wolChoice == "pin" || s.wolChoice == "configure") {
		if err := validNICName(s.wolNIC); err != nil {
			return privilegedRequest{}, errors.New("invalid network interface")
		}
		value := s.wolNIC
		nic = &value
	}
	request := privilegedRequest{
		SchemaVersion: 1, Action: action, Power: power, WOLInterface: nic,
		ReuseRetained: plan.RetainedStateCandidate,
	}
	if s.wolChoice == "configure" && !plan.WOLPreviewSkipped {
		if plan.WOLPolicy == nil || !plan.WOLPolicy.valid(s.wolNIC) {
			return privilegedRequest{}, errors.New("persistent WOL policy could not be reviewed; choose Keep or configure manually")
		}
		request.WOLPlanDigest = plan.WOLPolicy.Digest
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
	case "restored", "restored_cleanup_required":
		if action != "restore" || reply.IdentityPreserved != "verified" || reply.CredentialContinuity != "verified" {
			return privilegedResult{}, errors.New("invalid historical restore outcome")
		}
	case "uninstalled", "uninstalled_cleanup_required":
		if action != "uninstall" {
			return privilegedResult{}, errors.New("unexpected uninstall outcome")
		}
		if reply.IdentityPreserved != "verified" && reply.IdentityPreserved != "not_verified" {
			return privilegedResult{}, errors.New("invalid uninstall identity outcome")
		}
	case "passed":
		if action != "status" && action != "recover" && action != "wol-check" && action != "wol-remove" && action != "backups" {
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
	case "", "install", "upgrade", "repair", "uninstall", "restore":
	default:
		return privilegedResult{}, errors.New("invalid recovery operation")
	}
	if reply.RecoveryOperation != "" && (action != "recover" || reply.Status != "passed" ||
		reply.RecoveryStatus == "" || reply.RecoveryStatus == "nothing_to_recover") {
		return privilegedResult{}, errors.New("unexpected recovery operation")
	}
	if !validBackupReply(reply, action) {
		return privilegedResult{}, errors.New("invalid backup list")
	}
	if !validWOLStatus(reply, action) {
		return privilegedResult{}, errors.New("invalid WOL outcome")
	}
	if reply.WOLReviewRequired && !((action == "recover" && reply.Status == "passed" && reply.RecoveryStatus == "rolled_back") ||
		(action != "status" && action != "recover" && reply.Status == "error" && reply.ErrorCode == "rolled_back")) {
		return privilegedResult{}, errors.New("unexpected WOL review outcome")
	}
	if !validateContinuityReply(&reply, action) {
		return privilegedResult{}, errors.New("invalid credential continuity outcome")
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
		"unsafe_lock", "not_installed", "recovery_helper_missing", "wol_review_required", "invalid_backup":
		return true
	}
	return false
}

func userFacingPrivilegeFailure(reply privilegedResult) error {
	if reply.ContinuityReason == "credential_continuity_unverified" {
		if reply.ErrorCode == "aborted" {
			return errors.New("credential continuity could not be verified before applying changes; ask an administrator to inspect the retained credential layout, ownership, permissions and hard links before retrying. Do not delete or reset credentials")
		}
		return errors.New("credential continuity could not be verified; preserve retained private state and recovery evidence. Run -recover for managed-state recovery; it cannot verify continuity with the interrupted transaction")
	}
	switch reply.ErrorCode {
	case "invalid_backup":
		return errors.New("the selected local backup is unavailable, changed or unsuitable. List backups again; do not edit the backup or retained credentials")
	case "wol_review_required":
		return errors.New("Wake-on-LAN ownership or network policy needs review. Open Configure (-configure) to check or remove the installer setting; existing administrator configuration is not overwritten")
	case "installation_busy":
		return errors.New("another installation or recovery is in progress. Finish that operation before retrying")
	case "unsafe_lock":
		return errors.New("an installer lock is unsafe. After confirming no installation or recovery is running, ask an administrator to inspect /run/lock/linux-host-agent-install.lock and /run/computer-host-lan/bootstrap.lock; do not delete lock files during an active installation")
	case "rolled_back":
		if reply.WOLReviewRequired {
			return errors.New("previous agent files and service state were restored. The Wake-on-LAN setting needs a manual check; open Configure (-configure) to check or remove the installer setting. Do not repeat recovery for WOL alone")
		}
		if reply.Operation == "restore" {
			return errors.New("historical restore was undone; previous files and service state were restored")
		}
		if reply.Operation == "uninstall" {
			return errors.New("uninstall was undone; previous files and service state were restored. Check prerequisites and run -uninstall again if desired")
		}
		return errors.New("installation could not complete; previous files and service state were restored. Check prerequisites and retry")
	case "recovery_helper_missing":
		return errors.New("the recovery helper is missing and protected transaction evidence may remain. Preserve the journal and staging directories; seek help obtaining a verified compatible recovery helper before retrying")
	case "recovery_required":
		return errors.New("installer transaction requires recovery. Run this wizard with -recover before retrying; preserve the protected journal and backup")
	case "adoption_required":
		return errors.New("Retained state could not be approved for reuse. Preserve the identity, control key and backups. " +
			"Reuse requires explicit consent, intact private files, a valid v2 backup and stopped services. Do not delete the state.")
	case "unsupported_python":
		return errors.New("a system Python 3.10 or newer is required; install a compatible interpreter without changing the system default")
	case "not_installed":
		return errors.New("no installed Linux agent was found; nothing to uninstall. Retained state and recovery files have not been removed")
	case "unsupported_environment":
		return errors.New("the existing installation or operating environment needs attention. Check the read-only inspection before retrying")
	case "aborted":
		if reply.Operation == "restore" {
			return errors.New("historical restore was aborted before applying changes; check the current installation and selected backup")
		}
		if reply.Operation == "uninstall" {
			return errors.New("uninstall was aborted before applying changes; inspect the existing installation and snapshot prerequisites before retrying")
		}
		switch reply.FailureStage {
		case "payload":
			return errors.New("installation aborted before applying changes (payload verification/staging); check protected payload staging prerequisites")
		case "existing_state":
			return errors.New("installation aborted before applying changes (existing agent/service state); inspect service and protected identity prerequisites")
		case "plan":
			return errors.New("installation aborted before applying changes (installation plan); inspect managed paths, systemd templates or Wake-on-LAN policy. Choose Keep to install without changing WOL, or use Configure (-configure) to check/remove an existing installer setting first")
		case "snapshot":
			return errors.New("installation aborted before applying changes (backup snapshot); inspect the existing backup directory and available storage")
		default:
			return errors.New("installation was aborted safely before applying changes; inspect prerequisites before retrying")
		}
	case "untrusted_root_launcher", "invalid_trusted_manifest":
		return errors.New("the privileged launcher did not pass the protected handoff or embedded manifest check; obtain a verified installer and run it as an ordinary user. Do not invoke the internal -root-bootstrap mode directly")
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
	snapshot, err := snapshotRunningExecutable()
	if err != nil {
		return privilegedResult{}, &authorizationUnavailableError{cause: err}
	}
	defer snapshot.cleanup()
	python, err := trustedSystemPython()
	if err != nil {
		return privilegedResult{}, &authorizationUnavailableError{cause: errors.New("a root-owned, non-writable Python 3.10+ interpreter is required for protected privilege handoff")}
	}
	elevate, err := chooseElevationCommand(python, snapshot.directory, snapshot.digest,
		os.Getuid(), interactive, payload, method, isExecutableFile)
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
		if result.ErrorCode == "rolled_back" {
			showCredentialContinuity(w, result)
		}
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

// Print instructions only. Reading or displaying the secret remains an explicit
// administrator action outside the wizard and its result protocol.
func showPowerKeyInstructions(w io.Writer) {
	fmt.Fprintln(w, "If you need the control key, read it privately as administrator on this computer:")
	fmt.Fprintln(w, "  sudo cat /var/lib/linux-host-agent/control-token")
	fmt.Fprintln(w, "  or: run0 cat /var/lib/linux-host-agent/control-token")
	fmt.Fprintln(w, "  or: su -c 'cat /var/lib/linux-host-agent/control-token' (requires the root password)")
	fmt.Fprintln(w, "Use a private terminal; do not record, screenshot, log or share the output.")
	fmt.Fprintln(w, "In the SmartThings device settings, enter the 64-character value in Power control key (64 hex chars) [controlKey] and turn on Enable shutdown/reboot/suspend (allowPowerCommands).")
}

func showInstallationOutcome(w io.Writer, s *liveSelection, req privilegedRequest, result privilegedResult) {
	fmt.Fprintln(w, "\nComputer Host LAN:", result.Status)
	showCredentialContinuity(w, result)
	if onboardingMode(result) == "check_existing_device" {
		fmt.Fprintln(w, "Existing agent identity verified.")
		fmt.Fprintln(w, "Open your existing SmartThings computer device and refresh it first. Rediscovery is normally unnecessary.")
		fmt.Fprintln(w, "Only if no device is registered, install the Computer Host LAN Edge driver if needed, then Add device → Scan nearby.")
	} else {
		if req.Action == "install" {
			fmt.Fprintln(w, "New agent installation completed; no previous identity was verified.")
		} else {
			fmt.Fprintln(w, "Previous agent identity was not verified.")
		}
		fmt.Fprintln(w, "If you already have a SmartThings computer device, check and refresh it first.")
		fmt.Fprintln(w, "For first-time onboarding, install the Computer Host LAN Edge driver, then Add device → Scan nearby.")
	}
	fmt.Fprintln(w, "If you need the Edge driver, enroll your hub using the channel invitation:")
	fmt.Fprintln(w, "  https://bestow-regional.api.smartthings.com/invite/1J2Qy7ZkxL20")
	fmt.Fprintln(w, "Keep the hub and computer on a trusted private LAN; allow incoming TCP 8765 (or your configured agent port) from the hub and mDNS where needed. Never forward the agent port to the Internet.")
	s.showNetworkWarnings(w)
	fmt.Fprintln(w, "These are pre-install observations, not proof of discovery or connectivity. If warnings appear above, recheck those conditions before relying on Scan nearby.")
	fmt.Fprintln(w, "Automatic hub pairing and firewall changes were not performed.")
	if result.WOLStatus == "unsupported" {
		fmt.Fprintln(w, "Wake-on-LAN is not supported by this adapter; the agent is installed without configuring it.")
	} else if result.WOLStatus == "capability_unknown" {
		fmt.Fprintln(w, "Wake-on-LAN could not be checked. The agent is installed without configuring it. Install ethtool if missing, then run the installer again and choose Configure.")
	} else if req.WOLPlanDigest != "" {
		fmt.Fprintln(w, "Persistent WOL configuration was verified for the selected wired interface. Enable WOL in BIOS/UEFI. Test: shut down from SmartThings, then switch on again. Reboot and repeat the test.")
		fmt.Fprintln(w, "Wi-Fi and routed-subnet WOL are not supported by this setup.")
	} else {
		fmt.Fprintln(w, "Persistent WOL configuration was left unchanged.")
	}
	switch req.Power {
	case "enable":
		fmt.Fprintln(w, "For remote power, turn on Enable shutdown/reboot/suspend (allowPowerCommands) and configure Power control key (64 hex chars) [controlKey] in the SmartThings device if needed.")
		fmt.Fprintln(w, "If the retained control key is unchanged and already configured, no key update is normally needed. Identity verification alone does not verify key equality.")
		fmt.Fprintln(w, "The control key is not shown here.")
		showPowerKeyInstructions(w)
	case "preserve":
		fmt.Fprintln(w, "Current/default power choice was retained. If remote power is enabled, an unchanged and already configured control key normally needs no update.")
		fmt.Fprintln(w, "Only if power is already enabled and the key is needed, use the following instructions:")
		showPowerKeyInstructions(w)
	case "disable":
		fmt.Fprintln(w, "Remote power was disabled on the computer; no control key setup is needed for monitoring.")
	}
	if result.Status == "installed_cleanup_required" {
		fmt.Fprintln(w, "Installation committed, but helper cleanup is pending. Run -recover before another installation.")
	}
}

func runInstallingWizard(accessible bool, apiPath string, reader io.Reader, writer io.Writer, method string) error {
	return runInstallingWizardMode(accessible, apiPath, reader, writer, method, false, "")
}

func runInstallingWizardMode(accessible bool, apiPath string, reader io.Reader, writer io.Writer, method string, startMenu bool, action string) error {
	if os.Geteuid() == 0 {
		return errors.New("run the wizard as your normal user; sudo is requested only after review")
	}
	if !accessible && !stdinIsTerminal() {
		return errors.New("interactive installation needs a terminal; use -accessible")
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
	if startMenu && maintenanceNeeded(info) {
		return runMaintenancePresentation(accessible, reader, writer, info, func(choice string) error {
			return dispatchMaintenance(choice, accessible, apiPath, reader, writer, method, info)
		})
	}
	if action != "" && ((action == "install") == info.Installation.Detected) {
		return errors.New("installation state changed; start setup again")
	}
	hubs := discoverHubs()
	s := newLiveSelection(api, info, hubs)
	s.requestedAction = action
	if accessible {
		// The plain-text form includes a literal INSTALL confirmation on
		// its final page; no extra raw-terminal/sudo prompt is mixed in.
		// Accessible/plain-text mode can still run inside a real terminal.
		// Only use sudo -n when there is no TTY; otherwise allow sudo's
		// usual /dev/tty password prompt after the plain form completes.
		hasTTY := stdinIsTerminal()
		return runLiveAccessibleSelection(reader, writer, s,
			true, func(s *liveSelection) error {
				return installSelection(s, writer, hasTTY, method)
			})
	}
	s.firewalldActive = firewalldRunning()
	if detailTerminal(accessible, reader, writer) {
		accepted, err := runInstallConsentWizard(s)
		if err != nil {
			return err
		}
		if !accepted {
			fmt.Fprintln(writer, "Cancelled. No changes made.")
			return nil
		}
		// Native terminal ownership has been restored; no input is
		// forwarded from the confirmation editor to the provider.
		return installSelection(s, writer, true, method)
	}
	fmt.Fprintln(writer, "COMPUTER HOST LAN — LINUX INSTALLATION")
	fmt.Fprintln(writer, "The agent will not be changed until you approve the final confirmation.")
	if err := runStyledLiveWizard(s, true); err != nil {
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
	// The form runner has exited and restored the normal terminal.
	fmt.Fprintf(writer, "\nType %s to authorize system changes (anything else cancels): ", s.installConfirmation())
	line, err := readConfirmationLine(reader)
	if err != nil && err != io.EOF {
		return err
	}
	if err == io.EOF || strings.TrimSpace(line) != s.installConfirmation() {
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

// Plain fallback preserves the complete original review and literal consent.
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
	return executeConfirmedUninstall(writer, authorize)
}

func executeConfirmedUninstall(writer io.Writer, authorize func(privilegedRequest) (privilegedResult, error)) error {
	fmt.Fprintln(writer, "Authorizing uninstall. This can take several minutes.")
	reply, err := authorize(privilegedRequest{SchemaVersion: 2, Action: "uninstall"})
	if err != nil {
		if reply.ErrorCode == "rolled_back" {
			showCredentialContinuity(writer, reply)
		}
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
	showCredentialContinuity(writer, reply)
	fmt.Fprintln(writer, "Private state, recovery snapshots and the recovery helper are retained.")
	fmt.Fprintln(writer, "The SmartThings device is not automatically removed.")
	return nil
}

func runUninstallWizard(reader io.Reader, writer io.Writer, method string) error {
	return runUninstallPresentation(false, reader, writer, method)
}

func runUninstallPresentation(accessible bool, reader io.Reader, writer io.Writer, method string) error {
	if os.Geteuid() == 0 {
		return errors.New("run the wizard as your normal user; administrator authorization follows confirmation")
	}
	if !stdinIsTerminal() {
		return errors.New("interactive uninstall needs a terminal")
	}
	visual := detailTerminal(accessible, reader, writer)
	removed := false
	authorize := func(request privilegedRequest) (privilegedResult, error) {
		result, err := executeAuthorizedBootstrap(request, true, method)
		removed = err == nil && result.Status == "uninstalled"
		return result, err
	}
	var err error
	if visual {
		screen := uninstallScreen()
		screen.frame.monochrome = os.Getenv("NO_COLOR") != ""
		proceed, reviewErr := runOperationConsent(screen, "UNINSTALL")
		if reviewErr != nil {
			return reviewErr
		}
		if !proceed {
			fmt.Fprintln(writer, "Uninstall cancelled. No changes made.")
			return nil
		}
		err = executeConfirmedUninstall(writer, authorize)
	} else {
		err = confirmUninstall(reader, writer, authorize)
	}
	if err != nil || !removed {
		return err
	}
	fmt.Fprint(writer, "Also remove the Wake-on-LAN setting this installer made? [y/N]: ")
	answer, err := readConfirmationLine(reader)
	if err != nil || !strings.EqualFold(strings.TrimSpace(answer), "y") {
		return nil
	}
	if err := runWOLManagement(reader, writer, method, true); err != nil {
		fmt.Fprintln(writer, "Agent uninstalled. WOL removal was not completed:", err)
	}
	return nil
}

func showRecoveryOutcome(writer io.Writer, response privilegedResult) {
	fmt.Fprintln(writer, "Recovery outcome:", response.RecoveryStatus)
	showCredentialContinuity(writer, response)
	if response.WOLReviewRequired {
		fmt.Fprintln(writer, "The agent was restored. The Wake-on-LAN setting needs a manual check; open Configure (-configure) to check or remove the installer setting. Do not repeat recovery for WOL alone.")
	}
	switch response.RecoveryStatus {
	case "nothing_to_recover":
		fmt.Fprintln(writer, "No protected transaction needs recovery.")
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
	return runRecoveryPresentation(false, reader, writer, method)
}

func runRecoveryPresentation(accessible bool, reader io.Reader, writer io.Writer, method string) error {
	if os.Geteuid() == 0 {
		return errors.New("run the wizard as your normal user; sudo is requested after confirmation")
	}
	if !stdinIsTerminal() {
		return errors.New("interactive recovery needs a terminal")
	}
	authorize := func(request privilegedRequest) (privilegedResult, error) {
		return executeAuthorizedBootstrap(request, true, method)
	}
	if detailTerminal(accessible, reader, writer) {
		screen := recoveryScreen()
		screen.frame.monochrome = os.Getenv("NO_COLOR") != ""
		proceed, err := runOperationConsent(screen, "RECOVER")
		if err != nil {
			return err
		}
		if !proceed {
			fmt.Fprintln(writer, "Recovery cancelled. No changes made.")
			return nil
		}
		return executeConfirmedRecovery(writer, authorize)
	}
	return confirmRecovery(reader, writer, authorize)
}

func confirmRecovery(reader io.Reader, writer io.Writer, authorize func(privilegedRequest) (privilegedResult, error)) error {
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
	return executeConfirmedRecovery(writer, authorize)
}

func executeConfirmedRecovery(writer io.Writer, authorize func(privilegedRequest) (privilegedResult, error)) error {
	response, err := authorize(privilegedRequest{SchemaVersion: 1, Action: "recover"})
	if err != nil {
		return err
	}
	showRecoveryOutcome(writer, response)
	return nil
}
