package main

// Real, unprivileged *read-only* inspection and planning. Unlike the existing
// UI demo this invokes the merged installer-api.sh from the source checkout.
// It does not invoke install-agent.sh, sudo, systemctl mutations or networking.
// It has no operation capable of writing system or agent files.

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
	"regexp"
	"strings"
	"sync"
	"time"

	"charm.land/huh/v2"
)

const maxAPIBytes = 32 * 1024

var safePythonPath = regexp.MustCompile(`^/[A-Za-z0-9_./+-]+$`)
var safeInterfaceName = regexp.MustCompile(`^[A-Za-z0-9_.-]{1,15}$`)

type apiCheck struct {
	ID     string `json:"id"`
	Status string `json:"status"`
}
type apiInspect struct {
	SchemaVersion int        `json:"schema_version"`
	Operation     string     `json:"operation"`
	Mode          string     `json:"mode"`
	Checks        []apiCheck `json:"checks"`
	Python        struct {
		SelectedInterpreter string `json:"selected_interpreter"`
		VersionSupported    bool   `json:"version_supported"`
	} `json:"python"`
	Avahi struct {
		ServicesDirectory string `json:"services_directory"`
		DaemonState       string `json:"daemon_state"`
	} `json:"avahi"`
	Installation struct {
		Detected            bool   `json:"detected"`
		ServiceFile         string `json:"service_file"`
		PowerDropin         string `json:"power_dropin"`
		AvahiServiceFile    string `json:"avahi_service_file"`
		AgentServiceState   string `json:"agent_service_state"`
		AgentServiceEnabled string `json:"agent_service_enabled"`
	} `json:"installation"`
	PrivilegedTransactionState string `json:"privileged_transaction_state"`
	IdentityPreserved          string `json:"identity_preserved"`
	SecretsIncluded            bool   `json:"secrets_included"`
}

type apiChange struct {
	Path   string `json:"path"`
	Action string `json:"action"`
}
type apiPlan struct {
	SchemaVersion              int         `json:"schema_version"`
	Operation                  string      `json:"operation"`
	Mode                       string      `json:"mode"`
	Changes                    []apiChange `json:"changes"`
	SelectedPython             string      `json:"selected_python"`
	PowerOption                string      `json:"power_option"`
	WOLInterfaceRequested      bool        `json:"wol_interface_requested"`
	PrivilegedTransactionState string      `json:"privileged_transaction_state"`
	RuntimeVerified            bool        `json:"runtime_verified"`
	ChangesApplied             bool        `json:"changes_applied"`
	SecretsIncluded            bool        `json:"secrets_included"`
}

type apiFailure struct {
	SchemaVersion int    `json:"schema_version"`
	Operation     string `json:"operation"`
	Mode          string `json:"mode"`
	Error         struct {
		Code string `json:"code"`
	} `json:"error"`
}

// No raw subprocess stderr, CLI input or unknown error descriptions are ever
// displayed: the Go UI recognizes only these stable backend error categories.
type apiError struct{ code string }

func (e apiError) Error() string { return "read-only backend: " + e.code }

func permittedError(code string) bool {
	switch code {
	case "invalid_argument", "unsafe_managed_path", "source_unavailable",
		"prerequisite_missing", "internal_error":
		return true
	default:
		return false
	}
}

type cappedBuffer struct{ bytes.Buffer }

func (b *cappedBuffer) Write(p []byte) (int, error) {
	if b.Len()+len(p) > maxAPIBytes {
		return 0, errors.New("read-only API response exceeded size limit")
	}
	return b.Buffer.Write(p)
}

type apiClient struct{ executable string }

