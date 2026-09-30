import re
from pathlib import Path

from core import errors

DOCS = Path(__file__).resolve().parent.parent / "docs" / "error-codes.md"


def test_codes_are_unique_and_well_formed():
    codes = [e.code for e in errors.ALL_ERRORS]
    assert len(codes) == len(set(codes))
    assert all(re.fullmatch(r"SC-\d{3}", code) for code in codes)


def test_every_defined_error_is_registered():
    defined = {v for v in vars(errors).values() if isinstance(v, errors.ErrorCode)}
    assert defined == set(errors.ALL_ERRORS)


def test_every_code_is_documented():
    docs = DOCS.read_text(encoding="utf-8")
    missing = [e.code for e in errors.ALL_ERRORS if e.code not in docs]
    assert not missing, f"Add these to docs/error-codes.md: {missing}"
