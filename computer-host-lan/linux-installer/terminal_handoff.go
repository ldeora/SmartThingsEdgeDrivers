package main

import (
	"fmt"
	"os"

	tea "charm.land/bubbletea/v2"
	"golang.org/x/sys/unix"
)

// Bubble Tea owns the input loop during Run. It restores the tty on exit,
// but its shutdown path ignores a restoration error. Verify the original
// modes explicitly before any caller can hand the terminal to a provider.
// This does not claim that a mode check proves the input reader stopped.
func runFramedProgram(model tea.Model) (tea.Model, error) {
	in, out := int(os.Stdin.Fd()), int(os.Stdout.Fd())
	input, err := unix.IoctlGetTermios(in, unix.TCGETS)
	if err != nil {
		return nil, fmt.Errorf("cannot capture terminal input state")
	}
	output, err := unix.IoctlGetTermios(out, unix.TCGETS)
	if err != nil {
		return nil, fmt.Errorf("cannot capture terminal output state")
	}
	result, runErr := tea.NewProgram(model, tea.WithInput(os.Stdin), tea.WithOutput(os.Stdout)).Run()
	// Attempt both even if one fails. A failed restoration prevents
	// execution of any previously selected or confirmed operation.
	outErr := verifyTerminalState(out, output)
	inErr := verifyTerminalState(in, input)
	if outErr != nil || inErr != nil {
		return nil, fmt.Errorf("terminal restoration failed; operation not started")
	}
	return result, runErr
}

func verifyTerminalState(fd int, original *unix.Termios) error {
	current, err := unix.IoctlGetTermios(fd, unix.TCGETS)
	if err != nil {
		return err
	}
	if *current != *original {
		if err := unix.IoctlSetTermios(fd, unix.TCSETS, original); err != nil {
			return err
		}
		current, err = unix.IoctlGetTermios(fd, unix.TCGETS)
		if err != nil {
			return err
		}
		if *current != *original {
			return fmt.Errorf("terminal mode differs from saved state")
		}
	}
	return nil
}
