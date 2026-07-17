from typing import Annotated

from pydantic import BaseModel, EmailStr, Field, StringConstraints, field_validator

SingleLine = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
]


class FormSchema(BaseModel):
    email: EmailStr
    message: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=5000)
    ]
    name: SingleLine
    subject: SingleLine
    # Honeypot: hidden field on the form, empty for humans
    website: str = Field(default="", max_length=500)

    @field_validator("name", "subject")
    @classmethod
    def no_line_breaks(cls, value: str) -> str:
        # These fields end up in the mail Subject header
        if "\r" in value or "\n" in value:
            raise ValueError("must not contain line breaks")
        return value
