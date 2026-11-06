"""Behavioral checks using synthetic shapes, not commercial icon assets."""

import hashlib
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "validate_svg.py"
SPEC = importlib.util.spec_from_file_location("validate_svg", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class SvgValidationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.file = Path(self.directory.name) / "sample.svg"

    def write(self, path="M1 1H23V23H1Z M5 5V19H19V5Z", fill="#fff", extra="", child=None):
        element = child if child is not None else f'<path fill="{fill}" d="{path}"/>'
        data = f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" {extra}>{element}</svg>'
        self.file.write_text(data, encoding="utf-8")

    def result(self, **kwargs):
        return MODULE.validate_svg(self.file, kwargs.get("width", 24), kwargs.get("height", 24), kwargs.get("color", "#ffffff"))

    def test_closed_compound_is_read_only_and_hashed(self):
        self.write()
        before = self.file.read_bytes()
        report = self.result()
        self.assertTrue(report["passed"], report)
        self.assertEqual(report["path_count"], 1)
        self.assertEqual(report["bytes"], len(before))
        self.assertEqual(report["sha256"], hashlib.sha256(before).hexdigest())
        self.assertEqual(self.file.read_bytes(), before)

    def test_color_forms(self):
        for fill in ("white", "#fff", "#FFFFFF", "rgb(255, 255, 255)"):
            with self.subTest(fill=fill):
                self.write(fill=fill)
                self.assertTrue(self.result()["passed"])

    def test_inherited_fill_and_default_rule(self):
        self.write(extra='fill="white"', child='<path d="M1 1L20 1 20 20 1 20z"/>')
        self.assertTrue(self.result()["passed"])

    def test_valid_path_commands(self):
        for path in (
            "m1e-1 .1 10 0 0 10 -10 0z",
            "M1 1C2 1 3 2 4 4S8 8 9 9Q10 10 9 11T1 1Z",
            "M1 1a5 5 0 0 1 10 0L1 1z",
            "M1 1h10v10H1V1Z",
        ):
            with self.subTest(path=path):
                self.write(path=path)
                self.assertTrue(self.result()["passed"], self.result())

    def test_invalid_paths(self):
        for path in (
            "M1 1L2 2Z M3 3L4 4", "M1 1L2 2 M3 3L4 4Z",
            "M1 1C2 2 3 3Z", "M1 1R2 2Z", "M1 1L1e999 2Z",
            "M1 1Z", "L1 1L2 2Z", "M1 1L2 2ZL3 3Z",
            "M1 1A-1 2 0 0 1 3 3Z", "M1 1A1 2 0 2 1 3 3Z",
            "M1 1L2 2Z 3 3", "", "M1 1Lnan 2Z",
            "M1 1L2,,2Z", "M,1 1L2 2Z", "M1 1L2 2Z,",
        ):
            with self.subTest(path=path):
                self.write(path=path)
                self.assertFalse(self.result()["passed"])

    def test_forbidden_structure_and_attributes(self):
        for extra in ('fill-rule="evenodd"', 'stroke="none"', 'style="fill:white"', 'id="icon"', 'opacity="0.5"'):
            with self.subTest(extra=extra):
                self.write(extra=extra)
                self.assertFalse(self.result()["passed"])
        for child in (
            '<g><path fill="white" d="M1 1L2 2Z"/></g>',
            '<path fill="white" d="M1 1L2 2Z"/><rect/>',
            '<mask/>', '<clipPath/>', '<linearGradient/>', '<image/>', '<text>x</text>',
            '<path fill="white" fill-rule="evenodd" d="M1 1L2 2Z"/>',
            '<path fill="white" transform="translate(1)" d="M1 1L2 2Z"/>',
            '<path xmlns:xlink="http://www.w3.org/1999/xlink" xlink:href="test" fill="white" d="M1 1L2 2Z"/>',
        ):
            with self.subTest(child=child):
                self.write(child=child)
                self.assertFalse(self.result()["passed"])

    def test_wrong_or_unsupported_color(self):
        for fill in ("black", "currentColor", "url(#x)", "none", "rgba(255,255,255,.5)", "rgb(999,0,0)"):
            with self.subTest(fill=fill):
                self.write(fill=fill)
                self.assertFalse(self.result()["passed"])

    def test_wrong_canvas(self):
        self.write()
        self.assertFalse(self.result(width=16)["passed"])
        self.assertFalse(self.result(width=float("nan"))["passed"])
        for old, new in (("0 0 24 24", "1 0 24 24"), ('height="24"', 'height="0"'), ('width="24"', 'width="100%"')):
            self.write()
            self.file.write_text(self.file.read_text().replace(old, new))
            self.assertFalse(self.result()["passed"])

    def test_xml_rejections(self):
        for data in (
            "<svg>", '<!DOCTYPE svg [<!ENTITY x "x">]><svg/>',
            '<svg xmlns="https://invalid.test"/>', '<?xml-stylesheet href="x"?><svg/>',
        ):
            with self.subTest(data=data):
                self.file.write_text(data)
                self.assertFalse(self.result()["passed"])

    def test_cli_success_and_failure(self):
        self.write()
        command = [sys.executable, str(SCRIPT), str(self.file), "--width", "24", "--height", "24", "--color", "white"]
        self.assertEqual(subprocess.run(command, capture_output=True).returncode, 0)
        self.write(path="M1 1L2 2")
        self.assertEqual(subprocess.run(command, capture_output=True).returncode, 1)

    def test_missing_file_is_reported(self):
        self.assertFalse(self.result()["passed"])


if __name__ == "__main__":
    unittest.main()