func newAPIClient(path string) (apiClient, error) {
	if path == "" {
		return apiClient{}, errors.New("backend path required")
	}
	abs, err := filepath.Abs(path)
	if err != nil {
		return apiClient{}, errors.New("cannot resolve backend path")
	}
	info, err := os.Lstat(abs)
	if err != nil || !info.Mode().IsRegular() || info.Mode()&0o111 == 0 {
		return apiClient{}, errors.New("read-only backend is missing or not executable; supply a trusted launcher with -api")
	}
	// An explicitly selected launcher must not be writable by another user.
	// Never turn this source-checkout prototype into a privileged runner.
	if info.Mode().Perm()&0o022 != 0 {
		return apiClient{}, errors.New("read-only backend is group/world writable; choose a trusted -api launcher")
	}
	return apiClient{executable: abs}, nil
}

func (c apiClient) call(operation string, args ...string) ([]byte, error) {
	if operation != "inspect" && operation != "plan" {
		return nil, apiError{"invalid_argument"}
	}
	// The shell selector, Python selector, and bounded systemctl probes can
	// legitimately exceed 12 seconds in series on a slow Linux host.
	ctx, cancel := context.WithTimeout(context.Background(), 45*time.Second)
	defer cancel()
	command := exec.CommandContext(ctx, c.executable, append([]string{operation}, args...)...)
	// Prevent orphaned grandchildren holding stdout/stderr open indefinitely.
	command.WaitDelay = 2 * time.Second
	// Avoid Python import bytecode caches in the source tree during inspection.
	command.Env = append(os.Environ(), "PYTHONDONTWRITEBYTECODE=1")
	// The CLI receives no stdin; there can be no terminal/sudo prompt while
	// Bubble Tea owns the TTY. Arguments are never composed into a shell.
	var stdout, stderr cappedBuffer
	command.Stdout = &stdout
	command.Stderr = &stderr
	err := command.Run()
	if err != nil {
		if errors.Is(ctx.Err(), context.DeadlineExceeded) {
			return nil, apiError{"backend_timeout"}
		}
		if ctx.Err() != nil {
			return nil, apiError{"backend_unavailable"}
		}
		var reply apiFailure
		if json.Unmarshal(stderr.Bytes(), &reply) == nil &&
			reply.SchemaVersion == 1 && reply.Mode == "read_only" &&
			reply.Operation == operation && permittedError(reply.Error.Code) {
			return nil, apiError{reply.Error.Code}
		}
		return nil, apiError{"backend_unavailable"}
	}
	if stdout.Len() == 0 || stdout.Len() >= maxAPIBytes || stderr.Len() != 0 {
		return nil, apiError{"invalid_response"}
	}
	return stdout.Bytes(), nil
}

func readOneJSON(payload []byte, out any) error {
	decoder := json.NewDecoder(bytes.NewReader(payload))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(out); err != nil {
		return apiError{"invalid_response"}
	}
	var extra any
	if err := decoder.Decode(&extra); !errors.Is(err, io.EOF) {
		return apiError{"invalid_response"}
	}
	return nil
}

func (c apiClient) inspect() (apiInspect, error) {
	raw, err := c.call("inspect")
	if err != nil {
		return apiInspect{}, err
	}
	var value apiInspect
	if err := readOneJSON(raw, &value); err != nil {
		return apiInspect{}, err
	}
	if value.SchemaVersion != 1 || value.Operation != "inspect" || value.Mode != "read_only" ||
		value.SecretsIncluded || value.PrivilegedTransactionState != "unknown" ||
		value.IdentityPreserved != "not_verified" || len(value.Checks) == 0 || len(value.Checks) > 20 ||
		(value.Python.SelectedInterpreter != "" && !safePythonPath.MatchString(value.Python.SelectedInterpreter)) ||
		value.Python.VersionSupported != (value.Python.SelectedInterpreter != "") {
		return apiInspect{}, apiError{"invalid_response"}
	}
	for _, check := range value.Checks {
		switch check.Status {
		case "passed", "blocked", "warning", "not_verified":
		default:
			return apiInspect{}, apiError{"invalid_response"}
		}
		if !knownCheck(check.ID) {
			return apiInspect{}, apiError{"invalid_response"}
		}
	}
	if !fileState(value.Installation.ServiceFile) || !fileState(value.Installation.PowerDropin) ||
		!fileState(value.Installation.AvahiServiceFile) ||
		!serviceActivity(value.Installation.AgentServiceState) ||
		!serviceEnabled(value.Installation.AgentServiceEnabled) ||
		(value.Avahi.ServicesDirectory != "present" && value.Avahi.ServicesDirectory != "absent") ||
		!serviceActivity(value.Avahi.DaemonState) {
		return apiInspect{}, apiError{"invalid_response"}
	}
	return value, nil
}

