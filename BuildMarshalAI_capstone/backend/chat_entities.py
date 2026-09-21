"""Turning a sentence in Marshal Chat into a project or a user.

Marshal Chat could already book a meeting or write an email from a sentence,
but "create a project called Riverside Tower" fell through to document search
and answered that it could not find it -- while the same sentence worked on the
Onboarding page. This closes that, for the two records people ask for by name.

Three rules, the same ones onboarding works to:

* **The schema decides what is mandatory.** Required fields, enums and the
  reference lists all come from :mod:`entity_schema`, which derives them from
  the application's own constructors and validators. Nothing is restated here.
* **Nothing is invented.** A reference field -- a project type, a role -- is
  only accepted when it matches a record that actually exists. An unmatched
  value is dropped and asked about instead.
* **Interpretation creates nothing.** This module reads a sentence and reports
  what it understood and what is still missing. The record is created by the
  ordinary ``POST /api/projects`` or ``POST /api/users`` route, with the
  ordinary permission check, after the administrator has seen the form.

The model is asked first because it reads a sentence far better than a pattern
does; when it is unreachable or answers with something unusable, a deterministic
reader takes what it can (a quoted name, an email address, a known role) and the
form collects the rest. So the feature degrades to "a prefilled form" rather
than to an error.
"""
from __future__ import annotations

import json
import re
from datetime import date
from typing import Any, Callable, Mapping, Sequence

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

try:  # the notebook puts this directory on sys.path
    from entity_schema import (ENTITIES, coerce, missing_required,
                               read_date, reference_choices)
except ModuleNotFoundError:  # imported as backend.chat_entities
    from backend.entity_schema import (ENTITIES, coerce, missing_required,
                                       read_date, reference_choices)

#: What chat can create directly: every kind the application has a create
#: route for, so the ordinary permission check and validator still decide.
#:
CHAT_KINDS: tuple[str, ...] = (
    "project", "user", "task", "task_type", "project_type", "role_type",
    "trade", "vendor", "project_cost", "task_cost", "procurement",
)

#: Creating a user needs a password, which the user schema does not carry
#: because onboarding generates one. ``POST /api/users`` does require it, so it
#: is named here as a field the form must collect rather than invented.
#: ``asked_in`` says who collects it. A temporary password is generated in the
#: dialog, so asking for it in chat would be asking somebody to type a password
#: into a conversation -- which is both useless and wrong.
EXTRA_REQUIRED: dict[str, tuple[dict[str, str], ...]] = {
    "user": ({"name": "password", "label": "Temporary password",
              "type": "password", "asked_in": "form"},),
}

#: Fields chat treats as mandatory although the create route would accept the
#: record without them. A project with no manager and no start date is a
#: project nobody can plan against, and a user with no role cannot be given
#: anything to do -- so they are asked for rather than left blank.
INSISTED: dict[str, tuple[str, ...]] = {
    "project": ("manager", "start_date"),
    "user": ("role",),
}

MAX_INTERPRET_TOKENS = 700


class InterpretRequest(BaseModel):
    """One sentence to read, plus anything already settled in earlier turns.

    Declared at module level because FastAPI resolves a handler's annotations
    against module globals; a model nested in the register function is invisible
    there and the body silently becomes a query parameter.
    """

    text: str = Field(default="", max_length=4000)
    kind: str = Field(default="", max_length=40)
    known: dict[str, Any] = Field(default_factory=dict)
    #: The project the person has open. Used only as a fallback for a record
    #: that needs a parent and whose sentence does not name one -- "create a
    #: task for the slab pour" while looking at a project means that project.
    parent_id: str = Field(default="", max_length=80)
    #: The fields the last reply asked for. Knowing them is what lets a bare
    #: "October 1" be read as an answer rather than discarded.
    asking: list[str] = Field(default_factory=list)


# ── Reading the intent ───────────────────────────────────────────────────

CREATE_VERB = re.compile(
    r"\b(?:creat\w+|add|adds|adding|make|makes|making|set\s*up|setup|"
    r"register\w*|open|opens|start\w*|new)\b", re.I)

