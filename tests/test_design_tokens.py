"""Every colour pairing the app uses must meet its contrast target (SPEC §7)."""

import re
from pathlib import Path

import pytest

TOKENS = Path(__file__).resolve().parent.parent / "core" / "static" / "core" / "css" / "tokens.css"

BODY_TEXT = 7.0  # AAA for reading text
OTHER_TEXT = 4.5  # AA
UI_PARTS = 3.0  # AA for borders, dots and focus rings

PAIRS = [
    # (foreground, background, minimum)
    ("text-primary", "background", BODY_TEXT),
    ("text-primary", "surface", BODY_TEXT),
    ("text-primary", "background-deep", BODY_TEXT),
    ("text-primary", "staff-soft", BODY_TEXT),
    ("text-primary", "volunteer-soft", BODY_TEXT),
    ("text-primary", "success-soft", BODY_TEXT),
    ("text-primary", "warning-soft", BODY_TEXT),
    ("text-primary", "danger-soft", BODY_TEXT),
    ("on-action", "action", BODY_TEXT),
    ("on-action", "action-hover", BODY_TEXT),
    ("surface", "text-primary", BODY_TEXT),
    # Secondary text is for supporting words (hints, dates), so AA rather than AAA.
    ("text-secondary", "background", OTHER_TEXT),
    ("text-secondary", "surface", OTHER_TEXT),
    ("text-secondary", "background-deep", OTHER_TEXT),
    ("staff", "surface", OTHER_TEXT),
    ("staff", "background", OTHER_TEXT),
    ("staff", "staff-soft", OTHER_TEXT),
    ("on-role", "staff", OTHER_TEXT),
    ("volunteer", "surface", OTHER_TEXT),
    ("volunteer", "background", OTHER_TEXT),
    ("volunteer", "volunteer-soft", OTHER_TEXT),
    ("on-role", "volunteer", OTHER_TEXT),
    ("success", "surface", OTHER_TEXT),
    ("success", "background", OTHER_TEXT),
    ("success", "success-soft", OTHER_TEXT),
    ("warning", "surface", OTHER_TEXT),
    ("warning", "background", OTHER_TEXT),
    ("warning", "warning-soft", OTHER_TEXT),
    ("danger", "surface", OTHER_TEXT),
    ("danger", "background", OTHER_TEXT),
    ("danger", "danger-soft", OTHER_TEXT),
    ("on-danger", "danger", OTHER_TEXT),
    ("on-action", "success", OTHER_TEXT),
    ("on-action", "warning", OTHER_TEXT),
    ("disabled-text", "disabled-bg", OTHER_TEXT),
    ("border-strong", "surface", UI_PARTS),
    ("border-strong", "background", UI_PARTS),
    ("action", "surface", UI_PARTS),
    ("focus", "surface", UI_PARTS),
    ("focus", "background", UI_PARTS),
]


def _tokens():
    """Read every `--color-name: #hex` colour from tokens.css, keyed without the prefix."""
    css = TOKENS.read_text(encoding="utf-8")
    return dict(re.findall(r"--color-([\w-]+):\s*(#[0-9A-Fa-f]{6})", css))


def _luminance(hex_colour):
    """WCAG relative luminance."""
    channels = [int(hex_colour[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(a, b):
    """WCAG contrast ratio between two hex colours."""
    high, low = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


@pytest.mark.parametrize(("fg", "bg", "minimum"), PAIRS, ids=[f"{f}-on-{b}" for f, b, _ in PAIRS])
def test_colour_pair_meets_contrast_target(fg, bg, minimum):
    tokens = _tokens()
    ratio = contrast(tokens[fg], tokens[bg])
    assert ratio >= minimum, f"{fg} on {bg} is {ratio:.2f}:1, needs {minimum}:1"


def test_contrast_maths_matches_known_values():
    assert contrast("#000000", "#FFFFFF") == pytest.approx(21.0)
    assert contrast("#777777", "#FFFFFF") == pytest.approx(4.48, abs=0.01)


CSS_DIR = TOKENS.parent
TEMPLATES = TOKENS.parents[4] / "templates"


def test_colours_are_only_defined_in_tokens():
    """Styles and page templates use tokens, never raw colours. Emails can't, so they're skipped."""
    hex_colour = re.compile(r"#[0-9A-Fa-f]{6}\b|#[0-9A-Fa-f]{3}\b")
    offenders = [
        path.name
        for path in CSS_DIR.glob("*.css")
        if path != TOKENS and hex_colour.search(path.read_text(encoding="utf-8"))
    ]
    for path in TEMPLATES.rglob("*.html"):
        relative = path.relative_to(TEMPLATES).as_posix()
        if relative.startswith("emails/") or relative == "errors/fallback.html":
            continue
        text = re.sub(r"&#\d+;|&#x[0-9A-Fa-f]+;", "", path.read_text(encoding="utf-8"))
        if hex_colour.search(text):
            offenders.append(relative)
    assert not offenders


def test_every_colour_the_styles_use_exists():
    """A misspelt token would silently fall back to no colour at all."""
    defined = set(re.findall(r"--(color-[\w-]+):", TOKENS.read_text(encoding="utf-8")))
    styles = (CSS_DIR / "base.css").read_text(encoding="utf-8")
    used = set(re.findall(r"var\(--(color-[\w-]+)", styles))
    assert used - defined == set()
