import re

from fastapi.templating import Jinja2Templates
from markupsafe import Markup, escape

templates = Jinja2Templates(directory="templates")

FOOTNOTE_REF = re.compile(r"\[\^(\d+)\]")


def footnotes(text: str) -> Markup:
    """Render `[^1]` markers in copy as linked superscripts.

    Menu copy is plain text in `src/menu.py`, so the marker survives being
    escaped and only becomes markup here.
    """
    escaped = str(escape(text))

    def link(match: re.Match[str]) -> str:
        number = match.group(1)
        return (
            f'<sup class="fn-ref"><a href="#fn-{number}" '
            f'aria-label="Footnote {number}">{number}</a></sup>'
        )

    # Safe by construction: input is escaped first and the replacement only
    # interpolates digits captured by FOOTNOTE_REF.
    return Markup(FOOTNOTE_REF.sub(link, escaped))


def strip_footnotes(text: str) -> str:
    """Remove footnote markers from plain-text labels."""
    return FOOTNOTE_REF.sub("", text)


templates.env.filters["footnotes"] = footnotes
templates.env.filters["strip_footnotes"] = strip_footnotes
