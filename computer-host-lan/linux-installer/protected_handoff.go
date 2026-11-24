package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"syscall"
)

const (
	maxHandoffExecutableBytes = 128 << 20
	protectedHandoffRoot     = "/run/computer-host-lan"
)

var (
	errUntrustedRootHandoff = errors.New("privileged bootstrap did not start from a protected executable handoff")
	handoffDirectoryPattern = regexp.MustCompile(`^handoff-[0-9a-f]{32}$`)
	sha256Pattern           = regexp.MustCompile(`^[0-9a-f]{64}$`)
)

// The elevation provider executes this fixed system interpreter, not the
// user-owned Go executable. It snapshots the running executable into a
// root-only /run directory, checks the digest computed by the still-running
// parent, and only then starts the protected copy. stdin/stdout/stderr are
// inherited so sudo/doas/run0 keep the bounded JSON pipe and su keeps its TTY.
const protectedHandoffScript = `import hashlib, json, os, secrets, shutil, stat, subprocess, sys

def fail():
    raise RuntimeError("protected handoff rejected")

def stable(a, b):
    return (a.st_dev, a.st_ino, a.st_mode, a.st_uid, a.st_gid, a.st_size,
            a.st_mtime_ns, a.st_ctime_ns) == (
            b.st_dev, b.st_ino, b.st_mode, b.st_uid, b.st_gid, b.st_size,
            b.st_mtime_ns, b.st_ctime_ns)

def sync(fd):
    os.fsync(fd)

handoff = None
base_fd = None
source_fd = None
source_dir_fd = None
parent_fd = None
dest_fd = None
try:
    if len(sys.argv) != 8:
        fail()
    source_dir, expected_digest, caller_uid_text, base_parent, base_name, base_uid_text, child_args_text = sys.argv[1:]
    caller_uid = int(caller_uid_text)
    base_uid = int(base_uid_text)
    if (not 0 < caller_uid < 2**31 or base_uid != os.geteuid() or
            not expected_digest or len(expected_digest) != 64 or
            any(c not in "0123456789abcdef" for c in expected_digest) or
            not os.path.isabs(source_dir) or not os.path.isabs(base_parent) or
            base_name != "computer-host-lan"):
        fail()
    if base_uid == 0 and base_parent != "/run":
        fail()

    child_args = json.loads(child_args_text)
    if not isinstance(child_args, list) or not child_args or not all(
            isinstance(x, str) and "\x00" not in x for x in child_args):
        fail()
    if base_uid == 0:
        if (child_args[0] != "-root-bootstrap" or
                not (len(child_args) == 1 or
                     (len(child_args) == 3 and child_args[1] == "-request" and
                      len(child_args[2]) <= 4096))):
            fail()
    elif len(child_args) > 8:
        # Non-root base directories exist only in isolated execution tests.
        fail()

    # Pin the caller-owned snapshot directory and file by descriptor.
    source_dir_fd = os.open(source_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    source_dir_stat = os.fstat(source_dir_fd)
    source_dir_visible = os.stat(source_dir, follow_symlinks=False)
    if (not stat.S_ISDIR(source_dir_stat.st_mode) or source_dir_stat.st_uid != caller_uid or
            stat.S_IMODE(source_dir_stat.st_mode) != 0o700 or
            (source_dir_stat.st_dev, source_dir_stat.st_ino) !=
            (source_dir_visible.st_dev, source_dir_visible.st_ino)):
        fail()

    source_fd = os.open("installer", os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=source_dir_fd)
    source_before = os.fstat(source_fd)
    source_visible = os.stat("installer", dir_fd=source_dir_fd, follow_symlinks=False)
    if (not stat.S_ISREG(source_before.st_mode) or source_before.st_uid != caller_uid or
            stat.S_IMODE(source_before.st_mode) != 0o600 or source_before.st_nlink != 1 or
            source_before.st_size <= 0 or source_before.st_size > 128 * 1024 * 1024 or
            (source_before.st_dev, source_before.st_ino) !=
            (source_visible.st_dev, source_visible.st_ino)):
        fail()

    # /run is a fixed, root-owned parent. The child directory is private and
    # is also used by the Go bootstrap lifetime lock.
    parent_fd = os.open(base_parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    parent_stat = os.fstat(parent_fd)
    if (not stat.S_ISDIR(parent_stat.st_mode) or parent_stat.st_uid != base_uid or
            parent_stat.st_mode & 0o022):
        fail()
    try:
        os.mkdir(base_name, 0o700, dir_fd=parent_fd)
        sync(parent_fd)
    except FileExistsError:
        pass
    base_fd = os.open(base_name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent_fd)
    base_stat = os.fstat(base_fd)
    base_visible = os.stat(base_name, dir_fd=parent_fd, follow_symlinks=False)
    if (not stat.S_ISDIR(base_stat.st_mode) or base_stat.st_uid != base_uid or
            stat.S_IMODE(base_stat.st_mode) != 0o700 or
            (base_stat.st_dev, base_stat.st_ino) != (base_visible.st_dev, base_visible.st_ino)):
        fail()

    handoff_name = "handoff-" + secrets.token_hex(16)
    os.mkdir(handoff_name, 0o700, dir_fd=base_fd)
    handoff = os.path.join(base_parent, base_name, handoff_name)
    handoff_fd = os.open(handoff_name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=base_fd)
    try:
        dest_fd = os.open("installer", os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                          os.O_NOFOLLOW | os.O_CLOEXEC, 0o700, dir_fd=handoff_fd)
        digest = hashlib.sha256()
        total = 0
        while True:
            block = os.read(source_fd, 1024 * 1024)
            if not block:
                break
            total += len(block)
            if total > 128 * 1024 * 1024:
                fail()
            digest.update(block)
            view = memoryview(block)
            while view:
                written = os.write(dest_fd, view)
                view = view[written:]
        source_after = os.fstat(source_fd)
        if not stable(source_before, source_after) or total != source_before.st_size:
            fail()
        if digest.hexdigest() != expected_digest:
            fail()
        os.fchmod(dest_fd, 0o700)
        sync(dest_fd)
        dest_stat = os.fstat(dest_fd)
        if (not stat.S_ISREG(dest_stat.st_mode) or dest_stat.st_uid != base_uid or
                stat.S_IMODE(dest_stat.st_mode) != 0o700 or dest_stat.st_nlink != 1 or
                dest_stat.st_size != total):
            fail()
        sync(handoff_fd)
        sync(base_fd)
    finally:
        if dest_fd is not None:
            os.close(dest_fd)
            dest_fd = None
        os.close(handoff_fd)

    executable = os.path.join(handoff, "installer")
    env = {
        "PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
        "HOME": "/root" if base_uid == 0 else os.environ.get("HOME", "/tmp"),
        "LANG": "C",
        "LC_ALL": "C",
        "TERM": "dumb",
    }
    result = subprocess.run([executable] + child_args, stdin=sys.stdin.buffer,
                            cwd="/", env=env, check=False)
    raise SystemExit(result.returncode)
except SystemExit:
    raise
except BaseException:
    sys.stderr.write("protected installer handoff failed\n")
    raise SystemExit(126)
finally:
    if dest_fd is not None:
        try:
            os.close(dest_fd)
        except OSError:
            pass
    if source_fd is not None:
        os.close(source_fd)
    if source_dir_fd is not None:
        os.close(source_dir_fd)
    if base_fd is not None:
        if handoff is not None:
            try:
                shutil.rmtree(handoff)
                sync(base_fd)
            except OSError:
                # /run is volatile; a root-only orphan is harmless and is
                # removed on reboot. Never turn a committed operation into
                # failure solely because this best-effort cleanup failed.
                pass
        os.close(base_fd)
    if parent_fd is not None:
        os.close(parent_fd)
`

