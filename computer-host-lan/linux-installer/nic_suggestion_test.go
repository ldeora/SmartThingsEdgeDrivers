package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func addNICFixture(t *testing.T, root, name, state string) {
	t.Helper()
	path := filepath.Join(root, name)
	if err := os.MkdirAll(filepath.Join(path, "device"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(path, "type"), []byte("1\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(path, "operstate"), []byte(state+"\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, name, "uevent"), []byte("INTERFACE="+name+"\n"), 0o644); err != nil {
		t.Fatal(err)
	}
}

func TestSuggestedNICUsesRouteAndRequiresExistingInterface(t *testing.T) {
	root := t.TempDir()
	addNICFixture(t, root, "enp1s0f0", "up")
	addNICFixture(t, root, "LAN0", "up")
	route := func(ip string) string {
		if ip != "192.168.1.103" {
			t.Fatalf("wrong route destination: %s", ip)
		}
		return "LAN0"
	}
	if got := suggestedNICAt(root, "192.168.1.103", route); got != "LAN0" {
		t.Fatalf("case-sensitive routed NIC not selected: %q", got)
	}
	if got := suggestedNICAt(root, "192.168.1.103", func(string) string { return "missing" }); got != "" {
		t.Fatalf("nonexistent routed NIC should not be suggested: %q", got)
	}
	if got := suggestedNICAt(root, "bad/input", route); got != "" {
		t.Fatalf("route accepted invalid hub address: %q", got)
	}
}

func TestSuggestedNICSingleActivePhysicalInterfaceFallback(t *testing.T) {
	root := t.TempDir()
	addNICFixture(t, root, "enp1s0f0", "up")
	addNICFixture(t, root, "enp2s0", "down")
	if err := os.MkdirAll(filepath.Join(root, "br0"), 0o755); err != nil {
		t.Fatal(err)
	}
	if got := suggestedNICAt(root, "", nil); got != "enp1s0f0" {
		t.Fatalf("expected only active hardware NIC, got %q", got)
	}
	addNICFixture(t, root, "LAN0", "up")
	if got := suggestedNICAt(root, "", nil); got != "" {
		t.Fatalf("ambiguous physical NICs must not be guessed: %q", got)
	}
}

func TestDefaultHubAndReviewUseBeginnerFriendlyWords(t *testing.T) {
	client := fixtureClient(t)
	info, err := client.inspect()
	if err != nil {
		t.Fatal(err)
	}
	hubs := []discoveredHub{{IPv4: "192.168.1.103", Port: 12345}}
	s := newLiveSelection(client, info, hubs)
	if s.hubChoice != "discovered:192.168.1.103" {
		t.Fatalf("discovered hub was not preselected: %s", s.hubChoice)
	}
	if defaultHubChoice(nil) != "manual" {
		t.Fatal("no-hub case should suggest manual IP entry")
	}
	choices := liveHubOptions(hubs)
	if len(choices) != 3 {
		t.Fatalf("expected discovered/manual/later options, got %d", len(choices))
	}
	review := s.preview()
	for _, text := range []string{
		"Your SmartThings setup",
		"192.168.1.103 (found automatically)",
		"Keep power control enabled",
		"Network:       Leave existing settings unchanged",
		"Preview only",
	} {
		if !strings.Contains(review, text) {
			t.Fatalf("review missing %q: %s", text, review)
		}
	}
	for _, forbidden := range []string{"/etc/", "/opt/", "root recovery inspection", "replace:"} {
		if strings.Contains(review, forbidden) {
			t.Fatalf("advanced internal details leaked into primary Review: %s", review)
		}
	}
	if len(livePowerOptions(info)) != 2 {
		t.Fatal("power control should be a simple default/alternative choice")
	}
}

func TestSuggestedNICRejectsWirelessHardware(t *testing.T) {
	root := t.TempDir()
	addNICFixture(t, root, "wlan0", "up")
	if err := os.Mkdir(filepath.Join(root,"wlan0","wireless"), 0o755); err != nil {
		t.Fatal(err)
	}
	if got := suggestedNICAt(root,"192.168.1.103",func(string) string { return "wlan0" }); got != "" {
		t.Fatalf("Wireless route was suggested: %q", got)
	}
}
