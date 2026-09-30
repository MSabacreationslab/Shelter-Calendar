"""Loading current volunteers from the shelter's spreadsheet (SPEC §6, Phase 9; Q17).

The spreadsheet is saved from Excel as "CSV UTF-8", one row per volunteer. Columns are
matched by heading, ignoring case and punctuation. Any heading that isn't a known column
is a job: a mark under it adds that job to the person's skills. Training isn't in this
spreadsheet; staff record it in the app.
"""

import csv
import io
import pathlib
import re
from dataclasses import dataclass, field
from datetime import datetime

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction

from accounts import services
from accounts.models import Role, Skill, User, normalize_login_name
from core import audit
from core.phones import normalize_phone

COLUMNS = {
    "last name": "last_name",
    "first name": "first_name",
    "active": "active",
    "email address": "email",
    "email": "email",
    "phone number": "phone",
    "phone": "phone",
    "minor": "minor",
    "birthday": "birthday",
}
# In the spreadsheet but not kept: the app never mails anything, and "Test" isn't needed.
IGNORED = {"test", "address", "city", "state", "zip code", "zip"}
NO = {"", "n", "no", "false", "0", "-"}
ACTIVE_YES = {"x", "y", "yes", "true", "1", "active", "a"}
ACTIVE_NO = NO | {"inactive", "i"}
SIMPLE_MARKS = {"x", "y", "yes", "true", "1", "✓", "✔"}
HEADER_SEARCH_ROWS = 10
DATE_FORMATS = ["%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d", "%m-%d-%Y", "%d-%b-%y", "%d-%b-%Y"]
DATE_FORMATS += ["%B %d, %Y", "%b %d, %Y"]
# Without a year; parsed in a leap year so February 29 works.
YEARLESS_FORMATS = ["%m/%d", "%B %d", "%b %d", "%d-%b"]


class SpreadsheetError(Exception):
    """The file can't be read at all (no heading row, not a CSV)."""


@dataclass
class Person:
    row: int
    first_name: str
    last_name: str
    email: str = ""
    phone: str = ""
    birthday: tuple[int, int] | None = None
    active: bool = True
    minor: bool = False
    jobs: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        """First Last."""
        return f"{self.first_name} {self.last_name}"


@dataclass
class Plan:
    people: list[Person] = field(default_factory=list)
    skipped: list[tuple[int, str, str]] = field(default_factory=list)  # row, name, why
    jobs: list[str] = field(default_factory=list)
    new_jobs: list[str] = field(default_factory=list)
    ignored_columns: list[str] = field(default_factory=list)


def _key(heading: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (heading or "").lower()).strip()


def _tidy(value) -> str:
    return " ".join(str(value or "").split())


def is_marked(value: str) -> bool:
    """A job or Minor cell counts unless it's blank or plainly "no"."""
    return _tidy(value).lower() not in NO


def parse_birthday(value: str) -> tuple[int, int] | None:
    """(month, day) from the ways Excel writes dates. The year isn't kept. Raises ValueError."""
    text = _tidy(value)
    if not text:
        return None
    for fmt in DATE_FORMATS:
        try:
            parsed = datetime.strptime(text, fmt)
            return parsed.month, parsed.day
        except ValueError:
            continue
    for fmt in YEARLESS_FORMATS:
        try:
            parsed = datetime.strptime(f"{text} 2000", f"{fmt} %Y")
            return parsed.month, parsed.day
        except ValueError:
            continue
    raise ValueError(f"didn't understand the birthday “{text}”")


def _find_heading(rows: list[list[str]]) -> int:
    for index, row in enumerate(rows[:HEADER_SEARCH_ROWS]):
        keys = {_key(cell) for cell in row}
        if {"first name", "last name"} <= keys:
            return index
    raise SpreadsheetError(
        "Couldn't find the heading row. It needs columns called First Name and Last Name."
    )


def read_rows(stream) -> list[list[str]]:
    """All rows of a CSV file, as text."""
    return [row for row in csv.reader(stream)]


def open_csv(path) -> list[list[str]]:
    """Read a CSV saved by Excel, either "CSV UTF-8" or the older Windows kind."""
    if str(path).lower().endswith((".xlsx", ".xls")):
        raise SpreadsheetError(
            "That's an Excel file. In Excel, choose File, Save As, and pick “CSV UTF-8”, "
            "then run this again with the .csv file."
        )
    raw = pathlib.Path(path).read_bytes()
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return read_rows(io.StringIO(raw.decode(encoding), newline=""))
        except UnicodeDecodeError:
            continue
    raise SpreadsheetError("Couldn't read the file's text. Save it again as “CSV UTF-8”.")


