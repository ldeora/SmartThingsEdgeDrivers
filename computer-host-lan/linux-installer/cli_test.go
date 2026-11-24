package main

import (
	"errors"
	"strings"
	"testing"
)

func TestCLIRejectsAmbiguousOrUnauthorizedOptions(t *testing.T) {
	cases := [][]string{
		nil, {"install"}, {"install", "--confirm", "install"},
		{"install", "--confirm", "UPGRADE"}, {"upgrade", "--confirm", "INSTALL"},
		{"install", "--confirm", "INSTALL", "--confirm", "INSTALL"},
		{"install", "--confirm", "INSTALL", "--power", "enable", "--power", "disable"},
		{"install", "--confirm", "INSTALL", "--power"},
		{"install", "--confirm", "INSTALL", "--power", "enabled"},
		{"install", "--confirm", "INSTALL", "--wol-interface", ".."},
		{"install", "--confirm", "INSTALL", "--wol-interface", ""},
		{"install", "--confirm", "INSTALL", "--elevation", "su"},
		{"install", "--confirm", "INSTALL", "--configure-wol", "yes"},
		{"install", "--confirm", "INSTALL", "--adopt-retained-state", "yes"},
		{"install", "--confirm", "INSTALL", "--python", "/usr/bin/python3"},
		{"install", "--confirm", "INSTALL", "--source", "/tmp/source"},
		{"install", "--confirm", "INSTALL", "-root-bootstrap"},
		{"uninstall", "--confirm", "UNINSTALL", "--power", "preserve"},
		{"recover", "--confirm", "RECOVER", "--wol-interface", "eth0"},
		{"status", "--confirm", ""}, {"status", "--elevation", "auto", "extra"},
		{"rollback", "--confirm", "ROLLBACK"}, {"status", "--request", "{}"},
		{"plan"}, {"plan", "--action", "uninstall"},
		{"plan", "--action", "install", "--confirm", "INSTALL"},
		{"plan", "--action", "upgrade", "--elevation", "auto"},
		{"plan", "--action", "repair", "--action", "upgrade"},
		{"upgrade", "--confirm", "UPGRADE", "--action", "install"},
	}
	for _, args := range cases {
		t.Run(strings.Join(args, "_"), func(t *testing.T) {
			result, code := executeCLI(args, false,
				func(cliOptions) (cliPrepared, error) {
					t.Fatal("invalid arguments reached preflight")
					return cliPrepared{}, nil
				}, func(privilegedRequest, bool, string) (privilegedResult, error) {
					t.Fatal("invalid arguments reached authorization")
					return privilegedResult{}, nil
				})
			if code != 2 || result.ErrorCode != "invalid_cli_arguments" || result.SecretsIncluded {
				t.Fatalf("unexpected rejection: %+v, %d", result, code)
			}
		})
	}
}

func TestCLIRejectsRootBeforePreflight(t *testing.T) {
	for _, args := range [][]string{{"status"}, {"install", "--confirm", "INSTALL"}} {
		result, code := executeCLI(args, true, nil, nil)
		if code != 2 || result.ErrorCode != "run_as_normal_user" {
			t.Fatalf("root invocation not rejected: %+v, %d", result, code)
		}
	}
}

func TestCLIInstallPreflightReusesWizardAndRequiresMatchingAction(t *testing.T) {
	api := fixtureClient(t)
	info, err := api.inspect()
	if err != nil {
		t.Fatal(err)
	}
	for _, action := range []string{"install", "upgrade", "repair"} {
		opts, err := parseCLI([]string{action, "--confirm", strings.ToUpper(action),
			"--power", "disable", "--wol-interface", "LAN0", "--elevation", "sudo"})
		if err != nil {
			t.Fatal(err)
		}
		detected := info
		detected.Installation.Detected = action != "install"
		req, err := cliInstallRequest(opts, api, detected)
		if err != nil || req.Action != action || req.Power != "disable" ||
			req.WOLInterface == nil || *req.WOLInterface != "LAN0" || req.SchemaVersion != 1 {
			t.Fatalf("unexpected request: %+v, %v", req, err)
		}
		detected.Installation.Detected = !detected.Installation.Detected
		if _, err := cliInstallRequest(opts, api, detected); err == nil {
			t.Fatal("operation mismatch accepted")
		}
	}
	opts, err := parseCLI([]string{"upgrade", "--confirm", "UPGRADE"})
	if err != nil {
		t.Fatal(err)
	}
	info.Python.VersionSupported = false
	if _, err := cliInstallRequest(opts, api, info); err == nil {
		t.Fatal("unsupported interpreter accepted")
	}
}