#: The nouns that name each record. Order is the whole point, twice over:
#:
#: * "add a new user to the project" is a user, so user is tested before project.
#: * a compound is tested before the word inside it, or "add a task cost" reads
#:   as a task and "create a project cost" reads as a project -- both of which
#:   create the wrong record rather than declining to create one.
KIND_NOUNS: tuple[tuple[str, str], ...] = (
    ("user", r"users?|accounts?|team\s*members?|teammates?|staff\s*members?|"
             r"employees?|colleagues?|people|persons?"),
    ("task_cost", r"task\s*costs?"),
    ("task_type", r"task\s*types?"),
    ("project_cost", r"project\s*costs?"),
    ("project_type", r"project\s*types?"),
    ("role_type", r"roles?|permission\s*sets?"),
    ("procurement", r"procurements?|purchases?|purchase\s*orders?|materials?"),
    ("project", r"projects?|jobs?|schemes?"),
    ("task", r"tasks?|sub-?tasks?|activities|activity"),
    ("project_cost", r"costs?|budget\s*lines?|expenses?"),
    ("trade", r"trades?"),
    ("vendor", r"vendors?|suppliers?|external\s*comp(?:any|anies)"),
)

KIND_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (kind, re.compile(rf"\b(?:{nouns})\b", re.I)) for kind, nouns in KIND_NOUNS)

#: A noun reached through a preposition says where something goes, not what is
#: being made: "add a note to the project" is not a request for a new project.
LOCATIVE = re.compile(
    r"\b(?:to|for|in|on|of|from|within|under|about|against|onto|into)\s+"
    r"(?:the|this|that|a|an|my|our|its|their)?\s*$", re.I)

#: "generate a project document" and "create a report" are other features and
#: must not be mistaken for creating a project.
NOT_CREATION = re.compile(
    r"\b(document|report|pdf|summary|draft\s+an?\s+email|meeting|event|"
    r"invite|to-?do\s*list|chart|statistic)s?\b", re.I)


def detect_kind(text: str) -> str:
    """Which record, if any, this sentence asks to create.

    Deliberately conservative: when in doubt it returns nothing and the message
    goes to document search, which is the behaviour people already expect.
    """
    message = str(text or "")
    if not message.strip() or NOT_CREATION.search(message):
        return ""
    verb = CREATE_VERB.search(message)
    if not verb:
        return ""

    after = verb.end()
    for kind, pattern in KIND_PATTERNS:
        for found in pattern.finditer(message, after):
            if not LOCATIVE.search(message[after:found.start()]):
                return kind
    return ""


# ── Reading the fields without a model ───────────────────────────────────

QUOTED = re.compile(r"[\"“‘']([^\"”’']{2,80})[\"”’']")
CALLED = re.compile(
    r"\b(?:called|named|titled)\s+(?:the\s+)?([A-Z0-9][\w'&.\-]*(?:\s+[\w'&.\-]+){0,6})")

#: "for" names a record only sometimes: "a task for the slab pour" names it,
#: "a task for Dana Whitfield" says who it is for. Read as a name only when the
#: phrase is not the name of a record this account has.
FOR_PHRASE = re.compile(
    r"\bfor\s+(?:the\s+)?([A-Z0-9][\w'&.\-]*(?:\s+[\w'&.\-]+){0,6})")
EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
CODE = re.compile(r"\b(?:code|reference|ref)\s+(?:is\s+)?([A-Z0-9][A-Z0-9\-_/]{1,19})\b", re.I)
# Letters then digits, and the letters may carry digits of their own:
# PVH-2026, HP2-2027, A1-99.
BARE_CODE = re.compile(r"\b([A-Z][A-Z0-9]{1,5}-\d{1,5})\b")
DATED = re.compile(
    r"\b(?:start(?:ing|s)?|from|begin(?:ning|s)?)\b[^.,;]{0,24}?"
    r"(\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}|\d{4}-\d{2}-\d{2})", re.I)
ENDS = re.compile(
    r"\b(?:end(?:ing|s)?|until|finish(?:ing|es)?|complet\w*|due|by)\b[^.,;]{0,24}?"
    r"(\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}|\d{4}-\d{2}-\d{2})", re.I)

