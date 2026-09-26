"""The design system's rules, enforced where discipline fails.

The app is React Native, and each rule below is one it cannot enforce itself.
They are tests rather than review notes because the failure mode of each is
silent: one stray hex quietly breaks dark mode, and nobody notices until
someone is standing in it.
"""

import re
from pathlib import Path

MOBILE = Path(__file__).resolve().parent.parent / "mobile"

# The only file allowed to hold a color: the theme's token table.
TOKEN_FILES = {"tokens.ts"}

HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")


def source_files():
    for path in (MOBILE / "src").rglob("*"):
        if path.suffix in {".js", ".jsx", ".ts", ".tsx"}:
            yield path


def test_no_hex_color_exists_outside_the_token_files():
    """The dual palette dies from one stray hex — G8 in the brief.

    A literal color in a component is invisible in the light theme and wrong in
    the dark one.
    """
    offenders = []
    for path in source_files():
        if path.name in TOKEN_FILES:
            continue
        for number, line in enumerate(path.read_text().splitlines(), 1):
            if HEX.search(line):
                offenders.append(f"{path.name}:{number}: {line.strip()[:80]}")
    assert not offenders, "colors belong in mobile/src/theme/tokens.ts:\n" + "\n".join(offenders)


def test_banned_copy_never_ships():
    """'Runs' is pipeline vocabulary, 'tab' is browser vocabulary, and neither
    means anything to somebody on a phone."""
    offenders = []
    for path in source_files():
        for number, line in enumerate(path.read_text().splitlines(), 1):
            if re.search(r"[>\"]\s*Your runs", line) or "close this tab" in line.lower():
                offenders.append(f"{path.name}:{number}")
    assert not offenders, "\n".join(offenders)
