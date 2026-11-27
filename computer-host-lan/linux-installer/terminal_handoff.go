package main

import (
	"fmt"
	"os"

	tea "charm.land/bubbletea/v2"
	"golang.org/x/sys/unix"
)

// Bubble Tea owns terminal presentation during Run, but its event-loop
// shutdown is not a join of the underlying byte reader. Independently
// revoke access to terminal input and verify the original tty modes before
// returning a selected/confirmed operation to the caller.
func runFramedProgram(model tea.Model) (result tea.Model, runErr error) {
	in, out := int(os.Stdin.Fd()), int(os.Stdout.Fd())
	input, err := unix.IoctlGetTermios(in, unix.TCGETS)
	if err != nil {
		return nil, fmt.Errorf("cannot capture terminal input state")
	}
	output, err := unix.IoctlGetTermios(out, unix.TCGETS)
	if err != nil {
		return nil, fmt.Errorf("cannot capture terminal output state")
	}
	reader, err := newFramedInput(os.Stdin)
	if err != nil {
		return nil, fmt.Errorf("cannot establish exclusive terminal input: %w", err)
	}
	defer func() {
		// Revocation waits for the last permitted kernel read and closes
		// only our private descriptors. Even a late library goroutine can
		// never read the terminal after this point.
		readErr := reader.Close()
		// Attempt both mode checks even if revocation or one check fails.
		outErr := verifyTerminalState(out, output)
		inErr := verifyTerminalState(in, input)
		if readErr != nil || outErr != nil || inErr != nil {
			result = nil
			runErr = fmt.Errorf("terminal handoff failed; cannot safely continue")
		}
	}()
	return tea.NewProgram(model, tea.WithInput(reader), tea.WithOutput(os.Stdout)).Run()
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
