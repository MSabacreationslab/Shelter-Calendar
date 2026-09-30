"""Loading the shelter's volunteer spreadsheet (SPEC §6, Phase 9). All data here is made up."""

import csv
import io

import pytest
from django.core import mail
from django.core.management import CommandError, call_command

from accounts import importing
from accounts.models import SetupLink, Skill, User
from core.models import AuditEvent
from tests.factories import AdminFactory, UserFactory

pytestmark = pytest.mark.django_db

# The shelter's headings, in their order (from Mike's screenshot).
HEADINGS = [
    "Last Name", "First Name", "ACTIVE", "Test", "Address", "City", "State", "Zip Code",
    "Email Address", "Phone Number", "Minor", "Dog Walking", "Dog Social",
    "Dog Kennel Cleaning", "Cat Social", "Cat Room Cleaning", "Surgery Recovery", "Fundraisers",
    "Building Maintenance", "Laundry & Dishes", "Gardening", "Mowing", "Administrative",
    "Fostering", "Surgical Packs", "Birthday",
]  # fmt: skip


def row(**values):
    """One spreadsheet row; keys are headings with spaces as underscores."""
    cells = {h: "" for h in HEADINGS}
    for key, value in values.items():
        cells[key.replace("_", " ")] = value
    return [cells[h] for h in HEADINGS]


def sheet(*rows, headings=HEADINGS, above=()):
    """The rows as a CSV file would read."""
    out = io.StringIO()
    writer = csv.writer(out)
    for line in above:
        writer.writerow(line)
    writer.writerow(headings)
    for r in rows:
        writer.writerow(r)
    return importing.read_rows(io.StringIO(out.getvalue()))


def mary(**extra):
    values = {
        "Last_Name": "Example",
        "First_Name": "Mary",
        "ACTIVE": "X",
        "Email_Address": "mary@example.com",
        "Phone_Number": "740-555-0101",
        "Birthday": "3/14/1950",
        "Dog_Walking": "X",
        "Laundry_&_Dishes": "x",
    }
    values.update(extra)
    return row(**values)


def test_columns_are_matched_and_jobs_found():
    plan = importing.plan(sheet(mary()))
    assert [p.name for p in plan.people] == ["Mary Example"]
    assert plan.ignored_columns == ["Test", "Address", "City", "State", "Zip Code"]
    assert len(plan.jobs) == 14 and "Laundry & Dishes" in plan.jobs
    # "Dog walking" is already on the starting list, so it isn't new.
    assert "Dog Walking" not in plan.new_jobs and "Mowing" in plan.new_jobs


def test_one_persons_details_are_read():
    person = importing.plan(sheet(mary(Minor="Y"))).people[0]
    assert person.email == "mary@example.com" and person.phone == "7405550101"
    assert person.birthday == (3, 14)
    assert person.active and person.minor
    assert person.jobs == ["Dog Walking", "Laundry & Dishes"]
    assert person.warnings == []


def test_not_active_means_needs_approval():
    plan = importing.plan(
        sheet(
            mary(First_Name="A", ACTIVE=""),
            mary(First_Name="B", ACTIVE="No", Email_Address="b@example.com"),
            mary(First_Name="C", ACTIVE="maybe", Email_Address="c@example.com"),
        )
    )
    assert [p.active for p in plan.people] == [False, False, False]
    assert "didn't understand ACTIVE" in plan.people[2].warnings[0]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("3/14/1950", (3, 14)),
        ("03/14/50", (3, 14)),
        ("1950-03-14", (3, 14)),
        ("14-Mar-50", (3, 14)),
        ("March 14", (3, 14)),
        ("Mar 14, 1950", (3, 14)),
        ("2/29", (2, 29)),
        ("", None),
    ],
)
def test_birthdays_in_the_ways_excel_writes_them(text, expected):
    assert importing.parse_birthday(text) == expected


def test_problems_are_warnings_not_failures():
    person = importing.plan(
        sheet(mary(Email_Address="not an email", Phone_Number="555-01", Birthday="someday"))
    ).people[0]
    assert person.email == "" and person.phone == "" and person.birthday is None
    assert len(person.warnings) == 3