func knownCheck(id string) bool {
	switch id {
	case "linux", "python_3_10_plus", "systemd_pid1", "tool_systemctl", "tool_useradd",
		"tool_getent", "tool_install", "tool_sed", "avahi_discovery",
		"managed_path_integrity", "managed_path_visibility":
		return true
	default:
		return false
	}
}
func fileState(s string) bool {
	return s == "present" || s == "absent" || s == "unsafe" || s == "unreadable"
}
func serviceActivity(s string) bool {
	switch s {
	case "active", "inactive", "failed", "activating", "deactivating", "unknown":
		return true
	}
	return false
}
func serviceEnabled(s string) bool {
	switch s {
	case "enabled", "disabled", "static", "indirect", "masked", "linked",
		"linked-runtime", "enabled-runtime", "alias", "generated", "transient", "unknown":
		return true
	}
	return false
}

var approvedPaths = map[string]bool{
	"/opt/linux-host-agent/linux_host_agent.py":                            true,
	"/opt/linux-host-agent/power_helper.py":                                true,
	"/etc/systemd/system/linux-host-agent.service":                         true,
	"/etc/systemd/system/linux-host-agent-power.service":                   true,
	"/etc/systemd/system/linux-host-agent-power.socket":                    true,
	"/etc/systemd/system/linux-host-agent.service.d/enable-power.conf":     true,
	"/etc/systemd/system/linux-host-agent.service.d/90-wol-interface.conf": true,
	"/etc/avahi/services/linux-host-agent.service":                         true,
}

type planOptions struct {
	power  string // "keep", "enabled", "disabled"
	wolNIC string // empty = retain current, non-empty = pin chosen interface
}

func (o planOptions) args() ([]string, error) {
	var result []string
	switch o.power {
	case "keep", "":
	case "enabled":
		result = append(result, "--enable-power")
	case "disabled":
		result = append(result, "--disable-power")
	default:
		return nil, apiError{"invalid_argument"}
	}
	if o.wolNIC != "" {
		if err := validNICName(o.wolNIC); err != nil {
			return nil, err
		}
		result = append(result, "--wol-interface", o.wolNIC)
	}
	return result, nil
}

func validNICName(name string) error {
	if !safeInterfaceName.MatchString(name) || name == "." || name == ".." {
		return apiError{"invalid_argument"}
	}
	// Not a hardware/WOL capability test; matching /sys is done in Python.
	return nil
}

// Huh's NIC error must not imply that the Python backend rejected input.
// This checks only the spelling; Python checks sysfs existence separately.
func validateNICInput(name string) error {
	if err := validNICName(name); err != nil {
		return errors.New("Enter an interface name (1–15 letters, digits, _, . or -; case-sensitive)")
	}
	return nil
}

func (c apiClient) plan(o planOptions) (apiPlan, error) {
	args, err := o.args()
	if err != nil {
		return apiPlan{}, err
	}
	raw, err := c.call("plan", args...)
	if err != nil {
		return apiPlan{}, err
	}
	var value apiPlan
	if err := readOneJSON(raw, &value); err != nil {
		return apiPlan{}, err
	}
	wantPower := "preserve"
	if o.power == "enabled" {
		wantPower = "enable"
	}
	if o.power == "disabled" {
		wantPower = "disable"
	}
	if value.SchemaVersion != 1 || value.Operation != "plan" ||
		value.Mode != "read_only" || value.SecretsIncluded || value.ChangesApplied ||
		value.RuntimeVerified || value.PrivilegedTransactionState != "unknown" ||
		!safePythonPath.MatchString(value.SelectedPython) ||
		value.PowerOption != wantPower || value.WOLInterfaceRequested != (o.wolNIC != "") ||
		len(value.Changes) == 0 || len(value.Changes) > len(approvedPaths) {
		return apiPlan{}, apiError{"invalid_response"}
	}
	seen := make(map[string]bool)
	for _, change := range value.Changes {
		if !approvedPaths[change.Path] || seen[change.Path] {
			return apiPlan{}, apiError{"invalid_response"}
		}
		seen[change.Path] = true
		switch change.Action {
		case "create", "replace", "remove", "unchanged":
		default:
			return apiPlan{}, apiError{"invalid_response"}
		}
	}
	return value, nil
}