#: The same two cues, for dates written as words. Defined after MONTH_ALT.
TEXT_START = None   # bound below, once MONTH_ALT exists
TEXT_END = None

#: "add a user Dana Whitfield d.whitfield@..." names the person without saying
#: "called", so capitalised words straight after the noun are read as the name.
PERSON = re.compile(
    r"\b(?:user|account|team\s*member|teammate|staff\s*member|employee|colleague|person)\s+"
    r"(?!called\b|named\b|with\b|for\b|to\b)"
    r"([A-Z][\w'’\-]+(?:\s+[A-Z][\w'’\-]+){0,3})")

#: Trailing words that belong to the sentence rather than to the name. "of" is
#: here because "Crane hire of 45,000 taka" is a cost called Crane hire, and a
#: name that swallows the amount takes the amount with it.
NAME_TAIL = re.compile(
    r"\s+\b(?:with|for|and|of|starting|start|from|ending|ends|until|due|by|"
    r"managed|run\s+by|code|as|in|on|at|to|priority|status|worth|costing|"
    r"assigned|under)\b.*$", re.I)


#: Construction sentences write dates as words as often as digits, and
#: ``read_date`` only knows digits. "4th May 2026" has to survive.
MONTHS = ("january", "february", "march", "april", "may", "june", "july",
          "august", "september", "october", "november", "december")
MONTH_ALT = "|".join(name[:3] for name in MONTHS)
TEXT_DATE = re.compile(
    rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({MONTH_ALT})[a-z]*\.?,?\s+(\d{{4}})\b"
    rf"|\b({MONTH_ALT})[a-z]*\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b", re.I)

#: An amount is only read when it is written as one -- a currency mark or a
#: unit. A bare number in a sentence is far more often a quantity or a floor.
AMOUNT = re.compile(
    r"(?:\u09f3|Tk\.?|BDT|USD|\$|\u00a3|\u20ac|\u20b9)\s*([\d,]+(?:\.\d{1,2})?)"
    r"|\b([\d,]+(?:\.\d{1,2})?)\s*(?:taka|tk\b|bdt|dollars?|pounds?|euros?)", re.I)

QUANTITY = re.compile(r"\b(?:quantity|qty|count|number)\s*(?:of|is|:|=)?\s*([\d,]+)\b", re.I)

_WRITTEN = (rf"\d{{1,2}}(?:st|nd|rd|th)?\s+(?:{MONTH_ALT})[a-z]*\.?,?\s+\d{{4}}"
            rf"|(?:{MONTH_ALT})[a-z]*\.?\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+\d{{4}}")
TEXT_START = re.compile(
    rf"\b(?:start(?:ing|s)?|from|begin(?:ning|s)?)\b[^.,;]{{0,24}}?({_WRITTEN})", re.I)
TEXT_END = re.compile(
    rf"\b(?:end(?:ing|s)?|until|to|finish(?:ing|es)?|complet\w*|due|by)\b"
    rf"[^.,;]{{0,24}}?({_WRITTEN})", re.I)


def clean_name(value: str) -> str:
    text = NAME_TAIL.sub("", str(value or "").strip()).strip(" .,;:-")
    return text[:120]


def read_any_date(value: str) -> str:
    """An ISO date from a numeric or a written form, or nothing."""
    text = str(value or "").strip()
    if not text:
        return ""
    written = TEXT_DATE.search(text)
    if written:
        day, month, year = (written.group(1), written.group(2), written.group(3))
        if not day:
            month, day, year = (written.group(4), written.group(5), written.group(6))
        index = next((position for position, name in enumerate(MONTHS, start=1)
                      if name.startswith(str(month).lower()[:3])), 0)
        if index:
            return read_date(f"{int(year):04d}-{index:02d}-{int(day):02d}")
    return read_date(text)


def match_existing_record(message: str,
                          rows: Sequence[Mapping[str, str]]) -> dict[str, str]:
    """The record this sentence names, or nothing at all.

    Longest name first, so "Padma View Specialised Hospital Extension" is not
    beaten by a project called "Padma View". Only a name that really exists is
    ever returned: a task filed against a project somebody guessed is worse
    than a task that was not created.
    """
    text = str(message or "")
    for row in sorted(rows, key=lambda item: len(str(item.get("label") or "")),
                      reverse=True):
        label = str(row.get("label") or "").strip()
        if len(label) < 3:
            continue
        if re.search(rf"(?<!\w){re.escape(label)}(?!\w)", text, re.I):
            return dict(row)
    return {}


