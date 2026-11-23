package main

import (
	"bytes"
	"strings"
	"testing"
)

func TestInstallerReviewProducesVersionedRootRequest(t *testing.T) {
	client := fixtureClient(t)
	info, err := client.inspect()
	if err != nil {
		t.Fatal(err)
	}
	s := newLiveSelection(client, info, nil)
	s.hubChoice = "skip"
	s.recordHubChoice("skip")
	request, err := approvedRootRequest(s)
	if err != nil {
		t.Fatal(err)
	}
	if request.Action != "upgrade" || request.Power != "preserve" ||
		request.WOLInterface != nil || request.SchemaVersion != 1 {
		t.Fatalf("Unexpected upgrade request: %+v", request)
	}
	s.powerChoice = "disabled"
	s.wolChoice = "pin"
	s.wolNIC = "LAN0"
	request, err = approvedRootRequest(s)
	if err != nil || request.Power != "disable" || *request.WOLInterface != "LAN0" {
		t.Fatalf("Choice lost: %+v, %v", request, err)
	}
	if strings.Contains(s.installPreview(), "Preview only —") {
		t.Fatal("actual installer must not claim it will make no changes")
	}
}

func TestAccessibleInstallationRequiresLiteralInstallConfirmation(t *testing.T) {
	client := fixtureClient(t)
	info, err := client.inspect()
	if err != nil {
		t.Fatal(err)
	}
	for _, tc := range []struct {
		name  string
		input string
		run   bool
	}{
		{"approved", "s\nk\nk\nINSTALL\n", true},
		{"declined", "s\nk\nk\ny\nquit\n", false},
		{"cancelled", "quit\n", false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			var output bytes.Buffer
			called := false
			err := runLiveAccessibleWithHubsMode(
				strings.NewReader(tc.input), &output, client, info, nil, true,
				func(s *liveSelection) error {
					called = true
					request, err := approvedRootRequest(s)
					if err != nil || request.Action != "upgrade" {
						t.Fatalf("Unexpected approved request %+v: %v", request, err)
					}
					return nil
				})
			if err != nil {
				t.Fatal(err)
			}
			if called != tc.run {
				t.Fatalf("Confirmation bypassed: called=%v, expected=%v; output=%s",
					called, tc.run, output.String())
			}
			if !strings.Contains(output.String(), "Type INSTALL") {
				if tc.name != "cancelled" {
					t.Fatal("No explicit install confirmation prompt")
				}
			}
		})
	}
}

func TestInstallWithoutCompatibleInterpreterBlockedBeforePrivilege(t *testing.T) {
	client := fixtureClient(t)
	info, err := client.inspect()
	if err != nil {
		t.Fatal(err)
	}
	info.Python.VersionSupported = false
	s := newLiveSelection(client, info, nil)
	if _, err := approvedRootRequest(s); err == nil {
		t.Fatal("Unsupported Python could reach privileged execution")
	}
}

func TestPrivilegedActionRejectsUnconfirmedSettings(t *testing.T) {
	cases := []privilegedRequest{
		{SchemaVersion: 0, Action: "install", Power: "preserve"},
		{SchemaVersion: 1, Action: "status", Power: "enable"},
		{SchemaVersion: 1, Action: "install", Power: ""},
		{SchemaVersion: 1, Action: "reveal_power_key"},
	}
	for _, request := range cases {
		if request.validate() == nil {
			t.Fatalf("Unexpected privileged action accepted: %+v", request)
		}
	}
}
