package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"
	"syscall"
	"time"
)

const (
	trustedDir  = "/usr/libexec/computer-host-lan"
	trustedLock = "/run/lock/linux-host-agent-install.lock"
	// Only the Go wizard uses this lifetime lock; unlike the legacy manual
	// install lock it can live in a private root-owned runtime directory.
	bootstrapLock = "/run/computer-host-lan/bootstrap.lock"
)

var (
	errInstallerBusy            = errors.New("another installer is running")
	errUnsafeInstallerLock      = errors.New("unsafe installer lock")
	errInstallerRecoveryPending = errors.New("recover previous installer transaction before changing the trusted helper")
	errUnavailablePython        = errors.New("installed helper could not select a compatible system Python")
	errInvalidHelperResponse    = errors.New("invalid privileged helper response")
)

var interfacePattern = regexp.MustCompile(`^[A-Za-z0-9_.-]{1,15}$`)

type privilegedRequest struct {
	SchemaVersion int     `json:"schema_version"`
	Action        string  `json:"action"`
	Power         string  `json:"power,omitempty"`
	WOLInterface  *string `json:"wol_interface,omitempty"`
}

type privilegedResult struct {
	SchemaVersion              int    `json:"schema_version"`
	Status                     string `json:"status"`
	Operation                  string `json:"operation"`
	ErrorCode                  string `json:"error_code"`
	FailureStage               string `json:"failure_stage,omitempty"`
	RecoveryStatus             string `json:"recovery_status"`
	PrivilegedTransactionState string `json:"privileged_transaction_state"`
	IdentityPreserved          string `json:"identity_preserved"`
	SecretsIncluded            bool   `json:"secrets_included"`
}

func (r privilegedRequest) validate() error {
	if r.SchemaVersion != 1 {
		return errors.New("unsupported privileged request version")
	}
	switch r.Action {
	case "status", "recover":
		if r.Power != "" || r.WOLInterface != nil {
			return errors.New("status/recover do not accept installation settings")
		}
	case "install", "upgrade", "repair":
		if r.Power != "preserve" && r.Power != "enable" && r.Power != "disable" {
			return errors.New("invalid power setting")
		}
		if r.WOLInterface != nil && (!interfacePattern.MatchString(*r.WOLInterface) ||
			*r.WOLInterface == "." || *r.WOLInterface == "..") {
			return errors.New("invalid interface name")
		}
	default:
		return errors.New("unsupported privileged action")
	}
	return nil
}

func decodePrivilegedRequest(r io.Reader) (privilegedRequest, error) {
	raw, err := io.ReadAll(io.LimitReader(r, 4097))
	if err != nil || len(raw) == 0 || len(raw) > 4096 {
		return privilegedRequest{}, errors.New("invalid privileged request length")
	}
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.DisallowUnknownFields()
	var request privilegedRequest
	if err := decoder.Decode(&request); err != nil {
		return privilegedRequest{}, errors.New("invalid privileged request")
	}
	var extra any
	if decoder.Decode(&extra) != io.EOF {
		return privilegedRequest{}, errors.New("unexpected data after privileged request")
	}
	if err := request.validate(); err != nil {
		return privilegedRequest{}, err
	}
	return request, nil
}

func pythonRequest(r privilegedRequest) ([]byte, error) {
	if err := r.validate(); err != nil {
		return nil, err
	}
	data := map[string]any{"schema_version": 1, "action": r.Action}
	if r.Action == "install" || r.Action == "upgrade" || r.Action == "repair" {
		data["source"] = trustedDir + "/payload"
		data["power"] = r.Power
		data["wol_interface"] = r.WOLInterface
	}
	return json.Marshal(data)
}

func protectedPath(path string, ownerUID int, wantDir bool) error {
	info, err := os.Lstat(path)
	if err != nil {
		return err
	}
	if int(info.Sys().(*syscall.Stat_t).Uid) != ownerUID || info.Mode().Perm()&0o022 != 0 {
		return errors.New("unsafe installer-owned path")
	}
	if wantDir {
		if !info.IsDir() {
			return errors.New("installer directory is not a real directory")
		}
	} else if !info.Mode().IsRegular() || info.Sys().(*syscall.Stat_t).Nlink != 1 {
		return errors.New("installer file is not a regular single-link file")
	}
	return nil
}

