from __future__ import annotations

from io import StringIO

import pytest
from django.core.management import call_command


@pytest.mark.migration
@pytest.mark.django_db
def test_no_model_changes_are_missing_migrations() -> None:
    output = StringIO()

    call_command("makemigrations", "--check", "--dry-run", stdout=output)

    assert output.getvalue().strip() in {"", "No changes detected"}


@pytest.mark.migration
@pytest.mark.django_db(transaction=True)
def test_database_migrations_can_be_applied() -> None:
    call_command("migrate", "--noinput", verbosity=0)