func (s apiInspect) brief() string {
	var b strings.Builder
	fmt.Fprintln(&b, "REAL HOST — READ-ONLY INSPECTION")
	if s.Installation.Detected {
		fmt.Fprintf(&b, "Agent service file: present (existing installation)\n")
	} else {
		fmt.Fprintf(&b, "Agent service file: absent (new installation candidate)\n")
	}
	fmt.Fprintf(&b, "Agent active: %s; enabled: %s\n", s.Installation.AgentServiceState, s.Installation.AgentServiceEnabled)
	if s.Python.SelectedInterpreter == "" {
		fmt.Fprintln(&b, "Compatible Python: not found")
	} else {
		fmt.Fprintf(&b, "Compatible Python: %s\n", s.Python.SelectedInterpreter)
	}
	fmt.Fprintf(&b, "Avahi services directory: %s; daemon: %s\n", s.Avahi.ServicesDirectory, s.Avahi.DaemonState)
	for _, check := range s.Checks {
		fmt.Fprintf(&b, "%s: %s\n", check.ID, check.Status)
	}
	fmt.Fprintln(&b, "Privileged transaction/recovery status: UNKNOWN (not inspected)")
	fmt.Fprintln(&b, "Credentials/installation identity: not accessed or verified")
	return strings.TrimSpace(b.String())
}

func (p apiPlan) brief() string {
	var b strings.Builder
	fmt.Fprintln(&b, "REAL READ-ONLY FILE PLAN — NOTHING IS APPLIED")
	fmt.Fprintf(&b, "Interpreter: %s\n", p.SelectedPython)
	fmt.Fprintf(&b, "Power setting: %s\n", p.PowerOption)
	fmt.Fprintf(&b, "WOL interface pin requested: %t\n", p.WOLInterfaceRequested)
	for _, change := range p.Changes {
		fmt.Fprintf(&b, "%s: %s\n", change.Action, change.Path)
	}
	fmt.Fprintln(&b, "No runtime check, root recovery inspection or privileged action.")
	fmt.Fprintln(&b, "No WOL hardware configuration, firewall change, or hub discovery.")
	return strings.TrimSpace(b.String())
}

type liveSelection struct {
	api                apiClient
	inspection         apiInspect
	hubs               []discoveredHub
	hubChoice          string // skip, manual, or discovered:<literal IPv4>
	hubManual          string
	hubMu              sync.RWMutex // The Review description runs off the UI goroutine.
	hubConfirmedChoice string
	hubConfirmedManual string
	powerChoice        string
	wolChoice          string
	wolNIC             string
	finished           bool
	cacheMu            sync.Mutex // Huh invokes DescriptionFunc off the UI goroutine.
	cacheKey           string
	cached             apiPlan
	cacheErr           error
}

func (s *liveSelection) options() planOptions {
	nic := ""
	if s.wolChoice == "pin" {
		nic = s.wolNIC
	}
	return planOptions{power: s.powerChoice, wolNIC: nic}
}
func (s *liveSelection) currentPlan() (apiPlan, error) {
	// Huh runs the Review DescriptionFunc on a background command while the
	// Confirm Validate callback can run on the UI goroutine. Serialize the
	// entire lookup (including the subprocess) so neither sees partial state
	// or starts a duplicate plan. The UI inputs themselves remain Huh-owned.
	s.cacheMu.Lock()
	defer s.cacheMu.Unlock()
	options := s.options()
	key := options.power + "\x00" + options.wolNIC
	if s.cacheKey != key {
		plan, err := s.api.plan(options)
		s.cached, s.cacheErr, s.cacheKey = plan, err, key
	}
	return s.cached, s.cacheErr
}