func verifyParents(root string, ownerUID int) error {
	root = filepath.Clean(root)
	part := string(filepath.Separator)
	if err := protectedPath(part, ownerUID, true); err != nil {
		return err
	}
	for _, component := range strings.Split(strings.TrimPrefix(root, part), part) {
		if component == "" {
			continue
		}
		part = filepath.Join(part, component)
		if err := protectedPath(part, ownerUID, true); err != nil {
			return err
		}
	}
	return nil
}

func syncDirectory(dir string) error {
	f, err := os.Open(dir)
	if err != nil {
		return err
	}
	defer f.Close()
	return f.Sync()
}

func writeFreshFile(path string, content []byte, mode os.FileMode) error {
	f, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, mode)
	if err != nil {
		return err
	}
	if err := f.Chmod(mode); err != nil {
		f.Close()
		return err
	}
	if _, err := f.Write(content); err != nil {
		f.Close()
		return err
	}
	if err := f.Sync(); err != nil {
		f.Close()
		return err
	}
	return f.Close()
}

func writeEmbeddedSet(stage string) error {
	for _, name := range installedHelpers {
		data, err := bundleRead("scripts/" + name)
		if err != nil {
			return err
		}
		mode := os.FileMode(0o644)
		if strings.HasSuffix(name, ".sh") {
			mode = 0o755
		}
		if err := writeFreshFile(filepath.Join(stage, name), data, mode); err != nil {
			return err
		}
	}
	if err := os.Mkdir(filepath.Join(stage, "payload"), 0o700); err != nil {
		return err
	}
	for _, name := range payloadFiles {
		target := filepath.Join(stage, "payload", filepath.FromSlash(name))
		if err := os.MkdirAll(filepath.Dir(target), 0o700); err != nil {
			return err
		}
		data, err := bundleRead(name)
		if err != nil {
			return err
		}
		if err := writeFreshFile(target, data, 0o600); err != nil {
			return err
		}
	}
	manifest, err := manifestFromEmbedded()
	if err != nil {
		return err
	}
	if err := writeFreshFile(filepath.Join(stage, "trusted-payload.json"), manifest, 0o644); err != nil {
		return err
	}
	return filepath.WalkDir(stage, func(path string, entry os.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if entry.IsDir() {
			return syncDirectory(path)
		}
		return nil
	})
}

// The bootstrap lock has no legacy/manual consumers. Create its private
// directory under trusted /run and reject any existing symlink or unsafe
// permissions. Never chmod or replace an attacker-controlled entry.
func ensurePrivateBootstrapLockDir(path string, ownerUID int) error {
	parent := filepath.Dir(path)
	if path == filepath.Dir(bootstrapLock) && ownerUID == 0 {
		if err := verifyParents(parent, 0); err != nil {
			return errUnsafeInstallerLock
		}
	} else {
		// Alternate paths exist solely for isolated non-root test fixtures.
		if ownerUID != os.Geteuid() {
			return errUnsafeInstallerLock
		}
		if err := protectedPath(parent, ownerUID, true); err != nil {
			return errUnsafeInstallerLock
		}
	}
	if err := os.Mkdir(path, 0o700); err != nil && !os.IsExist(err) {
		return errUnsafeInstallerLock
	}
	info, err := os.Lstat(path)
	if err != nil || !info.IsDir() || info.Mode().Perm() != 0o700 {
		return errUnsafeInstallerLock
	}
	st, ok := info.Sys().(*syscall.Stat_t)
	if !ok || int(st.Uid) != ownerUID {
		return errUnsafeInstallerLock
	}
	return nil
}

