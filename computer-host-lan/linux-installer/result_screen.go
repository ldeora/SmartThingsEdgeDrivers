package main

// Presentation of the existing validated helper result. Neither the screen
// nor its close handler can execute, retry or recover an operation.
import (
	"errors"
	"fmt"
	"io"
	"os"
	"strings"
)

type operationReport struct {
	action        string
	power         string
	wolConfigured bool
	reply         privilegedResult
	runErr        error
	called        bool
	screenFailed  bool
	continueWOL   bool
}

func operationLabel(action string) string {
	switch action {
	case "install":
		return "Installation"
	case "upgrade":
		return "Upgrade / configuration"
	case "repair":
		return "Repair"
	case "restore":
		return "Restore"
	case "recover":
		return "Recovery"
	case "uninstall":
		return "Uninstall"
	case "backups":
		return "Backup listing"
	case "wol-check":
		return "Wake-on-LAN check"
	case "wol-remove":
		return "Wake-on-LAN removal"
	default:
		return "Operation"
	}
}

// Use the original runner synchronously, with exclusive terminal ownership.
// There is no trustworthy progress stream or authorization-complete event.
// Do not display a spinner over a real password prompt or invent a stage.
func (r *operationReport) observe(w io.Writer, run func(privilegedRequest) (privilegedResult, error)) func(privilegedRequest) (privilegedResult, error) {
	return func(req privilegedRequest) (privilegedResult, error) {
		*r = operationReport{action: req.Action, power: req.Power,
			wolConfigured: req.WOLPlanDigest != "", called: true}
		fmt.Fprintf(w, "\n%s: waiting for administrator authorization and helper result.\n", operationLabel(req.Action))
		fmt.Fprintln(w, "This may take several minutes. No intermediate progress is reported.")
		reply, err := run(req)
		r.reply, r.runErr = reply, err
		return reply, err
	}
}

func (r operationReport) visible(err error) bool {
	// Successful listing/check has its own chooser/review; no extra result
	// screen for a cancellation there. Failed protected checks do show.
	return r.called && (err != nil || (r.action != "backups" && r.action != "wol-check"))
}

func continuityRows(reply privilegedResult) []detailRow {
	if reply.RecoveryStatus == "nothing_to_recover" {
		return nil
	}
	if reply.CredentialContinuity == "verified" {
		return []detailRow{{"Identity and key metadata unchanged during this transaction.", "normal"}}
	}
	return []detailRow{{"Credential continuity: not verified.", "muted"}}
}

func (r operationReport) rows(err error) []detailRow {
	rows := []detailRow{{operationLabel(r.action), "header"}}
	add := func(s, tone string) { rows = append(rows, detailRow{s, tone}) }
	reply := r.reply
	if err != nil {
		var unavailable *authorizationUnavailableError
		switch {
		case errors.As(r.runErr, &unavailable):
			add("Not started", "warning")
			add("Administrator authorization or preparation was unavailable.", "normal")
			add("Check the terminal message before trying again.", "muted")
		case r.runErr != nil && reply.Status == "error" && knownPrivilegedError(reply.ErrorCode):
			switch reply.ErrorCode {
			case "rolled_back":
				add("Operation rolled back", "warning")
				rows = append(rows, continuityRows(reply)...)
			case "aborted":
				add("Aborted before managed changes", "warning")
			case "recovery_required", "recovery_helper_missing":
				add("Recovery required", "warning")
			case "wol_review_required":
				add("Wake-on-LAN needs review", "warning")
			default:
				add("Operation did not complete", "warning")
			}
			// This existing formatter uses only validated enum values
			// and fixed text, never raw subprocess stderr or secrets.
			add(resultPrivilegeFailure(reply), "normal")
		default:
			add("No confirmed result", "warning")
			add("If authorization failed before the helper started, no changes were made.", "normal")
			add("If unsure, open Inspect or choose Recover in the menu before retrying.", "normal")
		}
		return rows
	}
	switch r.action {
	case "install", "upgrade", "repair":
		if reply.Status != "installed" && reply.Status != "installed_cleanup_required" {
			add("Outcome not confirmed", "warning")
			return rows
		}
		completion := "Installation complete"
		switch r.action {
		case "upgrade":
			completion = "Upgrade complete"
		case "repair":
			completion = "Repair complete"
		}
		add(completion, "success")
		if reply.Status == "installed_cleanup_required" {
			add("Cleanup required: choose Recover in the menu.", "warning")
		}
		if reply.IdentityPreserved == "verified" {
			add("Existing device: refresh in the SmartThings app.", "normal")
		} else {
			add("Check your existing device; if it does not respond, use Scan nearby.", "normal")
		}
		switch r.power {
		case "enable":
			add("Power control: enabled on this computer", "normal")
		case "disable":
			add("Power control: disabled", "normal")
		default:
			add("Power control: unchanged", "normal")
		}
		switch reply.WOLStatus {
		case "unsupported":
			add("Wake-on-LAN: unsupported; not configured", "warning")
		case "capability_unknown":
			add("Wake-on-LAN: capability unknown; not configured", "warning")
		default:
			if r.wolConfigured {
				add("Wake-on-LAN: persistent configuration verified", "normal")
			} else {
				add("Wake-on-LAN: unchanged", "normal")
			}
		}
	case "restore":
		if reply.Status != "restored" && reply.Status != "restored_cleanup_required" {
			add("Outcome not confirmed", "warning")
			return rows
		}
		add("Historical backup restored", "success")
		rows = append(rows, continuityRows(reply)...)
		if reply.Status == "restored_cleanup_required" {
			add("Restore committed; choose Recover in the menu to finish cleanup.", "warning")
		}
		add("Refresh the existing SmartThings device and test operation.", "normal")
	case "uninstall":
		if reply.Status != "uninstalled" && reply.Status != "uninstalled_cleanup_required" {
			add("Outcome not confirmed", "warning")
			return rows
		}
		add("Agent uninstalled", "success")
		rows = append(rows, continuityRows(reply)...)
		if reply.Status == "uninstalled_cleanup_required" {
			add("Uninstall committed; choose Recover in the menu to finish cleanup.", "warning")
		}
		add("Private state and recovery backups retained.", "normal")
		add("SmartThings device not deleted.", "normal")
		add("Wake-on-LAN removal is a separate optional operation.", "muted")
	case "recover":
		if reply.Status != "passed" {
			add("Outcome not confirmed", "warning")
			return rows
		}
		switch reply.RecoveryStatus {
		case "nothing_to_recover":
			add("No protected transaction needs recovery", "normal")
		case "rolled_back":
			add("Previous files and service state restored", "success")
		case "aborted":
			add("Interrupted operation aborted before managed changes", "normal")
		case "cleaned":
			add("Transaction cleanup completed", "success")
		default:
			add("Recovery outcome not confirmed", "warning")
			return rows
		}
		rows = append(rows, continuityRows(reply)...)
		if reply.WOLReviewRequired {
			add("Wake-on-LAN needs manual review; do not repeat recovery for WOL alone.", "warning")
		}
		add("Recovery does not resume the interrupted operation.", "muted")
	case "wol-remove":
		if reply.Status == "passed" && reply.WOLStatus == "removed" {
			add("Installer-owned Wake-on-LAN setting removed", "success")
			add("Agent and administrator settings unchanged.", "normal")
			add("Reboot may be required to observe persistent policy.", "normal")
		} else if reply.Status == "passed" && reply.WOLStatus == "not_managed" {
			add("No installer-owned setting to remove", "normal")
		} else {
			add("Outcome not confirmed", "warning")
		}
	default:
		add("Outcome not confirmed", "warning")
	}
	return rows
}

