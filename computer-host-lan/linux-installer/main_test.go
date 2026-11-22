package main

import (
	"bytes"
	"strings"
	"testing"
)

func TestValidHubIPv4(t *testing.T) {
	for _, input := range []string{"192.168.1.20", "10.0.0.10", "172.16.1.4", "100.64.2.2", "8.8.8.8"} {
		if err := validHubIPv4(input); err != nil {
			t.Errorf("expected %q valid: %v", input, err)
		}
	}
	for _, input := range []string{
		"", "192.168.1", "192.168.1.300", "::1", "::ffff:192.168.1.20",
		"127.0.0.1", "0.0.0.0", "255.255.255.255", "224.0.0.251",
		"169.254.0.1", "192.168.1.20 ", "192.168.1.20;shutdown",
		"010.0.0.1",
	} {
		if err := validHubIPv4(input); err == nil {
			t.Errorf("expected %q rejected", input)
		}
	}
}

func TestPublicHubWarning(t *testing.T) {
	for _, input := range []string{"8.8.8.8", "192.0.2.10"} {
		if warning := hubAddressWarning(input); !strings.Contains(warning, "WARNING") {
			t.Errorf("expected public warning for %s", input)
		}
	}
	for _, input := range []string{"192.168.0.1", "10.2.1.3", "172.17.0.2", "100.64.0.1"} {
		if warning := hubAddressWarning(input); warning != "" {
			t.Errorf("unexpected warning for %s: %q", input, warning)
		}
	}
}

func TestFreshInstallDefaultsMonitoringOnly(t *testing.T) {
	s := selection{action: "install", hubChoice: "none", powerChoice: "keep", wolChoice: "keep"}
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

func TestUpgradeDemoPreservesCurrentPowerChoice(t *testing.T) {
	s := selection{action: "upgrade", hubChoice: "demo-a", powerChoice: "keep", wolChoice: "keep"}
	got := s.preview()
	for _, want := range []string{"Existing installation upgrade", "reserved TEST-NET", "Power management: true", "NO CHANGES WILL BE MADE"} {
		if !strings.Contains(got, want) {
			t.Errorf("preview missing %q: %s", want, got)
		}
	}
	s.powerChoice = "disabled"
	if s.effectivePower() {
		t.Fatal("explicit disable was ignored")
	}
}

func TestAccessibleFlowContainsNoANSIAndSkipsManualIP(t *testing.T) {
	var out bytes.Buffer
	input := "1\n4\nk\nk\ny\n"
	if err := runAccessible(strings.NewReader(input), &out); err != nil {
		t.Fatal(err)
	}
	got := out.String()
	for _, want := range []string{"Fresh installation", "Power management: false", "DEMO COMPLETE"} {
		if !strings.Contains(got, want) {
			t.Errorf("accessible flow missing %q: %s", want, got)
		}
	}
	if strings.Contains(got, "\x1b") || strings.Contains(got, "Hub IPv4 (never contacted)") {
		t.Fatalf("unexpected ANSI or hidden field prompt: %q", got)
	}
}

func TestAccessibleManualIPPublicWarningAndBack(t *testing.T) {
	var out bytes.Buffer
	// Switch from upgrade to install using Back, then select manual hub with
	// public IPv4, explicitly acknowledge the warning, and finish.
	input := "2\nback\n1\n3\n8.8.8.8\ny\nn\nk\nn\n"
	if err := runAccessible(strings.NewReader(input), &out); err != nil {
		t.Fatal(err)
	}
	got := out.String()
	for _, want := range []string{"WARNING:", "8.8.8.8", "Fresh installation", "Power management: false"} {
		if !strings.Contains(got, want) {
			t.Errorf("missing expected output %q: %q", want, got)
		}
	}
	if strings.Contains(got, "\x1b") {
		t.Fatalf("accessible flow emitted escape sequences: %q", got)
	}
}

func TestAccessibleCancelWithoutError(t *testing.T) {
	var out bytes.Buffer
	if err := runAccessible(strings.NewReader("quit\n"), &out); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(out.String(), "Cancelled; no changes made.") {
		t.Fatal("cancel was not handled cleanly")
	}
}