type executableSnapshot struct {
	directory string
	digest    string
	cleanup   func()
}

// snapshotRunningExecutable copies the inode the kernel actually started,
// not os.Executable()'s mutable pathname. The root launcher independently
// checks this snapshot against the digest before copying it into /run.
func snapshotRunningExecutable() (executableSnapshot, error) {
	if os.Geteuid() == 0 || os.Geteuid() != os.Getuid() {
		return executableSnapshot{}, errors.New("run the installer as an ordinary user")
	}
	source, err := os.Open("/proc/self/exe")
	if err != nil {
		return executableSnapshot{}, errors.New("cannot open the running installer image")
	}
	defer source.Close()
	before, err := source.Stat()
	if err != nil {
		return executableSnapshot{}, errors.New("cannot inspect the running installer image")
	}
	st, ok := before.Sys().(*syscall.Stat_t)
	if !ok || !before.Mode().IsRegular() || before.Mode().Perm()&0o111 == 0 ||
		before.Mode().Perm()&0o022 != 0 || (int(st.Uid) != 0 && int(st.Uid) != os.Getuid()) ||
		before.Size() <= 0 || before.Size() > maxHandoffExecutableBytes {
		return executableSnapshot{}, errors.New("running installer image has unsafe metadata")
	}

	directory, err := os.MkdirTemp("", "computer-host-handoff-")
	if err != nil {
		return executableSnapshot{}, errors.New("cannot create a private installer handoff snapshot")
	}
	cleanup := func() { _ = os.RemoveAll(directory) }
	fail := func(err error) (executableSnapshot, error) {
		cleanup()
		return executableSnapshot{}, err
	}
	if err := os.Chmod(directory, 0o700); err != nil {
		return fail(errors.New("cannot protect the installer handoff snapshot"))
	}
	target, err := os.OpenFile(filepath.Join(directory, "installer"),
		os.O_WRONLY|os.O_CREATE|os.O_EXCL|syscall.O_NOFOLLOW|syscall.O_CLOEXEC, 0o600)
	if err != nil {
		return fail(errors.New("cannot create the installer handoff snapshot"))
	}
	hash := sha256.New()
	n, copyErr := io.Copy(io.MultiWriter(target, hash), io.LimitReader(source, maxHandoffExecutableBytes+1))
	if copyErr != nil || n != before.Size() || n > maxHandoffExecutableBytes {
		target.Close()
		return fail(errors.New("cannot copy the complete running installer image"))
	}
	after, err := source.Stat()
	if err != nil {
		target.Close()
		return fail(errors.New("cannot recheck the running installer image"))
	}
	afterStat, ok := after.Sys().(*syscall.Stat_t)
	if !ok || !sameHandoffSourceStat(st, afterStat) {
		target.Close()
		return fail(errors.New("running installer image changed while being copied"))
	}
	if err := target.Chmod(0o600); err != nil {
		target.Close()
		return fail(errors.New("cannot protect the installer handoff snapshot"))
	}
	if err := target.Sync(); err != nil {
		target.Close()
		return fail(errors.New("cannot sync the installer handoff snapshot"))
	}
	targetInfo, err := target.Stat()
	if err != nil {
		target.Close()
		return fail(errors.New("cannot verify the installer handoff snapshot"))
	}
	targetStat, ok := targetInfo.Sys().(*syscall.Stat_t)
	if !ok || !targetInfo.Mode().IsRegular() || int(targetStat.Uid) != os.Getuid() ||
		targetInfo.Mode().Perm() != 0o600 || targetStat.Nlink != 1 || targetInfo.Size() != n {
		target.Close()
		return fail(errors.New("installer handoff snapshot metadata is unsafe"))
	}
	if err := target.Close(); err != nil {
		return fail(errors.New("cannot close the installer handoff snapshot"))
	}
	if err := syncDirectory(directory); err != nil {
		return fail(errors.New("cannot sync the installer handoff directory"))
	}
	return executableSnapshot{directory: directory, digest: hex.EncodeToString(hash.Sum(nil)), cleanup: cleanup}, nil
}

