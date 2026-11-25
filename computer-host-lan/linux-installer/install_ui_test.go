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
		{"unterminated", "s\nk\nk\nINSTALL", false},
		{"typed ahead", "s\nk\nk\nINSTALL\nnext-line\n", true},
		{"declined", "s\nk\nk\ny\nquit\n", false},
		{"cancelled", "quit\n", false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			var output bytes.Buffer
			called := false
			reader := strings.NewReader(tc.input)
			err := runLiveAccessibleWithHubsMode(
				reader, &output, client, info, nil, true,
				func(s *liveSelection) error {
					if tc.name == "typed ahead" && reader.Len() != len("next-line\n") {
						t.Fatal("Installation consumed input before elevation")
					}
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

func TestInstallationReviewAndCompletionWarnAboutDiscoveryAndFirewall(t *testing.T) {
	client := fixtureClient(t)
	info, err := client.inspect()
	if err != nil {
		t.Fatal(err)
	}
	s := newLiveSelection(client, info, nil)
	s.hubChoice = "skip"
	s.recordHubChoice("skip")
	s.firewalldActive = true
	for i := range s.inspection.Checks {
		if s.inspection.Checks[i].ID == "avahi_discovery" {
			s.inspection.Checks[i].Status = "warning"
		}
	}
	review := s.installPreview()
	for _, phrase := range []string{
		"WARNING: Avahi discovery is not confirmed",
		"WARNING: firewalld is active",
		"TCP 8765 may be blocked",
	} {
		if !strings.Contains(review, phrase) {
			t.Errorf("Review missing warning %q: %s", phrase, review)
		}
	}
	var completion bytes.Buffer
	s.showNetworkWarnings(&completion)
	if !strings.Contains(completion.String(), "Scan nearby may not find") ||
		!strings.Contains(completion.String(), "firewalld is active") {
		t.Fatalf("Completion hid network warnings: %s", completion.String())
	}
	s.firewalldActive = false
	for i := range s.inspection.Checks {
		if s.inspection.Checks[i].ID == "avahi_discovery" {
			s.inspection.Checks[i].Status = "passed"
		}
	}
	if warnings := s.networkWarnings(); len(warnings) != 0 {
		t.Fatalf("Healthy network should not have warnings: %+v", warnings)
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

func TestUninstallRequiresSubmittedLiteralConfirmation(t *testing.T) {
	for _, input := range []string{"", "UNINSTALL", "INSTALL\n", "yes\n", "uninstall\n", "UNINSTALL\n"} {
		var out bytes.Buffer
		calls := 0
		err := confirmUninstall(strings.NewReader(input), &out, func(req privilegedRequest) (privilegedResult, error) {
			calls++
			if req.SchemaVersion != 2 || req.Action != "uninstall" || req.Power != "" || req.WOLInterface != nil {
				t.Fatalf("Unexpected uninstall request: %+v", req)
			}
			return privilegedResult{Status: "uninstalled", IdentityPreserved: "verified"}, nil
		})
		if err != nil {
			t.Fatal(err)
		}
		want := 0
		if input == "UNINSTALL\n" {
			want = 1
		}
		if calls != want {
			t.Fatalf("Confirmation %q invoked authorization %d times", input, calls)
		}
		for _, phrase := range []string{"control key", "recovery snapshots", "Wake-on-LAN", "SmartThings device will go offline", "not a full purge"} {
			if !strings.Contains(out.String(), phrase) {
				t.Fatalf("Review missing %q", phrase)
			}
		}
	}
}

func TestUninstallCleanupAndRollbackMessages(t *testing.T) {
	var out bytes.Buffer
	err := confirmUninstall(strings.NewReader("UNINSTALL\n"), &out, func(req privilegedRequest) (privilegedResult, error) {
		return privilegedResult{Status: "uninstalled_cleanup_required", IdentityPreserved: "not_verified"}, nil
	})
	if err != nil || !strings.Contains(out.String(), "-recover") {
		t.Fatalf("Missing cleanup instruction: %s (%v)", out.String(), err)
	}
	out.Reset()
	showRecoveryOutcome(&out, privilegedResult{RecoveryStatus: "rolled_back", RecoveryOperation: "uninstall"})
	if !strings.Contains(out.String(), "uninstall was undone") || !strings.Contains(out.String(), "-uninstall again") {
		t.Fatal(out.String())
	}
	out.Reset()
	showRecoveryOutcome(&out, privilegedResult{RecoveryStatus: "cleaned", RecoveryOperation: "uninstall"})
	if !strings.Contains(out.String(), "No uninstall or installation was resumed") {
		t.Fatal(out.String())
	}
}

func TestConfirmationDoesNotConsumeTypedAheadInput(t *testing.T) {
	for _, word := range []string{"INSTALL", "UNINSTALL", "RECOVER"} {
		reader := strings.NewReader(word + "\nnext-line\n")
		line, err := readConfirmationLine(reader)
		if err != nil || line != word {
			t.Fatalf("Confirmation: %q %v", line, err)
		}
		if reader.Len() != len("next-line\n") {
			t.Fatal("Confirmation consumed input intended for the next prompt")
		}
	}
	reader := strings.NewReader("UNINSTALL\nnext-line\n")
	var out bytes.Buffer
	calls := 0
	err := confirmUninstall(reader, &out, func(req privilegedRequest) (privilegedResult, error) {
		calls++
		if reader.Len() != len("next-line\n") {
			t.Fatal("Uninstall consumed input before elevation")
		}
		return privilegedResult{Status: "uninstalled", IdentityPreserved: "verified"}, nil
	})
	if err != nil || calls != 1 {
		t.Fatalf("Confirmation failed: %v, calls=%d", err, calls)
	}
	if _, err := readConfirmationLine(strings.NewReader(strings.Repeat("x", 129) + "\n")); err == nil {
		t.Fatal("Unbounded confirmation accepted")
	}
}

func TestInstallationOutcomeUsesIdentityAndPowerChoices(t *testing.T) {
	s := &liveSelection{firewalldActive: true}
	for _, identity := range []string{"verified", "not_verified"} {
		for _, power := range []string{"preserve", "enable", "disable"} {
			t.Run(identity+"_"+power, func(t *testing.T) {
				var out bytes.Buffer
				showInstallationOutcome(&out, s,
					privilegedRequest{Action: "install", Power: power},
					privilegedResult{Status: "installed_cleanup_required", IdentityPreserved: identity})
				text := out.String()
				for _, phrase := range []string{"refresh", "Scan nearby", "Avahi discovery is not confirmed",
					"firewalld is active", "persistent WOL configuration were not performed", "-recover",
					"https://bestow-regional.api.smartthings.com/invite/1J2Qy7ZkxL20",
					"Never forward the agent port to the Internet"} {
					if !strings.Contains(text, phrase) {
						t.Fatalf("missing %q: %s", phrase, text)
					}
				}
				if identity == "verified" {
					if !strings.Contains(text, "Existing agent identity verified.") ||
						!strings.Contains(text, "Only if no device is registered") ||
						strings.Contains(text, "For first-time onboarding") {
						t.Fatal(text)
					}
				} else if !strings.Contains(text, "For first-time onboarding") ||
					strings.Contains(text, "Existing agent identity verified.") {
					t.Fatal(text)
				}
				if power != "disable" {
					for _, phrase := range []string{"sudo cat /var/lib/linux-host-agent/control-token",
						"su -c 'cat /var/lib/linux-host-agent/control-token'",
						"do not record, screenshot, log or share", "allowPowerCommands"} {
						if !strings.Contains(text, phrase) {
							t.Fatalf("missing private key guidance %q: %s", phrase, text)
						}
					}
				}
				switch power {
				case "enable":
					if !strings.Contains(text, "allowPowerCommands") || !strings.Contains(text, "controlKey") ||
						!strings.Contains(text, "does not verify key equality") {
						t.Fatal(text)
					}
				case "preserve":
					if !strings.Contains(text, "unchanged and already configured control key normally needs no update") {
						t.Fatal(text)
					}
				case "disable":
					if !strings.Contains(text, "no control key setup is needed") || strings.Contains(text, "allowPower") ||
						strings.Contains(text, "/var/lib/linux-host-agent/control-token") {
						t.Fatal(text)
					}
				}
			})
		}
	}
}

func TestNetworkObservationNeverInfersConnectivityFromMissingFirewallEvidence(t *testing.T) {
	info := apiInspect{}
	got := observeNetwork(info, false)
	if got.AvahiPrerequisites != "not_verified" || got.Firewalld != "not_verified" {
		t.Fatalf("missing probes claimed verification: %+v", got)
	}
	info.Checks = []apiCheck{{ID: "avahi_discovery", Status: "passed"}}
	got = observeNetwork(info, true)
	if got.AvahiPrerequisites != "passed" || got.Firewalld != "active" {
		t.Fatalf("confirmed observations lost: %+v", got)
	}
}

func TestInstallationOutcomeDistinguishesNewInstallAndUnverifiedUpgrade(t *testing.T) {
	for _, tc := range []struct {
		action   string
		identity string
		want     string
		absent   string
	}{
		{"install", "not_verified", "New agent installation completed;", "Previous agent identity was not verified."},
		{"upgrade", "not_verified", "Previous agent identity was not verified.", "New agent installation completed;"},
		{"install", "verified", "Existing agent identity verified.", "New agent installation completed;"},
	} {
		var out bytes.Buffer
		showInstallationOutcome(&out, &liveSelection{},
			privilegedRequest{Action: tc.action, Power: "preserve"},
			privilegedResult{Status: "installed", IdentityPreserved: tc.identity})
		if !strings.Contains(out.String(), tc.want) || strings.Contains(out.String(), tc.absent) {
			t.Fatalf("unexpected wording: %s", out.String())
		}
	}
}
