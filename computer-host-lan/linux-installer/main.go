// Computer Host LAN Linux installer: consent-gated setup and explicit diagnostics.
//
// Demo mode performs no installation, inspection, network discovery or writes.
// Live preview cannot install or elevate, but may explicitly browse local
// mDNS via Avahi for SmartThings hub candidates. No endpoint is contacted.
// The demo IPs are reserved documentation addresses and are never contacted.
package main

import (
	"bufio"
	"errors"
	"flag"
	"fmt"
	"io"
	"net/netip"
	"os"
	"strings"

	"charm.land/huh/v2"
	"github.com/charmbracelet/x/term"
)

var cgnat = netip.MustParsePrefix("100.64.0.0/10")

type selection struct {
	action      string
	hubChoice   string
	manualHub   string
	powerChoice string
	wolChoice   string
	acceptWAN   bool
	showResult  bool
}

// We accept only literal, canonical IPv4 syntax, never an IPv4-mapped IPv6
// representation. A public address is not automatically invalid, but must be
// explicitly acknowledged before the *demo* advances.
func validHubIPv4(raw string) error {
	if strings.TrimSpace(raw) != raw {
		return fmt.Errorf("enter an IPv4 address without surrounding spaces")
	}
	addr, err := netip.ParseAddr(raw)
	if err != nil || !addr.Is4() || addr.String() != raw {
		return fmt.Errorf("enter a canonical IPv4 address (not an IPv6 representation)")
	}
	if addr.IsUnspecified() || addr.IsLoopback() || addr.IsMulticast() ||
		addr.IsLinkLocalUnicast() || addr == netip.MustParseAddr("255.255.255.255") {
		return fmt.Errorf("enter a usable, unicast SmartThings hub IPv4 address")
	}
	return nil
}

func hubAddressWarning(raw string) string {
	if err := validHubIPv4(raw); err != nil {
		return ""
	}
	addr := netip.MustParseAddr(raw)
	if !addr.IsPrivate() && !cgnat.Contains(addr) {
		return "WARNING: address is outside RFC1918 and 100.64/10 local address ranges. " +
			"Do not create an unrestricted or public firewall rule. Confirm your trusted LAN topology."
	}
	return ""
}

func (s selection) hubName() string {
	switch s.hubChoice {
	case "demo-a":
		return "Demo hub A (192.0.2.10; reserved TEST-NET example)"
	case "demo-b":
		return "Demo hub B (198.51.100.24; reserved TEST-NET example)"
	case "manual":
		return s.manualHub + " (user-entered; not discovered or contacted)"
	default:
		return "None selected"
	}
}

func (s selection) effectivePower() bool {
	switch s.powerChoice {
	case "enabled":
		return true
	case "disabled":
		return false
	default:
		return s.action == "upgrade" // simulated pre-existing setting
	}
}

func (s selection) effectiveWOL() bool {
	switch s.wolChoice {
	case "enabled":
		return true
	default:
		return false // simulated existing/new setting
	}
}

func (s selection) preview() string {
	action := "Fresh installation"
	if s.action == "upgrade" {
		action = "Existing installation upgrade"
	}
	preview := fmt.Sprintf(
		"DEMO ONLY — NO CHANGES WILL BE MADE\n"+
			"Action: %s\n"+
			"Compatibility: simulated, NOT CHECKED\n"+
			"Hub: %s\n"+
			"Monitoring: enabled\n"+
			"Power management: %t\n"+
			"Persistent Wake-on-LAN: %t\n"+
			"Next: root-authorized transaction and runtime verification (NOT IMPLEMENTED)",
		action, s.hubName(), s.effectivePower(), s.effectiveWOL(),
	)
	if s.hubChoice == "manual" {
		if warning := hubAddressWarning(s.manualHub); warning != "" {
			preview += "\n" + warning
		}
	}
	return preview
}

