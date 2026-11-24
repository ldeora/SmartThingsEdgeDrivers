package main

import (
	"fmt"
	"io"
)

// Legacy helpers omit all four fields. Absence is never verification.
// New replies must use a consistent, bounded set of public enums.
func validateContinuityReply(reply *privilegedResult, action string) bool {
	id, token := reply.InstallationIDContinuity, reply.ControlTokenContinuity
	legacy := id == "" && token == "" && reply.CredentialContinuity == "" && reply.ContinuityReason == ""
	if action == "status" {
		return legacy
	}
	if legacy {
		reply.InstallationIDContinuity = "not_verified"
		reply.ControlTokenContinuity = "not_verified"
		reply.CredentialContinuity = "not_verified"
		if action == "recover" && reply.RecoveryStatus != "nothing_to_recover" {
			reply.ContinuityReason = "continuity_unverified_after_interruption"
		}
		return true
	}
	valid := func(s string) bool {
		switch s {
		case "verified", "absent", "newly_present", "not_verified":
			return true
		}
		return false
	}
	if !valid(id) || !valid(token) || (id == "not_verified") != (token == "not_verified") {
		return false
	}
	aggregate := "not_verified"
	if id == "verified" && token == "verified" {
		aggregate = "verified"
	}
	if reply.CredentialContinuity != aggregate {
		return false
	}
	if action == "recover" {
		if id != "not_verified" {
			return false
		}
		if reply.RecoveryStatus == "nothing_to_recover" {
			return reply.ContinuityReason == ""
		}
		return reply.ContinuityReason == "continuity_unverified_after_interruption"
	}
	if reply.Status == "error" {
		if reply.ContinuityReason == "credential_continuity_unverified" {
			return id == "not_verified" && (reply.ErrorCode == "aborted" || reply.ErrorCode == "recovery_required")
		}
		return reply.ContinuityReason == "" && (reply.ErrorCode == "rolled_back" || id == "not_verified")
	}
	if action == "uninstall" && (id == "newly_present" || token == "newly_present") {
		return false
	}
	return reply.ContinuityReason == ""
}

func showCredentialContinuity(w io.Writer, reply privilegedResult) {
	if reply.RecoveryStatus == "nothing_to_recover" {
		return
	}
	if reply.ContinuityReason == "continuity_unverified_after_interruption" {
		fmt.Fprintln(w, "Credential continuity was not verified after the interruption; managed-state recovery is a separate result.")
		return
	}
	label := func(s string) string {
		switch s {
		case "verified":
			return "metadata unchanged during this transaction"
		case "absent":
			return "absent before and after the transaction"
		case "newly_present":
			return "newly present; no prior credential to compare"
		default:
			return "not verified"
		}
	}
	fmt.Fprintln(w, "Installation ID continuity:", label(reply.InstallationIDContinuity))
	fmt.Fprintln(w, "Control token continuity:", label(reply.ControlTokenContinuity))
}