// Huh writes its bound input fields on the UI goroutine. Only copy values
// into these protected, confirmed snapshots during the field's validation.
// The background Review description must never read the bound fields.
func (s *liveSelection) recordHubChoice(choice string) {
	s.hubMu.Lock()
	s.hubConfirmedChoice = choice
	s.hubMu.Unlock()
}
func (s *liveSelection) recordHubManual(ip string) {
	s.hubMu.Lock()
	s.hubConfirmedManual = ip
	s.hubMu.Unlock()
}
func (s *liveSelection) hubSnapshot() (choice, ip string) {
	s.hubMu.RLock()
	defer s.hubMu.RUnlock()
	return s.hubConfirmedChoice, s.hubConfirmedManual
}
func (s *liveSelection) selectedHub() string {
	choice, manual := s.hubSnapshot()
	switch {
	case choice == "manual":
		if validHubIPv4(manual) == nil {
			return manual + " (entered manually)"
		}
		return "Enter your hub's IP address"
	case strings.HasPrefix(choice, "discovered:"):
		ip := strings.TrimPrefix(choice, "discovered:")
		for _, hub := range s.hubs {
			if hub.IPv4 == ip {
				return ip + " (found automatically)"
			}
		}
	}
	return "I'll choose later"
}

func defaultHubChoice(hubs []discoveredHub) string {
	if len(hubs) != 0 {
		return "discovered:" + hubs[0].IPv4
	}
	return "manual"
}

func liveHubOptions(hubs []discoveredHub) []huh.Option[string] {
	options := []huh.Option[string]{}
	for _, hub := range hubs {
		if validHubIPv4(hub.IPv4) == nil {
			options = append(options, huh.NewOption("SmartThings hub at "+hub.IPv4+" (found)", "discovered:"+hub.IPv4))
		}
	}
	options = append(options,
		huh.NewOption("Enter my hub's IP address instead", "manual"),
		huh.NewOption("Choose a hub later", "skip"))
	return options
}

func livePowerOptions(info apiInspect) []huh.Option[string] {
	if info.Installation.PowerDropin == "present" {
		return []huh.Option[string]{
			huh.NewOption("Keep power control enabled (current setting)", "keep"),
			huh.NewOption("Turn power control off (monitor only)", "disabled"),
		}
	}
	return []huh.Option[string]{
		huh.NewOption("Monitor only — no shutdown or restart (recommended)", "keep"),
		huh.NewOption("Allow shutdown, restart and suspend from SmartThings", "enabled"),
	}
}

func (s *liveSelection) friendlyPower() string {
	switch s.powerChoice {
	case "enabled":
		return "Allow shutdown, restart and suspend (requires authentication)"
	case "disabled":
		return "Monitoring only (power control off)"
	default:
		if s.inspection.Installation.PowerDropin == "present" {
			return "Keep power control enabled (existing setting)"
		}
		return "Monitoring only (power control off)"
	}
}

func (s *liveSelection) inspectionSummary() string {
	var b strings.Builder
	if s.inspection.Installation.Detected {
		fmt.Fprintln(&b, "Computer Host LAN is already installed on this computer.")
		if s.inspection.Installation.AgentServiceState == "active" {
			fmt.Fprintln(&b, "The agent service is running.")
		} else {
			fmt.Fprintln(&b, "The agent is not confirmed running. Check its status before upgrading.")
		}
	} else {
		fmt.Fprintln(&b, "Get this Linux computer ready to use with SmartThings.")
	}
	blocked := false
	for _, check := range s.inspection.Checks {
		if check.Status == "blocked" {
			blocked = true
			break
		}
	}
	if blocked {
		fmt.Fprintln(&b, "A requirement needs attention. Run -live -preview for details.")
	} else {
		fmt.Fprintln(&b, "Basic Linux and Python checks are available in -live -preview.")
	}
	fmt.Fprint(&b, "This is an early PREVIEW: it will not install or change anything.")
	return b.String()
}

