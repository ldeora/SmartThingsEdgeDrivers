package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"strings"
)

const cliUsage = `Computer Host LAN — noninteractive installer (development only)

Usage:
  installer cli plan --action install|upgrade|repair [--power preserve|enable|disable] [--wol-interface IFNAME]
  installer cli install   --confirm INSTALL   [--power preserve|enable|disable] [--wol-interface IFNAME] [--elevation auto|sudo|doas|run0]
  installer cli upgrade   --confirm UPGRADE   [same options]
  installer cli repair    --confirm REPAIR    [same options]
  installer cli uninstall --confirm UNINSTALL [--elevation auto|sudo|doas|run0]
  installer cli recover   --confirm RECOVER   [--elevation auto|sudo|doas|run0]
  installer cli status                         [--elevation auto|sudo|doas|run0]

Plan is unprivileged and never requests authorization. For other commands,
run as an ordinary user with preauthorized administrator access; no password
prompts or provider retries. No hub discovery, pairing, firewall or persistent
WOL configuration. Status/recovery use the existing protected helper.
Use an independently authenticated executable for any eventual release.
Except for --help, stdout contains a single JSON result.
Exit: 0 completed, 1 failed/unknown, 2 invalid invocation,
      3 outstanding transaction or cleanup required.
`

type cliOptions struct {
	action    string
	target    string
	power     string
	nic       string
	elevation string
}

func (o cliOptions) isInstall() bool {
	return o.action == "install" || o.action == "upgrade" || o.action == "repair"
}

// No flag aliases, implicit confirmation, repeated options, positional
// arguments or option-value guessing. Each option consumes exactly one value.
func parseCLI(args []string) (cliOptions, error) {
	o := cliOptions{power: "preserve", elevation: "auto"}
	invalid := errors.New("invalid CLI invocation")
	if len(args) == 0 {
		return cliOptions{}, invalid
	}
	o.action = args[0]
	switch o.action {
	case "install", "upgrade", "repair", "uninstall", "recover", "status", "plan":
	default:
		return cliOptions{}, invalid
	}
	seen := make(map[string]bool)
	confirm := ""
	for i := 1; i < len(args); i += 2 {
		name := args[i]
		if seen[name] || i+1 >= len(args) {
			return cliOptions{}, invalid
		}
		seen[name] = true
		value := args[i+1]
		switch name {
		case "--confirm":
			confirm = value
		case "--action":
			if o.action != "plan" || (value != "install" && value != "upgrade" && value != "repair") {
				return cliOptions{}, invalid
			}
			o.target = value
		case "--elevation":
			if o.action == "plan" {
				return cliOptions{}, invalid
			}
			switch value {
			case "auto", "sudo", "doas", "run0":
				o.elevation = value
			default:
				return cliOptions{}, invalid
			}
		case "--power":
			if (!o.isInstall() && o.action != "plan") || (value != "preserve" && value != "enable" && value != "disable") {
				return cliOptions{}, invalid
			}
			o.power = value
		case "--wol-interface":
			if (!o.isInstall() && o.action != "plan") || validNICName(value) != nil {
				return cliOptions{}, invalid
			}
			o.nic = value
		default:
			return cliOptions{}, invalid
		}
	}
	if o.action == "plan" {
		if !seen["--action"] || seen["--confirm"] {
			return cliOptions{}, invalid
		}
	} else if o.action == "status" {
		if seen["--confirm"] {
			return cliOptions{}, invalid
		}
	} else if !seen["--confirm"] || confirm != strings.ToUpper(o.action) {
		return cliOptions{}, invalid
	}
	return o, nil
}

// Reuse the interactive installer's exact read-only preflight and request
// validation, without constructing a wizard or browsing for hub candidates.
// The explicit operation is never silently converted into another action.
func cliInstallRequest(o cliOptions, api apiClient, info apiInspect) (privilegedRequest, error) {
	prepared, err := cliInstallPreflight(o, api, info, false)
	return prepared.request, err
}

type cliPrepared struct {
	request privilegedRequest
	plan    *apiPlan
	network *networkObservation
	checks  []apiCheck
}

type cliResult struct {
	privilegedResult
	PlannedAction string              `json:"planned_action,omitempty"`
	Plan          *apiPlan            `json:"plan,omitempty"`
	Network       *networkObservation `json:"preflight_network,omitempty"`
	Onboarding    string              `json:"onboarding,omitempty"`
	Checks        []apiCheck          `json:"checks,omitempty"`
}

// Copy only the fixed inspector enums. Never expose a raw diagnostic,
// even if the plan call fails before approvedRootRequest checks prerequisites.
func preflightChecks(info apiInspect) []apiCheck {
	if len(info.Checks) == 0 || len(info.Checks) > 20 {
		return nil
	}
	checks := make([]apiCheck, 0, len(info.Checks))
	for _, check := range info.Checks {
		if !knownCheck(check.ID) {
			return nil
		}
		switch check.Status {
		case "passed", "blocked", "warning", "not_verified":
			checks = append(checks, check)
		default:
			return nil
		}
	}
	return checks
}