def read_plainly(kind: str, text: str,
                 choices: Mapping[str, Sequence[Mapping[str, str]]]) -> dict[str, Any]:
    """Take what can be read from the sentence with no model at all.

    Driven by the schema rather than by a branch per kind, so a kind added to
    :mod:`entity_schema` is read without touching this. Deliberately shy
    throughout: it would rather leave a field for the form than guess it.
    """
    message = str(text or "")
    spec = ENTITIES[kind]
    fields = spec.field_map
    found: dict[str, Any] = {}

    # The name, however the sentence gives it.
    if "name" in fields:
        quoted = QUOTED.search(message)
        if quoted:
            found["name"] = clean_name(quoted.group(1))
        else:
            called = CALLED.search(message)
            if called:
                found["name"] = clean_name(called.group(1))
            else:
                phrase = FOR_PHRASE.search(message)
                candidate = clean_name(phrase.group(1)) if phrase else ""
                names_a_record = candidate and any(
                    match_existing_record(candidate, rows) for rows in choices.values())
                if candidate and not names_a_record:
                    found["name"] = candidate

    if kind == "user":
        if "name" not in found:
            person = PERSON.search(message)
            if person:
                found["name"] = clean_name(person.group(1))
        email = EMAIL.search(message)
        if email:
            found["email"] = email.group(0)

    if kind == "project":
        code = CODE.search(message) or BARE_CODE.search(message)
        if code:
            found["project_code"] = code.group(1).upper()

    # Everything from here is read from the sentence with the name taken out of
    # it. "Rebar inspection" is a task called Rebar inspection, not a task in
    # the Rebar trade, and a word inside the name is not also a field.
    scan = message
    if found.get("name"):
        scan = scan.replace(str(found["name"]), " ", 1)

    # A select field is filled only by one of its own options, written out.
    for field in spec.fields:
        if not field.options or field.name in found:
            continue
        for option in field.options:
            if re.search(rf"(?<!\w){re.escape(str(option))}(?!\w)", scan, re.I):
                found[field.name] = option
                break

    # A reference field is filled only by a record that exists. One name fills
    # one field per referenced kind: a task naming a person means an assignee,
    # and reading that same person as the on-site worker too would be invention.
    taken: set[str] = set()
    for field in spec.fields:
        if not field.reference or field.name in found or field.reference in taken:
            continue
        match = match_existing_record(scan, choices.get(field.name, ()))
        if match:
            found[field.name] = match["label"]
            taken.add(field.reference)

    # Dates, in the order the schema declares them: what starts takes the
    # first, what ends takes the last.
    dated = [field for field in spec.fields if field.type in ("date", "datetime")]
    if dated:
        starts = DATED.search(scan) or TEXT_START.search(scan)
        ends = ENDS.search(scan) or TEXT_END.search(scan)
        if starts and dated[0].name not in found:
            parsed = read_any_date(starts.group(1))
            if parsed:
                found[dated[0].name] = parsed
        if ends and len(dated) > 1:
            # The cue decides, not field order: "due 8 May" is the due date,
            # while "ending 8 May" closes what the start opened.
            due = next((field for field in dated if field.name == "due_date"), None)
            asks_due = re.match(r"\s*(?:due|by)\b", ends.group(0), re.I)
            target = due if (asks_due and due) else dated[1]
            if target.name not in found:
                parsed = read_any_date(ends.group(1))
                if parsed:
                    found[target.name] = parsed
        # A single written date with no cue at all still belongs on the first.
        if not starts and not ends:
            plain = TEXT_DATE.search(scan)
            if plain and dated[0].name not in found:
                parsed = read_any_date(plain.group(0))
                if parsed:
                    found[dated[0].name] = parsed

    # Money, and a quantity where the schema has one.
    money = [field for field in spec.fields if field.type == "money"]
    if money and money[0].name not in found:
        amount = AMOUNT.search(scan)
        if amount:
            digits = (amount.group(1) or amount.group(2) or "").replace(",", "")
            if digits:
                found[money[0].name] = digits
    if "quantity" in fields and "quantity" not in found:
        quantity = QUANTITY.search(scan)
        if quantity:
            found["quantity"] = quantity.group(1).replace(",", "")

    return found


