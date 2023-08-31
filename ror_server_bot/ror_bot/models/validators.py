from pydantic import field_validator


def strip_nulls_after(*fields: str):
    """A validator that strips null characters from provided fields."""
    def __strip_null_character(v: str) -> str:
        return v.strip('\x00')
    return field_validator(
        *fields,
        mode='after',
        check_fields=False
    )(__strip_null_character)
