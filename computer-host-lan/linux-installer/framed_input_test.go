package main

import (
	"errors"
	"fmt"
	"io"
	"os"
	"runtime"
	"testing"
	"time"

	"golang.org/x/sys/unix"
)

// Wait until Read owns the critical section. No timing assumption about
// how long the library's reader needs to enter its blocking poll.
func waitForFramedRead(t *testing.T, r *framedInput) {
	t.Helper()
	deadline := time.Now().Add(2 * time.Second)
	for time.Now().Before(deadline) {
		if !r.readMu.TryLock() {
			return
		}
		r.readMu.Unlock()
		runtime.Gosched()
	}
	t.Fatal("reader did not enter the critical section")
}

func checkFramedReadRevoked(t *testing.T, r *framedInput) {
	t.Helper()
	var buf [32]byte
	if n, err := r.Read(buf[:]); n != 0 || !errors.Is(err, io.EOF) {
		t.Fatalf("revoked reader returned %d bytes, error %v", n, err)
	}
}

func stopPendingFramedRead(t *testing.T, r *framedInput) {
	t.Helper()
	readDone := make(chan error, 1)
	go func() {
		var buf [32]byte
		n, err := r.Read(buf[:])
		if n != 0 {
			err = fmt.Errorf("unexpected bytes from empty input")
		}
		readDone <- err
	}()
	waitForFramedRead(t, r)
	closeDone := make(chan error, 1)
	go func() { closeDone <- r.Close() }()
	select {
	case err := <-closeDone:
		if err != nil {
			t.Fatal(err)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("revocation blocked on a pending terminal read")
	}
	select {
	case err := <-readDone:
		if !errors.Is(err, io.EOF) {
			t.Fatalf("pending read was not revoked: %v", err)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("revoked read did not return")
	}
}

func TestFramedInputRevokesPendingAndLateReads(t *testing.T) {
	var fds [2]int
	if err := unix.Pipe2(fds[:], unix.O_NONBLOCK|unix.O_CLOEXEC); err != nil {
		t.Fatal(err)
	}
	defer unix.Close(fds[0])
	defer unix.Close(fds[1])
	fd, err := unix.FcntlInt(uintptr(fds[0]), unix.F_DUPFD_CLOEXEC, 0)
	if err != nil {
		t.Fatal(err)
	}
	r, err := newFramedInputFD(os.Stdin, fd)
	if err != nil {
		t.Fatal(err)
	}
	// Deliberately keep Name absent so the pinned dependency does not
	// install a second epoll reader on the original terminal descriptor.
	if _, ok := any(r).(interface{ Name() string }); ok {
		t.Fatal("unexpected file Name method")
	}
	stopPendingFramedRead(t, r)
	want := "next owner input"
	if _, err := unix.Write(fds[1], []byte(want)); err != nil {
		t.Fatal(err)
	}
	// Input is already queued before the obsolete reader tries again.
	// Even descriptor-number reuse cannot bypass the stopped check.
	checkFramedReadRevoked(t, r)
	var buf [64]byte
	n, err := unix.Read(fds[0], buf[:])
	if err != nil || string(buf[:max(n, 0)]) != want {
		t.Fatalf("next reader did not receive intact input: n=%d err=%v", n, err)
	}
	if err := r.Close(); err != nil {
		t.Fatal(err)
	}
}

func TestFramedInputPTYHarness(t *testing.T) {
	if os.Getenv("COMPUTER_HOST_TEST_INPUT_PTY") != "1" {
		t.Skip("external PTY harness")
	}
	fd := int(os.Stdin.Fd())
	flags, err := unix.FcntlInt(os.Stdin.Fd(), unix.F_GETFL, 0)
	if err != nil {
		t.Fatal(err)
	}
	modes, err := unix.IoctlGetTermios(fd, unix.TCGETS)
	if err != nil {
		t.Fatal(err)
	}
	r, err := newFramedInput(os.Stdin)
	if err != nil {
		t.Fatal(err)
	}
	privateFlags, err := unix.FcntlInt(uintptr(r.readFD), unix.F_GETFL, 0)
	if err != nil || privateFlags&unix.O_NONBLOCK == 0 {
		t.Fatalf("private reader is not nonblocking: %v", err)
	}
	stopPendingFramedRead(t, r)
	now, err := unix.FcntlInt(os.Stdin.Fd(), unix.F_GETFL, 0)
	if err != nil || now != flags {
		t.Fatalf("original descriptor flags changed: %v", err)
	}
	current, err := unix.IoctlGetTermios(fd, unix.TCGETS)
	if err != nil || *current != *modes {
		t.Fatalf("original terminal modes changed: %v", err)
	}
	fmt.Println("PTY INPUT REVOKED")
	checkFramedReadRevoked(t, r)
	line, err := readConfirmationLine(os.Stdin)
	if err != nil || line != "ordinary terminal input" {
		t.Fatal("ordinary input not preserved after revocation")
	}
	fmt.Println("PTY INPUT OWNER VERIFIED")
}
