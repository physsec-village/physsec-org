from typing import Annotated, Literal

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
    # Cloudflare Turnstile response token (empty when Turnstile is disabled)
    turnstile_token: str = Field(default="", max_length=2048)

    @field_validator("name", "subject")
    @classmethod
    def no_line_breaks(cls, value: str) -> str:
        # These fields end up in the mail Subject header
        if "\r" in value or "\n" in value:
            raise ValueError("must not contain line breaks")
        return value


OptionalSingleLine = Annotated[
    str, StringConstraints(strip_whitespace=True, max_length=200)
]


class VolunteerFormSchema(BaseModel):
    name: SingleLine
    email: EmailStr
    discord_handle: SingleLine
    discord_user_id: Annotated[
        str, StringConstraints(strip_whitespace=True, pattern=r"^\d{17,20}$")
    ]
    shirt_size: Literal["", "XS", "S", "M", "L", "XL", "2XL", "3XL", "4XL"] = ""
    location: OptionalSingleLine = ""
    food_limitations: SingleLine
    conferences: Annotated[
        list[Literal["RSAC", "HOPE", "DEF CON", "Ekoparty", "Northsec"]],
        Field(min_length=1, max_length=5),
    ]
    volunteered_before: Annotated[str, Field(pattern=r"^(yes|no)$")]
    interest: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=3000)
    ]
    other_information: Annotated[
        str, StringConstraints(strip_whitespace=True, max_length=3000)
    ] = ""
    consent: Annotated[bool, Field(strict=True)]
    website: str = Field(default="", max_length=500)
    turnstile_token: str = Field(default="", max_length=2048)

    @field_validator("consent")
    @classmethod
    def consent_is_required(cls, value: bool) -> bool:
        if not value:
            raise ValueError("consent is required")
        return value

    @field_validator("conferences")
    @classmethod
    def conferences_are_unique(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("conferences must not contain duplicates")
        return value
