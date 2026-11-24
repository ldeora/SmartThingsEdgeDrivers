package main

import (
	"bytes"
	"errors"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"syscall"
)

var errUnsupportedUninstall = errors.New("existing managed agent is not a verified v2 layout")

// Mirrors the installed-agent branch of install_core.detect_installed_protocol.
// The owner record is not decisive when managed files remain. This preflight
// only prevents unnecessary helper promotion; Python still decides whether
// uninstall is authorized under its own lock. Never inspect private state.
var installedProtocolMarker = regexp.MustCompile(`(?m)^[[:space:]]*PROTOCOL[[:space:]]*=[[:space:]]*['"](linux-host-agent|computer-host-agent)['"][[:space:]]*(?:#.*)?$`)

const maxInstalledMarkerBytes = 128 * 1024

func readInstalledMarker(base, path string, uid int) ([]byte, error) {
	rel, err := filepath.Rel(base, filepath.Dir(path))
	if err != nil || rel == ".." || strings.HasPrefix(rel, ".."+string(filepath.Separator)) {
		return nil, errUnsupportedUninstall
	}
	parent := base
	if err := protectedPath(parent, uid, true); err != nil {
		return nil, err
	}
	if rel != "." {
		for _, name := range strings.Split(rel, string(filepath.Separator)) {
			parent = filepath.Join(parent, name)
			if err := protectedPath(parent, uid, true); err != nil {
				return nil, err
			}
		}
	}
	if err := protectedPath(path, uid, false); err != nil {
		return nil, err
	}
	f, err := os.OpenFile(path, os.O_RDONLY|syscall.O_NOFOLLOW|syscall.O_NONBLOCK|syscall.O_CLOEXEC, 0)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	info, err := f.Stat()
	if err != nil || !info.Mode().IsRegular() || int(info.Sys().(*syscall.Stat_t).Uid) != uid || info.Mode().Perm()&0o022 != 0 || info.Sys().(*syscall.Stat_t).Nlink != 1 {
		return nil, errUnsupportedUninstall
	}
	visible, err := os.Lstat(path)
	if err != nil || !os.SameFile(info, visible) {
		return nil, errUnsupportedUninstall
	}
	content, err := io.ReadAll(io.LimitReader(f, maxInstalledMarkerBytes+1))
	if err != nil || len(content) > maxInstalledMarkerBytes {
		return nil, errUnsupportedUninstall
	}
	return content, nil
}

func requireV2UninstallTarget(root, agent string, uid int) error {
	base := "/"
	if root != trustedDir || uid != 0 {
		base = filepath.Dir(root)
	}
	app, err := readInstalledMarker(base, agent, uid)
	if err != nil {
		return errUnsupportedUninstall
	}
	names := installedProtocolMarker.FindAllSubmatch(app, -1)
	if len(names) != 1 || string(names[0][1]) != "computer-host-agent" {
		return errUnsupportedUninstall
	}
	avahi, err := readInstalledMarker(base, filepath.Join(base, "etc/avahi/services/linux-host-agent.service"), uid)
	if os.IsNotExist(err) {
		return nil
	}
	if err != nil || bytes.Contains(avahi, []byte("_linuxhost._tcp")) || !bytes.Contains(avahi, []byte("_computerhost._tcp")) {
		return errUnsupportedUninstall
	}
	return nil
}
