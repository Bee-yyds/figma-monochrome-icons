#!/usr/bin/env python3
"""Read-only checks for this Skill's normalized, opaque Iconfont SVG profile.

Checks syntax and file structure, not geometric bounds, winding or appearance.
SPDX-License-Identifier: GPL-3.0-only
"""

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET


NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
TOKEN = re.compile(rf"[MmLlHhVvCcSsQqTtAaZz]|{NUMBER}")
COMMANDS = set("MmLlHhVvCcSsQqTtAaZz")
COUNTS = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6,
          "S": 4, "Q": 4, "T": 2, "A": 7}
NAMESPACE = "http://www.w3.org/2000/svg"
NAMED = dict(zip(
    "black silver gray white maroon red purple fuchsia green lime olive yellow navy blue teal aqua".split(),
    "000000 c0c0c0 808080 ffffff 800000 ff0000 800080 ff00ff 008000 00ff00 808000 ffff00 000080 0000ff 008080 00ffff".split(),
))


def color(value):
    """Return opaque RGB bytes; deliberately reject unsupported CSS syntax."""
    value = value.strip().lower()
    value = "#" + NAMED[value] if value in NAMED else value
    if re.fullmatch(r"#[0-9a-f]{3}", value):
        value = "#" + "".join(c * 2 for c in value[1:])
    if re.fullmatch(r"#[0-9a-f]{6}", value):
        return tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))
    match = re.fullmatch(r"rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)", value)
    if match and all(int(n) <= 255 for n in match.groups()):
        return tuple(map(int, match.groups()))
    raise ValueError("unsupported opaque solid color: " + value)


def path_error(data):
    """Validate command arities and explicit closure of every subpath."""
    tokens = []
    end = 0
    for match in TOKEN.finditer(data):
        gap = data[end:match.start()]
        if gap.strip(" \t\r\n,"):
            return "path contains unknown command or invalid data"
        if "," in gap and (gap.count(",") != 1 or not tokens
                           or tokens[-1] in COMMANDS or match.group() in COMMANDS):
            return "invalid comma separator in path"
        tokens.append(match.group())
        end = match.end()
    if data[end:].strip(" \t\r\n") or not tokens:
        return "path is empty or contains invalid data"

    index = 0
    command = None
    opened = False
    drawn = False
    subpaths = 0
    while index < len(tokens):
        if tokens[index] in COMMANDS:
            command = tokens[index]
            index += 1
            if command.upper() == "Z":
                if not opened or not drawn:
                    return "empty subpath or unexpected close command"
                opened = False
                command = None
                continue
        elif command is None:
            return "path must start each subpath with moveto"

        upper = command.upper()
        count = COUNTS[upper]
        args = tokens[index:index + count]
        if len(args) != count or any(n in COMMANDS for n in args):
            return "incomplete arguments for " + command
        values = list(map(float, args))
        if not all(math.isfinite(n) for n in values):
            return "non-finite path coordinate"
        if upper == "M":
            if opened:
                return "previous subpath is not closed"
            opened, drawn = True, False
            subpaths += 1
            command = "l" if command == "m" else "L"
        else:
            if not opened:
                return "drawing command without an open subpath"
            drawn = True
            if upper == "A" and (values[0] < 0 or values[1] < 0
                                  or args[3] not in ("0", "1")
                                  or args[4] not in ("0", "1")):
                return "invalid arc radii or flags"
        index += count
    if opened:
        return "subpath is not explicitly closed"
    if not subpaths:
        return "path contains no closed subpath"
    return None


def dimension(value):
    if not re.fullmatch(rf"\s*{NUMBER}(?:px)?\s*", value):
        raise ValueError("dimension must be numeric or px")
    result = float(value.strip().removesuffix("px"))
    if not math.isfinite(result) or result <= 0:
        raise ValueError("dimension must be finite and positive")
    return result


def validate_svg(filename, width, height, expected_color):
    report = {"file": str(filename), "passed": False, "errors": []}
    errors = report["errors"]
    try:
        payload = Path(filename).read_bytes()
    except OSError as exc:
        errors.append(str(exc))
        return report
    report.update(bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest())
    try:
        if not all(math.isfinite(n) and n > 0 for n in (width, height)):
            raise ValueError("expected canvas must be finite and positive")
        expected_rgb = color(expected_color)
        source = payload.decode("utf-8")
        if re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b", source, re.I):
            raise ValueError("DOCTYPE and entity declarations are forbidden")
        if re.search(r"<\?(?!xml\s)", source, re.I):
            raise ValueError("processing instructions are forbidden")
        parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))
        root = ET.fromstring(source, parser=parser)
        if root.tag not in ("svg", "{" + NAMESPACE + "}svg"):
            raise ValueError("root must be an SVG element")
        prefix = "{" + NAMESPACE + "}" if root.tag.startswith("{") else ""
        paths = [el for el in root.iter() if el.tag == prefix + "path"]
        report["path_count"] = len(paths)
        if len(root) != 1 or len(paths) != 1 or root[0] is not paths[0]:
            errors.append("SVG must contain exactly one direct path and no other elements")
        for el in root.iter():
            if el is root:
                allowed = {"width", "height", "viewBox", "version", "fill", "fill-rule", "opacity", "fill-opacity"}
            elif el.tag == prefix + "path":
                allowed = {"d", "fill", "fill-rule", "opacity", "fill-opacity"}
            else:
                errors.append("unsupported SVG element: " + str(el.tag))
                continue
            for key, value in el.attrib.items():
                if key not in allowed:
                    errors.append("forbidden or unsupported attribute: " + key)
                elif key == "fill-rule" and value != "nonzero":
                    errors.append("fill-rule must be nonzero")
                elif key in ("opacity", "fill-opacity") and value.strip() not in ("1", "1.0", "100%"):
                    errors.append("only opaque fill is supported")
                elif key == "fill" and color(value) != expected_rgb:
                    errors.append("fill differs from expected resolved semantic color")
            if el.text and el.text.strip() or el.tail and el.tail.strip():
                errors.append("text content is forbidden")
        actual_width = dimension(root.get("width", ""))
        actual_height = dimension(root.get("height", ""))
        if not math.isclose(actual_width, width, abs_tol=1e-8) or not math.isclose(actual_height, height, abs_tol=1e-8):
            errors.append("width/height differ from expected component canvas")
        box = root.get("viewBox", "").replace(",", " ").split()
        if len(box) != 4 or not all(math.isclose(float(a), b, abs_tol=1e-8) for a, b in zip(box, (0, 0, width, height))):
            errors.append("viewBox must be 0 0 width height")
        for el in paths:
            if not el.get("fill", root.get("fill")):
                errors.append("explicit solid fill is required")
            issue = path_error(el.get("d", ""))
            if issue:
                errors.append(issue)
    except (ValueError, UnicodeError, ET.ParseError) as exc:
        errors.append(str(exc))
    report["passed"] = not errors
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    parser.add_argument("--width", required=True, type=float)
    parser.add_argument("--height", required=True, type=float)
    parser.add_argument("--color", required=True)
    args = parser.parse_args()
    report = validate_svg(args.file, args.width, args.height, args.color)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
