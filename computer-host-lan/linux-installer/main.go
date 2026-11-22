// Computer Host LAN Linux installer UX spike.
//
// This is an intentionally inert demonstration of the planned wizard.
// It performs no system probes, privilege escalation, downloads, network
// discovery, credential access, file writes, or installation.
package main

import (
	"flag"
	"fmt"
	"net"
	"os"
	"strings"

	"charm.land/huh/v2"
)

type selection struct {
	action      string
	hubChoice   string
	manualHub   string
	enablePower bool
	enableWOL   bool
}

func validHubIPv4(raw string) error {
	value := strings.TrimSpace(raw)
	ip := net.ParseIP(value)
	if ip == nil || ip.To4() == nil || value != raw {
		return fmt.Errorf("enter a valid IPv4 address")
	}
	v4 := ip.To4()
	if v4.IsUnspecified() || v4.IsLoopback() || v4.IsMulticast() ||
		v4.IsLinkLocalUnicast() || v4.Equal(net.IPv4bcast) {
		return fmt.Errorf("enter a reachable SmartThings hub IPv4 address")
	}
	return nil
}

func (s selection) hubName() string {
	switch s.hubChoice {
	case "demo-a":
		return "Demo hub A (192.0.2.10; TEST-NET address)"
	case "demo-b":
		return "Demo hub B (198.51.100.24; TEST-NET address)"
	case "manual":
		return s.manualHub + " (user-entered; not verified)"
	default:
		return "None selected"
	}
}

func (s selection) preview() string {
	action := "Fresh installation"
	if s.action == "upgrade" {
		action = "Existing installation upgrade"
	}
	return fmt.Sprintf(
		"DEMO ONLY — NO CHANGES WILL BE MADE\n"+
			"Action: %s\n"+
			"Compatibility: simulated, NOT CHECKED\n"+
			"Hub: %s\n"+
			"Monitoring: enabled\n"+
			"Power management: %t\n"+
			"Persistent Wake-on-LAN: %t\n"+
			"Next: root-authorized transaction and runtime verification (NOT IMPLEMENTED)",
		action, s.hubName(), s.enablePower, s.enableWOL,
	)
}

func form(accessible bool, fields ...huh.Field) error {
	return huh.NewForm(huh.NewGroup(fields...)).WithAccessible(accessible).Run()
}

func run(accessible bool) error {
	fmt.Println("COMPUTER HOST LAN — LINUX WIZARD EXPERIMENT")
	fmt.Println("DEMO ONLY: no discovery, probing, installation, key access or system changes.")
	fmt.Println()

	s := selection{}
	err := form(accessible,
		huh.NewSelect[string]().
			Title("What would you like to do?").
			Description("Both choices use simulated installation state.").
			Options(
				huh.NewOption("New installation (demo)", "install"),
				huh.NewOption("Upgrade an existing installation (demo)", "upgrade"),
			).
			Value(&s.action),
	)
	if err != nil {
		return err
	}

	// Future: replace this explicitly simulated screen with read-only probes.
	fmt.Println("\nDEMO ONLY — compatibility preview (not probed):")
	fmt.Println("  systemd: simulated; Python 3.10+: simulated; Avahi: simulated.")
	fmt.Println("  No network checks or system modifications have occurred.")\n\tfmt.Println()

	err = form(accessible,
		huh.NewSelect[string]().
			Title("Select a simulated SmartThings hub").
			Description("TEST-NET addresses are examples, not discovered hubs.").
			Options(
				huh.NewOption("Demo hub A (192.0.2.10)", "demo-a"),
				huh.NewOption("Demo hub B (198.51.100.24)", "demo-b"),
				huh.NewOption("Enter an IPv4 address (validation demo)", "manual"),
				huh.NewOption("Continue without selecting a hub", "none"),
			).
			Value(&s.hubChoice),
	)
	if err != nil {
		return err
	}
	if s.hubChoice == "manual" {
		err = form(accessible,
			huh.NewInput().
				Title("SmartThings hub IPv4").
				Description("Validation only: no connection is attempted.").
				Placeholder("192.168.1.20").
				Validate(validHubIPv4).
				Value(&s.manualHub),
		)
		if err != nil {
			return err
		}
	}

	// Simulate upgrade defaults to exercise preserving existing selections.
	if s.action == "upgrade" {
		s.enablePower = true
	}

	err = form(accessible,
		huh.NewConfirm().
			Title("Enable optional remote power management?").
			Description("Fresh installs default to off; upgrades keep the demo setting.").
			Affirmative("Enabled").
			Negative("Disabled").
			Value(&s.enablePower),
		huh.NewConfirm().
			Title("Configure persistent Wake-on-LAN?").
			Description("Separate opt-in; real NIC detection is NOT implemented here.").
			Affirmative("Enabled").
			Negative("Disabled").
			Value(&s.enableWOL),
	)
	if err != nil {
		return err
	}

	fmt.Println("\n" + s.preview() + "\n")

	var showResult bool
	err = form(accessible,
		huh.NewConfirm().
			Title("Show the simulated completion screen?").
			Description("This never invokes the existing installer or sudo.").
			Affirmative("Show demo").
			Negative("Exit").
			Value(&showResult),
	)
	if err != nil {
		return err
	}
	if !showResult {
		fmt.Println("Demo exited without making any changes.")
		return nil
	}
	fmt.Println("\nDEMO COMPLETE — nothing was installed, changed or verified.")
	fmt.Println("Future release: health verification, onboarding and safeguarded credentials.")
	return nil
}

func main() {
	accessible := flag.Bool("accessible", false, "use Huh accessible mode (screen readers)")
	preview := flag.Bool("preview", false, "print a sample plan without starting a TUI")
	flag.Parse()
	if flag.NArg() != 0 {
		fmt.Fprintln(os.Stderr, "unexpected arguments; use -h for help")
		os.Exit(2)
	}
	if *preview {
		fmt.Println((selection{action: "install", hubChoice: "none"}).preview())
		return
	}
	if err := run(*accessible); err != nil {
		fmt.Fprintln(os.Stderr, "Demo stopped:", err)
		os.Exit(1)
	}
}
