package main

import (
	"os"
	"path/filepath"
)

// Only call after the installed helper reports clean protected state under
// the shared manual lock. Preserve an unsafe entry and sync each successful
// retirement independently, including when a later retirement is refused.
func retireObsoleteHelperArtifacts(root string, uid int) error {
	for _, suffix := range []string{".previous", ".failed"} {
		path := root + suffix
		if _, err := os.Lstat(path); os.IsNotExist(err) {
			continue
		} else if err != nil {
			return err
		}
		if err := discardTrustedStage(path, uid); err != nil {
			return err
		}
		if err := syncDirectory(filepath.Dir(root)); err != nil {
			return err
		}
	}
	return nil
}

func finishHelperRetirementIfNeeded(root string, uid int) error {
	for _, suffix := range []string{".previous", ".failed"} {
		if _, err := os.Lstat(root + suffix); err == nil {
			return completeTrustedVersion(root, uid, false)
		} else if !os.IsNotExist(err) {
			return err
		}
	}
	return nil
}
