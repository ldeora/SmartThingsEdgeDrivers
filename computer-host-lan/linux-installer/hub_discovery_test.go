package main

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestParseAvahiHubResultsFiltersAndSorts(t *testing.T) {
	raw := strings.Join([]string{
		"+;enp1s0;IPv4;new;_smartthings._tcp;local",
		"=;enp1s0;IPv4;hub b;_smartthings._tcp;local;hub.local;192.168.1.30;5000;txt",
		"=;enp1s0;IPv4;hub a;_smartthings._tcp;local;hub.local;192.168.1.10;5555",
		"=;enp1s0;IPv4;duplicate;_smartthings._tcp;local;hub.local;192.168.1.10;9000",
		"=;enp1s0;IPv4;forged;_evil._tcp;local;hub.local;192.168.1.5;5555",
		"=;enp1s0;IPv4;internet;_smartthings._tcp;local;bad.com;8.8.8.8;5555",
		"=;enp1s0;IPv4;loopback;_smartthings._tcp;local;bad.local;127.0.0.1;5555",
		"=;enp1s0;IPv4;unspecified;_smartthings._tcp;local;bad.local;0.0.0.0;5555",
		"=;enp1s0;IPv4;badport;_smartthings._tcp;local;bad.local;192.168.1.6;0",
		"=;enp1s0;IPv6;ipv6;_smartthings._tcp;local;hub.local;2001:db8::1;5555",
		"=;enp1s0;IPv4;newline;_smartthings._tcp;local;hub.local;192.168.1.4;100000",
		"=;enp1s0;IPv4;shortcut;_smartthings._tcp;local;hub.local;192.168.01.5;5555",
		"=;enp1s0;IPv4;cgnet;_smartthings._tcp;local;hub.local;100.64.0.15;5555",
	}, "\n")
	got := parseAvahiHubResults([]byte(raw))
	expected := []discoveredHub{
		{"100.64.0.15", 5555},
		{"192.168.1.10", 5555},
		{"192.168.1.30", 5000},
	}
	if len(got) != len(expected) {
		t.Fatalf("hub candidates: got %#v, expected %#v", got, expected)
	}
	for i, want := range expected {
		if got[i] != want {
			t.Errorf("hub %d = %#v, want %#v", i, got[i], want)
		}
	}
}

func TestBoundedAvahiCommandUsesFixedArgvAndNoStdin(t *testing.T) {
	dir := t.TempDir()
	argsPath := filepath.Join(dir, "args")
	script := filepath.Join(dir, "avahi-browse")
	source := "#!/bin/sh\n" +
		"printf '%s\\n' \"$*\" > \"" + argsPath + "\"\n" +
		"printf '=;eth0;IPv4;Hub;_smartthings._tcp;local;hub.local;192.168.1.10;12345;txt\\n'\n"
	if err := os.WriteFile(script, []byte(source), 0o755); err != nil {
		t.Fatal(err)
	}
	got := discoverHubsWith(script)
	if len(got) != 1 || got[0].IPv4 != "192.168.1.10" {
		t.Fatalf("fake Avahi candidate not parsed: %#v", got)
	}
	args, err := os.ReadFile(argsPath)
	if err != nil {
		t.Fatal(err)
	}
	if strings.TrimSpace(string(args)) != "-r -t -p _smartthings._tcp" {
		t.Fatalf("unexpected Avahi arguments: %q", args)
	}
}

func TestHubSelectionReviewAndAccessibleManualFallback(t *testing.T) {
	client := fixtureClient(t)
	info, err := client.inspect()
	if err != nil {
		t.Fatal(err)
	}
	hubs := []discoveredHub{{"192.168.1.10", 12345}}
	s := liveSelection{
		api: client, inspection: info, powerChoice: "keep",
		wolChoice: "keep", hubChoice: "discovered:192.168.1.10", hubs: hubs,
	}
	if got := s.preview(); !strings.Contains(got, "192.168.1.10 (Avahi candidate") ||
		!strings.Contains(got, "no pairing or hub request") {
		t.Fatalf("hub selection missing/unverified incorrectly: %s", got)
	}
	s.hubChoice, s.hubManual = "manual", "192.168.1.20"
	if got := s.preview(); !strings.Contains(got, "192.168.1.20 (entered manually") {
		t.Fatalf("manual IPv4 missing: %s", got)
	}
	var output bytes.Buffer
	input := "k\nk\nm\n192.168.1.20\ny\n"
	if err := runLiveAccessibleWithHubs(strings.NewReader(input), &output, client, info, hubs); err != nil {
		t.Fatal(err)
	}
	result := output.String()
	for _, text := range []string{"192.168.1.10", "192.168.1.20 (entered manually", "READ-ONLY REVIEW COMPLETE"} {
		if !strings.Contains(result, text) {
			t.Fatalf("accessible manual hub flow omitted %q: %s", text, result)
		}
	}
	if strings.Contains(result, "\x1b") {
		t.Fatal("accessible mode contains ANSI bytes")
	}
	output.Reset()
	if err := runLiveAccessibleWithHubs(strings.NewReader("k\nk\n1\ny\n"), &output, client, info, hubs); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(output.String(), "192.168.1.10 (Avahi candidate") {
		t.Fatalf("accessible discovered hub was not selected: %s", output.String())
	}
}

func TestHubSelectionNeverInfersPairingOrContact(t *testing.T) {
	s := liveSelection{
		hubChoice: "discovered:192.168.1.11",
		hubs: []discoveredHub{{"192.168.1.10", 8765}},
	}
	if got := s.selectedHub(); !strings.Contains(got, "Not selected") {
		t.Fatalf("unlisted address trusted by UI: %s", got)
	}
	if got := len(liveHubOptions(nil)); got != 2 {
		t.Fatalf("manual and skip options missing without Avahi: %d", got)
	}
}