# ── Reading a reply to a question ────────────────────────────────────────

#: A date with no year: "October 1", "1 Oct". Only ever read as an answer to a
#: question about a date field, never out of a general sentence.
LOOSE_DATE = re.compile(
    rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({MONTH_ALT})[a-z]*\.?\b"
    rf"|\b({MONTH_ALT})[a-z]*\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\b", re.I)

#: Openers people put in front of a one-word answer.
ANSWER_OPENER = re.compile(
    r"^\s*(?:(?:it|that|the\s+\w+)\s*(?:'s|s|\s+is|\s+will\s+be)|"
    r"its|set\s+it\s+to|make\s+it|use|"
    r"(?:ok(?:ay)?|sure|yes|yeah|right)\s*[,.]?\s*)\s*", re.I)


def read_loose_date(value: str) -> str:
    """A date whose year was not given, resolved to its next occurrence.

    "October 1" is a real answer to "when does it start?", and refusing it
    would mean asking again for something the person has already said. The year
    is the only part inferred, and the form shows the whole date before
    anything is created.
    """
    match = LOOSE_DATE.search(str(value or ""))
    if not match:
        return ""
    day, month = (match.group(1), match.group(2))
    if not day:
        month, day = (match.group(3), match.group(4))
    index = next((position for position, name in enumerate(MONTHS, start=1)
                  if name.startswith(str(month).lower()[:3])), 0)
    if not index:
        return ""
    today = date.today()
    for year in (today.year, today.year + 1):
        try:
            settled = date(year, index, int(day))
        except ValueError:
            return ""
        if settled >= today:
            return settled.isoformat()
    return ""


def read_field_value(field: Any, raw: str,
                     choices: Mapping[str, Sequence[Mapping[str, str]]]) -> Any:
    """One field's value, read from the phrase that answered a question about it.

    Returns nothing when the phrase does not produce a value the field can
    hold -- an unparseable date, a role nobody has -- so the question is asked
    again rather than filled with something that was never said.
    """
    text = str(raw or "").strip().strip(".,;:!?")
    if not text:
        return ""
    if field.type in ("date", "datetime"):
        return read_any_date(text) or read_loose_date(text)
    if field.type in ("money", "number"):
        digits = re.sub(r"[^\d.]", "", text)
        return digits if re.search(r"\d", digits) else ""
    if field.options:
        return next((option for option in field.options
                     if str(option).casefold() == text.casefold()), "")
    if field.reference:
        row = match_existing_record(text, choices.get(field.name, ()))
        return str(row.get("label", "")) if row else ""
    return clean_name(text)