def plan(rows: list[list[str]]) -> Plan:
    """Work out who would be added, who is skipped and why, without changing anything."""
    heading_at = _find_heading(rows)
    headings = rows[heading_at]
    result = Plan()
    columns = {}  # index -> field name, or ("job", name)
    for index, heading in enumerate(headings):
        key = _key(heading)
        if not key:
            continue
        if key in COLUMNS:
            columns[index] = COLUMNS[key]
        elif key in IGNORED:
            result.ignored_columns.append(_tidy(heading))
        else:
            name = _tidy(heading)
            columns[index] = ("job", name)
            result.jobs.append(name)
    existing_skills = {s.name.lower() for s in Skill.objects.all()}
    result.new_jobs = [job for job in result.jobs if job.lower() not in existing_skills]

    in_app = {
        (first.lower(), last.lower())
        for first, last in User.objects.values_list("first_name", "last_name")
    }
    in_file = set()
    emails = User.objects.exclude(email="").values_list("email", flat=True)
    known_emails = {email.lower() for email in emails}
    for offset, row in enumerate(rows[heading_at + 1 :], start=heading_at + 2):
        cells = {}
        jobs, notes = [], []
        for index, target in columns.items():
            value = _tidy(row[index]) if index < len(row) else ""
            if isinstance(target, tuple):
                if is_marked(value):
                    jobs.append(target[1])
                    if value.lower() not in SIMPLE_MARKS:
                        notes.append(f"{target[1]}: {value}")
            else:
                cells[target] = value
        if not any(cells.values()) and not jobs:
            continue  # a blank row
        first, last = cells.get("first_name", ""), cells.get("last_name", "")
        shown = f"{first} {last}".strip() or "(no name)"
        if not first or not last:
            result.skipped.append((offset, shown, "needs both a first and a last name"))
            continue
        name_key = (first.lower(), last.lower())
        if name_key in in_app:
            result.skipped.append((offset, shown, "someone with this name is already in the app"))
            continue
        if name_key in in_file:
            result.skipped.append((offset, shown, "this name is in the spreadsheet twice"))
            continue
        person = Person(row=offset, first_name=first, last_name=last, jobs=jobs, notes=notes)
        _read_contact(person, cells)
        if person.email and person.email.lower() in known_emails:
            # Couples often share one address; each still gets their own sign-in.
            person.warnings.append(f"shares the email {person.email} with someone else")
        _read_flags(person, cells)
        in_file.add(name_key)
        if person.email:
            known_emails.add(person.email.lower())
        result.people.append(person)
    return result


def _read_contact(person: Person, cells: dict) -> None:
    email = cells.get("email", "")
    if email:
        try:
            validate_email(email)
            person.email = email
        except ValidationError:
            person.warnings.append(f"the email “{email}” doesn't look right, so it was left out")
    else:
        person.warnings.append("no email, so they can't get a welcome link until one is added")
    phone = cells.get("phone", "")
    if phone:
        try:
            person.phone = normalize_phone(phone)
        except ValueError:
            person.warnings.append(f"the phone “{phone}” isn't 10 digits, so it was left out")
    try:
        person.birthday = parse_birthday(cells.get("birthday", ""))
    except ValueError as exc:
        person.warnings.append(str(exc))


def _read_flags(person: Person, cells: dict) -> None:
    active = cells.get("active", "").lower()
    if "active" not in cells or active in ACTIVE_YES:
        person.active = True
    elif active in ACTIVE_NO:
        person.active = False
    else:
        person.active = False
        person.warnings.append(
            f"didn't understand ACTIVE “{cells.get('active')}”, so they need approval for shifts"
        )
    person.minor = is_marked(cells.get("minor", ""))


def _login_name(person: Person) -> str:
    base = normalize_login_name(person.name)
    chosen, number = base, 2
    while User.objects.filter(login_name__iexact=chosen).exists():
        chosen = f"{base} {number}"
        number += 1
    if chosen != base:
        person.warnings.append(f"signs in as “{chosen}” because “{base}” was taken")
    return chosen


@transaction.atomic
def save(result: Plan, *, by: User) -> list[User]:
    """Add everyone in the plan, all or nothing. No emails are sent."""
    skills = {}
    for job in result.jobs:
        skill = Skill.objects.filter(name__iexact=job).first()
        if skill is None:
            skill = Skill.objects.create(name=job)
            audit.record("skill.added", actor=by, target_repr=job, via="spreadsheet")
        skills[job] = skill
    added = []
    for person in result.people:
        user = services.create_person(
            first_name=person.first_name,
            last_name=person.last_name,
            email=person.email,
            role=Role.VOLUNTEER,
            login_name=_login_name(person),
            created_by=by,
            phone=person.phone,
        )
        profile = user.profile
        if person.birthday:
            profile.birthday_month, profile.birthday_day = person.birthday
        profile.is_minor = person.minor
        profile.needs_approval = not person.active
        if person.notes:
            profile.staff_notes = "From the volunteer spreadsheet: " + "; ".join(person.notes)
        profile.save()
        profile.skills.set([skills[job] for job in person.jobs])
        audit.record(
            "volunteer.imported",
            actor=by,
            target_user=user,
            row=person.row,
            needs_approval=not person.active,
        )
        added.append(user)
    return added
