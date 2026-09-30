"""What people read on screen stays non-technical (SPEC §7, "Words we use on screen")."""

import re
from pathlib import Path

from core import audit, errors

BASE_DIR = Path(__file__).resolve().parent.parent
# "session" isn't here: "training session" is the plain phrase staff use.
BANNED = [
    "server",
    "database",
    "exception",
    "token",
    "cookie",
    "csrf",
    "http",
    "null",
    "invalid",
]

HIDDEN = [
    re.compile(r"\{#.*?#\}", re.S),
    re.compile(r"\{%\s*comment\s*%\}.*?\{%\s*endcomment\s*%\}", re.S),
    re.compile(r"\{%.*?%\}", re.S),
    re.compile(r"\{\{.*?\}\}", re.S),
    re.compile(r"<!--.*?-->", re.S),
    re.compile(r"<(script|style)\b.*?</\1>", re.S | re.I),
    re.compile(r"<[^>]+>", re.S),
]


def visible_text(template_source):
    """Strip template syntax, comments and HTML tags, leaving words people could see."""
    text = template_source
    for pattern in HIDDEN:
        text = pattern.sub(" ", text)
    return text


def banned_words_in(text):
    """Return the banned words that appear as whole words in text."""
    return [word for word in BANNED if re.search(rf"\b{word}\b", text, re.I)]


def _templates():
    """Every HTML template in the project and its apps."""
    roots = [BASE_DIR / "templates", *BASE_DIR.glob("*/templates")]
    return sorted({path for root in roots for path in root.rglob("*.html")})


def test_templates_use_plain_words():
    problems = {}
    for path in _templates():
        hits = banned_words_in(visible_text(path.read_text(encoding="utf-8")))
        if hits:
            problems[str(path.relative_to(BASE_DIR))] = hits
    assert not problems


def test_error_messages_use_plain_words():
    problems = {e.code: banned_words_in(f"{e.title} {e.message}") for e in errors.ALL_ERRORS}
    assert not {code: hits for code, hits in problems.items() if hits}


def test_change_log_descriptions_use_plain_words():
    problems = {key: banned_words_in(text) for key, text in audit.ACTIONS.items()}
    assert not {key: hits for key, hits in problems.items() if hits}


def test_the_checker_catches_banned_words():
    assert banned_words_in(visible_text("<p>The server had an exception</p>")) == [
        "server",
        "exception",
    ]
    assert banned_words_in(visible_text("{% csrf_token %}<p>All good</p>")) == []


def test_template_notes_are_hidden():
    """Django only hides {# #} notes on one line; a longer note shows up on the page."""
    broken = [
        path.name
        for path in _templates()
        for line in path.read_text(encoding="utf-8").splitlines()
        if "{#" in line and "#}" not in line
    ]
    assert not broken