def read_answer(kind: str, text: str, asking: Sequence[str],
                choices: Mapping[str, Sequence[Mapping[str, str]]]) -> dict[str, Any]:
    """Read a reply to a question about named fields.

    Two shapes, because people answer in both: "the manager is John and it
    starts on 1 October" names its fields, and "October 1" does not. The
    second is only readable because the question is known, which is why a bare
    phrase becomes a value here and nowhere else.
    """
    spec = ENTITIES.get(kind)
    if spec is None:
        return {}
    by_name = spec.field_map
    message = str(text or "").strip()
    wanted = [name for name in asking if name in by_name]
    found: dict[str, Any] = {}
    if not message or not wanted:
        return found

    # Both ways round, because people answer in both: "the manager is John"
    # and "John is the project manager" are the same sentence.
    for name in wanted:
        field = by_name[name]
        label = re.escape(field.label)
        forward = re.compile(rf"\b{label}\s*(?:is|are|=|:|will\s+be)\s*([^.,;]+)", re.I)
        # Up to two words may sit between "the" and the label, so "the project
        # manager" and "the planned start date" both reach it.
        backward = re.compile(
            rf"(.+?)\s+(?:is|are|will\s+be)\s+(?:the\s+)?(?:\w+\s+){{0,2}}?{label}\b", re.I)
        match = forward.search(message) or backward.search(message)
        if match:
            value = read_field_value(field, match.group(1), choices)
            if value not in (None, ""):
                found[name] = value

    # A bare reply -- "John", "October 1" -- names no field, so the open
    # questions are tried against it and it is taken only when exactly one of
    # them can hold it. A field with a form (a date, an amount, a name from a
    # list) settles it outright; free text is the answer only when nothing
    # else could have been.
    remaining = [name for name in wanted if name not in found]
    if remaining and not found:
        bare = ANSWER_OPENER.sub("", message)
        readable = [(name, read_field_value(by_name[name], bare, choices))
                    for name in remaining]
        readable = [(name, value) for name, value in readable if value not in (None, "")]
        shaped = [(name, value) for name, value in readable
                  if by_name[name].type not in ("text", "textarea")]
        if len(shaped) == 1:
            found[shaped[0][0]] = shaped[0][1]
        elif not shaped and len(readable) == 1:
            found[readable[0][0]] = readable[0][1]
    return found


# ── Reading the fields with the model ────────────────────────────────────

def build_prompt(kind: str, text: str, known: Mapping[str, Any],
                 choices: Mapping[str, Sequence[Mapping[str, str]]]) -> str:
    """Describe the record from the schema, and ask only for what is in the text."""
    spec = ENTITIES[kind]
    lines = [
        f"You are reading one sentence from a construction project manager who "
        f"wants to create a {spec.label.lower()}.",
        "",
        "Return ONLY a JSON object of the form "
        '{"fields": {"<field>": "<value>"}}. No prose, no code fence.',
        "",
        f"The {spec.label.lower()} has these fields. Use no others:",
    ]
    for field in spec.fields:
        parts = [f"- {field.name} ({field.label})"]
        if field.required:
            parts.append("REQUIRED")
        if field.options:
            parts.append("one of: " + ", ".join(field.options))
        if field.reference:
            available = [str(row.get("label", "")) for row in choices.get(field.name, ())]
            parts.append("must be exactly one of the existing records: "
                         + (", ".join(available) if available else "(none exist yet)"))
        if field.type == "date":
            parts.append("ISO date, YYYY-MM-DD")
        lines.append("  " + " | ".join(parts))

    if known:
        lines += ["", "Already settled in earlier turns (do not repeat or change):",
                  "  " + json.dumps(dict(known), ensure_ascii=False)]

    lines += [
        "",
        "Rules you must follow:",
        "- Include a field ONLY if the sentence actually gives it. Omit everything else.",
        "- Never invent a name, a code, a date, an email address or an amount.",
        "- For a field with a list above, copy one of the listed values exactly,"
        " or omit the field. Never invent a new one.",
        "- If the sentence is ambiguous, omit the field. It will be asked for.",
        "",
        f"The sentence: {str(text or '').strip()}",
    ]
    return "\n".join(lines)


FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.I)


def parse_model_fields(raw: str) -> dict[str, Any]:
    """Pull the JSON object out of a model reply, tolerating chatter around it."""
    text = FENCE.sub("", str(raw or "").strip())
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            return {}
        try:
            parsed = json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            return {}
    if not isinstance(parsed, dict):
        return {}
    fields = parsed.get("fields", parsed)
    return dict(fields) if isinstance(fields, dict) else {}


# ── Putting a proposal together ──────────────────────────────────────────