// This is one single Huh form with multiple groups (pages). Unlike separate
// forms, it supports going Back to prior pages with Shift+Tab and preserving
// changed values. The manual IPv4 and public-address acknowledgement groups
// are conditional and never displayed for other hub choices.
func interactiveForm(s *selection) *huh.Form {
	return huh.NewForm(
		huh.NewGroup(
			huh.NewSelect[string]().
				Title("Computer Host LAN — What would you like to do?").
				Description("EXPERIMENT ONLY: no real installation state is inspected.").
				Options(
					huh.NewOption("New installation (demo)", "install"),
					huh.NewOption("Upgrade existing installation (demo)", "upgrade"),
				).
				Value(&s.action),
		).Title("1. Welcome"),

		huh.NewGroup(
			huh.NewSelect[string]().
				Title("Select a SIMULATED SmartThings hub").
				Description("Example TEST-NET addresses were not discovered; no network access occurs.").
				Options(
					huh.NewOption("Demo hub A (192.0.2.10)", "demo-a"),
					huh.NewOption("Demo hub B (198.51.100.24)", "demo-b"),
					huh.NewOption("Enter IPv4 manually (validation only)", "manual"),
					huh.NewOption("Continue without a hub", "none"),
				).
				Value(&s.hubChoice),
		).Title("2. Hub selection"),

		huh.NewGroup(
			huh.NewInput().
				Title("SmartThings hub IPv4").
				Description("No connection will be attempted.").
				Placeholder("192.168.1.20").
				Validate(validHubIPv4).
				Value(&s.manualHub),
		).Title("3. Manual address").WithHideFunc(func() bool { return s.hubChoice != "manual" }),

		huh.NewGroup(
			huh.NewConfirm().
				Title("Acknowledge that this is not a private/local IPv4 address?").
				Description("No firewall changes will be made. Use Shift+Tab to change the address.").
				Affirmative("I understand").
				Negative("Not yet").
				Validate(func(accepted bool) error {
					if !accepted {
						return errors.New("review the address or explicitly acknowledge the warning")
					}
					return nil
				}).
				Value(&s.acceptWAN),
		).Title("Address warning").WithHideFunc(func() bool {
			return s.hubChoice != "manual" || hubAddressWarning(s.manualHub) == ""
		}),

		huh.NewGroup(
			huh.NewSelect[string]().
				Title("Remote power management").
				Description("Keep means OFF on a new install and retains the demo ON setting on upgrade.").
				Options(
					huh.NewOption("Keep current/default setting (recommended)", "keep"),
					huh.NewOption("Enable", "enabled"),
					huh.NewOption("Disable", "disabled"),
				).
				Value(&s.powerChoice),
			huh.NewSelect[string]().
				Title("Persistent Wake-on-LAN").
				Description("Separate opt-in; NIC checks and WOL changes are NOT implemented.").
				Options(
					huh.NewOption("Keep current/default setting (recommended)", "keep"),
					huh.NewOption("Enable", "enabled"),
					huh.NewOption("Disable", "disabled"),
				).
				Value(&s.wolChoice),
		).Title("4. Features"),

		huh.NewGroup(
			huh.NewConfirm().
				Title("Review the SIMULATED plan and show the demo result?").
				// Huh hashes bound inputs to invalidate cached descriptions.
				// Binding the unexported selection struct would always hash to
				// the same value; bind the individual field pointers instead.
				DescriptionFunc(func() string { return s.preview() },
					[]any{&s.action, &s.hubChoice, &s.manualHub, &s.powerChoice, &s.wolChoice}).
				Affirmative("Show result").
				Negative("Exit without changes").
				Value(&s.showResult),
		).Title("5. Review"),
	)
}

// A character device such as /dev/null is not necessarily a terminal.
// Use the same terminal predicate for interactive UI and elevation selection.
func stdinIsTerminal() bool {
	return term.IsTerminal(os.Stdin.Fd())
}

