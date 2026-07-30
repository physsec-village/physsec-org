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

    return Markup(FOOTNOTE_REF.sub(link, escaped))


templates.env.filters["footnotes"] = footnotes