func lockInstaller(path string, ownerUID int) (*os.File, error) {
	// Shared flock with install_core.py and InstallerBackend. /run/lock can
	// be world-writable: never follow a planted symlink, never block opening
	// a FIFO, and validate the OPENED inode before acquiring the lock.
	// The legacy regular lock may legitimately have mode 0644; do not chmod.
	f, err := os.OpenFile(path, os.O_RDWR|os.O_CREATE|syscall.O_NOFOLLOW|syscall.O_NONBLOCK|syscall.O_CLOEXEC, 0o600)
	if err != nil {
		if errors.Is(err, syscall.ELOOP) || errors.Is(err, syscall.EISDIR) ||
			errors.Is(err, syscall.ENOTDIR) || errors.Is(err, syscall.EACCES) ||
			errors.Is(err, syscall.EPERM) || errors.Is(err, syscall.ENXIO) {
			return nil, errUnsafeInstallerLock
		}
		return nil, err
	}
	info, err := f.Stat()
	if err != nil {
		f.Close()
		return nil, err
	}
	st, ok := info.Sys().(*syscall.Stat_t)
	if !ok || !info.Mode().IsRegular() || int(st.Uid) != ownerUID ||
		st.Nlink != 1 || info.Mode().Perm()&0o022 != 0 {
		f.Close()
		return nil, errUnsafeInstallerLock
	}
	// Refuse an inode swapped at the pathname between open and validation.
	// Sticky /run/lock prevents unprivileged removal of root-owned files.
	visible, err := os.Lstat(path)
	if err != nil || !os.SameFile(info, visible) {
		f.Close()
		return nil, errUnsafeInstallerLock
	}
	if err := syscall.Flock(int(f.Fd()), syscall.LOCK_EX|syscall.LOCK_NB); err != nil {
		f.Close()
		return nil, errInstallerBusy
	}
	return f, nil
}

// prepareTrustedVersion holds the shared lock over its own version switch.
// It never runs the Python installer while holding that lock (which would
// deadlock when InstallerBackend acquires the same flock).
func prepareTrustedVersion(root, lock string, uid int, status func() (string, error)) (bool, error) {
	if err := validateEmbeddedBundle(); err != nil {
		return false, err
	}
	parent := filepath.Dir(root)
	if err := os.MkdirAll(parent, 0o755); err != nil {
		return false, err
	}
	if root == trustedDir && uid == 0 {
		if err := verifyParents(parent, uid); err != nil {
			return false, err
		}
	} else {
		// Only internal tests may inject a temporary root; the exported
		// rootBootstrap entry hardcodes trustedDir and UID 0.
		if uid == 0 || uid != os.Geteuid() {
			return false, errors.New("unsupported trusted directory override")
		}
		if err := protectedPath(parent, uid, true); err != nil {
			return false, err
		}
	}
	if err := os.MkdirAll(filepath.Dir(lock), 0o755); err != nil {
		return false, err
	}
	guard, err := lockInstaller(lock, uid)
	if err != nil {
		return false, err
	}
	defer guard.Close()
	previous, next := root+".previous", root+".next"
	hadPreviousArtifact := false
	if _, err := os.Lstat(previous); err == nil {
		hadPreviousArtifact = true
		if err := protectedPath(previous, uid, true); err != nil {
			return false, err
		}
		if _, missing := os.Lstat(root); os.IsNotExist(missing) {
			// Crash after moving the old helper aside but before
			// promoting the complete new helper. Restore the old one.
			if err := os.Rename(previous, root); err != nil {
				return false, err
			}
			hadPreviousArtifact = false
			if err := syncDirectory(parent); err != nil {
				return false, err
			}
		} else if missing != nil {
			return false, missing
		}
	} else if !os.IsNotExist(err) {
		return false, err
	}
	hasPrevious := false
	if _, err := os.Lstat(root); err == nil {
		if err := protectedPath(root, uid, true); err != nil {
			return false, err
		}
		state, err := status()
		if err != nil {
			return false, err
		}
		if state != "none" {
			return false, errInstallerRecoveryPending
		}
		hasPrevious = true
	} else if !os.IsNotExist(err) {
		return false, err
	}
	// The installed helper just confirmed no protected transaction is
	// outstanding. These version-swap artifacts are now safe to retire;
	// leaving them indefinitely would prevent every subsequent upgrade.
	if hadPreviousArtifact {
		if err := retirePreviousTrustedVersion(root, uid); err != nil {
			return false, err
		}
		if err := syncDirectory(parent); err != nil {
			return false, err
		}
	}
	if _, err := os.Lstat(next); err == nil {
		if err := discardTrustedStage(next, uid); err != nil {
			return false, err
		}
		if err := syncDirectory(parent); err != nil {
			return false, err
		}
	} else if !os.IsNotExist(err) {
		return false, err
	}
	if err := os.Mkdir(next, 0o700); err != nil {
		return false, err
	}
	if err := writeEmbeddedSet(next); err != nil {
		return false, err // Keep a root-only stage for diagnosis, not a half-updated helper.
	}
	if err := os.Chmod(next, 0o755); err != nil {
		return false, err
	}
	if err := syncDirectory(next); err != nil {
		return false, err
	}
	if hasPrevious {
		if err := os.Rename(root, previous); err != nil {
			return false, err
		}
		if err := syncDirectory(parent); err != nil {
			return false, err
		}
	}
	if err := os.Rename(next, root); err != nil {
		if hasPrevious {
			_ = os.Rename(previous, root)
		}
		return false, err
	}
	if err := syncDirectory(parent); err != nil {
		return false, err
	}
	return hasPrevious, nil
}

