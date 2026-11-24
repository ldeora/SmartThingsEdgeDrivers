package main

import (
	"errors"
	"io"
	"os"
	"path/filepath"
	"syscall"
)

var errRecoveryHelperMissing = errors.New("protected transaction evidence may remain without an installed recovery helper")

// The shared manual lock is held by the caller. Neither a missing helper nor
// an unreadable namespace proves that there is no transaction to recover.
// Do not interpret journal bytes, create evidence directories or retire files.
func requireNoProvisioningEvidence(root string, uid int) error {
	base := "/"
	if root != trustedDir || uid != 0 {
		// Same internal non-root fixture boundary as helper provisioning.
		if uid == 0 || uid != os.Geteuid() || root == trustedDir {
			return errRecoveryHelperMissing
		}
		base = filepath.Dir(root)
	}
	if !emptyEvidenceNamespace(base, uid, []string{"var", "backups", "linux-host-agent", "wizard-transactions"}, "lock", false) ||
		!emptyEvidenceNamespace(base, uid, []string{"var", "lib", "computer-host-installer", "staging"}, "stage.lock", true) {
		return errRecoveryHelperMissing
	}
	return nil
}

// A read-only, descriptor-relative walk of the same fixed namespace and
// permission rules as transaction_journal.py. Only ENOENT on a checked parent
// establishes absence. Keep the directory fd until its child is opened.
func emptyEvidenceNamespace(base string, uid int, components []string, lock string, exactPrivate bool) bool {
	const directoryFlags = syscall.O_RDONLY | syscall.O_DIRECTORY | syscall.O_NOFOLLOW | syscall.O_CLOEXEC
	fd, err := syscall.Open(base, directoryFlags, 0)
	if err != nil {
		return false
	}
	dir := os.NewFile(uintptr(fd), base)
	defer func() { dir.Close() }()
	for i := -1; ; i++ {
		info, err := dir.Stat()
		if err != nil || !info.IsDir() || int(info.Sys().(*syscall.Stat_t).Uid) != uid {
			return false
		}
		mode := info.Mode().Perm()
		if i >= 2 {
			if mode&0o077 != 0 || (exactPrivate && info.Mode()&(os.ModePerm|os.ModeSetuid|os.ModeSetgid|os.ModeSticky) != 0o700) {
				return false
			}
		} else if mode&0o022 != 0 {
			return false
		}
		if i+1 == len(components) {
			break
		}
		child, err := syscall.Openat(int(dir.Fd()), components[i+1], directoryFlags, 0)
		if errors.Is(err, syscall.ENOENT) {
			return true
		}
		if err != nil {
			return false
		}
		dir.Close()
		dir = os.NewFile(uintptr(child), components[i+1])
	}
	// At most one permitted entry; bound enumeration even for a huge directory.
	names, err := dir.Readdirnames(2)
	if err != nil && !errors.Is(err, io.EOF) {
		return false
	}
	if len(names) == 0 {
		return true
	}
	if len(names) != 1 || names[0] != lock {
		return false
	}
	// O_PATH (Linux amd64/arm64) observes metadata without opening a device,
	// FIFO or other special file for I/O. NOFOLLOW permits inspecting a link
	// itself, which fails the regular-file requirement below.
	const oPath = 0x200000
	lfd, err := syscall.Openat(int(dir.Fd()), lock, oPath|syscall.O_NOFOLLOW|syscall.O_CLOEXEC, 0)
	if err != nil {
		return false
	}
	defer syscall.Close(lfd)
	var st syscall.Stat_t
	return syscall.Fstat(lfd, &st) == nil && st.Mode&syscall.S_IFMT == syscall.S_IFREG &&
		int(st.Uid) == uid && st.Nlink == 1 && st.Mode&0o7777 == 0o600 && st.Size == 0
}

// Called before uninstall's missing-agent preflight as well as before any
// helper staging/retirement. A previous helper is handled by the existing
// version-swap recovery path, not by this absence check.
func guardMissingRecoveryHelper(root string, uid int) error {
	for _, name := range []string{root, root + ".previous"} {
		if _, err := os.Lstat(name); err == nil {
			return nil
		} else if !os.IsNotExist(err) {
			return err
		}
	}
	return requireNoProvisioningEvidence(root, uid)
}