def clean_fields(kind: str, raw: Mapping[str, Any],
                 choices: Mapping[str, Sequence[Mapping[str, str]]]) -> dict[str, Any]:
    """Keep only fields the schema knows, coerced, with references verified.

    A reference value that does not name a record which exists is dropped, not
    corrected to the nearest one -- guessing which project type somebody meant
    is exactly the kind of invention this is here to prevent.
    """
    spec = ENTITIES[kind]
    by_name = {field.name: field for field in spec.fields}
    kept: dict[str, Any] = {}

    for name, value in dict(raw or {}).items():
        field = by_name.get(str(name))
        if field is None or value in (None, ""):
            continue
        try:
            settled = coerce(kind, field.name, value)
        except (HTTPException, ValueError):
            continue
        if settled in (None, ""):
            continue
        if field.options:
            match = next((option for option in field.options
                          if str(option).casefold() == str(settled).casefold()), None)
            if match is None:
                continue
            settled = match
        if field.reference:
            available = choices.get(field.name, ())
            match = next((str(row.get("label")) for row in available
                          if str(row.get("label", "")).casefold() == str(settled).casefold()), None)
            if match is None:
                continue
            settled = match
        kept[field.name] = settled
    return kept


#: The name the parent is collected under. No entity has a field called this,
#: so it cannot collide with one.
PARENT_FIELD = "__parent__"


def outstanding(kind: str, fields: Mapping[str, Any]) -> list[dict[str, str]]:
    """Every mandatory field still unanswered, schema first.

    Each row carries ``asked_in``: "chat" for something to ask the person, or
    "form" for something the dialog produces by itself.
    """
    gaps = [{**row, "asked_in": "chat"}
            for row in missing_required(kind, fields, has_parent=True)]
    seen = {row["name"] for row in gaps}
    for extra in EXTRA_REQUIRED.get(kind, ()):
        if extra["name"] not in fields and extra["name"] not in seen:
            gaps.append({"asked_in": "chat", **dict(extra)})
            seen.add(extra["name"])
    for name in INSISTED.get(kind, ()):
        if name in fields or name in seen:
            continue
        field = next((f for f in ENTITIES[kind].fields if f.name == name), None)
        if field is not None:
            gaps.append({"name": field.name, "label": field.label,
                         "type": field.type, "reference": field.reference,
                         "asked_in": "chat"})
            seen.add(field.name)
    return gaps


def describe(kind: str, fields: Mapping[str, Any],
             parent: Mapping[str, Any] | None = None) -> str:
    """One line naming what was understood, for the chat reply."""
    spec = ENTITIES[kind]
    labels = {field.name: field.label for field in spec.fields}
    shown = []
    if parent and parent.get("name"):
        shown.append(f"**{parent.get('label') or 'Parent'}:** {parent['name']}")
    shown += [f"**{labels.get(name, name)}:** {value}"
              for name, value in fields.items() if value not in (None, "")]
    return " · ".join(shown[:6])


