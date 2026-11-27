package main

// Presentation of the existing validated helper result. Neither the screen
// nor its close handler can execute, retry or recover an operation.
import (
	"errors"
	"fmt"
	"io"
	"os"
)

type operationReport struct {
	action        string
	power         string
	wolConfigured bool
	reply         privilegedResult
	runErr        error
	called        bool
	screenFailed  bool
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
			add(userFacingPrivilegeFailure(reply).Error(), "normal")
		default:
			add("Outcome not confirmed", "warning")
			add("Authorization or helper execution did not yield a reliable outcome.", "normal")
			add("Inspect the installation and recovery state before retrying.", "normal")
			add("Do not assume the operation failed before making changes.", "muted")
		}
		return rows
	}
	switch r.action {
	case "install", "upgrade", "repair":
		if reply.Status != "installed" && reply.Status != "installed_cleanup_required" {
			add("Outcome not confirmed", "warning")
			return rows
		}
		add("Agent installation completed", "success")
		rows = append(rows, continuityRows(reply)...)
		if reply.Status == "installed_cleanup_required" {
			add("Cleanup required: run -recover before another installation.", "warning")
		}
		if reply.IdentityPreserved == "verified" {
			add("Refresh your existing SmartThings device first.", "normal")
		} else {
			add("Check an existing device first; otherwise use Scan nearby.", "normal")
		}
		switch r.power {
		case "enable":
			add("Remote power enabled on the computer; check device settings.", "normal")
		case "disable":
			add("Remote power disabled; monitoring remains available.", "normal")
		default:
			add("Power choice retained; test if enabled.", "normal")
		}
		switch reply.WOLStatus {
		case "unsupported":
			add("Wake-on-LAN unsupported; not configured.", "warning")
		case "capability_unknown":
			add("Wake-on-LAN capability unknown; not configured.", "warning")
		default:
			if r.wolConfigured {
				add("Persistent Wake-on-LAN configuration verified.", "normal")
			} else {
				add("Persistent Wake-on-LAN left unchanged.", "normal")
			}
		}
		add("Discovery, hub connectivity and power operation not tested.", "muted")
		add("No automatic pairing or firewall changes.", "muted")
	case "restore":
		if reply.Status != "restored" && reply.Status != "restored_cleanup_required" {
			add("Outcome not confirmed", "warning")
			return rows
		}
		add("Historical backup restored", "success")
		rows = append(rows, continuityRows(reply)...)
		if reply.Status == "restored_cleanup_required" {
			add("Restore committed; run -recover to finish cleanup.", "warning")
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
			add("Uninstall committed; run -recover to finish cleanup.", "warning")
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

// Keep the established console transcript, including the complete network,
// onboarding and recovery guidance, for scrollback after closing the screen.
// Preserve the original operation error/exit status even if rendering fails.
func (r *operationReport) present(w io.Writer, err error) error {
	return r.presentWith(w, err, func(m inspectionScreen) error {
		_, screenErr := runFramedProgram(m)
		return screenErr
	})
}

func (r *operationReport) presentWith(w io.Writer, err error, show func(inspectionScreen) error) error {
	if !r.visible(err) {
		return err
	}
	rows := r.rows(err)
	rows = append(rows, detailRow{"Close for the terminal summary and diagnostics.", "muted"})
	m := inspectionScreen{
		frame: detailFrame{monochrome: os.Getenv("NO_COLOR") != ""},
		rows:  rows, title: "RESULT", statusPrefix: "Operation result",
		closeHelp: "Up/Down Scroll | PgUp/PgDn Page | Enter/Esc/Q Close",
	}
	if screenErr := show(m); screenErr != nil {
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