func sameHandoffSourceStat(a, b *syscall.Stat_t) bool {
	return a.Dev == b.Dev && a.Ino == b.Ino && a.Mode == b.Mode &&
		a.Uid == b.Uid && a.Gid == b.Gid && a.Nlink == b.Nlink &&
		a.Size == b.Size && a.Mtim == b.Mtim && a.Ctim == b.Ctim
}

// Only root-owned, non-writable system Python executables may run the fixed
// launcher under sudo/doas/run0/su. User PATH and Python environment are not
// consulted, and isolated mode disables site and environment imports.
func trustedSystemPython() (string, error) {
	for _, candidate := range []string{
		"/usr/bin/python3", "/usr/bin/python3.14", "/usr/bin/python3.13",
		"/usr/bin/python3.12", "/usr/bin/python3.11", "/usr/bin/python3.10",
		"/bin/python3", "/bin/python3.14", "/bin/python3.13",
		"/bin/python3.12", "/bin/python3.11", "/bin/python3.10",
	} {
		resolved, err := filepath.EvalSymlinks(candidate)
		if err != nil || !filepath.IsAbs(resolved) {
			continue
		}
		if err := verifyParents(filepath.Dir(resolved), 0); err != nil {
			continue
		}
		if err := protectedPath(resolved, 0, false); err != nil || !isExecutableFile(resolved) {
			continue
		}
		cmd := exec.Command(resolved, "-I", "-S", "-B", "-c",
			"import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)")
		cmd.Dir = "/"
		cmd.Env = []string{"PATH=/usr/sbin:/usr/bin:/sbin:/bin", "HOME=/root", "LANG=C", "LC_ALL=C"}
		if cmd.Run() == nil {
			return resolved, nil
		}
	}
	return "", errUnavailablePython
}