// A single one-shot root helper call: only sanitized stdout JSON is consumed.
// Stderr is never passed to callers. The fixed missing-Python diagnostic is
// mapped to a safe error code without exposing arbitrary process output.
func runTrustedHelperCommand(cmd *exec.Cmd, request privilegedRequest) (privilegedResult, error) {
	payload, err := pythonRequest(request)
	if err != nil {
		return privilegedResult{}, err
	}
	cmd.Dir = "/"
	cmd.Env = []string{"PATH=/usr/sbin:/usr/bin:/sbin:/bin", "HOME=/root", "LANG=C", "LC_ALL=C"}
	cmd.Stdin = bytes.NewReader(payload)
	cmd.WaitDelay = 2 * time.Second
	var stdout, stderr cappedBuffer
	cmd.Stdout, cmd.Stderr = &stdout, &stderr
	runErr := cmd.Run()
	var reply privilegedResult
	if err := json.Unmarshal(stdout.Bytes(), &reply); err != nil ||
		reply.SchemaVersion != 1 || reply.SecretsIncluded {
		if runErr != nil &&
			strings.TrimSpace(stderr.String()) == "Python 3.10+ is required (install a compatible system Python interpreter)." {
			return privilegedResult{}, errUnavailablePython
		}
		return privilegedResult{}, errInvalidHelperResponse
	}
	if runErr != nil || reply.Status == "error" {
		if reply.ErrorCode != "" {
			return reply, fmt.Errorf("privileged helper reported %s", reply.ErrorCode)
		}
		return reply, errors.New("privileged helper failed")
	}
	return reply, nil
}

// Only read-only status checks have a process-wide deadline. Mutating
// requests must be allowed to finish their transaction or verified rollback;
// killing Python at 120 seconds can strand APPLYING/ROLLBACK state.
func installedHelperCommand(root, action string) (*exec.Cmd, func()) {
	argv := []string{filepath.Join(root, "installer-entry.sh"), "--request-stdin"}
	if action == "status" {
		ctx, cancel := context.WithTimeout(context.Background(), 120*time.Second)
		return exec.CommandContext(ctx, "/bin/sh", argv...), cancel
	}
	return exec.Command("/bin/sh", argv...), func() {}
}

func runInstalledHelper(root string, request privilegedRequest) (privilegedResult, error) {
	cmd, cancel := installedHelperCommand(root, request.Action)
	defer cancel()
	return runTrustedHelperCommand(cmd, request)
}

