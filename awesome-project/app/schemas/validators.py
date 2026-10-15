"""Shared validators."""

from __future__ import annotations

import re
from typing import Annotated

from pydantic import AfterValidator, Field

# Spaces, dashes, dots and parentheses are formatting, not content — strip them
# before checking. A leading "+" is the international prefix.
_SEPARATORS = re.compile(r"[\s\-()+.]")
_DIGITS_ONLY = re.compile(r"^\d{10,15}$")


def normalise_phone(value: str) -> str:
    """Strip formatting and require 10-15 digits.

    Accepts `+91 98765 43210`, `(020) 1234-5678`, `9876543210`.
    Rejects anything that is not 10-15 digits once separators are removed.
    Returns the digits only, so stored values are directly comparable.
    """
    cleaned = _SEPARATORS.sub("", value.strip())
    if not _DIGITS_ONLY.match(cleaned):
        raise ValueError(
            "phone must be 10-15 digits once spaces, dashes and a leading "
            "'+' are removed"
        )
    return cleaned


#: Optional phone number. Use as `phone: PhoneNumber | None = None`.
PhoneNumber = Annotated[str, AfterValidator(normalise_phone)]

#: Bounded free-text phone column, matching the SQL column width.
PhoneColumn = Annotated[str, Field(max_length=20)]