func protectedHandoffArguments(python, sourceDir, digest string, callerUID int, childArgs []string) ([]string, error) {
	if !filepath.IsAbs(python) || !filepath.IsAbs(sourceDir) || callerUID <= 0 ||
		!sha256Pattern.MatchString(digest) || len(childArgs) == 0 || childArgs[0] != "-root-bootstrap" {
		return nil, errors.New("invalid protected handoff arguments")
	}
	if len(childArgs) != 1 && !(len(childArgs) == 3 && childArgs[1] == "-request" && len(childArgs[2]) <= 4096) {
		return nil, errors.New("invalid protected bootstrap argument set")
	}
	encoded, err := json.Marshal(childArgs)
	if err != nil {
		return nil, err
	}
	return []string{
		"-I", "-S", "-B", "-c", protectedHandoffScript,
		sourceDir, digest, strconv.Itoa(callerUID),
		"/run", "computer-host-lan", "0", string(encoded),
	}, nil
}

func findElevationCommand(python, sourceDir, digest string, callerUID int, interactive bool,
	payload []byte, available func(string) bool) (elevationCommand, error) {
	if available == nil {
		return elevationCommand{}, errors.New("elevation provider lookup is unavailable")
	}
	childArgs := []string{"-root-bootstrap"}
	pythonArgs, err := protectedHandoffArguments(python, sourceDir, digest, callerUID, childArgs)
	if err != nil {
		return elevationCommand{}, err
	}
	find := func(names ...string) string {
		for _, name := range names {
			if available(name) {
				return name
			}
		}
		return ""
	}
	if sudo := find("/usr/bin/sudo", "/bin/sudo"); sudo != "" {
		args := append([]string{"--", python}, pythonArgs...)
		if !interactive {
			args = append([]string{"-n"}, args...)
		}
		return elevationCommand{"sudo", sudo, args}, nil
	}
	if doas := find("/usr/bin/doas", "/bin/doas"); doas != "" {
		args := append([]string{"--", python}, pythonArgs...)
		if !interactive {
			args = append([]string{"-n"}, args...)
		}
		return elevationCommand{"doas", doas, args}, nil
	}
	if run0 := find("/usr/bin/run0", "/bin/run0"); run0 != "" {
		args := append([]string{"--pipe", "--", python}, pythonArgs...)
		if !interactive {
			args = append([]string{"--no-ask-password"}, args...)
		}
		return elevationCommand{"run0", run0, args}, nil
	}
	if interactive {
		if su := find("/usr/bin/su", "/bin/su"); su != "" {
			childArgs = []string{"-root-bootstrap", "-request", string(payload)}
			pythonArgs, err = protectedHandoffArguments(python, sourceDir, digest, callerUID, childArgs)
			if err != nil {
				return elevationCommand{}, err
			}
			command := "exec " + quotePOSIXShell(python)
			for _, arg := range pythonArgs {
				command += " " + quotePOSIXShell(arg)
			}
			return elevationCommand{"su", su, []string{"root", "-c", command}}, nil
		}
	}
	return elevationCommand{}, errors.New("no supported administrator authorization method is available (sudo, doas, run0 or interactive su)")
}