func runInteractive(w io.Writer) error {
	if !stdinIsTerminal() {
		return errors.New("interactive demo needs a terminal; use -demo -accessible for plain prompts or -preview")
	}
	s := selection{action: "install", hubChoice: "none", powerChoice: "keep", wolChoice: "keep"}
	fmt.Fprintln(w, "COMPUTER HOST LAN — LINUX WIZARD EXPERIMENT")
	fmt.Fprintln(w, "DEMO ONLY: no probing, discovery, installation, key access or system changes.")
	err := interactiveForm(&s).Run()
	if errors.Is(err, huh.ErrUserAborted) {
		fmt.Fprintln(w, "Cancelled; no changes made.")
		return nil
	}
	if err != nil {
		return err
	}
	fmt.Fprintln(w, "\n"+s.preview())
	if s.showResult {
		fmt.Fprintln(w, "DEMO COMPLETE — nothing was installed, changed or verified.")
	} else {
		fmt.Fprintln(w, "Demo exited without making any changes.")
	}
	return nil
}

// Accessible mode deliberately uses plain, ANSI-free line prompts. Huh v2.0.3's
// accessible runner does not respect group WithHideFunc and can emit ANSI style
// codes. Keep conditional fields and Back navigation correct until upstream
// supports both in accessible mode; no terminal raw mode is entered here.
func runAccessible(reader io.Reader, writer io.Writer) error {
	s := selection{action: "install", hubChoice: "none", powerChoice: "keep", wolChoice: "keep"}
	sc := bufio.NewScanner(reader)
	fmt.Fprintln(writer, "COMPUTER HOST LAN — PLAIN-TEXT WIZARD EXPERIMENT")
	fmt.Fprintln(writer, "DEMO ONLY. Type 'back' for a previous step or 'quit' to cancel.")
	step := 0
	for step <= 5 {
		var prompt string
		switch step {
		case 0:
			prompt = "Action: [1] New installation [2] Upgrade demo: "
		case 1:
			prompt = "Hub: [1] Demo A [2] Demo B [3] Manual IPv4 [4] None: "
		case 2:
			if s.hubChoice != "manual" {
				step++
				continue
			}
			prompt = "Hub IPv4 (never contacted): "
		case 3:
			prompt = "Power: [k] Keep default/current [y] Enable [n] Disable: "
		case 4:
			prompt = "Wake-on-LAN: [k] Keep default/current [y] Enable [n] Disable: "
		case 5:
			fmt.Fprintln(writer, "\n"+s.preview())
			prompt = "Show simulated result? [y/N]: "
		}
		fmt.Fprint(writer, prompt)
		if !sc.Scan() {
			if err := sc.Err(); err != nil {
				return err
			}
			fmt.Fprintln(writer, "\nCancelled; no changes made.")
			return nil
		}
		input := strings.TrimSpace(sc.Text())
		switch strings.ToLower(input) {
		case "quit", "exit", "q":
			fmt.Fprintln(writer, "Cancelled; no changes made.")
			return nil
		case "back":
			if step > 0 {
				step--
				if step == 2 && s.hubChoice != "manual" {
					step--
				}
			} else {
				fmt.Fprintln(writer, "Already at the first step.")
			}
			continue
		}
		valid := true
		switch step {
		case 0:
			switch input {
			case "1":
				s.action = "install"
			case "2":
				s.action = "upgrade"
			default:
				valid = false
			}
		case 1:
			switch input {
			case "1":
				s.hubChoice = "demo-a"
			case "2":
				s.hubChoice = "demo-b"
			case "3":
				s.hubChoice = "manual"
			case "4":
				s.hubChoice = "none"
			default:
				valid = false
			}
		case 2:
			if err := validHubIPv4(input); err != nil {
				fmt.Fprintln(writer, err)
				valid = false
			} else {
				s.manualHub = input
				if warning := hubAddressWarning(input); warning != "" {
					fmt.Fprintln(writer, warning)
					fmt.Fprint(writer, "Explicitly acknowledge this address? [y/N]: ")
					if !sc.Scan() || !strings.EqualFold(strings.TrimSpace(sc.Text()), "y") {
						fmt.Fprintln(writer, "Address not accepted; choose another or type 'quit'.")
						valid = false
					}
				}
			}
		case 3, 4:
			var choice string
			switch strings.ToLower(input) {
			case "k", "":
				choice = "keep"
			case "y":
				choice = "enabled"
			case "n":
				choice = "disabled"
			default:
				valid = false
			}
			if valid {
				if step == 3 {
					s.powerChoice = choice
				} else {
					s.wolChoice = choice
				}
			}
		case 5:
			if strings.EqualFold(input, "y") {
				s.showResult = true
			} else if input == "" || strings.EqualFold(input, "n") {
				s.showResult = false
			} else {
				valid = false
			}
		}
		if !valid {
			fmt.Fprintln(writer, "Invalid selection. Please try again.")
			continue
		}
		step++
	}
	if s.showResult {
		fmt.Fprintln(writer, "DEMO COMPLETE — nothing was installed, changed or verified.")
	} else {
		fmt.Fprintln(writer, "Demo exited without making any changes.")
	}
	return nil
}