func TestCLINoninstallRequestsRetainProtectedSchema(t *testing.T) {
	for _, action := range []string{"status", "uninstall", "recover"} {
		args := []string{action}
		if action != "status" {
			args = append(args, "--confirm", strings.ToUpper(action))
		}
		result, code := executeCLI(args, false, prepareCLIRequest,
			func(req privilegedRequest, interactive bool, method string) (privilegedResult, error) {
				version := 1
				reply := privilegedResult{SchemaVersion: 1, Operation: action, Status: "passed"}
				if action == "uninstall" {
					version = 2
					reply.Status = "uninstalled"
					reply.IdentityPreserved = "verified"
				} else if action == "recover" {
					reply.RecoveryStatus = "nothing_to_recover"
				} else {
					reply.PrivilegedTransactionState = "none"
				}
				if req.Action != action || req.SchemaVersion != version || req.Power != "" ||
					req.WOLInterface != nil || interactive || method != "auto" {
					t.Fatalf("wrong authorization request: %+v, %v, %s", req, interactive, method)
				}
				return reply, nil
			})
		if code != 0 || result.Operation != action {
			t.Fatalf("unexpected outcome: %+v, %d", result, code)
		}
	}
}

func TestCLIResultAndExitCodeContracts(t *testing.T) {
	for _, tc := range []struct {
		name   string
		reply  privilegedResult
		err    error
		code   int
		status string
		error  string
	}{
		{"success", privilegedResult{SchemaVersion: 1, Operation: "upgrade", Status: "installed", IdentityPreserved: "verified"}, nil, 0, "installed", ""},
		{"cleanup", privilegedResult{SchemaVersion: 1, Operation: "upgrade", Status: "installed_cleanup_required"}, nil, 3, "installed_cleanup_required", ""},
		{"recovery", privilegedResult{SchemaVersion: 1, Operation: "upgrade", Status: "error", ErrorCode: "recovery_required"}, errors.New("fixture"), 3, "error", "recovery_required"},
		{"rollback", privilegedResult{SchemaVersion: 1, Operation: "upgrade", Status: "error", ErrorCode: "rolled_back"}, errors.New("fixture"), 1, "error", "rolled_back"},
		{"authorization unavailable", privilegedResult{}, &authorizationUnavailableError{cause: errors.New("private path")}, 1, "error", "authorization_unavailable"},
		{"lost reply", privilegedResult{}, errors.New("private output"), 1, "error", "outcome_unknown"},
		{"wrong action", privilegedResult{SchemaVersion: 1, Operation: "install", Status: "installed"}, nil, 1, "error", "outcome_unknown"},
		{"secret flag", privilegedResult{SchemaVersion: 1, Operation: "upgrade", Status: "installed", SecretsIncluded: true}, nil, 1, "error", "outcome_unknown"},
		{"unknown code", privilegedResult{SchemaVersion: 1, Operation: "upgrade", Status: "error", ErrorCode: "private output"}, errors.New("private output"), 1, "error", "outcome_unknown"},
		{"conflicting success", privilegedResult{SchemaVersion: 1, Operation: "upgrade", Status: "installed"}, errors.New("fixture"), 1, "error", "outcome_unknown"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			result, code := executeCLI([]string{"upgrade", "--confirm", "UPGRADE", "--elevation", "doas"}, false,
				func(o cliOptions) (cliPrepared, error) {
					return cliPrepared{request: privilegedRequest{SchemaVersion: 1, Action: o.action, Power: o.power}}, nil
				}, func(req privilegedRequest, interactive bool, method string) (privilegedResult, error) {
					if interactive || method != "doas" || req.Power != "preserve" {
						t.Fatal("incorrect authorization options")
					}
					return tc.reply, tc.err
				})
			if code != tc.code || result.Status != tc.status || result.ErrorCode != tc.error || result.SecretsIncluded {
				t.Fatalf("unexpected result: %+v, %d", result, code)
			}
		})
	}
}