func (s *liveSelection) preview() string {
	p, err := s.currentPlan()
	if err != nil {
		return "Cannot prepare the preview: " + err.Error() +
			"\nNothing has been changed. Go Back to review your choices."
	}
	if p.SelectedPython != s.inspection.Python.SelectedInterpreter {
		return "Preview cannot continue because the Python environment changed. Start again."
	}
	var b strings.Builder
	fmt.Fprintln(&b, "Your SmartThings setup")
	fmt.Fprintln(&b, "  Hub:           "+s.selectedHub())
	fmt.Fprintln(&b, "  Power control: "+s.friendlyPower())
	if s.wolChoice == "pin" {
		fmt.Fprintf(&b, "  Network:       %s (advanced interface suggestion)\n", s.wolNIC)
	} else {
		fmt.Fprintln(&b, "  Network:       Leave existing settings unchanged")
	}
	fmt.Fprintln(&b, "")
	fmt.Fprintln(&b, "Preview only — your Linux agent, SmartThings devices and settings")
	fmt.Fprintln(&b, "will remain unchanged. No installation or pairing will happen.")
	return strings.TrimSpace(b.String())
}

func liveForm(s *liveSelection) *huh.Form {
	nicHelp := "Press Enter to accept the suggested interface or edit it. Does NOT enable Wake-on-LAN."
	if s.wolNIC == "" {
		nicHelp = "Enter your interface name (for example enp1s0f0). Does NOT enable Wake-on-LAN."
	}
	return huh.NewForm(
		huh.NewGroup(
			huh.NewSelect[string]().
				Title("Welcome to Computer Host LAN").
				Description(s.inspectionSummary()).
				Options(huh.NewOption("Continue", "continue")),
		).Title("1. Welcome"),
		huh.NewGroup(
			huh.NewSelect[string]().
				Title("Which SmartThings hub do you use?").
				Description("A hub found on your network is already selected. Press Enter to continue, or choose another.").
				Options(liveHubOptions(s.hubs)...).
				Validate(func(choice string) error {
					s.recordHubChoice(choice)
					return nil
				}).
				Value(&s.hubChoice),
		).Title("2. SmartThings hub"),
		huh.NewGroup(
			huh.NewInput().
				Title("SmartThings hub IP address").
				Description("Enter your hub's IPv4 address. You can find it in your router or SmartThings hub settings.").
				Placeholder("e.g. 192.168.1.20").
				Validate(func(value string) error {
					if err := validHubIPv4(value); err != nil {
						return err
					}
					s.recordHubManual(value)
					return nil
				}).
				Value(&s.hubManual),
		).Title("Hub address").WithHideFunc(func() bool { return s.hubChoice != "manual" }),
		huh.NewGroup(
			huh.NewSelect[string]().
				Title("What should SmartThings be allowed to do?").
				Description("Monitoring works without power control. Upgrades keep the current setting unless you change it.").
				Options(livePowerOptions(s.inspection)...).
				Value(&s.powerChoice),
			huh.NewSelect[string]().
				Title("Advanced network setup").
				Description("Most people should keep the default. Wake-on-LAN itself is not configured by this preview.").
				Options(
					huh.NewOption("Keep network settings unchanged (recommended)", "keep"),
					huh.NewOption("Review the wake-up network interface (advanced)", "pin"),
				).Value(&s.wolChoice),
		).Title("3. Power control"),
		huh.NewGroup(
			huh.NewInput().
				Title("Network interface (advanced)").
				Description(nicHelp).
				Placeholder("e.g. enp1s0f0").
				Validate(validateNICInput).
				Value(&s.wolNIC),
		).Title("Network details").WithHideFunc(func() bool { return s.wolChoice != "pin" }),
		huh.NewGroup(
			huh.NewConfirm().
				Title("Review your choices").
				DescriptionFunc(func() string { return s.preview() },
					[]any{&s.powerChoice, &s.wolChoice, &s.wolNIC, &s.hubChoice, &s.hubManual}).
				Affirmative("Finish preview").Negative("Exit without changes").
				Validate(func(accepted bool) error {
					if !accepted {
						return nil
					}
					plan, err := s.currentPlan()
					if err != nil {
						return errors.New("Unable to validate these choices. Go Back or cancel.")
					}
					if plan.SelectedPython != s.inspection.Python.SelectedInterpreter {
						return errors.New("Python changed since the initial check. Please restart.")
					}
					return nil
				}).Value(&s.finished),
		).Title("4. Review"),
	)
}

