# Creating a record from chat

Marshal Chat could already book a meeting or write an email from a sentence, but
*"create a project called Riverside Tower"* fell through to document search and
answered that it could not find it — while the same sentence worked on the
Onboarding page. That gap is closed for every record the application has a
create route for.

| | |
| --- | --- |
| Interpreter | [`backend/chat_entities.py`](../backend/chat_entities.py) |
| Route | `POST /api/assistant/entities/interpret` |
| Frontend | `handleEntityCreateRequest`, `openChatEntityForm` in [`frontend/app.js`](../frontend/app.js) |
| Tests | `backend/tests/test_chat_entities.py` |

## What chat can create

| Kind | Created by | Needs a parent |
| --- | --- | --- |
| Project | `POST /api/projects` | — |
| User | `POST /api/users` | — |
| Task | `POST /api/projects/{id}/tasks` | project |
| Task type | `POST /api/task-types` | — |
| Project type | `POST /api/project-types` | — |
| Role | `POST /api/user-roles` | — |
| Trade | `POST /api/trades` | — |
| External company | `POST /api/vendors` | — |
| Project cost | `POST /api/projects/{id}/costs` | project |
| Procurement item | `POST /api/projects/{id}/procurement` | project |

| Task cost | `PUT /api/projects/{id}/tasks/{id}` | task |

A task cost is written by updating the task it belongs to, because that is what
it is: the task's `cost` field, not a record of its own.

## The collection

**The dialog opens once, at the end.** While anything mandatory is missing the
exchange stays in chat; each reply adds to what is already settled; and the
dialog opens when there is nothing left to ask — prefilled, for review. Nothing
is created until the person presses the button in it.

> **"Create a project called Website Redesign."**
> *Sure — I can create a project. I still need **Project code**, **Manager** and
> **Start date**.*
> **"WR-2027"** → *Got it. I still need **Manager** and **Start date**.*
> **"John is the project manager"** → *Got it. I still need **Start date**.*
> **"October 1 2027"** → the dialog opens with all four filled in.

The same four can arrive in one message instead; the dialog opens at the point
the last one lands, not before.

What makes a bare reply readable is that the question is known. `asking` carries
the fields the last reply asked about, and `read_answer` uses it:

* **"the manager is John"** and **"John is the project manager"** — both ways
  round, because people answer in both.
* **"October 1"** — nothing names a field, so each open question is tried and
  the answer is taken only when exactly one of them can hold it. A date, an
  amount or a name from a list settles it outright; free text is the answer only
  when nothing else could have been. With two free-text fields open, a bare
  phrase is refused and asked about again.
* **"sometime in the spring"** reads as no date at all, so the question is asked
  again rather than filled with something nobody said.

A year that was not given — "October 1" — is resolved to the next occurrence.
It is the only part ever inferred, and the dialog shows the whole date.

**Two ways out**, so a half-filled form can never trap the next thing typed:
*"cancel"* ends it, and a question of its own that answers nothing goes to
document search.

### What counts as mandatory

Two lists, and neither is written twice:

* what the **create route refuses without** — from `entity_schema.py`, which is
  checked against the application's own constructors at startup;
* what **chat insists on** beyond that, in `INSISTED` — a project's manager and
  start date, a user's role. A project with no manager and no start date is one
  nobody can plan against.

`EXTRA_REQUIRED` carries the third case: a field the **dialog** collects rather
than chat. A new account's temporary password is generated in the dialog, so
asking for it in conversation would be asking somebody to type a password into a
chat log. Each gap says which it is, in `asked_in`, and only the `chat` ones
hold the dialog back.

Project and user keep their own dialogs, which are richer than a generated form
and carry the temporary-password handling a new account needs. Every other kind
shares one form built from the schema the route returns, so a field added to
[`entity_schema.py`](../backend/entity_schema.py) appears in chat without the
client being touched.

## The parent

A task, a project cost and a procurement line cannot exist without a project,
so one is resolved before anything else is asked for:

1. a project **named in the sentence**, matched against projects that exist —
   longest name first, so *Padma View Specialised Hospital Extension* is not
   beaten by a project called *Padma View*;
2. otherwise **the project already open**, which the client sends as
   `parent_id`, so *"create a task for the slab pour"* works while looking at one;
