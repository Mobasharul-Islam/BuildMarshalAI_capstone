"""Which project a chat question is about, so retrieval searches only its documents.

A question that names a project -- "what is the RFI period on Padma View?" --
is answered from that project's documents alone. Other projects' documents
are not searched, so they cannot be cited. A question that names no project
keeps the ordinary account-wide search, or the project page it was asked from.

A project is named by its name, the first words of its name, or its project
code, as whole words and in any case. People shorten long names -- "Padma View"
for "Padma View Specialised Hospital Extension" -- so any leading run of two or
more of the name's words counts. When the names of two projects overlap
("Tower" and "Tower B"), the longer, more specific match wins. A question naming
two projects searches both.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Iterable, Iterator, Mapping

#: Names and codes shorter than this are too likely to be ordinary words.
MIN_NAME_LENGTH = 3

#: A shortened name must keep at least this many of the name's first words.
MIN_PREFIX_WORDS = 2


def _phrases(project: Mapping[str, Any]) -> list[str]:
    """Every way a question may name this project: code, full name, leading words."""
    words = _fold(project.get("name")).split()
    # The code and the whole name always count; shortened forms keep 2+ words.
    phrases = [_fold(project.get("project_code")), " ".join(words)]
    phrases += [" ".join(words[:n]) for n in range(len(words) - 1, MIN_PREFIX_WORDS - 1, -1)]
    return [p for p in dict.fromkeys(phrases) if len(p) >= MIN_NAME_LENGTH]


def _fold(value: Any) -> str:
    # NFC, so a Bengali name typed with decomposed vowel signs still matches.
    return " ".join(unicodedata.normalize("NFC", str(value or "")).split()).casefold()


def _pattern(phrase: str) -> re.Pattern[str]:
    words = [re.escape(word) for word in phrase.split()]
    # Any run of spaces or hyphens between words; the edges are checked by
    # _whole_word, which knows about scripts.
    return re.compile(r"[\s\-]+".join(words), re.IGNORECASE)


def _script(ch: str) -> str:
    """A coarse script for one character: 'latin', a Unicode script name, or ''."""
    if not ch or not (ch.isalnum() or unicodedata.category(ch).startswith("M")):
        return ""                       # space, punctuation, or nothing: a boundary
    if ch.isascii():
        return "latin"
    try:
        return unicodedata.name(ch).split()[0]     # e.g. BENGALI, DEVANAGARI
    except ValueError:
        return "other"


def _whole_word(text: str, start: int, end: int) -> bool:
    """Whether text[start:end] stands as whole words.

    A neighbour of the same script continues the word ("Towering"); one of a
    different script does not, so "fromপদ্মা ভিউ" still names পদ্মা ভিউ.
    """
    before = text[start - 1] if start > 0 else ""
    after = text[end] if end < len(text) else ""
    first, last = text[start], text[end - 1]
    if _script(before) and _script(before) == _script(first):
        return False
    # Latin words end where letters end ("Towering" is not "Tower"). Bengali,
    # Devanagari and similar scripts attach case endings to a name -- "পদ্মা
    # ভিউয়ের" is "of Padma View" -- so there a following letter is allowed.
    if _script(after) == "latin" and _script(last) == "latin":
        return False
    return True


def find_phrase(phrase: str, text: str) -> Iterator[re.Match[str]]:
    """Every whole-word occurrence of ``phrase`` in ``text`` (both NFC-normalised)."""
    for match in _pattern(phrase).finditer(text):
        if _whole_word(text, match.start(), match.end()):
            yield match


def mentioned_projects(query: str, projects: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The projects a question names explicitly, most specific first.

    Each result is ``{"id", "name", "matched"}``; ``matched`` is the text that
    named it.
    """
    text = unicodedata.normalize("NFC", str(query or ""))
    candidates: list[tuple[int, int, str, Mapping[str, Any]]] = []
    for project in projects:
        for phrase in _phrases(project):
            for match in find_phrase(phrase, text):
                candidates.append((match.start(), match.end(), match.group(0), project))

    # A match inside a longer one is the longer project's name ("Tower" in
    # "Tower B"), not a mention of its own.
    candidates.sort(key=lambda row: (-(row[1] - row[0]), row[0]))
    taken: list[tuple[int, int]] = []
    found: dict[str, dict[str, Any]] = {}
    for start, end, matched, project in candidates:
        if any(start >= a and end <= b for a, b in taken):
            continue
        taken.append((start, end))
        pid = str(project.get("id") or "")
        if pid and pid not in found:
            found[pid] = {"id": pid, "name": project.get("name") or pid, "matched": matched}
    return list(found.values())


def resolve_chat_scope(query: str, projects: Mapping[str, Mapping[str, Any]],
                       page_project_id: str | None = None) -> dict[str, Any]:
    """The project scope for one question.

    A project named in the question decides the scope. Failing that, the
    project page the question was asked from does. Failing both, the search is
    account-wide (``project_ids`` empty).
    """
    named = mentioned_projects(query, projects.values())
    if named:
        return {"project_ids": [row["id"] for row in named],
                "projects": named, "reason": "named in the question"}
    if page_project_id and page_project_id in projects:
        project = projects[page_project_id]
        return {"project_ids": [page_project_id],
                "projects": [{"id": page_project_id, "name": project.get("name") or page_project_id,
                              "matched": ""}],
                "reason": "asked from the project's page"}
    return {"project_ids": [], "projects": [], "reason": "no project named"}


__all__ = ["MIN_NAME_LENGTH", "MIN_PREFIX_WORDS", "find_phrase", "mentioned_projects", "resolve_chat_scope"]