func newLiveSelection(api apiClient, info apiInspect, hubs []discoveredHub) *liveSelection {
	s := &liveSelection{
		api: api, inspection: info, hubs: hubs,
		hubChoice: defaultHubChoice(hubs),
		powerChoice: "keep", wolChoice: "keep",
	}
	s.recordHubChoice(s.hubChoice)
	if len(hubs) > 0 {
		s.wolNIC = suggestedNIC(hubs[0].IPv4)
	} else {
		s.wolNIC = suggestedNIC("")
	}
	return s
}

func runLiveInteractive(w io.Writer, api apiClient, info apiInspect) error {
	stat, err := os.Stdin.Stat()
	if err != nil || stat.Mode()&os.ModeCharDevice == 0 {
		return errors.New("The interactive setup requires a terminal. Try -live -accessible.")
	}
	s := newLiveSelection(api, info, discoverHubs())
	fmt.Fprintln(w, "COMPUTER HOST LAN — SETUP PREVIEW")
	fmt.Fprintln(w, "No installation or system changes will be made.")
	err = liveForm(s).Run()
	if errors.Is(err, huh.ErrUserAborted) {
		fmt.Fprintln(w, "Setup preview cancelled. No changes made.")
		return nil
	}
	if err != nil {
		return err
	}
	if s.finished {
		fmt.Fprintln(w, "\n"+s.preview())
		fmt.Fprintln(w, "SETUP PREVIEW COMPLETE — no changes made.")
	} else {
		fmt.Fprintln(w, "Exited without changes.")
	}
	return nil
}
func runLiveAccessible(reader io.Reader, writer io.Writer, api apiClient, info apiInspect) error {
	return runLiveAccessibleWithHubs(reader, writer, api, info, nil)
}

