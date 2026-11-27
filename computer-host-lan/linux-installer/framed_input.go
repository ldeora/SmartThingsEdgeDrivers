package main

import (
	"errors"
	"fmt"
	"io"
	"os"
	"sync"

	"github.com/charmbracelet/x/term"
	"golang.org/x/sys/unix"
)

// framedInput implements term.File so Bubble Tea retains its real tty mode
// handling, but deliberately does not implement cancelreader.File (Name).
// The pinned cancelreader's fallback wrapper cannot cancel an active read;
// our own revocation does that, regardless of library shutdown ordering.
// A framed program is one-shot: it does not suspend and resume the input
// reader or execute a subprocess from inside its model.
type framedInput struct {
	terminal *os.File
	readFD   int
	wake     [2]int
	stopped  chan struct{}
	readMu   sync.Mutex
	stopOnce sync.Once
	stopErr  error
}

var _ term.File = (*framedInput)(nil)

// Reopen the already validated terminal, rather than dup it: O_NONBLOCK
// must belong to a separate open file description, not change stdin's flags
// for the subsequent provider. Verify the reopened device before using it.
func newFramedInput(terminal *os.File) (*framedInput, error) {
	var original, reopened unix.Stat_t
	if err := unix.Fstat(int(terminal.Fd()), &original); err != nil {
		return nil, err
	}
	fd, err := unix.Open(fmt.Sprintf("/proc/self/fd/%d", terminal.Fd()),
		unix.O_RDONLY|unix.O_NONBLOCK|unix.O_CLOEXEC|unix.O_NOCTTY, 0)
	if err != nil {
		return nil, err
	}
	if err := unix.Fstat(fd, &reopened); err != nil {
		_ = unix.Close(fd)
		return nil, err
	}
	if original.Dev != reopened.Dev || original.Ino != reopened.Ino ||
		original.Rdev != reopened.Rdev || original.Mode&unix.S_IFMT != unix.S_IFCHR ||
		!term.IsTerminal(uintptr(fd)) {
		_ = unix.Close(fd)
		return nil, fmt.Errorf("reopened input is not the original terminal")
	}
	return newFramedInputFD(terminal, fd)
}

// Takes ownership of fd on both success and failure. fd must be nonblocking.
func newFramedInputFD(terminal *os.File, fd int) (*framedInput, error) {
	r := &framedInput{terminal: terminal, readFD: fd, stopped: make(chan struct{})}
	if err := unix.Pipe2(r.wake[:], unix.O_CLOEXEC|unix.O_NONBLOCK); err != nil {
		_ = unix.Close(fd)
		return nil, err
	}
	return r, nil
}

// Fd is used for tty mode queries, not byte reads. Never close or change the
// status flags of the original stdin open file description.
func (r *framedInput) Fd() uintptr { return r.terminal.Fd() }

func (r *framedInput) Write([]byte) (int, error) { return 0, os.ErrPermission }

func (r *framedInput) isStopped() bool {
	select {
	case <-r.stopped:
		return true
	default:
		return false
	}
}

func (r *framedInput) Read(p []byte) (int, error) {
	r.readMu.Lock()
	defer r.readMu.Unlock()
	for {
		if r.isStopped() {
			return 0, io.EOF
		}
		if len(p) == 0 {
			return 0, nil
		}
		fds := []unix.PollFd{
			{Fd: int32(r.wake[0]), Events: unix.POLLIN},
			{Fd: int32(r.readFD), Events: unix.POLLIN},
		}
		if _, err := unix.Poll(fds, -1); err != nil {
			if errors.Is(err, unix.EINTR) {
				continue
			}
			return 0, err
		}
		// Prefer revocation even when the terminal also has input ready.
		if r.isStopped() {
			return 0, io.EOF
		}
		if fds[0].Revents != 0 || fds[1].Revents&unix.POLLNVAL != 0 {
			return 0, fmt.Errorf("terminal input poll failed")
		}
		if fds[1].Revents&(unix.POLLIN|unix.POLLHUP|unix.POLLERR) == 0 {
			continue
		}
		// A readiness notification can become stale. A nonblocking read
		// cannot then hang across revocation or a tty mode transition.
		n, err := unix.Read(r.readFD, p)
		if errors.Is(err, unix.EINTR) || errors.Is(err, unix.EAGAIN) {
			continue
		}
		if err != nil {
			return 0, err
		}
		if n == 0 {
			return 0, io.EOF
		}
		return n, nil
	}
}

func (r *framedInput) Close() error {
	r.stopOnce.Do(func() {
		// Publish revocation before waking the poll. Closing the pipe's
		// write end signals POLLHUP even if no input is available.
		close(r.stopped)
		wakeErr := unix.Close(r.wake[1])
		// Join the critical section, not just the library's event loop.
		// No future Read can reach a kernel read, even if an fd is reused.
		r.readMu.Lock()
		defer r.readMu.Unlock()
		r.stopErr = errors.Join(wakeErr, unix.Close(r.wake[0]), unix.Close(r.readFD))
	})
	return r.stopErr
}
