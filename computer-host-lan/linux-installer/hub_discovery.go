package main

// Explicit, unprivileged SmartThings hub discovery for the live wizard.
// Avahi browsing sends a local mDNS query, but never contacts an advertised
// endpoint, accepts credentials, or modifies host/network configuration.

import (
	"bytes"
	"context"
	"errors"
	"net/netip"
	"os"
	"os/exec"
	"sort"
	"strconv"
	"strings"
	"time"
)

const (
	maxHubs            = 8
	hubDiscoveryTimeout = 3 * time.Second
)

type discoveredHub struct {
	IPv4 string
	Port int
}

// A discovered address is a *candidate*, never a verified trusted hub.
// Only literal canonical unicast IPv4 addresses enter wizard state. We don't
// display untrusted service-instance labels or TXT strings in the terminal.
func parseAvahiHubResults(raw []byte) []discoveredHub {
	seen := map[string]bool{}
	var hubs []discoveredHub
	for _, rawLine := range bytes.Split(raw, []byte("\n")) {
		line := strings.TrimSpace(string(rawLine))
		if !strings.HasPrefix(line, "=;") || len(line) > 1024 {
			continue
		}
		// Avahi -p uses semicolons as separators. Escaped semicolons can
		// appear in names, so ignore those fields; only the fixed tail fields
		// address/port are used after filtering the service type.
		fields := strings.Split(line, ";")
		if len(fields) < 9 || fields[3] == "" ||
			fields[4] != "_smartthings._tcp" || fields[5] != "local" ||
			fields[2] != "IPv4" {
			continue
		}
		addr, err := netip.ParseAddr(fields[7])
		if err != nil || !addr.Is4() || addr.String() != fields[7] ||
			validHubIPv4(fields[7]) != nil {
			continue
		}
		port, err := strconv.Atoi(fields[8])
		if err != nil || port < 1 || port > 65535 || seen[fields[7]] {
			continue
		}
		seen[fields[7]] = true
		hubs = append(hubs, discoveredHub{IPv4: fields[7], Port: port})
	}
	sort.Slice(hubs, func(i, j int) bool {
		a := netip.MustParseAddr(hubs[i].IPv4)
		b := netip.MustParseAddr(hubs[j].IPv4)
		return a.Less(b)
	})
	if len(hubs) > maxHubs {
		hubs = hubs[:maxHubs]
	}
	return hubs
}

func discoverHubsWith(executable string) []discoveredHub {
	if executable == "" {
		return nil
	}
	ctx, cancel := context.WithTimeout(context.Background(), hubDiscoveryTimeout)
	defer cancel()
	cmd := exec.CommandContext(ctx, executable, "-r", "-t", "-p", "_smartthings._tcp")
	cmd.WaitDelay = 500 * time.Millisecond
	cmd.Stdin = nil
	cmd.Env = append(os.Environ(), "LC_ALL=C")
	var stdout, stderr cappedBuffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr
	if err := cmd.Run(); err != nil && !errors.Is(err, exec.ErrNotFound) {
		return nil // No unfiltered errors or Avahi output shown in UI.
	}
	return parseAvahiHubResults(stdout.Bytes())
}

func discoverHubs() []discoveredHub {
	executable, err := exec.LookPath("avahi-browse")
	if err != nil {
		return nil
	}
	return discoverHubsWith(executable)
}

func hubChoices(hubs []discoveredHub) []string {
	var ips []string
	for _, h := range hubs {
		if validHubIPv4(h.IPv4) == nil {
			ips = append(ips, h.IPv4)
		}
	}
	return ips
}
