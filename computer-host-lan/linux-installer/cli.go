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
  installer cli install   --confirm INSTALL   [--power preserve|enable|disable] [--wol-interface IFNAME] [--elevation auto|sudo|doas|run0]
  installer cli upgrade   --confirm UPGRADE   [same options]
  installer cli repair    --confirm REPAIR    [same options]
  installer cli uninstall --confirm UNINSTALL [--elevation auto|sudo|doas|run0]
  installer cli recover   --confirm RECOVER   [--elevation auto|sudo|doas|run0]
  installer cli status                         [--elevation auto|sudo|doas|run0]

Run as an ordinary user with preauthorized administrator access; no password
prompts or provider retries. No hub discovery, pairing, firewall or persistent
WOL configuration. Status/recovery use the existing protected helper.
Use an independently authenticated executable for any eventual release.
Except for --help, stdout contains a single JSON result.
Exit: 0 completed, 1 failed/unknown, 2 invalid invocation,
      3 outstanding transaction or cleanup required.
`

type cliOptions struct {
	action    string
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
	case "install", "upgrade", "repair", "uninstall", "recover", "status":
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
		case "--elevation":
			switch value {
			case "auto", "sudo", "doas", "run0":
				o.elevation = value
			default:
				return cliOptions{}, invalid
			}
		case "--power":
			if !o.isInstall() || (value != "preserve" && value != "enable" && value != "disable") {
				return cliOptions{}, invalid
			}
			o.power = value
		case "--wol-interface":
			if !o.isInstall() || validNICName(value) != nil {
				return cliOptions{}, invalid
			}
			o.nic = value
		default:
			return cliOptions{}, invalid
		}
	}
	if o.action == "status" {
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
	if !o.isInstall() || (o.action == "install") == info.Installation.Detected {
		return privilegedRequest{}, errors.New("requested action does not match observed installation")
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
		return privilegedRequest{}, errors.New("invalid power setting")
	}
	if o.nic != "" {
		s.wolChoice, s.wolNIC = "pin", o.nic
	}
	req, err := approvedRootRequest(s)
	if err != nil {
		return privilegedRequest{}, err
	}
	if o.action == "repair" && req.Action == "upgrade" {
		req.Action = "repair"
	}
	if req.Action != o.action {
		return privilegedRequest{}, errors.New("requested action mismatch")
	}
	return req, req.validate()
}

func prepareCLIRequest(o cliOptions) (privilegedRequest, error) {
	if !o.isInstall() {
		version := 1
		if o.action == "uninstall" {
			version = 2
		}
		req := privilegedRequest{SchemaVersion: version, Action: o.action}
		return req, req.validate()
	}
	path, cleanup, err := makeEmbeddedReadOnlyAPI()
	if err != nil {
		return privilegedRequest{}, err
	}
	defer cleanup()
	api, err := newAPIClient(path)
	if err != nil {
		return privilegedRequest{}, err
	}
	info, err := api.inspect()
	if err != nil {
		return privilegedRequest{}, err
	}
	return cliInstallRequest(o, api, info)
}

func cliFailure(action, code string) privilegedResult {
	return privilegedResult{SchemaVersion: 1, Operation: action, Status: "error", ErrorCode: code}
}

// Dependency injection is only for unprivileged tests. The real entry
// always uses the embedded inspector and existing authorized bootstrap.
func executeCLI(args []string, root bool,
	prepare func(cliOptions) (privilegedRequest, error),
	authorize func(privilegedRequest, bool, string) (privilegedResult, error),
) (privilegedResult, int) {
	o, err := parseCLI(args)
	if err != nil {
		return cliFailure("", "invalid_cli_arguments"), 2
	}
	if root {
		return cliFailure(o.action, "run_as_normal_user"), 2
	}
	req, err := prepare(o)
	if err != nil || req.Action != o.action || req.validate() != nil {
		return cliFailure(o.action, "preflight_failed"), 1
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
	if safe.Status == "error" {
		if safe.ErrorCode == "recovery_required" {
			return safe, 3
		}
		return safe, 1
	}
	if strings.HasSuffix(safe.Status, "_cleanup_required") {
		return safe, 3
	}
	if o.action == "status" {
		switch safe.PrivilegedTransactionState {
		case "none":
			return safe, 0
		case "in_progress", "incomplete", "recovery_required":
			return safe, 3
		default:
			// A successful status envelope without a state is not
			// evidence that there is no outstanding transaction.
			return cliFailure(o.action, "outcome_unknown"), 1
		}
	}
	return safe, 0
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
