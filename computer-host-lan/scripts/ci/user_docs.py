"""Shared layout for the current offline user documentation and Windows kit.

Explicit inclusion avoids dragging obsolete development/history into a user
download. Keep links relative to the project root and preserve image paths.
"""
from pathlib import Path

USER_DOCS = (
    "SECURITY.md",
    "docs/install-windows.md",
    "docs/install-linux.md",
    "docs/smartthings.md",
    "docs/upgrade.md",
    "docs/troubleshooting.md",
    "docs/testing.md",
    "docs/THIRD-PARTY-NOTICES.md",
    "docs/images/windows-setup/01-welcome.png",
    "docs/images/windows-setup/02-upgrade.png",
    "docs/images/windows-setup/04-connect.png",
)


def notes_path(version: str) -> str:
    directory = "beta" if "-beta." in version else "release"
    return f"docs/{directory}/RELEASE-NOTES-v{version}.md"


def docs_paths(version: str) -> tuple[str, ...]:
    return (*USER_DOCS, notes_path(version), "README.md", "CHANGELOG.md",
            "LICENSE", "release.json", "linux-installer/THIRD-PARTY-NOTICES.txt")


def validate_inputs(root: Path, paths: tuple[str, ...]) -> None:
    for name in paths:
        path = root / name
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"Missing or symlinked documentation input: {name}")
