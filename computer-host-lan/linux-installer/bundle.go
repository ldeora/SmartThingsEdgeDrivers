package main

import (
	"crypto/sha256"
	"embed"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"path"
	"regexp"
	"sort"
	"strings"
)

// A signed or independently checksum-verified Go binary is the trust anchor.
// At elevation, all helper/payload bytes come from THIS binary, not the
// downloaded checkout or any user-provided manifest.
//
//go:embed bundle
var installerBundle embed.FS

var installedHelpers = []string{
	"installer-entry.sh",
	"installer_root.py",
	"installer_transaction.py",
	"credential_continuity.py",
	"retained_state_eligibility.py",
	"historical_snapshot.py",
	"persistent_wol.py",
	"wol_ownership.py",
	"install_core.py",
	"payload_staging.py",
	"transaction_journal.py",
	"runtime_verify.py",
}

var payloadFiles = []string{
	"agent/linux_host_agent.py",
	"agent/power_helper.py",
	"agent/systemd/linux-host-agent.service",
	"agent/systemd/linux-host-agent-power.service",
	"agent/systemd/linux-host-agent-power.socket",
	"agent/systemd/enable-power.conf",
	"agent/systemd/avahi-linux-host-agent.service",
	"scripts/install_core.py",
	"scripts/runtime_verify.py",
	"scripts/transaction_journal.py",
}

var previewFiles = []string{
	"scripts/persistent_wol.py",
	"scripts/installer-api.sh",
	"scripts/installer_api.py",
	"scripts/python-selector.sh",
	"scripts/install_core.py",
	"scripts/runtime_verify.py",
	"scripts/transaction_journal.py",
	"agent/linux_host_agent.py",
	"agent/power_helper.py",
	"agent/systemd/linux-host-agent.service",
	"agent/systemd/linux-host-agent-power.service",
	"agent/systemd/linux-host-agent-power.socket",
	"agent/systemd/enable-power.conf",
	"agent/systemd/avahi-linux-host-agent.service",
}

var bundledAgentVersion = regexp.MustCompile("(?m)^VERSION = \"([A-Za-z0-9.+_-]+)\"[ \t]*$")

func bundleRead(name string) ([]byte, error) {
	if name == "" || strings.HasPrefix(name, "/") || path.Clean(name) != name ||
		strings.HasPrefix(name, "../") || strings.Contains(name, "\\") {
		return nil, errors.New("invalid embedded asset name")
	}
	return installerBundle.ReadFile("bundle/" + name)
}

func manifestFromEmbedded() ([]byte, error) {
	type manifest struct {
		SchemaVersion int               `json:"schema_version"`
		AgentVersion  string            `json:"agent_version"`
		Files         map[string]string `json:"files"`
	}
	content, err := bundleRead("agent/linux_host_agent.py")
	if err != nil {
		return nil, err
	}
	version := bundledAgentVersion.FindSubmatch(content)
	if len(version) != 2 {
		return nil, errors.New("embedded agent version missing or invalid")
	}
	files := make(map[string]string, len(payloadFiles))
	var total int
	for _, name := range payloadFiles {
		data, err := bundleRead(name)
		if err != nil {
			return nil, err
		}
		total += len(data)
		if len(data) == 0 || len(data) > 1<<20 || total > 4<<20 {
			return nil, errors.New("embedded payload exceeds fixed limits")
		}
		digest := sha256.Sum256(data)
		files[name] = hex.EncodeToString(digest[:])
	}
	return json.Marshal(manifest{SchemaVersion: 1, AgentVersion: string(version[1]), Files: files})
}

func validateEmbeddedBundle() error {
	manifest, err := manifestFromEmbedded()
	if err != nil || len(manifest) > 4096 {
		return errors.New("invalid embedded trusted manifest")
	}
	names := make(map[string]bool)
	for _, helper := range installedHelpers {
		name := "scripts/" + helper
		if names[name] {
			return errors.New("duplicate embedded helper")
		}
		names[name] = true
		if _, err := bundleRead(name); err != nil {
			return fmt.Errorf("missing embedded helper %s", helper)
		}
	}
	for _, name := range previewFiles {
		names[name] = true
		if _, err := bundleRead(name); err != nil {
			return fmt.Errorf("missing preview asset %s", name)
		}
	}
	for _, name := range payloadFiles {
		names[name] = true
	}
	var actual []string
	err = fs.WalkDir(installerBundle, "bundle", func(name string, entry fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if !entry.IsDir() {
			actual = append(actual, strings.TrimPrefix(name, "bundle/"))
		}
		return nil
	})
	if err != nil {
		return err
	}
	sort.Strings(actual)
	if len(actual) != len(names) {
		return fmt.Errorf("embedded asset count differs from allowlist: %d vs %d", len(actual), len(names))
	}
	for _, name := range actual {
		if !names[name] {
			return fmt.Errorf("unexpected embedded asset: %s", name)
		}
	}
	return nil
}
