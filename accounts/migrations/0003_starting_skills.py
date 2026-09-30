from django.db import migrations

# The shelter's starting list (SPEC Q7). Staff can add, rename and deactivate skills.
STARTING_SKILLS = [
    "Dog walking",
    "Cat enrichment",
    "Dog kennel cleaning",
    "Cat cage cleaning",
    "Special events",
]


def add_skills(apps, schema_editor):
    Skill = apps.get_model("accounts", "Skill")
    for name in STARTING_SKILLS:
        if not Skill.objects.filter(name__iexact=name).exists():
            Skill.objects.create(name=name)


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0002_loginattempt_setuplink_skill_volunteerprofile_and_more"),
    ]

    operations = [
        migrations.RunPython(add_skills, migrations.RunPython.noop),
    ]
