"""Spreadsheet downloads of the report tables (SPEC §6, Phase 7)."""

import csv

from core.templatetags.formatting import clock_text

# A cell starting with one of these is run as a formula by Excel; a leading ' stops that.
FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r")


def safe(value):
    """Make text safe to open in a spreadsheet; numbers pass through."""
    if isinstance(value, str) and value.startswith(FORMULA_STARTS):
        return "'" + value
    return value


def _people(report):
    yield [
        "Name",
        "Sign-in name",
        "Shifts done",
        "Hours",
        "Coming up",
        "Cancelled",
        "Urgent cancellations",
    ]
    for row in report.by_person:
        person = row["person"]
        yield [
            person.get_full_name(),
            person.login_name,
            row["done"],
            row["hours"],
            row["coming_up"],
            row["cancelled"],
            row["urgent"],
        ]


def _days(report):
    yield ["Date", "Day", "Shifts", "Spots", "Filled", "Filled %"]
    for row in report.by_day:
        percent = round(100 * row["filled"] / row["spots"]) if row["spots"] else 0
        yield [
            row["day"].isoformat(),
            row["day"].strftime("%A"),
            row["shifts"],
            row["spots"],
            row["filled"],
            percent,
        ]


def _shifts(report):
    yield ["Date", "Starts", "Ends", "Shift", "Training needed", "Spots", "Filled", "Who"]
    for shift in report.by_shift:
        training = shift.required_training.name if shift.required_training else ""
        if shift.kind == "training" and shift.teaches:
            training = f"Session: {shift.teaches.name}"
        yield [
            shift.local_date.isoformat(),
            clock_text(shift.starts_at),
            clock_text(shift.ends_at),
            shift.title,
            training,
            shift.capacity,
            min(shift.filled, shift.capacity),
            ", ".join(p.get_full_name() for p in shift.people),
        ]


TABLES = {"people": _people, "days": _days, "shifts": _shifts}


def write(table, report, stream) -> None:
    """Write one table as Excel-friendly CSV: a byte-order mark first, then safe rows."""
    stream.write("﻿")
    writer = csv.writer(stream)
    for row in TABLES[table](report):
        writer.writerow([safe(cell) for cell in row])
