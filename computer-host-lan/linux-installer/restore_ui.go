package main

import (
	"fmt"
	"io"
	"regexp"
	"sort"
	"strconv"
	"strings"
)

var backupNamePattern = regexp.MustCompile("^snapshot-[A-Za-z0-9_-]{6,64}$")
var backupVersionPattern = regexp.MustCompile("^[A-Za-z0-9.+_-]{1,64}$")

type backupSummary struct {
	Name         string `json:"name"`
	Version      string `json:"version"`
	Digest       string `json:"digest"`
	CapturedAt   int64  `json:"captured_at"`
	AgentActive  bool   `json:"agent_active"`
	AgentEnabled bool   `json:"agent_enabled"`
	Power        string `json:"power"`
	Coverage     string `json:"coverage"`
}

func validBackupReply(reply privilegedResult, action string) bool {
	if action != "backups" || reply.Status == "error" {
		return reply.Backups == nil
	}
	if reply.Status != "passed" || reply.Backups == nil || len(*reply.Backups) > 32 {
		return false
	}
	seen := map[string]bool{}
	for _, b := range *reply.Backups {
		if !backupNamePattern.MatchString(b.Name) || seen[b.Name] ||
			!backupVersionPattern.MatchString(b.Version) || !wolDigestPattern.MatchString(b.Digest) ||
			b.CapturedAt < 0 || b.CapturedAt > 253402300799 ||
			(b.Power != "enabled" && b.Power != "disabled" && b.Power != "keep") ||
			(b.Coverage != "complete" && b.Coverage != "partial") {
			return false
		}
		seen[b.Name] = true
	}
	return true
}

func runRestoreWizard(reader io.Reader, writer io.Writer, method string) error {
	return runRestorePresentation(false, reader, writer, method)
}

func runRestorePresentation(accessible bool, reader io.Reader, writer io.Writer, method string) error {
	choose := func(backups []backupSummary, currentVersion string) (int, error) {
		if detailTerminal(accessible, reader, writer) {
			return selectBackupScreen(backups, currentVersion)
		}
		return selectBackupPlain(reader, writer, backups, currentVersion)
	}
	return restoreWizardWithChooser(reader, writer, func(req privilegedRequest) (privilegedResult, error) {
		return executeAuthorizedBootstrap(req, true, method)
	}, installedAgentVersion(), choose)
}

func restoreWizard(reader io.Reader, writer io.Writer, authorize func(privilegedRequest) (privilegedResult, error), currentVersion string) error {
	return restoreWizardWithChooser(reader, writer, authorize, currentVersion,
		func(backups []backupSummary, version string) (int, error) {
			return selectBackupPlain(reader, writer, backups, version)
		})
}

func restoreWizardWithChooser(reader io.Reader, writer io.Writer, authorize func(privilegedRequest) (privilegedResult, error), currentVersion string, choose func([]backupSummary, string) (int, error)) error {
	fmt.Fprintln(writer, "Computer Host LAN — Restore a historical backup")
	fmt.Fprintln(writer, "Administrator authorization is needed to list local private backups. Listing does not restore agent files.")
	reply, err := authorize(privilegedRequest{SchemaVersion: 2, Action: "backups"})
	if err != nil {
		return err
	}
	if reply.Status != "passed" || !validBackupReply(reply, "backups") {
		return fmt.Errorf("invalid backup list")
	}
	backups := append([]backupSummary(nil), (*reply.Backups)...)
	sort.Slice(backups, func(i, j int) bool {
		if backups[i].CapturedAt == backups[j].CapturedAt {
			return backups[i].Name > backups[j].Name
		}
		return backups[i].CapturedAt > backups[j].CapturedAt
	})
	if len(backups) == 0 {
		fmt.Fprintln(writer, "No suitable installed-state v2 backups were found.")
		return nil
	}
	// Give the chooser a copy of the sorted validated list, but select
	// from our original list so the exact name/digest binding is preserved.
	index, err := choose(append([]backupSummary(nil), backups...), currentVersion)
	if err != nil {
		return err
	}
	if index == -1 {
		return nil
	}
	if index < 0 || index >= len(backups) {
		return fmt.Errorf("invalid backup selection")
	}
	b := backups[index]
	fmt.Fprintf(writer, "Restore agent %s from %s\n", b.Version, b.Name)
	fmt.Fprintf(writer, "Agent running: %t; enabled at boot: %t; saved power preference: %s\n", b.AgentActive, b.AgentEnabled, b.Power)
	if b.Coverage == "partial" {
		fmt.Fprintln(writer, "This backup records only some optional files. Unrecorded optional settings are kept.")
	}
	fmt.Fprintln(writer, "Older software may have known defects. The current agent files and service state will be backed up first. Your current identity, key and persistent NIC Wake-on-LAN settings are retained. The saved agent interface pin may be restored.")
	fmt.Fprint(writer, "Type RESTORE to authorize this backup (anything else cancels): ")
	line, err := readConfirmationLine(reader)
	if err != nil || strings.TrimSpace(line) != "RESTORE" {
		fmt.Fprintln(writer, "No agent changes made.")
		return nil
	}
	reply, err = authorize(privilegedRequest{SchemaVersion: 2, Action: "restore", Backup: b.Name, BackupDigest: b.Digest})
	if err != nil {
		return err
	}
	if (reply.Status != "restored" && reply.Status != "restored_cleanup_required") || reply.CredentialContinuity != "verified" || reply.IdentityPreserved != "verified" {
		return fmt.Errorf("unexpected restore outcome")
	}
	fmt.Fprintln(writer, "Historical backup restored. Refresh your existing SmartThings device and test monitoring and power control if enabled.")
	showCredentialContinuity(writer, reply)
	if reply.Status == "restored_cleanup_required" {
		fmt.Fprintln(writer, "Restore committed. Run -recover to finish installer cleanup.")
	}
	return nil
}

func selectBackupPlain(reader io.Reader, writer io.Writer, backups []backupSummary, currentVersion string) (int, error) {
	fmt.Fprintln(writer, "Installed agent file version (not runtime-verified):", currentVersion)
	for i, b := range backups {
		label := ""
		if i == 0 {
			label = " (Latest backup)"
		}
		fmt.Fprintf(writer, "%2d. Agent %s — %s%s — %s\n", i+1, b.Version, backupTime(b), label, b.Name)
	}
	fmt.Fprint(writer, "Choose a backup number (or quit): ")
	line, err := readConfirmationLine(reader)
	if err != nil || strings.TrimSpace(line) == "quit" || strings.TrimSpace(line) == "q" {
		return -1, nil
	}
	index, err := strconv.Atoi(strings.TrimSpace(line))
	if err != nil || index < 1 || index > len(backups) {
		return -1, fmt.Errorf("invalid backup number")
	}
	return index - 1, nil
}