func cliInstallPreflight(o cliOptions, api apiClient, info apiInspect, firewallActive bool) (cliPrepared, error) {
	prepared := cliPrepared{checks: preflightChecks(info)}
	if len(prepared.checks) == 0 {
		return prepared, errors.New("invalid preflight checks")
	}
	if o.action == "plan" {
		o.action = o.target
	}
	if !o.isInstall() || (o.action == "install") == info.Installation.Detected {
		return prepared, errors.New("requested action does not match observed installation")
	}
	s := &liveSelection{
		api: api, inspection: info, powerChoice: "keep", wolChoice: "keep",
	}
	switch o.power {
	case "enable":
		s.powerChoice = "enabled"
	case "disable":
		s.powerChoice = "disabled"
	case "preserve":
	default:
		return prepared, errors.New("invalid power setting")
	}
	if o.nic != "" {
		s.wolChoice, s.wolNIC = "pin", o.nic
	}
	req, err := approvedRootRequest(s)
	if err != nil {
		return prepared, err
	}
	if o.action == "repair" && req.Action == "upgrade" {
		req.Action = "repair"
	}
	if req.Action != o.action {
		return prepared, errors.New("requested action mismatch")
	}
	if err := req.validate(); err != nil {
		return prepared, err
	}
	plan, err := s.currentPlan()
	if err != nil {
		return prepared, err
	}
	network := observeNetwork(info, firewallActive)
	prepared.request, prepared.plan, prepared.network = req, &plan, &network
	return prepared, nil
}

func prepareCLIRequest(o cliOptions) (cliPrepared, error) {
	if !o.isInstall() && o.action != "plan" {
		version := 1
		if o.action == "uninstall" {
			version = 2
		}
		req := privilegedRequest{SchemaVersion: version, Action: o.action}
		return cliPrepared{request: req}, req.validate()
	}
	path, cleanup, err := makeEmbeddedReadOnlyAPI()
	if err != nil {
		return cliPrepared{}, err
	}
	defer cleanup()
	api, err := newAPIClient(path)
	if err != nil {
		return cliPrepared{}, err
	}
	info, err := api.inspect()
	if err != nil {
		return cliPrepared{}, err
	}
	return cliInstallPreflight(o, api, info, firewalldRunning())
}

func cliFailure(action, code string) cliResult {
	return cliResult{privilegedResult: privilegedResult{
		SchemaVersion: 1, Operation: action, Status: "error", ErrorCode: code,
	}}
}

// Dependency injection is only for unprivileged tests. The real entry
// always uses the embedded inspector and existing authorized bootstrap.
func executeCLI(args []string, root bool,
	prepare func(cliOptions) (cliPrepared, error),
	authorize func(privilegedRequest, bool, string) (privilegedResult, error),
) (cliResult, int) {
	o, err := parseCLI(args)
	if err != nil {
		return cliFailure("", "invalid_cli_arguments"), 2
	}
	if root {
		return cliFailure(o.action, "run_as_normal_user"), 2
	}
	prepared, err := prepare(o)
	req := prepared.request
	wantAction := o.action
	if o.action == "plan" {
		wantAction = o.target
	}
	if err != nil || req.Action != wantAction || req.validate() != nil {
		result := cliFailure(o.action, "preflight_failed")
		result.Checks = prepared.checks
		if o.action == "plan" {
			result.PlannedAction = wantAction
		}
		return result, 1
	}
	if o.action == "plan" {
		if prepared.plan == nil || prepared.network == nil {
			return cliFailure(o.action, "preflight_failed"), 1
		}
		return cliResult{
			privilegedResult: privilegedResult{
				SchemaVersion: 1, Operation: "plan", Status: "planned",
				PrivilegedTransactionState: "unknown", IdentityPreserved: "not_verified",
			},
			PlannedAction: wantAction, Plan: prepared.plan, Network: prepared.network,
			Checks: prepared.checks,
		}, 0
	}
	// A CLI request is noninteractive even if stdout/stdin happen to be
	// attached to a terminal. Never invoke su or a password prompt.
	reply, err := authorize(req, false, o.elevation)
	var unavailable *authorizationUnavailableError
	if errors.As(err, &unavailable) {
		return cliFailure(o.action, "authorization_unavailable"), 1
	}
	// Reuse the existing fixed-enum result checks before re-encoding. Do
	// not relay raw subprocess diagnostics or unknown response fields.
	raw, marshalErr := json.Marshal(reply)
	safe, decodeErr := validatedPrivilegedReply(raw, o.action)
	if marshalErr != nil || decodeErr != nil || (err != nil && safe.Status != "error") {
		// A lost response is not evidence that no mutation occurred.
		return cliFailure(o.action, "outcome_unknown"), 1
	}
	result := cliResult{privilegedResult: safe, Network: prepared.network, Checks: prepared.checks}
	if safe.Status == "error" {
		if safe.ErrorCode == "recovery_required" {
			return result, 3
		}
		return result, 1
	}
	if o.isInstall() {
		result.Onboarding = onboardingMode(safe)
	}
	if strings.HasSuffix(safe.Status, "_cleanup_required") {
		return result, 3
	}
	if o.action == "status" {
		switch safe.PrivilegedTransactionState {
		case "none":
			return result, 0
		case "in_progress", "incomplete", "recovery_required":
			return result, 3
		default:
			// A successful status envelope without a state is not
			// evidence that there is no outstanding transaction.
			return cliFailure(o.action, "outcome_unknown"), 1
		}
	}
	return result, 0
}

func runCLI(args []string, out io.Writer) int {
	if len(args) == 1 && (args[0] == "--help" || args[0] == "-h") {
		if _, err := fmt.Fprint(out, cliUsage); err != nil {
			return 1
		}
		return 0
	}
	result, code := executeCLI(args, os.Getuid() == 0 || os.Geteuid() == 0,
		prepareCLIRequest, executeAuthorizedBootstrap)
	if err := json.NewEncoder(out).Encode(result); err != nil {
		return 1
	}
	return code
}