func completeTrustedVersion(root string, ownerUID int, restore bool) error {
	// The Python backend releases the manual lock after its transaction.
	// Reacquire it before touching installed helper directories; otherwise
	// a manual installation could begin between backend completion and
	// the Go bootstrap's previous-version cleanup.
	guard, err := lockInstaller(trustedLock, ownerUID)
	if err != nil {
		return err
	}
	defer guard.Close()
	state, err := runInstalledHelper(root,
		privilegedRequest{SchemaVersion: 1, Action: "status"})
	if err != nil || state.PrivilegedTransactionState != "none" {
		return errors.New("cannot change helper version while recovery is pending")
	}
	if restore {
		err = restorePreviousTrustedVersion(root, ownerUID)
	} else {
		err = retirePreviousTrustedVersion(root, ownerUID)
	}
	if err != nil {
		return err
	}
	return syncDirectory(filepath.Dir(root))
}

// A root-side Python failure is a valid result, even though it exits
// non-zero. Forward the sanitized schema-v1 envelope rather than discarding
// it in Go and reducing everything to an authorization failure.
func relayHelperResponse(writer io.Writer, action string, reply privilegedResult, helperErr error) error {
	if reply.SchemaVersion != 1 {
		return helperErr
	}
	if reply.Status == "error" && reply.Operation == "" {
		// The Python root helper deliberately omits operation from its
		// fixed error envelope. The validated Go request supplies it.
		reply.Operation = action
	}
	if reply.Operation != action || reply.SecretsIncluded {
		return errors.New("invalid privileged helper reply")
	}
	if reply.Status == "error" && !knownPrivilegedError(reply.ErrorCode) {
		return errors.New("unexpected privileged helper error")
	}
	if !validAbortedFailureStage(reply.ErrorCode, reply.FailureStage) {
		// Reject any unexpected diagnostic payload rather than relaying
		// untrusted free-form text out of a privileged process.
		return errors.New("unexpected privileged failure stage")
	}
	if err := json.NewEncoder(writer).Encode(reply); err != nil {
		return err
	}
	return helperErr
}

func relayBootstrapFailure(writer io.Writer, action string, failure error) error {
	// These Go-only failures occur before Python can return its own JSON.
	// Keep the response schema stable without exposing filesystem paths,
	// environment contents, helper stderr or any credentials.
	code := "bootstrap_failed"
	if errors.Is(failure, errInstallerBusy) {
		code = "installation_busy"
	} else if errors.Is(failure, errUnsafeInstallerLock) {
		code = "unsafe_lock"
	} else if errors.Is(failure, errInstallerRecoveryPending) {
		code = "recovery_required"
	} else if errors.Is(failure, errUnavailablePython) {
		code = "unsupported_python"
	}
	_ = json.NewEncoder(writer).Encode(privilegedResult{
		SchemaVersion: 1, Operation: action, Status: "error", ErrorCode: code,
	})
	return failure
}

// A missing helper JSON reply after an interrupted mutation must not mask
// a durable journal that requires explicit recovery. Only a successful,
// fixed-schema read-only protected status may change the outward error code.
func classifyInterruptedHelper(helperErr error, status privilegedResult, statusErr error) error {
	if statusErr == nil && status.SchemaVersion == 1 && status.Status == "passed" &&
		status.Operation == "status" && !status.SecretsIncluded &&
		status.PrivilegedTransactionState != "" &&
		status.PrivilegedTransactionState != "none" {
		return errInstallerRecoveryPending
	}
	return helperErr
}