def test_skips_are_explained():
    UserFactory(first_name="Ann", last_name="Existing")
    plan = importing.plan(
        sheet(
            mary(),
            mary(Email_Address="second@example.com"),
            mary(First_Name="", Email_Address="x@example.com"),
            mary(First_Name="Ann", Last_Name="Existing", Email_Address="ann@example.com"),
            row(),
        )
    )
    assert [p.name for p in plan.people] == ["Mary Example"]
    assert plan.skipped == [
        (3, "Mary Example", "this name is in the spreadsheet twice"),
        (4, "Example", "needs both a first and a last name"),
        (5, "Ann Existing", "someone with this name is already in the app"),
    ]


def test_couples_sharing_an_email_are_both_added():
    UserFactory(first_name="Other", email="family@example.com")
    plan = importing.plan(
        sheet(
            mary(Email_Address="family@example.com"),
            mary(First_Name="John", Email_Address="family@example.com"),
        )
    )
    assert [p.name for p in plan.people] == ["Mary Example", "John Example"]
    assert all("shares the email" in p.warnings[0] for p in plan.people)


def test_the_heading_row_can_be_below_a_title():
    plan = importing.plan(sheet(mary(), above=[["Volunteer list 2026"], []]))
    assert plan.people[0].row == 4


def test_a_sheet_without_names_is_refused():
    with pytest.raises(importing.SpreadsheetError):
        importing.plan(sheet(["x"], headings=["Name", "Phone"]))


def test_saving_adds_everyone_with_jobs_flags_and_no_emails():
    admin = AdminFactory()
    plan = importing.plan(
        sheet(
            mary(Minor="X", Mowing="summer only"),
            mary(First_Name="Joe", ACTIVE="", Email_Address="", Dog_Walking=""),
        )
    )
    importing.save(plan, by=admin)
    mary_user = User.objects.get(first_name="Mary")
    profile = mary_user.profile
    assert mary_user.login_name == "Mary Example" and not mary_user.has_usable_password()
    assert profile.is_minor and not profile.needs_approval
    assert (profile.birthday_month, profile.birthday_day) == (3, 14)
    assert sorted(s.name for s in profile.skills.all()) == [
        "Dog walking",
        "Laundry & Dishes",
        "Mowing",
    ]
    assert profile.staff_notes == "From the volunteer spreadsheet: Mowing: summer only"
    assert not profile.no_training_eligible
    joe = User.objects.get(first_name="Joe").profile
    assert joe.needs_approval and joe.user.email == ""
    assert not mail.outbox and not SetupLink.objects.exists()
    assert AuditEvent.objects.filter(action="volunteer.imported").count() == 2
    assert Skill.objects.filter(name="Surgical Packs").exists()


def test_a_taken_sign_in_name_gets_a_number():
    UserFactory(first_name="Someone", last_name="Else", login_name="Mary Example")
    plan = importing.plan(sheet(mary()))
    importing.save(plan, by=AdminFactory())
    assert User.objects.get(first_name="Mary").login_name == "Mary Example 2"


# The command


def write(tmp_path, rows, encoding="utf-8-sig"):
    path = tmp_path / "volunteers.csv"
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(HEADINGS)
    writer.writerows(rows)
    path.write_bytes(out.getvalue().encode(encoding))
    return path


def test_the_command_previews_until_told_to_save(tmp_path):
    AdminFactory()
    path = write(tmp_path, [mary(), mary(First_Name="Zoë", Email_Address="z@example.com")])
    out = io.StringIO()
    call_command("import_volunteers", str(path), stdout=out)
    assert "Ready to add: 2 volunteers" in out.getvalue() and "This was a preview" in out.getvalue()
    assert not User.objects.filter(last_name="Example").exists()
    call_command("import_volunteers", str(path), "--save", stdout=io.StringIO())
    assert User.objects.filter(last_name="Example").count() == 2
    assert User.objects.filter(first_name="Zoë").exists()


def test_the_command_reads_older_windows_csv(tmp_path):
    AdminFactory()
    path = write(tmp_path, [mary(First_Name="Zoë")], encoding="cp1252")
    call_command("import_volunteers", str(path), "--save", stdout=io.StringIO())
    assert User.objects.filter(first_name="Zoë").exists()


def test_the_command_explains_excel_files_and_a_missing_admin(tmp_path):
    with pytest.raises(CommandError, match="create_admin"):
        call_command("import_volunteers", "volunteers.csv")
    AdminFactory()
    with pytest.raises(CommandError, match="CSV UTF-8"):
        call_command("import_volunteers", str(tmp_path / "volunteers.xlsx"))