// An explicit provider is important for remote SSH sessions where run0's
// polkit authorization can be unavailable even when su root works.
// Never retry another provider after failure or quietly weaken selection.
func chooseElevationCommand(python, sourceDir, digest string, callerUID int, interactive bool,
	payload []byte, method string, available func(string) bool) (elevationCommand, error) {
	if !validElevationChoice(method) {
		return elevationCommand{}, errors.New("invalid administrator authorization method")
	}
	if method == "auto" {
		return findElevationCommand(python, sourceDir, digest, callerUID, interactive, payload, available)
	}
	if method == "su" && !interactive {
		return elevationCommand{}, errors.New("su requires an interactive terminal for root password authentication")
	}
	selected, err := findElevationCommand(python, sourceDir, digest, callerUID, interactive, payload,
		func(candidate string) bool {
			return filepath.Base(candidate) == method && available(candidate)
		})
	if err != nil {
		return elevationCommand{}, fmt.Errorf("requested administrator authorization method %s is not available", method)
	}
	if selected.method != method {
		return elevationCommand{}, errors.New("requested administrator authorization method mismatch")
	}
	return selected, nil
}

// validateProtectedHandoffExecutablePath is separately testable with an
// isolated root. The production caller always supplies /run/computer-host-lan
// and uid 0; no user-controlled path can satisfy that boundary.
func validateProtectedHandoffExecutablePath(executable, root string, ownerUID int) error {
	if !filepath.IsAbs(executable) || !filepath.IsAbs(root) || ownerUID < 0 {
		return errUntrustedRootHandoff
	}
	executable = filepath.Clean(executable)
	root = filepath.Clean(root)
	rel, err := filepath.Rel(root, executable)
	if err != nil {
		return errUntrustedRootHandoff
	}
	parts := strings.Split(rel, string(os.PathSeparator))
	if len(parts) != 2 || parts[1] != "installer" || !handoffDirectoryPattern.MatchString(parts[0]) {
		return errUntrustedRootHandoff
	}
	if ownerUID == 0 {
		if err := verifyParents(root, ownerUID); err != nil {
			return errUntrustedRootHandoff
		}
	} else if err := protectedPath(root, ownerUID, true); err != nil {
		// Non-root owner overrides are used only by isolated fixture tests.
		return errUntrustedRootHandoff
	}
	directory := filepath.Join(root, parts[0])
	if err := protectedPath(directory, ownerUID, true); err != nil {
		return errUntrustedRootHandoff
	}
	dirInfo, err := os.Lstat(directory)
	if err != nil || dirInfo.Mode().Perm() != 0o700 {
		return errUntrustedRootHandoff
	}
	if err := protectedPath(executable, ownerUID, false); err != nil {
		return errUntrustedRootHandoff
	}
	fileInfo, err := os.Lstat(executable)
	if err != nil || fileInfo.Mode().Perm() != 0o700 {
		return errUntrustedRootHandoff
	}
	visible, err := os.Stat(executable)
	if err != nil || !os.SameFile(fileInfo, visible) {
		return errUntrustedRootHandoff
	}
	return nil
}

func requireProtectedHandoffExecutable() error {
	executable, err := filepath.EvalSymlinks("/proc/self/exe")
	if err != nil {
		return errUntrustedRootHandoff
	}
	return validateProtectedHandoffExecutablePath(executable, protectedHandoffRoot, 0)
}

