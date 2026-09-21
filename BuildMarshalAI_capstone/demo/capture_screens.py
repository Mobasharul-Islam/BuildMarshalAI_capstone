"""Capture the demonstration screenshots from a running demo backend.

Drives a headless Chrome at 2x against `demo/demo_server.py`, so every image is
the real interface rendering real numbers rather than a mockup. Start the server
first, then:

    python demo/demo_server.py          # in one terminal
    python demo/capture_screens.py      # in another

Images land in `demo/screens/`. The session is seeded by asking the API for a
token and writing it to localStorage -- the sign-in form is photographed, never
typed into.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from selenium import webdriver
from selenium.common.exceptions import (ElementNotInteractableException,
                                        JavascriptException,
                                        NoSuchElementException,
                                        TimeoutException)
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as expect
from selenium.webdriver.support.ui import WebDriverWait

HERE = Path(__file__).resolve().parent
SHOTS = HERE / "screens"
BASE = "http://127.0.0.1:8000"
EMAIL = "rafiqul.islam@purbachalcon.example"
PASSWORD = "PadmaView2026!"


def token() -> str:
    """Ask the API for a session, the way the sign-in form would."""
    request = urllib.request.Request(
        f"{BASE}/api/auth/login", method="POST",
        headers={"Content-Type": "application/json"},
        data=json.dumps({"email": EMAIL, "password": PASSWORD}).encode())
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read())["token"]


def driver() -> webdriver.Chrome:
    options = Options()
    for flag in ("--headless=new", "--window-size=1600,1000", "--hide-scrollbars",
                 "--force-device-scale-factor=2", "--no-sandbox",
                 "--disable-gpu", "--disable-dev-shm-usage"):
        options.add_argument(flag)
    browser = webdriver.Chrome(options=options)
    browser.set_page_load_timeout(40)
    return browser


class Shooter:
    def __init__(self, browser: webdriver.Chrome) -> None:
        self.browser = browser
        self.taken: list[tuple[str, int]] = []
        #: frame name -> what the viewer did to arrive at it.
        self.gestures: dict[str, dict] = {}
        self._pending: dict | None = None
        SHOTS.mkdir(parents=True, exist_ok=True)

    # -- primitives ------------------------------------------------------
    def js(self, script: str):
        try:
            return self.browser.execute_script(script)
        except JavascriptException as error:
            print(f"    ! script failed: {str(error)[:90]}")
            return None

    def wait_for(self, selector: str, seconds: float = 12) -> bool:
        try:
            WebDriverWait(self.browser, seconds).until(
                expect.presence_of_element_located((By.CSS_SELECTOR, selector)))
            return True
        except TimeoutException:
            return False

    def note_click(self, element, label: str) -> None:
        """Record where a click landed, as a fraction of the viewport.

        Fractions rather than pixels, so the clip builder need not know the
        device pixel ratio or how the screenshot was later scaled.
        """
        try:
            spot = self.browser.execute_script(
                "const r = arguments[0].getBoundingClientRect();"
                "return {x:(r.left + r.width / 2) / window.innerWidth,"
                " y:(r.top + r.height / 2) / window.innerHeight,"
                " w:r.width / window.innerWidth, h:r.height / window.innerHeight};",
                element)
        except JavascriptException:
            return
        if spot and 0 <= spot["x"] <= 1 and 0 <= spot["y"] <= 1:
            self._pending = {"kind": "click", "label": label, **spot}

    def click(self, selector: str, settle: float = 1.4) -> bool:
        try:
            element = self.browser.find_element(By.CSS_SELECTOR, selector)
            self.note_click(element, selector)
            self.browser.execute_script("arguments[0].click()", element)
            time.sleep(settle)
            return True
        except (NoSuchElementException, ElementNotInteractableException):
            print(f"    ! no element {selector}")
            self._pending = None
            return False

    def shot(self, name: str, note: str = "") -> None:
        path = SHOTS / f"{name}.png"
        self.browser.save_screenshot(str(path))
        size = path.stat().st_size
        self.taken.append((name, size))
        if self._pending:
            self.gestures[name] = self._pending
            self._pending = None
        print(f"  {size:>9,}  {name}.png{'  — ' + note if note else ''}")

    def open_project(self, label: str) -> bool:
        """Open the project whose name contains `label`."""
        links = self.browser.find_elements(By.CSS_SELECTOR, 'a[data-action="open-project"]')
        target = next((link for link in links if label.lower() in link.text.lower()), None)
        if target is None:
            print(f"    ! no project matching {label!r}")
            return False
        self.note_click(target, f"project: {label}")
        self.browser.execute_script("arguments[0].click()", target)
        time.sleep(3.0)
        return True

    # -- navigation ------------------------------------------------------
    def page(self, key: str, settle: float = 2.0) -> bool:
        ok = self.click(f'.nav-item[data-page="{key}"]', settle)
        if not ok:
            self.js(f"document.querySelector('[data-page=\"{key}\"]')?.click()")
            time.sleep(settle)
        return ok

    def tab(self, key: str, settle: float = 2.2) -> bool:
        return self.click(f'.tab-btn[data-tab="{key}"]', settle)

    def ask(self, question: str, settle: float = 3.5) -> None:
        """Put a question to Marshal the way a person would."""
        try:
            box = self.browser.find_element(By.CSS_SELECTOR, "#chatInput")
        except NoSuchElementException:
            print("    ! no chat input")
            return
        box.clear()
        box.send_keys(question)
        time.sleep(0.4)
        self.click("#btnChatSend", settle)

    def dismiss(self) -> None:
        """Close whatever dialog is open, so it does not sit over the next page."""
        self.js("document.querySelectorAll('.modal-overlay.open')"
                ".forEach(m => m.classList.remove('open'));")
        time.sleep(0.5)

    def chat(self, visible: bool) -> None:
        """The chat is docked by default and eats a quarter of every frame."""
        self.js("const p=document.getElementById('chatPanel'); if(p){"
                + ("p.classList.add('visible');p.classList.remove('collapsed');"
                   if visible else
                   "p.classList.add('collapsed');p.classList.remove('visible');")
                + "}")
        time.sleep(0.6)

    def top(self) -> None:
        self.js("window.scrollTo(0,0); document.querySelector('.content-area')?.scrollTo(0,0)")
        time.sleep(0.3)

    def scroll_to_bottom(self) -> None:
        self.js("const a=document.querySelector('.content-area');"
                "(a||window).scrollTo(0,(a||document.body).scrollHeight)")
        self._pending = {"kind": "scroll", "label": "scrolled to the end"}
        time.sleep(0.9)

    def scroll(self, pixels: int) -> None:
        self.js(f"const a=document.querySelector('.content-area');"
                f"(a||window).scrollTo(0,{pixels})")
        self._pending = {"kind": "scroll", "label": f"scrolled to {pixels}px"}
        time.sleep(0.8)


def capture() -> tuple[list[tuple[str, int]], dict]:
    browser = driver()
    shoot = Shooter(browser)
    try:
        # 1 — the gate, photographed before any session exists.
        browser.get(BASE)
        shoot.wait_for("#authGate, .auth-gate, input[type=password]", 15)
        time.sleep(1.5)
        shoot.shot("01-signin", "the gate every account starts behind")

        # Seed the session rather than typing a password into the form.
        session = json.dumps({"token": token()})
        browser.execute_script(
            "localStorage.setItem('bmarshal_session', arguments[0]);"
            "localStorage.setItem('bmarshal_api_url', arguments[1]);", session, BASE)
        browser.get(BASE)
        if not shoot.wait_for(".nav-item", 20):
            print("  ! the app never signed in")
            return shoot.taken, shoot.gestures
        time.sleep(4.0)
        shoot.chat(False)

        # 2 — projects
        shoot.page("all-projects", 2.6)
        shoot.top()
        shoot.shot("02-projects", "the project register")

        # 3 — open the project and walk its tabs
        shoot.open_project("Padma View")
        if not shoot.wait_for('.tab-btn[data-tab="stats"]', 10):
            print("    ! the project did not open -- its tabs were not captured")
        shoot.top()
        shoot.shot("03-project-overview", "overview")

        for key, name, note in (
                ("people", "04-project-people", "members and their roles"),
                ("cost", "05-project-cost", "budget against commitment"),
                ("timeline", "06-project-timeline", "the Gantt"),
                ("procore", "07-project-procurement", "procurement register")):
            if shoot.tab(key):
                shoot.top()
                shoot.shot(name, note)

        # 4 — statistics, the long one
        if shoot.tab("stats", 4.0):
            shoot.top()
            shoot.shot("08-statistics-top", "earned value and the headline row")
            shoot.scroll(780)
            shoot.shot("09-statistics-curve", "the S-curve and cost")
            shoot.scroll(1620)
            shoot.shot("10-statistics-flow", "flow and schedule health")
            shoot.scroll_to_bottom()
            shoot.shot("11-statistics-risks", "risks, each naming its number")
            shoot.top()

        # 5 — the report dialog
        if shoot.click("[data-action='project-report']", 3.2):
            shoot.shot("12-report-dialog", "what the report would contain")
            shoot.dismiss()

        # 5b — the same dialog on projects at other stages, because the phase
        # is what decides which report gets written.
        for index, (label, note) in enumerate((
                ("Banasree", "a project that has not started \u2014 Baseline"),
                ("Agrabad", "a project that has finished \u2014 Final"))):
            shoot.page("all-projects", 2.4)
            if not shoot.open_project(label):
                continue
            if shoot.click('[data-action="project-report"]', 3.2):
                shoot.shot(f"12{'bc'[index]}-report-{'baseline' if index == 0 else 'final'}", note)
                shoot.dismiss()

        # 6 — tasks
        shoot.page("tasks", 2.8)
        shoot.top()
        shoot.shot("13-tasks", "tasks with their hierarchy")

        # 7 — documents, then storage
        shoot.page("documents", 2.8)
        shoot.top()
        shoot.shot("14-documents", "what is indexed")
        if shoot.click("#btnStorageOpen", 3.0):
            shoot.top()
            shoot.shot("15-storage", "where the space went")
            shoot.scroll(900)
            shoot.shot("16-storage-reclaim", "what a sweep would remove")

        # 8 — onboarding, through its three steps
        shoot.page("onboarding", 3.0)
        shoot.top()
        shoot.shot("17-onboarding", "the drafts on this account")
        if shoot.click("[data-onb-open]", 3.4):
            shoot.click('[data-onb-step="1"]', 2.0)
            shoot.top()
            shoot.shot("17b-onboarding-upload", "step 1 — the documents to read")
            shoot.click('[data-onb-step="2"]', 2.6)
            shoot.top()
            shoot.shot("17c-onboarding-draft", "step 2 — the editable draft tree")
            shoot.scroll(900)
            shoot.shot("17d-onboarding-missing", "incomplete items, and what they are missing")
            shoot.click('[data-onb-step="3"]', 3.0)
            shoot.top()
            shoot.shot("17e-onboarding-plan", "step 3 — create, reuse, refuse")

        # 9 — settings pages
        shoot.js("document.querySelector('[data-page=\"company-info\"]')"
                 "?.closest('.nav-group,li')?.querySelector('.nav-item')?.click()")
        time.sleep(1.0)
        for key, name, note in (
                ("company-info", "18-company", "the company profile"),
                ("task-types", "19-task-types", "the task-type catalogue"),
                ("project-types", "20-project-types", "the project-type catalogue"),
                ("trades", "21-trades", "trades"),
                ("user-roles", "22-user-roles", "roles built from permissions"),
                ("users", "23-users", "the people on the account")):
            shoot.page(key, 2.4)
            shoot.top()
            shoot.shot(name, note)

        # 10 — calendar and to-do lists
        shoot.page("calendar", 3.0)
        shoot.top()
        shoot.shot("24-calendar", "one month, every source")
        shoot.page("todo-lists", 2.6)
        shoot.top()
        shoot.shot("25-todo-lists", "a list built from open tasks")

        # 10b — Google Workspace and Microsoft 365
        for page, provider, label in (("google-workspace", "google", "Google Workspace"),
                                      ("microsoft-workspace", "microsoft", "Microsoft 365")):
            prefix = "29" if provider == "google" else "30"
            shoot.page(page, 3.0)
            shoot.top()
            shoot.shot(f"{prefix}-{provider}-connected", f"{label} \u2014 the linked account")
            # Files: load them, then tick two to index.
            shoot.click(f'[data-provider-tab="files"]', 2.0)
            shoot.click(f"#btn{provider.capitalize()}DriveRefresh", 3.0)
            shoot.top()
            shoot.shot(f"{prefix}b-{provider}-drive", "documents in the linked drive")
            boxes = browser.find_elements(By.CSS_SELECTOR, ".provider-file-check")
            for box in boxes[:2]:
                browser.execute_script("arguments[0].click()", box)
            time.sleep(1.4)
            shoot.shot(f"{prefix}c-{provider}-drive-selected", "chosen for indexing")
            # Mail.
            shoot.click(f'[data-provider-tab="mail"]', 2.0)
            shoot.click(f"#btn{provider.capitalize()}MailRefresh", 3.0)
            shoot.top()
            shoot.shot(f"{prefix}d-{provider}-mail", "the inbox, and Marshal's composer")
            # Calendar.
            shoot.click(f'[data-provider-tab="calendar"]', 2.6)
            shoot.top()
            shoot.shot(f"{prefix}e-{provider}-calendar", "events on the linked calendar")

        # 10c — creating records and booking a meeting from chat
        shoot.page("all-projects", 2.4)
        shoot.chat(True)
        time.sleep(1.0)
        shoot.ask("create a project called Mirpur Clinic Extension "
                  "with code MCE-2027 starting 2027-04-05")
        shoot.shot("31-chat-create-project", "a project, understood and prefilled")
        shoot.dismiss()
        shoot.ask("add a new user Ashraful Alam ashraful.alam@purbachalcon.example "
                  "as a Site Supervisor")
        shoot.shot("32-chat-create-user", "a person and their role, with a temporary password")
        shoot.dismiss()
        shoot.ask("schedule a Google Meet about \"Level 4 pour readiness\" "
                  "tomorrow at 10am", 5.0)
        shoot.shot("33-chat-schedule-meeting", "a meeting, asked for and confirmed in chat")
        shoot.ask("create a task for the level 4 slab pour")
        shoot.shot("34-chat-redirect-onboarding", "what belongs in a draft is sent there")

        # 11 — the chat, in each of its three window states
        shoot.page("marshal-chat", 2.4)
        shoot.chat(True)
        time.sleep(1.2)
        shoot.ask("What is the RFI response period on this contract?")
        shoot.shot("26-chat-answer", "an answer, with the page it came from")
        shoot.ask("What concrete grade is specified for the slabs?")
        shoot.shot("26b-chat-cited", "a second question, cited to the specification")

        # Docked beside the work is the ordinary case.
        shoot.page("all-projects", 2.2)
        shoot.chat(True)
        time.sleep(1.0)
        shoot.shot("26c-chat-docked", "docked beside the work")
        if shoot.click("#btnChatMaximize", 1.6):
            shoot.shot("27-chat-full", "full screen")
            shoot.click("#btnChatMaximize", 1.4)
        if shoot.click("#btnChatMinimize", 1.6):
            shoot.shot("28-chat-minimised", "minimised to a pill")
        return shoot.taken, shoot.gestures
    finally:
        browser.quit()


if __name__ == "__main__":
    try:
        urllib.request.urlopen(f"{BASE}/api/health", timeout=6).read()
    except (urllib.error.URLError, OSError) as error:
        sys.exit(f"The demonstration backend is not answering on {BASE}: {error}\n"
                 f"Start it first:  python demo/demo_server.py")
    print(f"capturing to {SHOTS}")
    taken, gestures = capture()
    (SHOTS / "gestures.json").write_text(json.dumps(gestures, indent=2), encoding="utf-8")
    print(f"recorded {len(gestures)} gestures")
    print(f"\n{len(taken)} screenshots")
    thin = [name for name, size in taken if size < 40_000]
    if thin:
        print(f"suspiciously small (probably an empty page): {', '.join(thin)}")
