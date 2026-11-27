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
	Action         string  `json:"action"`
	Interface      string  `json:"interface"`
	MAC            string  `json:"mac"`
	Backend        string  `json:"backend"`
	Profile        *string `json:"profile"`
	Previous       *string `json:"previous"`
	LinkName       *string `json:"link_name"`
	LinkText       *string `json:"link_text"`
	Digest         string  `json:"digest"`
	Capability     string  `json:"capability"`
	ConnectionName string  `json:"connection_name,omitempty"`
}

func (p wolPolicy) valid(nic string) bool {
	if p.Action != "configure" || p.Interface != nic || !wiredNICName(nic) ||
		!wolMACPattern.MatchString(p.MAC) || !wolDigestPattern.MatchString(p.Digest) ||
		(p.Capability != "supported" && p.Capability != "unknown" && p.Capability != "unsupported") {
		return false
	}
	if len(p.ConnectionName) > 256 || (p.Backend != "nm" && p.ConnectionName != "") {
		return false
	}
	for _, ch := range p.ConnectionName {
		if !unicode.IsPrint(ch) {
			return false
		}
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
		name := p.ConnectionName
		if name == "" {
			name = "selected wired connection"
		}
		fmt.Fprintf(&b, "Keep Wake-on-LAN enabled after restarts. NetworkManager connection %q will enable magic packets if not already enabled.\n", name)
	case "link-create":
		fmt.Fprintf(&b, "Create /etc/systemd/network/%s (Wake-on-LAN after restarts; preserve other default link settings).\n", *p.LinkName)
		fmt.Fprintln(&b, "Full rule is available in the CLI plan JSON.")
	case "link-existing":
		fmt.Fprintln(&b, "Existing matching administrator .link policy: retain unchanged.")
	}
	fmt.Fprintln(&b, "Hardware support is checked after authorization. No network restart.")
	if p.Capability == "unsupported" {
		fmt.Fprintln(&b, "This adapter currently reports no magic-packet support. If confirmed, the agent will install without Wake-on-LAN.")
	}
	return strings.TrimSpace(b.String())
}

func validWOLStatus(r privilegedResult, action string) bool {
	if action != "wol-check" && action != "wol-remove" {
		if r.WOLStatus == "" {
			return true
		}
		return (r.WOLStatus == "unsupported" || r.WOLStatus == "capability_unknown") &&
			(action == "install" || action == "upgrade" || action == "repair") &&
			(r.Status == "installed" || r.Status == "installed_cleanup_required")
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
		fmt.Fprintln(w, "Wake-on-LAN was already set up on this computer. Computer Host LAN did not change its persistent setting.")
	case "review_required":
		fmt.Fprintln(w, "The Wake-on-LAN setting could not be verified and is left as it is. Check it in NetworkManager or /etc/systemd/network if waking does not work. Keep the saved installer record.")
	case "not_managed":
		fmt.Fprintln(w, "No installer-owned Wake-on-LAN setting for this interface. Administrator settings are unchanged.")
	case "removed":
		fmt.Fprintln(w, "Installer-owned Wake-on-LAN setting removed; administrator settings and agent are unchanged. Reboot may be required to observe persistent policy.")
	}
}

func runWOLManagement(reader io.Reader, writer io.Writer, method string, remove bool) error {
	return runWOLPresentation(false, reader, writer, method, remove)
}

func manageWOL(reader io.Reader, writer io.Writer, remove bool, authorize func(privilegedRequest) (privilegedResult, error)) error {
	fmt.Fprintln(writer, "Configure — Wake-on-LAN")
	fmt.Fprintln(writer, "Check or remove the saved Wake-on-LAN setting. To enable WOL, use Configure → Change power or Wake-on-LAN.")
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