def register_chat_entity_routes(namespace: Mapping[str, Any]) -> dict[str, Any]:
    """Register the chat entity interpreter on the notebook app.

    Interpretation only. The records are created by the ordinary project and
    user routes, so their permission checks and validators are the ones that
    actually decide.
    """
    required = ("app", "require_account")
    missing = [name for name in required if name not in namespace]
    if missing:
        raise RuntimeError(f"Chat entity integration is missing: {', '.join(missing)}")

    app = namespace["app"]
    require_account = namespace["require_account"]
    registry = namespace.get("ACCOUNT_REGISTRY")
    generate: Callable[..., Any] | None = namespace.get("vl_generate")

    def live_choices(context: Any, kind: str) -> dict[str, list[dict[str, str]]]:
        """The records a reference field may point at, for this account."""
        found: dict[str, list[dict[str, str]]] = {}
        for field in ENTITIES[kind].fields:
            if not field.reference:
                continue
            found[field.name] = reference_choices(
                field.reference, workspace=context.workspace,
                registry=registry, account_id=context.account_id)
        return found

    async def ask_model(prompt: str) -> str:
        if not callable(generate):
            return ""
        try:
            reply = generate(prompt, max_tokens=MAX_INTERPRET_TOKENS)
            if hasattr(reply, "__await__"):
                reply = await reply
            return str(reply or "")
        except Exception:  # pragma: no cover - model transport
            return ""

    @app.post("/api/assistant/entities/interpret")
    async def interpret_entity(body: InterpretRequest,
                               context=Depends(require_account)) -> dict[str, Any]:
        kind = str(body.kind or "").strip() or detect_kind(body.text)
        if not kind:
            return {"supported": False, "kind": "", "reason": "no_intent"}

        if kind not in CHAT_KINDS:
            spec = ENTITIES.get(kind)
            return {
                "supported": False, "kind": kind, "reason": "use_onboarding",
                "label": spec.label if spec else kind,
                "plural": spec.plural if spec else kind,
            }

        spec = ENTITIES[kind]
        # The guards the create route itself applies, mirrored so chat never
        # opens a form for something the person would then be refused.
        if spec.permission and not context.can(spec.permission):
            raise HTTPException(403, f"You do not have permission to create {spec.plural.lower()}")
        if kind == "user":
            context.require_admin()
        elif kind == "role_type":
            context.require_super_admin()

        choices = live_choices(context, kind)
        known = clean_fields(kind, body.known, choices)

        # The parent is settled before anything else is read, because its name
        # is not also a value. Answering "which project?" with "Harbour Point
        # Phase 2" was otherwise read as a task called Harbour Point Phase 2,
        # of the task type Phase -- every field in the answer, twice over.
        parent: dict[str, Any] | None = None
        reading = str(body.text or "")
        if spec.parent:
            rows = reference_choices(spec.parent, workspace=context.workspace,
                                     registry=registry, account_id=context.account_id)
            # A name the sentence gives wins over the project the person happens
            # to have open: naming one is the more deliberate act of the two.
            chosen = match_existing_record(reading, rows)
            if chosen:
                reading = re.sub(rf"(?<!\w){re.escape(str(chosen['label']))}(?!\w)",
                                 " ", reading, count=1, flags=re.I)
            elif body.parent_id:
                chosen = next((dict(row) for row in rows
                               if str(row.get("id")) == str(body.parent_id)), {})
            parent = {
                "kind": spec.parent,
                "label": spec.parent_label or ENTITIES[spec.parent].label,
                "id": str(chosen.get("id") or ""),
                "name": str(chosen.get("label") or ""),
                "options": rows,
            }

        # A reply to a question is read first and beats the general readers: it
        # is the one case where what the field means is already known.
        asking = [str(name) for name in (body.asking or [])]
        answered = clean_fields(kind, read_answer(kind, reading, asking, choices),
                                choices) if asking else {}

        # The model reads the sentence; the plain reader is the floor under it.
        raw = await ask_model(build_prompt(kind, reading, known, choices))
        from_model = clean_fields(kind, parse_model_fields(raw), choices)
        plainly = clean_fields(kind, read_plainly(kind, reading, choices), choices)
        fields = {**plainly, **from_model, **answered, **known}
        source = ("answer" if answered else
                  "model" if from_model else ("text" if plainly else "none"))

        gaps = outstanding(kind, fields)
        if parent and not parent["id"]:
            # First, because there is no point filling a task in before you know
            # which project it belongs to.
            gaps.insert(0, {"name": PARENT_FIELD, "label": parent["label"],
                            "type": "reference", "reference": parent["kind"],
                            "asked_in": "chat"})

        # What is still to be asked in conversation, as against what the dialog
        # produces by itself. The form opens only when this is empty.
        to_ask = [row for row in gaps if row.get("asked_in", "chat") == "chat"]

        return {
            "supported": True, "kind": kind, "label": spec.label,
            "plural": spec.plural, "stored_in": spec.stored_in,
            "permission": spec.permission, "fields": fields,
            "missing": gaps, "chat_missing": to_ask, "ready": not to_ask,
            "choices": choices,
            "parent": parent, "parent_field": PARENT_FIELD,
            # The form is rendered from this, so a field added to the schema
            # appears in chat without the client being changed.
            "spec": spec.as_dict(),
            "summary": describe(kind, fields, parent), "source": source,
        }

    return {"kinds": list(CHAT_KINDS), "model": bool(callable(generate))}


__all__ = [
    "CHAT_KINDS", "EXTRA_REQUIRED", "INSISTED", "PARENT_FIELD", "InterpretRequest",
    "build_prompt", "clean_fields", "clean_name", "describe", "detect_kind",
    "match_existing_record", "outstanding", "parse_model_fields", "read_answer",
    "read_any_date", "read_field_value", "read_loose_date", "read_plainly",
    "register_chat_entity_routes", "KIND_NOUNS",
]