func TestCLIPreflightFailureDoesNotAuthorize(t *testing.T) {
	result, code := executeCLI([]string{"install", "--confirm", "INSTALL"}, false,
		func(cliOptions) (cliPrepared, error) {
			return cliPrepared{}, errors.New("private path")
		}, nil)
	if code != 1 || result.ErrorCode != "preflight_failed" || result.SecretsIncluded {
		t.Fatalf("unexpected result: %+v, %d", result, code)
	}
}

func TestCLIStatusExitCodes(t *testing.T) {
	for _, tc := range []struct {
		state string
		code  int
	}{
		{"none", 0},
		{"in_progress", 3},
		{"incomplete", 3},
		{"recovery_required", 3},
		{"", 1},
	} {
		t.Run(tc.state, func(t *testing.T) {
			result, code := executeCLI([]string{"status"}, false, prepareCLIRequest,
				func(req privilegedRequest, interactive bool, method string) (privilegedResult, error) {
					return privilegedResult{
						SchemaVersion: 1, Operation: req.Action, Status: "passed",
						PrivilegedTransactionState: tc.state,
					}, nil
				})
			if code != tc.code || result.SecretsIncluded {
				t.Fatalf("unexpected status outcome: %+v, %d", result, code)
			}
			if tc.state == "" {
				if result.ErrorCode != "outcome_unknown" {
					t.Fatalf("empty state accepted: %+v", result)
				}
			} else if result.Status != "passed" || result.PrivilegedTransactionState != tc.state {
				t.Fatalf("status evidence lost: %+v", result)
			}
		})
	}
}

func TestCLIPlanUsesSharedPreflightWithoutAuthorization(t *testing.T) {
	api := fixtureClient(t)
	info, err := api.inspect()
	if err != nil {
		t.Fatal(err)
	}
	for _, action := range []string{"install", "upgrade", "repair"} {
		info.Installation.Detected = action != "install"
		result, code := executeCLI([]string{"plan", "--action", action, "--power", "enable",
			"--wol-interface", "LAN0"}, false,
			func(o cliOptions) (cliPrepared, error) {
				return cliInstallPreflight(o, api, info, true)
			}, func(privilegedRequest, bool, string) (privilegedResult, error) {
				t.Fatal("read-only plan reached authorization")
				return privilegedResult{}, nil
			})
		if code != 0 || result.Status != "planned" || result.Operation != "plan" ||
			result.PlannedAction != action || result.Plan == nil || result.Plan.ChangesApplied ||
			result.Plan.RuntimeVerified || result.Plan.SecretsIncluded || result.SecretsIncluded ||
			result.PrivilegedTransactionState != "unknown" || result.IdentityPreserved != "not_verified" ||
			result.Plan.PowerOption != "enable" || !result.Plan.WOLInterfaceRequested ||
			result.Network == nil || result.Network.Firewalld != "active" || result.Onboarding != "" {
			t.Fatalf("unexpected plan: %+v, %d", result, code)
		}
	}
	info.Installation.Detected = true
	result, code := executeCLI([]string{"plan", "--action", "install"}, false,
		func(o cliOptions) (cliPrepared, error) {
			return cliInstallPreflight(o, api, info, false)
		}, nil)
	if code != 1 || result.ErrorCode != "preflight_failed" || result.Plan != nil {
		t.Fatalf("mismatched plan accepted: %+v, %d", result, code)
	}
}

func TestCLIInstallOutcomeCarriesScopedNetworkAndOnboarding(t *testing.T) {
	for _, identity := range []string{"verified", "not_verified"} {
		api := fixtureClient(t)
		info, err := api.inspect()
		if err != nil {
			t.Fatal(err)
		}
		result, code := executeCLI([]string{"upgrade", "--confirm", "UPGRADE"}, false,
			func(o cliOptions) (cliPrepared, error) {
				return cliInstallPreflight(o, api, info, false)
			}, func(req privilegedRequest, interactive bool, method string) (privilegedResult, error) {
				return privilegedResult{SchemaVersion: 1, Operation: req.Action,
					Status: "installed", IdentityPreserved: identity}, nil
			})
		want := "check_or_discover"
		if identity == "verified" {
			want = "check_existing_device"
		}
		if code != 0 || result.Onboarding != want || result.Network == nil ||
			result.Network.Firewalld != "not_verified" || result.Plan != nil {
			t.Fatalf("unexpected completion: %+v, %d", result, code)
		}
	}
}
