"""Synthetic evidence-collection tests; no SDK or network required."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from collect_license_evidence import collect_dotnet, collect_go, package_record


class LicenseEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cache = self.root / "cache"
        self.cache.mkdir()
        self.binary = self.root / "binary"
        self.binary.write_bytes(b"fixture executable")

    def package(self, name, version, files):
        directory = self.cache / name.lower() / version
        directory.mkdir(parents=True)
        for filename, data in files.items():
            path = directory / filename
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        return directory

    def test_runtime_target_and_download_pack_preserve_original_text(self):
        self.package("Example", "1.0.0", {
            "example.nuspec": b'<package xmlns="urn:test"><metadata><license type="file">terms/custom.txt</license></metadata></package>',
            "terms/custom.txt": b"Original\r\nLicense\n",
            "lib/net10.0/example.dll": b"not a license",
        })
        self.package("Microsoft.NETCore.App.Runtime.win-x64", "10.0.1", {
            "LICENSE.TXT": b"Runtime license",
            "THIRD-PARTY-NOTICES.TXT": b"Runtime notices",
        })
        graph = {
            "targets": {
                "net10.0": {"Other/9.0": {"type": "package"}},
                "net10.0/win-x64": {"Example/1.0.0": {"type": "package"}},
            },
            "project": {"frameworks": {"net10.0": {"downloadDependencies": [
                {"name": "Microsoft.NETCore.App.Runtime.win-x64", "version": "[10.0.1]"},
            ]}}},
            "packageFolders": {str(self.cache): {}},
        }
        assets = self.root / "project.assets.json"
        assets.write_text(json.dumps(graph), encoding="utf-8")
        output = self.root / "out"
        collect_dotnet(assets, self.binary, output, "win-x64")
        evidence = json.loads((output / "resolved.json").read_text())
        self.assertEqual(evidence["target_packages"], ["Example/1.0.0"])
        self.assertEqual(evidence["download_dependencies"], ["Microsoft.NETCore.App.Runtime.win-x64/10.0.1"])
        self.assertEqual(evidence["review_status"], "not_signed_off")
        self.assertEqual((output / "packages/example/1.0.0/terms/custom.txt").read_bytes(),
                         b"Original\r\nLicense\n")
        self.assertFalse((output / "packages/example/1.0.0/lib").exists())
        self.assertTrue((output / "packages/microsoft.netcore.app.runtime.win-x64/10.0.1/THIRD-PARTY-NOTICES.TXT").is_file())
        with self.assertRaises(ValueError):
            collect_dotnet(assets, self.binary, self.root / "wrong", "win-arm64")

        download = graph["project"]["frameworks"]["net10.0"]["downloadDependencies"][0]
        # .NET 10 emits equal inclusive bounds for an exact runtime pack.
        for index, exact in enumerate(("[10.0.1, 10.0.1]", "[ 10.0.1 , 10.0.1 ]")):
            with self.subTest(version=exact):
                download["version"] = exact
                assets.write_text(json.dumps(graph), encoding="utf-8")
                destination = self.root / f"equal-bounds-{index}"
                collect_dotnet(assets, self.binary, destination, "win-x64")
                actual = json.loads((destination / "resolved.json").read_text())
                self.assertEqual(actual, evidence)
        for index, version in enumerate(("[10.0.1, 10.0.2]", "[10.0.1,)", "(10.0.1, 10.0.1]", "10.0.1")):
            with self.subTest(version=version):
                download["version"] = version
                assets.write_text(json.dumps(graph), encoding="utf-8")
                destination = self.root / f"unresolved-{index}"
                with self.assertRaisesRegex(ValueError, "Unresolved runtime-pack version"):
                    collect_dotnet(assets, self.binary, destination, "win-x64")
                self.assertFalse(destination.exists())

    def test_missing_package_and_expression_only_are_review_items(self):
        output = self.root / "out"
        self.assertEqual(package_record("Missing/1.0", [self.cache], output)["status"],
                         "package_not_found")
        self.package("Example", "1.0", {
            "example.nuspec": b'<package><metadata><license type="expression">MIT</license></metadata></package>',
        })
        record = package_record("Example/1.0", [self.cache], output)
        self.assertEqual(record["status"], "missing_notice_text")
        self.assertEqual(record["license_metadata"]["license"]["text"], "MIT")

    def test_declared_license_cannot_escape(self):
        self.package("Example", "1.0", {
            "example.nuspec": b'<package><metadata><license type="file">../../outside.txt</license></metadata></package>',
        })
        with self.assertRaises(ValueError):
            package_record("Example/1.0", [self.cache], self.root / "out")

    def test_go_inventory_matches_binary_and_copies_notice_bytes(self):
        module_dir = self.package("module", "1.0", {"LICENSE": b"Module license"})
        goroot = self.root / "goroot"
        goroot.mkdir()
        (goroot / "LICENSE").write_bytes(b"Go license")
        module = {"Path": "example.org/module", "Version": "v1.0.0", "Dir": str(module_dir)}

        def command(args, **kwargs):
            if args[:2] == ["go", "list"]:
                return json.dumps({"ImportPath": "fmt"}) + "\n" + json.dumps({"Module": module})
            if args[:3] == ["go", "version", "-m"]:
                return "binary: go1.25.14\n\tdep\texample.org/module\tv1.0.0\th1:fixture\n"
            if args == ["go", "env", "GOROOT"]:
                return str(goroot)
            if args == ["go", "env", "GOVERSION"]:
                return "go1.25.14\n"
            raise AssertionError(args)

        output = self.root / "go-evidence"
        with patch("collect_license_evidence.subprocess.check_output", side_effect=command):
            collect_go(self.binary, output)
        record = json.loads((output / "resolved.json").read_text())
        self.assertEqual(record["modules"][0]["module"], "example.org/module")
        self.assertEqual((output / "modules/0/LICENSE").read_bytes(), b"Module license")
        self.assertEqual((output / "toolchain/LICENSE").read_bytes(), b"Go license")
        module["Version"] = "v2.0.0"
        with patch("collect_license_evidence.subprocess.check_output", side_effect=command):
            with self.assertRaises(ValueError):
                collect_go(self.binary, self.root / "mismatch")


if __name__ == "__main__":
    unittest.main()