func rootBootstrap(reader io.Reader, writer io.Writer) error {
	if os.Geteuid() != 0 {
		return errors.New("privileged bootstrap requires explicit sudo authorization")
	}
	request, err := decodePrivilegedRequest(reader)
	if err != nil {
		return err
	}
	if err := validateEmbeddedBundle(); err != nil {
		return relayBootstrapFailure(writer, request.Action, err)
	}
	// Unlike the manual lock, this dedicated root-owned lifetime lock is
	// held across Go helper promotion AND Python execution. It prevents a
	// second Go bootstrap from swapping the helper underneath the first
	// process while allowing Python to reacquire the manual install lock.
	if err := ensurePrivateBootstrapLockDir(filepath.Dir(bootstrapLock), 0); err != nil {
		return relayBootstrapFailure(writer, request.Action, err)
	}
	bootstrapGuard, err := lockInstaller(bootstrapLock, 0)
	if err != nil {
		return relayBootstrapFailure(writer, request.Action, err)
	}
	defer bootstrapGuard.Close()
	if request.Action == "status" || request.Action == "recover" {
		response, helperErr := runInstalledHelper(trustedDir, request)
		if response.SchemaVersion == 1 {
			return relayHelperResponse(writer, request.Action, response, helperErr)
		}
		if request.Action == "recover" {
			state, statusErr := runInstalledHelper(trustedDir,
				privilegedRequest{SchemaVersion: 1, Action: "status"})
			helperErr = classifyInterruptedHelper(helperErr, state, statusErr)
		}
		return relayBootstrapFailure(writer, request.Action, helperErr)
	}
	old, err := prepareTrustedVersion(trustedDir, trustedLock, 0, func() (string, error) {
		response, err := runInstalledHelper(trustedDir, privilegedRequest{SchemaVersion: 1, Action: "status"})
		return response.PrivilegedTransactionState, err
	})
	if err != nil {
		return relayBootstrapFailure(writer, request.Action, err)
	}
	response, err := runInstalledHelper(trustedDir, request)
	if err != nil {
		// Do not switch a helper version underneath an incomplete rollback:
		// its matching new manifest and engine are still needed for recovery.
		state, statusErr := runInstalledHelper(trustedDir,
			privilegedRequest{SchemaVersion: 1, Action: "status"})
		if old && statusErr == nil && state.PrivilegedTransactionState == "none" {
			if restoreErr := completeTrustedVersion(trustedDir, 0, true); restoreErr != nil {
				return relayBootstrapFailure(writer, request.Action,
					errors.New("previous trusted helper could not be restored"))
			}
		}
		if response.SchemaVersion == 1 {
			return relayHelperResponse(writer, request.Action, response, err)
		}
		return relayBootstrapFailure(writer, request.Action,
			classifyInterruptedHelper(err, state, statusErr))
	}
	// Once verified success and cleanup is complete the old helper may be
	// retired. A retained previous copy is never executed automatically.
	if old && response.Status == "installed" {
		if err := completeTrustedVersion(trustedDir, 0, false); err != nil {
			// A committed installation must never be presented as failed
			// solely because the previous launcher cleanup could not finish.
			response.Status = "installed_cleanup_required"
		}
	}
	return relayHelperResponse(writer, request.Action, response, nil)
}

func discardTrustedStage(stage string, ownerUID int) error {
	// Only fixed root-owned staging directories created by this bootstrap
	// are recyclable. Go's RemoveAll never traverses a symbolic link;
	// this check also rejects a symlink at the top-level stage path.
	if err := protectedPath(stage, ownerUID, true); err != nil {
		return err
	}
	return os.RemoveAll(stage)
}

func restorePreviousTrustedVersion(root string, ownerUID int) error {
	previous := root + ".previous"
	if err := protectedPath(previous, ownerUID, true); err != nil {
		return err
	}
	failed := root + ".failed"
	if err := protectedPath(failed, ownerUID, true); err == nil {
		// Only a previously created root-owned failed *helper bundle*
		// is deleted. No agent state, backups or secret directories live
		// here. A second failed upgrade must not collide with stale files.
		if err := os.RemoveAll(failed); err != nil {
			return err
		}
		if err := syncDirectory(filepath.Dir(root)); err != nil {
			return err
		}
	} else if !os.IsNotExist(err) {
		// Refuse symlinks, other owners and unsafe modes; never blindly
		// rename over an unvalidated path.
		return err
	}
	if err := os.Rename(root, failed); err != nil {
		return err
	}
	if err := os.Rename(previous, root); err != nil {
		_ = os.Rename(failed, root)
		return err
	}
	return syncDirectory(filepath.Dir(root))
}

func retirePreviousTrustedVersion(root string, ownerUID int) error {
	previous := root + ".previous"
	if err := protectedPath(previous, ownerUID, true); err != nil {
		return err
	}
	// Every file was created by the earlier verified bootstrap. A symlink
	// must never let RemoveAll traverse into an unrelated filesystem tree.
	return os.RemoveAll(previous)
}
