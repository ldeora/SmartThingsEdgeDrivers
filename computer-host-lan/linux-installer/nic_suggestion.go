package main

// Optional, read-only suggestion of the interface used to reach a selected
// hub. This never checks or changes WOL hardware settings. It does not
// transmit traffic: "ip route get" only asks the local routing table.

import (
	"context"
	"net/netip"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strings"
	"time"
)

type routeCommand func(string) string

func routeDeviceForHub(hubIP string) string {
	if validHubIPv4(hubIP) != nil {
		return ""
	}
	ip, err := exec.LookPath("ip")
	if err != nil {
		return ""
	}
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	command := exec.CommandContext(ctx, ip, "-4", "-o", "route", "get", hubIP)
	command.WaitDelay = 250 * time.Millisecond
	command.Stdin = nil
	output, err := command.Output()
	if err != nil || len(output) > 4096 {
		return ""
	}
	parts := strings.Fields(string(output))
	for i := 0; i+1 < len(parts); i++ {
		if parts[i] == "dev" && validNICName(parts[i+1]) == nil {
			return parts[i+1]
		}
	}
	return ""
}

func suggestedNICAt(sysfs string, hubIP string, route routeCommand) string {
	if hubIP != "" && validHubIPv4(hubIP) == nil && route != nil {
		if name := route(hubIP); validNICName(name) == nil && name != "lo" {
			// Validate the suggested name exists; route output is never
			// accepted as proof of a physical Ethernet or WOL capability.
			if _, err := os.Stat(filepath.Join(sysfs, name)); err == nil {
				return name
			}
		}
	}
	entries, err := os.ReadDir(sysfs)
	if err != nil {
		return ""
	}
	var candidates []string
	for _, entry := range entries {
		name := entry.Name()
		if name == "lo" || validNICName(name) != nil {
			continue
		}
		p := filepath.Join(sysfs, name)
		// A "device" link distinguishes common hardware NICs from veth,
		// tun, bridges and other purely software interfaces. Wi-Fi also
		// has a device link; treat all suggestions as unverified.
		if _, err := os.Stat(filepath.Join(p, "device")); err != nil {
			continue
		}
		typ, err := os.ReadFile(filepath.Join(p, "type"))
		if err != nil || strings.TrimSpace(string(typ)) != "1" {
			continue
		}
		state, err := os.ReadFile(filepath.Join(p, "operstate"))
		if err == nil && strings.TrimSpace(string(state)) == "up" {
			candidates = append(candidates, name)
		}
	}
	sort.Strings(candidates)
	if len(candidates) == 1 {
		return candidates[0]
	}
	return ""
}

func suggestedNIC(hubIP string) string {
	// A valid IPv4 preference can be selected manually or advertised by
	// Avahi; never assume a detected candidate is authenticated.
	if addr, err := netip.ParseAddr(hubIP); err != nil || !addr.Is4() {
		hubIP = ""
	}
	return suggestedNICAt("/sys/class/net", hubIP, routeDeviceForHub)
}
