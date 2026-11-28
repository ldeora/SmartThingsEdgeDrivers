"""Focused fixtures for the documentation link gate."""
from collections import Counter
import unittest

from check_computer_host_docs import check, parse


class LinkTests(unittest.TestCase):
    def defects(self, files):
        return check(set(files), files.__getitem__)

    def test_links_images_reference_and_encoded_path(self):
        files = {
            "computer-host-lan/README.md": """# Start
[guide](docs/guide.md#some-heading)
[duplicate](docs/guide.md#some-heading-1)
[ref][guide]
![image](docs/image%20one.png)
<a href="docs/guide.md#explicit">HTML link</a>

[guide]: docs/guide.md
""",
            "computer-host-lan/docs/guide.md": "# Some **Heading**\n# Some Heading\n<a id=\"explicit\"></a>",
            "computer-host-lan/docs/image one.png": "",
        }
        self.assertEqual(self.defects(files), Counter())

    def test_missing_path_anchor_case_and_escape(self):
        files = {
            "computer-host-lan/README.md": "[bad](missing.md)\n"
            "[anchor](guide.md#not-there)\n[case](Guide.md)\n[escape](../../bad)\n",
            "computer-host-lan/guide.md": "# Present",
        }
        self.assertEqual(sum(self.defects(files).values()), 4)

    def test_code_and_external_links_are_not_checked(self):
        files = {"computer-host-lan/README.md": """# Heading
`[bad](missing.md)`

~~~md
[bad](missing.md)
~~~

    [bad](missing.md)

[web](https://example.com/a#b)
[mail](mailto:a@example.com)
[heading](#heading)
"""}
        self.assertEqual(self.defects(files), Counter())

    def test_tables_unicode_and_setext_headings(self):
        links, anchors = parse("État / Power (on)\n=================\n\n"
                               "| Item |\n| --- |\n| [x](a.md) |\n")
        self.assertIn("état--power-on", anchors)
        self.assertEqual(links, ["a.md"])

    def test_baseline_counts_occurrences_not_lines(self):
        p = "computer-host-lan/README.md"
        before = self.defects({p: "[x](gone.md)"})
        after = self.defects({p: "\n[x](gone.md)\n[x](gone.md)"})
        self.assertEqual(sum((after - before).values()), 1)
        self.assertFalse(before - after)
        self.assertEqual(sum((before - self.defects({p: "# Fixed"})).values()), 1)

    def test_root_directory_and_same_page_links(self):
        files = {
            "README.md": "[project](computer-host-lan/)",
            "computer-host-lan/README.md": "# Start\n[here](#start)\n"
            "[root](/README.md)\n[dir](docs/)",
            "computer-host-lan/docs/guide.md": "# Guide",
        }
        self.assertEqual(self.defects(files), Counter())


if __name__ == "__main__":
    unittest.main()
