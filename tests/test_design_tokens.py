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
    ("ink", "bg", BODY_TEXT),
    ("ink", "surface", BODY_TEXT),
    ("ink-soft", "bg", BODY_TEXT),
    ("ink-soft", "surface", BODY_TEXT),
    ("primary", "bg", BODY_TEXT),
    ("primary", "surface", BODY_TEXT),
    ("on-primary", "primary", BODY_TEXT),
    ("on-primary", "primary-hover", BODY_TEXT),
    ("primary-hover", "primary-tint", BODY_TEXT),
    ("ink", "primary-tint", BODY_TEXT),
    ("ink", "success-tint", BODY_TEXT),
    ("ink", "warning-tint", BODY_TEXT),
    ("ink", "error-tint", BODY_TEXT),
    ("accent-ink", "bg", OTHER_TEXT),
    ("on-accent", "accent", OTHER_TEXT),
    ("success", "bg", OTHER_TEXT),
    ("success", "surface", OTHER_TEXT),
    ("warning", "bg", OTHER_TEXT),
    ("warning", "surface", OTHER_TEXT),
    ("error", "bg", OTHER_TEXT),
    ("error", "surface", OTHER_TEXT),
    ("on-error", "error", OTHER_TEXT),
    ("on-primary", "success", OTHER_TEXT),
    ("on-primary", "warning", OTHER_TEXT),
    ("on-primary", "error", OTHER_TEXT),
    ("surface", "ink", OTHER_TEXT),
    ("disabled-ink", "disabled-bg", OTHER_TEXT),
    ("open-dot", "bg", UI_PARTS),
    ("open-dot", "surface", UI_PARTS),
    ("open-dot", "primary-tint", UI_PARTS),
    ("primary", "primary-tint", UI_PARTS),
    ("on-primary", "primary", OTHER_TEXT),
    ("border", "surface", UI_PARTS),
    ("focus", "surface", UI_PARTS),
    ("focus", "bg", UI_PARTS),
    ("error", "surface", UI_PARTS),
]


def _tokens():
    """Read every `--name: #hex` colour from tokens.css."""
    css = TOKENS.read_text(encoding="utf-8")
    return {name: value for name, value in re.findall(r"--([\w-]+):\s*(#[0-9A-Fa-f]{6})", css)}


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
