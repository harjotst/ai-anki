"""The design system's rules, enforced where discipline fails.

Every screen here is rendered twice — React on the web today, React Native on
the phone later — and each rule below is a pattern that survives both. They are
tests rather than review notes because the failure mode of each is silent: one
stray hex quietly breaks dark mode, one `<table>` quietly makes a screen
unportable, and neither is noticed until someone is standing in it.
"""

import re
from pathlib import Path

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
MOBILE = Path(__file__).resolve().parent.parent / "mobile"

# The only files allowed to hold a color. tokens.css and tokens.ts are
# generated from tokens.json, which is the source of truth — the mobile
# theme copy included, because it is emitted from the same source.
TOKEN_FILES = {"tokens.json", "tokens.css", "tokens.ts"}

HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")


def source_files():
    """Both renderers. The rules exist because every screen ships twice;
    checking one renderer would let the other rot."""
    roots = [FRONTEND / "src"]
    if (MOBILE / "src").exists():
        roots.append(MOBILE / "src")
    for root in roots:
        for path in root.rglob("*"):
            if path.suffix in {".js", ".jsx", ".ts", ".tsx", ".css", ".html"}:
                yield path


def test_no_hex_color_exists_outside_the_token_files():
    """The dual palette dies from one stray hex — G8 in the brief.

    A literal color in a component is invisible in the light theme and wrong in
    the dark one, and it never reaches the React Native theme at all.
    """
    offenders = []
    for path in source_files():
        if path.name in TOKEN_FILES:
            continue
        for number, line in enumerate(path.read_text().splitlines(), 1):
            if HEX.search(line):
                offenders.append(f"{path.name}:{number}: {line.strip()[:80]}")
    assert not offenders, "colors belong in tokens.json:\n" + "\n".join(offenders)


def test_no_table_and_no_sticky_because_react_native_has_neither():
    offenders = []
    for path in source_files():
        text = path.read_text()
        if "<table" in text or "<td" in text or "<th " in text:
            offenders.append(f"{path.name}: <table>")
        if "position: sticky" in text or "position:sticky" in text:
            offenders.append(f"{path.name}: position sticky")
    assert not offenders, "\n".join(offenders)


def test_banned_copy_never_ships():
    """'Runs' is pipeline vocabulary, 'tab' is browser vocabulary, and neither
    means anything to somebody on a phone."""
    offenders = []
    for path in source_files():
        for number, line in enumerate(path.read_text().splitlines(), 1):
            if re.search(r"[>\"]\s*Your runs", line) or "close this tab" in line.lower():
                offenders.append(f"{path.name}:{number}")
    assert not offenders, "\n".join(offenders)


def test_the_token_files_are_in_sync_with_their_source():
    """tokens.css is generated; a hand-edit or a stale emit would let the two
    renderers drift apart, which is the exact failure the pipeline prevents."""
    import json

    source = json.loads((FRONTEND / "tokens.json").read_text())
    css = (FRONTEND / "src" / "tokens.css").read_text()
    for palette in ("light", "dark"):
        for value in source["color"][palette].values():
            assert value in css, f"{palette} value {value} missing from tokens.css"
    ts = (FRONTEND / "src" / "tokens.ts").read_text()
    assert source["color"]["dark"]["accent"] in ts
    mobile_ts = MOBILE / "src" / "theme" / "tokens.ts"
    if mobile_ts.exists():
        assert mobile_ts.read_text() == ts, "mobile tokens.ts differs from the web's"