func runLiveAccessibleWithHubs(reader io.Reader, writer io.Writer, api apiClient, info apiInspect, hubs []discoveredHub) error {
	fmt.Fprintln(writer, "COMPUTER HOST LAN — LIVE READ-ONLY, ANSI-FREE MODE")
	fmt.Fprintln(writer, info.brief())
	fmt.Fprintln(writer, "No installation or configuration is possible here. Type back or quit.")
	s := liveSelection{api: api, inspection: info, hubs: hubs, hubChoice: "skip", powerChoice: "keep", wolChoice: "keep"}
	scanner := bufio.NewScanner(reader)
	step := 0
	for {
		switch step {
		case 0:
			fmt.Fprint(writer, "Power: [k] preserve (default), [y] request enable, [n] request disable: ")
		case 1:
			fmt.Fprint(writer, "WOL interface: [k] preserve (default), [p] preview pin: ")
		case 2:
			if s.wolChoice != "pin" {
				step++
				continue
			}
			fmt.Fprint(writer, "Existing NIC name (not WOL hardware validation): ")
		case 3:
			fmt.Fprintln(writer, "SmartThings hub selection (read-only; no hub connection):")
			for i, hub := range hubs {
				fmt.Fprintf(writer, "  [%d] Avahi candidate %s (unverified)\n", i+1, hub.IPv4)
			}
			fmt.Fprint(writer, "Hub: [k] skip (default), [m] enter IPv4 manually, or candidate number: ")
		case 4:
			if s.hubChoice != "manual" {
				step++
				continue
			}
			fmt.Fprint(writer, "SmartThings hub IPv4 (literal address, not contacted): ")
		case 5:
			fmt.Fprintln(writer, "\n"+s.preview())
			fmt.Fprint(writer, "Finish read-only review? [y/N]: ")
		}
		if !scanner.Scan() {
			if err := scanner.Err(); err != nil {
				return err
			}
			fmt.Fprintln(writer, "\nCancelled; no changes made.")
			return nil
		}
		rawInput := strings.TrimSpace(scanner.Text())
		input := strings.ToLower(rawInput)
		switch input {
		case "quit", "exit", "q":
			fmt.Fprintln(writer, "Cancelled; no changes made.")
			return nil
		case "back":
			if step > 0 {
				step--
			} else {
				fmt.Fprintln(writer, "Already at first step.")
			}
			if step == 4 && s.hubChoice != "manual" {
				step--
			}
			if step == 2 && s.wolChoice != "pin" {
				step--
			}
			continue
		}
		accepted := true
		switch step {
		case 0:
			switch input {
			case "", "k":
				s.powerChoice = "keep"
			case "y":
				s.powerChoice = "enabled"
			case "n":
				s.powerChoice = "disabled"
			default:
				accepted = false
			}
		case 1:
			switch input {
			case "", "k":
				s.wolChoice = "keep"
			case "p":
				s.wolChoice = "pin"
			default:
				accepted = false
			}
		case 2:
			if validNICName(rawInput) != nil {
				accepted = false
			} else {
				s.wolNIC = rawInput
			}
		case 3:
			switch input {
			case "", "k":
				s.hubChoice = "skip"
			case "m":
				s.hubChoice = "manual"
			default:
				index := -1
				if len(input) == 1 && input[0] >= '1' && input[0] <= '8' {
					index = int(input[0] - '1')
				}
				if index < 0 || index >= len(hubs) {
					accepted = false
				} else {
					s.hubChoice = "discovered:" + hubs[index].IPv4
				}
			}
		case 4:
			if validHubIPv4(rawInput) != nil {
				accepted = false
			} else {
				s.hubManual = rawInput
			}
		case 5:
			if input != "y" && input != "n" && input != "" {
				accepted = false
				break
			}
			if input == "y" {
				plan, err := s.currentPlan()
				if err != nil || plan.SelectedPython != s.inspection.Python.SelectedInterpreter {
					fmt.Fprintln(writer, "Cannot finish: read-only plan invalid or unavailable. Type back to change options, or quit.")
					continue
				}
				fmt.Fprintln(writer, "READ-ONLY REVIEW COMPLETE — nothing installed or modified.")
			} else {
				fmt.Fprintln(writer, "Exited; no changes made.")
			}
			return nil
		}
		if !accepted {
			fmt.Fprintln(writer, "Invalid option. Try again.")
			continue
		}
		// Maintain the same immutable review snapshots as full-screen Huh.
		if step == 3 {
			s.recordHubChoice(s.hubChoice)
		} else if step == 4 {
			s.recordHubManual(s.hubManual)
		}
		step++
	}
}

func runLive(preview, accessible bool, apiPath string, r io.Reader, w io.Writer) error {
	client, err := newAPIClient(apiPath)
	if err != nil {
		return err
	}
	info, err := client.inspect()
	if err != nil {
		return err
	}
	if preview {
		fmt.Fprintln(w, info.brief())
		plan, err := client.plan(planOptions{power: "keep"})
		if err != nil {
			return err
		}
		if plan.SelectedPython != info.Python.SelectedInterpreter {
			return apiError{"invalid_response"}
		}
		fmt.Fprintln(w, "\n"+plan.brief())
		return nil
	}
	if accessible {
		return runLiveAccessibleWithHubs(r, w, client, info, discoverHubs())
	}
	return runLiveInteractive(w, client, info)
}
