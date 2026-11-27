"""Fixture tests for the Linux installer third-party notices (#190). No Go needed."""
from pathlib import Path
import tempfile
import unittest

import linux_third_party_notices as notices

MIT = """MIT License

Copyright (c) 2026 Example

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software").
"""
BSD3 = """Copyright 2009 The Go Authors.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:
   * Neither the name of Google LLC nor the names of its contributors may be
used to endorse or promote products derived from this software.
"""


class NoticesTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def module(self, name, files):
        directory = self.root / name
        directory.mkdir(parents=True)
        for filename, text in files.items():
            (directory / filename).write_text(text)
        return directory

    def test_classifies_known_licences_and_refuses_unknown(self):
        self.assertEqual(notices.classify(MIT), "MIT")
        self.assertEqual(notices.classify(BSD3), "BSD-3-Clause")
        with self.assertRaisesRegex(notices.NoticeError, "unrecognised"):
            notices.classify("All rights reserved. Contact us for terms.")

    def test_render_includes_every_full_text_and_lists_modules(self):
        goroot = self.module("goroot", {"LICENSE": BSD3, "PATENTS": "Additional IP Rights Grant"})
        mod = self.module("mod", {"LICENSE.txt": MIT, "README.md": "ignored"})
        text = notices.render([("example.com/mod", "v1.2.3", mod)], goroot)
        self.assertIn("Components (2):", text)
        self.assertIn("Module: example.com/mod v1.2.3\nLicense: MIT", text)
        self.assertIn("--- LICENSE.txt ---", text)
        self.assertIn("--- PATENTS ---", text)
        self.assertIn("Permission is hereby granted", text)
        self.assertNotIn("ignored", text)
        self.assertEqual(notices.listed_modules(text), {("example.com/mod", "v1.2.3")})
        # Deterministic output.
        self.assertEqual(text, notices.render([("example.com/mod", "v1.2.3", mod)], goroot))

    def test_module_without_licence_fails(self):
        goroot = self.module("goroot", {"LICENSE": BSD3})
        mod = self.module("bare", {"README.md": "no licence"})
        with self.assertRaisesRegex(notices.NoticeError, "no licence file"):
            notices.render([("example.com/bare", "v1.0.0", mod)], goroot)

    def test_conflicting_licences_fail(self):
        mod = self.module("two", {"LICENSE": MIT, "COPYING": BSD3})
        with self.assertRaisesRegex(notices.NoticeError, "expected one licence"):
            notices.licence_of(notices.licence_files(mod))

    def test_build_info_must_match_listed_modules(self):
        text = ("Go standard library and runtime\n"
                "Module: example.com/a v1.0.0\nModule: example.com/b v2.0.0\n")
        info = ("installer: go1.25.14\n\tpath\texample.com/installer\n"
                "\tdep\texample.com/a\tv1.0.0\th1:a=\n"
                "\tdep\texample.com/b\tv2.0.0\th1:b=\n\tbuild\tGOOS=linux\n")
        notices.check_build_info(text, info)
        with self.assertRaisesRegex(notices.NoticeError, r"missing \['example.com/c v1.0.0'\]"):
            notices.check_build_info(text, info + "\tdep\texample.com/c\tv1.0.0\th1:c=\n")
        with self.assertRaisesRegex(notices.NoticeError, r"extra \['example.com/b v2.0.0'\]"):
            notices.check_build_info(text, info.replace("\tdep\texample.com/b\tv2.0.0\th1:b=\n", ""))
        with self.assertRaisesRegex(notices.NoticeError, "replaced"):
            notices.check_build_info(text, info + "\t=>\texample.com/fork\tv0.0.1\th1:f=\n")

    def test_notices_must_cover_the_go_standard_library(self):
        with self.assertRaisesRegex(notices.NoticeError, "standard library"):
            notices.listed_modules("Module: example.com/a v1.0.0\n")

    def test_committed_notices_are_well_formed(self):
        text = notices.NOTICES.read_text(encoding="utf-8")
        modules = notices.listed_modules(text)
        self.assertTrue(modules)
        self.assertIn("golang.org/x/sys", {path for path, _ in modules})
        # Every listed component carries a full licence text section.
        self.assertGreaterEqual(text.count("\n--- LICENSE"), len(modules) + 1)


if __name__ == "__main__":
    unittest.main()
