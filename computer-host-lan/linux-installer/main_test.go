package main

import (
	"strings"
	"testing"
)

func TestValidHubIPv4(t *testing.T) {
	for _, input := range []string{"192.168.1.20", "10.0.0.10", "172.16.1.4"} {
		if err := validHubIPv4(input); err != nil {
			t.Errorf("expected %q valid: %v", input, err)
		}
	}
	for _, input := range []string{"", "192.168.1", "192.168.1.300", "::1", "127.0.0.1",
		"0.0.0.0", "255.255.255.255", "224.0.0.251", "169.254.0.1",
		"192.168.1.20 ", "192.168.1.20;shutdown"} {
		if err := validHubIPv4(input); err == nil {
			t.Errorf("expected %q rejected", input)
		}
	}
}

func TestFreshInstallDefaultsMonitoringOnly(t *testing.T) {
	s := selection{action: "install", hubChoice: "none"}
	got := s.preview()
	for _, want := range []string{
		"DEMO ONLY", "Monitoring: enabled",
		"Power management: false", "Persistent Wake-on-LAN: false",
		"NOT CHECKED", "NOT IMPLEMENTED",
	} {
		if !strings.Contains(got, want) {
			t.Errorf("preview missing %q: %s", want, got)
		}
	}
}

func TestUpgradePreviewDoesNotClaimInstallation(t *testing.T) {
	s := selection{action: "upgrade", hubChoice: "demo-a", enablePower: true}
	got := s.preview()
	if !strings.Contains(got, "Existing installation upgrade") ||
		!strings.Contains(got, "TEST-NET address") ||
		!strings.Contains(got, "NO CHANGES WILL BE MADE") {
		t.Fatalf("unsafe/misleading demo preview: %q", got)
	}
}
