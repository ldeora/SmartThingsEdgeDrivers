package main

import (
	"fmt"
	"io"
	"regexp"
	"strings"
	"unicode"
)

var wolDigestPattern = regexp.MustCompile("^[0-9a-f]{64}$")
var wolMACPattern = regexp.MustCompile("^([0-9a-f]{2}:){5}[0-9a-f]{2}$")
var wolProfilePattern = regexp.MustCompile("^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
var wolFlagsPattern = regexp.MustCompile("^[0-9]{1,5}$")

func wiredNICName(name string) bool {
	return validNICName(name) == nil && name != "lo" && !strings.HasPrefix(name, "-")
}

type wolPolicy struct {
	Action     string  `json:"action"`
	Interface  string  `json:"interface"`
	MAC        string  `json:"mac"`
	Backend    string  `json:"backend"`
	Profile    *string `json:"profile"`
	Previous   *string `json:"previous"`
	LinkName   *string `json:"link_name"`
	LinkText   *string `json:"link_text"`
	Digest     string  `json:"digest"`
	Capability string  `json:"capability"`
}

func (p wolPolicy) valid(nic string) bool {
	if p.Action != "configure" || p.Interface != nic || !wiredNICName(nic) ||
		!wolMACPattern.MatchString(p.MAC) || !wolDigestPattern.MatchString(p.Digest) ||
		(p.Capability != "supported" && p.Capability != "unknown") {
		return false
	}
	switch p.Backend {
	case "nm":
		return p.Profile != nil && wolProfilePattern.MatchString(*p.Profile) &&
			p.Previous != nil && wolFlagsPattern.MatchString(*p.Previous) &&
			p.LinkName == nil && p.LinkText == nil
	case "link-create":
		if p.Profile != nil || p.Previous != nil || p.LinkName == nil ||
			*p.LinkName != "10-linux-host-wol-"+strings.ReplaceAll(p.MAC, ":", "")+".link" ||
			p.LinkText == nil || len(*p.LinkText) > 8192 {
			return false
		}
		for _, ch := range *p.LinkText {
			if unicode.IsControl(ch) && ch != '\n' && ch != '\t' {
				return false
			}
		}
		return strings.HasPrefix(*p.LinkText, "[Match]\nMACAddress="+p.MAC+"\n\n[Link]\n") &&
			strings.HasSuffix(*p.LinkText, "\nWakeOnLan=magic\n")
	case "link-existing":
		return p.Profile == nil && p.Previous == nil && p.LinkName == nil && p.LinkText == nil
	}
	return false
}

func (p wolPolicy) description() string {
	var b strings.Builder
	fmt.Fprintf(&b, "Wake-on-LAN: configure %s (%s)\n", p.Interface, p.MAC)
	switch p.Backend {
	case "nm":
		fmt.Fprintf(&b, "NetworkManager profile %s: existing WOL flags %s; enable magic if missing, otherwise retain flags.\n", *p.Profile, *p.Previous)
	case "link-create":
		fmt.Fprintf(&b, "Create /etc/systemd/network/%s without overwriting existing files:\n%s\n", *p.LinkName, *p.LinkText)
	case "link-existing":
		fmt.Fprintln(&b, "Existing matching administrator .link policy: retain unchanged.")
	}
	fmt.Fprintln(&b, "Runtime: enable magic packets if missing; no network restart.")
	if p.Capability == "unknown" {
		fmt.Fprintln(&b, "Hardware capability unknown without authorization; checked again before installation.")
	}
	return strings.TrimSpace(b.String())
}

func validWOLStatus(r privilegedResult, action string) bool {
	if action != "wol-check" && action != "wol-remove" {
		return r.WOLStatus == ""
	}
	if r.Status == "error" {
		return r.WOLStatus == ""
	}
	if r.Status != "passed" {
		return false
	}
	if action == "wol-check" {
		return r.WOLStatus == "managed" || r.WOLStatus == "not_managed" ||
			r.WOLStatus == "review_required" || r.WOLStatus == "runtime_only"
	}
	return r.WOLStatus == "removed" || r.WOLStatus == "not_managed"
}

func showWOLStatus(w io.Writer, r privilegedResult) {
	switch r.WOLStatus {
	case "managed":
		fmt.Fprintln(w, "Wake-on-LAN is configured by Computer Host LAN.")
	case "runtime_only":
		fmt.Fprintln(w, "Persistent policy was already configured independently; only installer runtime state is recorded.")
	case "review_required":
		fmt.Fprintln(w, "Wake-on-LAN ownership needs a manual check. Remove only if the saved setting can be verified; do not delete the ownership record.")
	case "not_managed":
		fmt.Fprintln(w, "No installer-owned Wake-on-LAN setting for this interface. Administrator settings are unchanged.")
	case "removed":
		fmt.Fprintln(w, "Installer-owned Wake-on-LAN setting removed; administrator settings and agent are unchanged. Reboot may be required to observe persistent policy.")
	}
}

func runWOLManagement(reader io.Reader, writer io.Writer, method string, remove bool) error {
	return manageWOL(reader, writer, remove, func(req privilegedRequest) (privilegedResult, error) {
		return executeAuthorizedBootstrap(req, true, method)
	})
}

func manageWOL(reader io.Reader, writer io.Writer, remove bool, authorize func(privilegedRequest) (privilegedResult, error)) error {
	fmt.Fprintln(writer, "Configure — Wake-on-LAN")
	fmt.Fprintln(writer, "Check or remove only settings previously recorded by Computer Host LAN. To configure WOL, run the installation/upgrade wizard and select Configure.")
	nic := suggestedNIC("")
	fmt.Fprintf(writer, "Wired interface [%s] (or quit): ", nic)
	value, err := readConfirmationLine(reader)
	if err != nil {
		return nil
	}
	value = strings.TrimSpace(value)
	if value == "quit" || value == "q" {
		return nil
	}
	if value != "" {
		nic = value
	}
	if !wiredNICName(nic) {
		return fmt.Errorf("enter a valid wired interface name")
	}
	result, err := authorize(privilegedRequest{SchemaVersion: 2, Action: "wol-check", WOLInterface: &nic})
	if err != nil {
		return err
	}
	showWOLStatus(writer, result)
	if result.WOLStatus == "not_managed" {
		return nil
	}
	if !remove {
		fmt.Fprint(writer, "Remove the installer setting? [y/N]: ")
		answer, err := readConfirmationLine(reader)
		if err != nil || !strings.EqualFold(strings.TrimSpace(answer), "y") {
			return nil
		}
	}
	fmt.Fprint(writer, "Type REMOVE to restore the saved WOL policy (anything else cancels): ")
	answer, err := readConfirmationLine(reader)
	if err != nil || strings.TrimSpace(answer) != "REMOVE" {
		fmt.Fprintln(writer, "WOL unchanged.")
		return nil
	}
	result, err = authorize(privilegedRequest{SchemaVersion: 2, Action: "wol-remove", WOLInterface: &nic})
	if err != nil {
		return err
	}
	showWOLStatus(writer, result)
	return nil
}
