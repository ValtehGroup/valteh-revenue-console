import re
from pathlib import Path

from dash import dcc, html

GUIDE_PATH = Path(__file__).resolve().parents[2] / "docs" / "dashboard-user-guide.md"
CONTENTS_HEADING = "## In this guide"
SECTION_PATTERN = re.compile(r"^(#{2,3})\s+(.+?)\s*$", re.MULTILINE)


def layout() -> html.Div:
    markdown = _guide_markdown()
    preamble, sections = _guide_sections(markdown)
    return html.Div(
        [
            html.Nav(
                [
                    html.Div("In this guide", className="user-guide-nav-title"),
                    html.Ul(
                        [
                            html.Li(
                                html.A(section[1], href=f"#{section[0]}"),
                                className=f"user-guide-nav-level-{section[2]}",
                            )
                            for section in sections
                        ]
                    ),
                ],
                className="user-guide-nav",
                **{"aria-label": "User guide sections"},
            ),
            html.Div(
                [
                    dcc.Markdown(preamble, link_target="_blank"),
                    *[
                        html.Section(
                            dcc.Markdown(section[3], link_target="_blank"),
                            id=section[0],
                        )
                        for section in sections
                    ],
                ],
                className="user-guide-content",
            ),
        ],
        className="user-guide-page user-guide-shell",
    )


def _guide_sections(markdown: str) -> tuple[str, list[tuple[str, str, int, str]]]:
    body = _without_contents(markdown)
    matches = list(SECTION_PATTERN.finditer(body))
    if not matches:
        return body, []

    sections = []
    used_slugs: set[str] = set()
    for index, match in enumerate(matches):
        title = match.group(2)
        slug = _unique_slug(_slugify(title), used_slugs)
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        sections.append((slug, title, len(match.group(1)), body[match.start() : end].strip()))
    return body[: matches[0].start()].strip(), sections


def _without_contents(markdown: str) -> str:
    start = markdown.find(CONTENTS_HEADING)
    if start == -1:
        return markdown
    end = markdown.find("\n## ", start + len(CONTENTS_HEADING))
    if end == -1:
        return markdown[:start].rstrip()
    return f"{markdown[:start].rstrip()}\n\n{markdown[end + 1 :].lstrip()}"


def _slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug or "section"


def _unique_slug(slug: str, used_slugs: set[str]) -> str:
    candidate = slug
    suffix = 2
    while candidate in used_slugs:
        candidate = f"{slug}-{suffix}"
        suffix += 1
    used_slugs.add(candidate)
    return candidate


def _guide_markdown() -> str:
    try:
        return GUIDE_PATH.read_text(encoding="utf-8")
    except OSError:
        return "# User Guide\n\nThe user guide is temporarily unavailable."