func main() {
	// Separate grammar: CLI flags cannot leak into demo, wizard or the
	// internal privileged bootstrap invocation.
	if len(os.Args) > 1 && os.Args[1] == "cli" {
		os.Exit(runCLI(os.Args[2:], os.Stdout))
	}
	flag.Usage = func() {
		fmt.Fprintln(flag.CommandLine.Output(), "Usage: computer-host-linux-installer [wizard flags] or computer-host-linux-installer cli --help")
		fmt.Fprintln(flag.CommandLine.Output(), "Without mode flags, open the installation/upgrade wizard. Run as your normal user.")
		fmt.Fprintln(flag.CommandLine.Output(), "Use -live -preview for read-only host inspection, or -demo for a simulated wizard.")
		flag.PrintDefaults()
	}
	accessible := flag.Bool("accessible", false, "use ANSI-free plain prompts with Back support")
	preview := flag.Bool("preview", false, "print a simulated plan, or inspect the real host with -live")
	demo := flag.Bool("demo", false, "open the inert simulated wizard")
	live := flag.Bool("live", false, "read-only Linux inspection/plan, or explicit installation with -install")
	apiPath := flag.String("api", "", "optional trusted read-only source API launcher for explicit -live modes; otherwise use the embedded inspector")
	install := flag.Bool("install", false, "guided real installation; explicit final approval and administrator authorization required")
	rootMode := flag.Bool("root-bootstrap", false, "internal: fixed privileged bootstrap, never run the UI as root")
	recoverMode := flag.Bool("recover", false, "explicitly recover an interrupted installer operation")
	uninstallMode := flag.Bool("uninstall", false, "guided removal of the agent; retain identity, backups and recovery helper")
	configureMode := flag.Bool("configure", false, "check or remove installer-owned Wake-on-LAN")
	elevation := flag.String("elevation", "auto", "authorization provider for install/uninstall/recover: auto, sudo, doas, run0 or su")
	requestArg := flag.String("request", "", "internal: bounded non-secret JSON input for su-only root bootstrap")
	flag.Parse()
	requestFlagProvided := false
	implicitInstall := true
	flag.Visit(func(f *flag.Flag) {
		// Only presentation and authorization-provider options can
		// accompany the default wizard. An explicitly false mode flag,
		// internal flag or source override must not fall into installation.
		if f.Name != "accessible" && f.Name != "elevation" {
			implicitInstall = false
		}
		if f.Name == "request" {
			requestFlagProvided = true
		}
	})
	if flag.NArg() != 0 {
		fmt.Fprintln(os.Stderr, "unexpected arguments; use -h for help")
		os.Exit(2)
	}
	if !validElevationChoice(*elevation) {
		fmt.Fprintln(os.Stderr, "unsupported -elevation choice; use auto, sudo, doas, run0 or su")
		os.Exit(2)
	}
	if *rootMode {
		if *live || *install || *preview || *demo || *accessible || *apiPath != "" || *recoverMode || *uninstallMode || *configureMode || *elevation != "auto" {
			fmt.Fprintln(os.Stderr, "Invalid privileged bootstrap invocation.")
			os.Exit(2)
		}
		bootstrapInput := io.Reader(os.Stdin)
		if requestFlagProvided {
			// util-linux su consumes stdin to authenticate via PAM.
			// The same strict 4096-byte decoder validates this argument
			// instead; stdin stays attached to the user's terminal.
			bootstrapInput = strings.NewReader(*requestArg)
		}
		if err := rootBootstrap(bootstrapInput, os.Stdout); err != nil {
			fmt.Fprintln(os.Stderr, "Privileged bootstrap failed:", err)
			os.Exit(1)
		}
		return
	}
	if requestFlagProvided {
		fmt.Fprintln(os.Stderr, "-request is supported only by the privileged bootstrap")
		os.Exit(2)
	}
	if implicitInstall {
		*live, *install = true, true
	}
	if *demo && (*live || *install || *recoverMode || *uninstallMode || *configureMode || *apiPath != "") {
		fmt.Fprintln(os.Stderr, "-demo cannot be combined with live, recovery or uninstall modes or -api")
		os.Exit(2)
	}
	if *apiPath != "" && !*live {
		fmt.Fprintln(os.Stderr, "-api requires an explicit -live mode")
		os.Exit(2)
	}
	if *elevation != "auto" && !*recoverMode && !*install && !*uninstallMode && !*configureMode {
		fmt.Fprintln(os.Stderr, "-elevation is allowed only with installation, uninstall or recovery")
		os.Exit(2)
	}
	if *configureMode {
		if *install || *uninstallMode || *recoverMode || *live || *preview || *demo || *accessible || *apiPath != "" || os.Geteuid() == 0 || !stdinIsTerminal() {
			fmt.Fprintln(os.Stderr, "-configure requires a normal-user terminal and cannot be combined with other modes")
			os.Exit(2)
		}
		if err := runWOLManagement(os.Stdin, os.Stdout, *elevation, false); err != nil {
			fmt.Fprintln(os.Stderr, "Wake-on-LAN:", err)
			os.Exit(1)
		}
		return
	}
	if *uninstallMode {
		if *install || *recoverMode || *live || *preview || *accessible || *apiPath != "" {
			fmt.Fprintln(os.Stderr, "-uninstall cannot be combined with other wizard modes")
			os.Exit(2)
		}
		if err := runUninstallWizard(os.Stdin, os.Stdout, *elevation); err != nil {
			fmt.Fprintln(os.Stderr, "Uninstall not completed:", err)
			os.Exit(1)
		}
		return
	}
	if *recoverMode {
		if *install || *live || *preview || *accessible || *apiPath != "" {
			fmt.Fprintln(os.Stderr, "-recover cannot be combined with other wizard modes")
			os.Exit(2)
		}
		if err := runRecoveryWizard(os.Stdin, os.Stdout, *elevation); err != nil {
			fmt.Fprintln(os.Stderr, "Recovery not completed:", err)
			os.Exit(1)
		}
		return
	}
	if *install {
		if !*live || *preview {
			fmt.Fprintln(os.Stderr, "-install requires -live and cannot be combined with -preview")
			os.Exit(2)
		}
		if err := runInstallingWizard(*accessible, *apiPath, os.Stdin, os.Stdout, *elevation); err != nil {
			fmt.Fprintln(os.Stderr, "Installation not completed:", err)
			os.Exit(1)
		}
		return
	}
	if *live {
		if err := runLive(*preview, *accessible, *apiPath, os.Stdin, os.Stdout); err != nil {
			fmt.Fprintln(os.Stderr, "Read-only inspection failed:", err)
			os.Exit(1)
		}
		return
	}
	if *preview {
		fmt.Println((selection{action: "install", hubChoice: "none"}).preview())
		return
	}
	if !*demo {
		fmt.Fprintln(os.Stderr, "no valid wizard mode selected; use -h for help")
		os.Exit(2)
	}
	var err error
	if *accessible {
		err = runAccessible(os.Stdin, os.Stdout)
	} else {
		err = runInteractive(os.Stdout)
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, "Demo failed:", err)
		os.Exit(1)
	}
}