// Translate only known CLI navigation phrases for the interactive screen.
// The original enum-based diagnostic remains unchanged on the terminal.
func resultPrivilegeFailure(reply privilegedResult) string {
	return strings.NewReplacer(
		"Run -recover for managed-state recovery", "Choose Recover in the menu for managed-state recovery",
		"Run this wizard with -recover before retrying", "Choose Recover in the menu before retrying",
		"Configure (-configure)", "Configure in the menu",
		"run -uninstall again", "choose Uninstall in the menu again",
	).Replace(userFacingPrivilegeFailure(reply).Error())
}

// Keep the established console transcript, including the complete network,
// onboarding and recovery guidance, for scrollback after closing the screen.
// Preserve the original operation error/exit status even if rendering fails.
func (r *operationReport) present(w io.Writer, err error) error {
	return r.presentWith(w, err, func(m inspectionScreen) (string, error) {
		result, screenErr := runFramedProgram(m)
		if screenErr != nil {
			return "", screenErr
		}
		final, ok := result.(inspectionScreen)
		if !ok {
			return "", fmt.Errorf("unexpected result screen")
		}
		return final.closedBy, nil
	})
}

func (r *operationReport) presentWith(w io.Writer, err error, show func(inspectionScreen) (string, error)) error {
	if !r.visible(err) {
		return err
	}
	rows := r.rows(err)
	rows = append(rows, detailRow{"Close for the full terminal summary.", "muted"})
	m := inspectionScreen{
		frame: detailFrame{monochrome: os.Getenv("NO_COLOR") != ""},
		rows:  rows, title: "RESULT", statusPrefix: "Operation result",
		closeHelp: "Up/Down Scroll | PgUp/PgDn Page | Enter/Esc/Q Close",
	}
	optionalWOL := err == nil && r.action == "uninstall" && r.reply.Status == "uninstalled"
	if optionalWOL {
		m.closeHelp = "Scroll | Enter WOL options | Esc/Q/Ctrl+C Finish"
	}
	key, screenErr := show(m)
	r.continueWOL = screenErr == nil && optionalWOL && key == "enter"
	if screenErr != nil {
		r.screenFailed = true
		fmt.Fprintln(w, "Result screen unavailable. Use the terminal summary; do not repeat an operation just to see its result.")
	}
	return err
}

func observedAuthorization(w io.Writer, method string, report *operationReport) func(privilegedRequest) (privilegedResult, error) {
	return report.observe(w, func(req privilegedRequest) (privilegedResult, error) {
		return executeAuthorizedBootstrap(req, true, method)
	})
}

func installSelectionPresentation(s *liveSelection, w io.Writer, method string) error {
	var report operationReport
	err := installSelectionWithAuthorization(s, w, method, observedAuthorization(w, method, &report))
	if !report.called && err != nil {
		// The reviewed plan was rejected locally, before any helper call.
		action := s.requestedAction
		if action == "" {
			action = "install"
			if s.inspection.Installation.Detected {
				action = "upgrade"
			}
		}
		report = operationReport{action: action, called: true,
			runErr: &authorizationUnavailableError{cause: err}}
	}
	return report.present(w, err)
}

func recoverPresentation(w io.Writer, method string) error {
	var report operationReport
	err := executeConfirmedRecovery(w, observedAuthorization(w, method, &report))
	return report.present(w, err)
}