3. otherwise it is the **first thing the form asks for**, as a list of the
   projects that exist rather than a text box.

A name that matches no project is never accepted. A task filed against a
guessed project is worse than a task that was not created.

---

## What happens

> **"create a project called Riverside Tower with code RVT-2027 starting 2027-01-11"**

Marshal replies with what it understood, the **New Project** dialog opens with
those three fields already filled, and one click creates it.

> **"set up a Healthcare project called Mill Lane Clinic"**

Same dialog, name and type filled — and **Project Code** ringed in amber with
*needs an answer* beside its label, with the caret already in it. The chat says
*"I still need Project code. I have opened the form with the rest filled in."*

> **"add a new user Dana Whitfield d.whitfield@calderwood.example as a Site Supervisor"**

The **Create User** dialog, with the name, the email and the role all set, and a
temporary password generated for you to pass on.

> **"create a task for the slab pour"**

Not created. A task belongs to a draft you can review first, so chat says so and
points at Onboarding.

> **"what is the RFI response period?"**

Untouched. It goes to document retrieval, exactly as before.

---

## Why it is built this way

### The schema decides what is mandatory

Required fields, enums and the lists a reference field may point at all come
from [`entity_schema.py`](../backend/entity_schema.py), which derives them from
the application's own constructors and validators. Nothing is restated in the
chat layer, so there is no second definition to drift.

One exception is named rather than hidden: `POST /api/users` requires a
password, which the user schema does not carry because onboarding generates one.
`EXTRA_REQUIRED` says so in one line, next to the reason.

### Nothing is invented

A value for a reference field is accepted **only** when it names a record that
actually exists. "Site Supervisior" is not corrected to "Site Supervisor" — it is
dropped, and the form asks. Guessing which one somebody meant is exactly the
failure this is here to prevent. The same goes for enums: a status the schema
does not list is discarded, not snapped to the nearest.

### Interpretation creates nothing

The route reads a sentence and reports what it understood and what is still
missing. The record is created by the ordinary `POST /api/projects` or
`POST /api/users` route, so the real permission check and the real validators are
the ones that decide. Chat is a faster way to reach the same form, not a second
way into the database.

### The model is preferred, but not required

The model reads a sentence far better than a pattern does, so it is asked first,
with a prompt built from the schema. When it is unreachable or answers with
something unusable, a deterministic reader takes what it can — a quoted name, an
email address, a code, a date, a role that exists — and the form collects the
rest.

So the feature degrades to *"a prefilled form"* rather than to an error, and it
works in the demonstration backend, which has no model at all. The response says
which path was taken in `source`: `model`, `text`, or `none`.

---

## What counts as a creation request

Detection is two steps — find a create verb, then find the record noun after it —
so an adjective in between does not break it ("set up a **Healthcare** project").

A noun reached through a preposition names where something goes rather than what
is being made, so *"add a note **to the** project"* is not a request for a new
project. And the features that share this vocabulary are excluded outright:
*generate a project **document***, *create a **report***, *schedule a **meeting***.

A false positive here steals a question from retrieval, so detection is
deliberately conservative: when in doubt it returns nothing.

| Sentence | Read as |
| --- | --- |
| create a project called Riverside Tower | project |
| set up a Healthcare project "Mill Lane Clinic" | project |
| start a job called Bridge Deck Repairs | project |
| add a new user Dana Whitfield as a Site Supervisor | user |
| register an employee named Callum Byrne | user |
| add a user to the project | user |
| create a task for the slab pour | task |
| make a new vendor called Aquaseal | vendor |
| add a task cost of 5000 taka | task cost → Onboarding |
| add a note to the project | nothing |
| generate a project document | nothing |
| how many projects are there? | nothing |

---

## Permissions

Checked before anything is offered, so a refusal arrives as a sentence rather
than as a failed save:

* a project needs `project.create`;
* a user needs an account administrator.

Both are checked again by the create routes themselves, which is where they
actually bite.

---

## Cost

A chat message only reaches the interpreter when it contains a create-ish verb —
a superset of the server's own list, checked in the browser. Everything else goes
straight to retrieval with no extra round trip. When the interpreter is reached
but the sentence is not a creation request, it answers from patterns alone and
never calls the model.
