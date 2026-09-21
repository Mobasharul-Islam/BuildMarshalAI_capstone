"""Generate the BuildMarshalAI demonstration document pack.

One fictional Bangladeshi construction project -- a specialised hospital
extension in Uttara, Dhaka -- described the way project information actually
arrives on a site office desk: a brief, a programme, a team list, a cost plan,
a procurement schedule, a specification, a drawing register and an architectural
floor plan. Bangla and English mixed the way they are mixed in practice, money
in Taka with lakh/crore grouping.

Every figure reconciles: the cost plan is generated *from* the programme, so it
cannot drift, and `check()` proves it before anything is written.

PDFs are printed from HTML by headless Chrome rather than drawn by a PDF
library, because Bengali needs complex text shaping -- conjuncts and vowel signs
that reorder around the consonant -- which reportlab and Pillow cannot do and a
browser does correctly.

    python scripts/make_demo_pack.py
"""
from __future__ import annotations

import base64
import csv
import datetime as dt
from pathlib import Path
from urllib.parse import quote

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt, RGBColor
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

OUT = Path("demo/project-pack")

# ── The project ──────────────────────────────────────────────────────────
PROJECT_BN = "পদ্মা ভিউ স্পেশালাইজড হাসপাতাল সম্প্রসারণ"
PROJECT_EN = "Padma View Specialised Hospital Extension"
PROJECT = f"{PROJECT_BN} / {PROJECT_EN}"
CODE = "PVH-2026"
CLIENT_BN, CLIENT_EN = "মেঘনা হেলথ ফাউন্ডেশন", "Meghna Health Foundation"
CONTRACTOR_BN, CONTRACTOR_EN = "পূর্বাচল কনস্ট্রাকশন লিমিটেড", "Purbachal Construction Ltd"
SITE_BN = "সেক্টর ১১, উত্তরা, ঢাকা ১২৩০"
SITE_EN = "Sector 11, Uttara, Dhaka 1230"

GIA_M2 = 8_400
PRELIMINARIES = 38_500_000
CONTINGENCY = 25_000_000
OVERHEAD_PROFIT = 27_000_000

START = dt.date(2026, 2, 2)
FINISH = dt.date(2027, 6, 30)

LD_PERCENT_EN = "0.05% per day, capped at 10% of the contract sum"
RFI_DAYS = 7
DEFECTS_MONTHS = 12

INK = "#1f2933"
ACCENT = "#1f6f4a"
RULE = "#c9cdd2"
BAND = "#eef4f0"
BANGLA_STACK = "'Nirmala UI', 'Kalpurush', 'Shonar Bangla', 'Noto Sans Bengali', sans-serif"


def bd_group(amount: float) -> str:
    """Group digits the way Bangladesh does: 6,00,00,000 rather than 600,000,000."""
    digits = f"{int(round(amount)):d}"
    if len(digits) <= 3:
        return digits
    head, tail = digits[:-3], digits[-3:]
    parts: list[str] = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return ",".join(parts + [tail])


def taka(amount: float) -> str:
    return f"৳ {bd_group(amount)}"


def crore(amount: float) -> str:
    """The unit a Bangladeshi project manager actually speaks in."""
    if amount >= 10_000_000:
        return f"৳ {amount / 10_000_000:,.2f} crore"
    return f"৳ {amount / 100_000:,.2f} lakh"


# ── The programme ────────────────────────────────────────────────────────
# (name, parent, trade, assignee, start, end, cost, priority, status, type)
TASKS = [
    ("Site Preparation & Enabling", "", "General", "Shahidul Haque",
     "2026-02-02", "2026-03-26", 0, "High", "Completed", "Phase"),
    ("Site hoarding and office setup", "Site Preparation & Enabling", "General",
     "Shahidul Haque", "2026-02-02", "2026-02-19", 4_200_000, "High", "Completed", "Construction"),
    ("Soil test and topographic survey", "Site Preparation & Enabling", "General",
     "Kamrul Hasan", "2026-02-09", "2026-02-26", 2_100_000, "High", "Completed", "Survey"),
    ("Demolition of old block", "Site Preparation & Enabling", "Earthworks",
     "Shahidul Haque", "2026-03-01", "2026-03-26", 8_600_000, "High", "Completed", "Construction"),
    ("Temporary power and water connection", "Site Preparation & Enabling", "Electrical",
     "Tanvir Ahmed", "2026-03-01", "2026-03-19", 3_600_000, "Normal", "Completed", "Construction"),

    ("Piling & Foundation", "", "Piling", "Nusrat Jahan",
     "2026-03-29", "2026-07-09", 0, "High", "Completed", "Phase"),
    ("Bored piling - 320 piles", "Piling & Foundation", "Piling",
     "Nusrat Jahan", "2026-03-29", "2026-05-21", 48_000_000, "High", "Completed", "Construction"),
    ("Pile caps and grade beams", "Piling & Foundation", "Concrete",
     "Nusrat Jahan", "2026-05-24", "2026-06-25", 19_500_000, "High", "Completed", "Construction"),
    ("Earth filling and compaction", "Piling & Foundation", "Earthworks",
     "Farhana Akter", "2026-06-07", "2026-06-25", 5_400_000, "Normal", "Completed", "Construction"),
    ("Below-ground drainage", "Piling & Foundation", "Plumbing",
     "Farhana Akter", "2026-06-14", "2026-07-09", 6_100_000, "Normal", "Completed", "Construction"),

    ("Superstructure", "", "Concrete", "Nusrat Jahan",
     "2026-07-12", "2026-12-17", 0, "High", "In Progress", "Phase"),
    ("Level 1 slab casting", "Superstructure", "Concrete", "Nusrat Jahan",
     "2026-07-12", "2026-08-06", 26_500_000, "High", "Completed", "Construction"),
    ("Level 2 slab casting", "Superstructure", "Concrete", "Nusrat Jahan",
     "2026-08-09", "2026-09-03", 26_500_000, "High", "In Progress", "Construction"),
    ("Level 3 slab casting", "Superstructure", "Concrete", "Nusrat Jahan",
     "2026-09-06", "2026-10-01", 26_500_000, "High", "In Progress", "Construction"),
    ("Level 4 slab casting", "Superstructure", "Concrete", "Nusrat Jahan",
     "2026-10-04", "2026-10-29", 26_500_000, "High", "Open", "Construction"),
    ("Level 5 and roof deck", "Superstructure", "Concrete", "Nusrat Jahan",
     "2026-11-01", "2026-12-03", 28_000_000, "High", "Open", "Construction"),
    ("Stair and lift core", "Superstructure", "Rebar", "Kamrul Hasan",
     "2026-11-15", "2026-12-17", 8_000_000, "Normal", "Open", "Construction"),

    ("Envelope & Roofing", "", "Glazing", "Sabrina Chowdhury",
     "2026-08-16", "2027-02-25", 0, "High", "In Progress", "Phase"),
    ("Glazing sample panel approval", "Envelope & Roofing", "Glazing",
     "Sabrina Chowdhury", "2026-08-16", "2026-09-05", 1_500_000, "Urgent", "Blocked", "Design"),
    ("External masonry and plaster", "Envelope & Roofing", "Masonry",
     "Sabrina Chowdhury", "2026-10-11", "2026-12-24", 24_000_000, "High", "Open", "Construction"),
    ("Aluminium glazing installation", "Envelope & Roofing", "Glazing",
     "Sabrina Chowdhury", "2026-12-06", "2027-02-25", 27_000_000, "High", "Open", "Construction"),
    ("Roof waterproofing", "Envelope & Roofing", "General",
     "Farhana Akter", "2026-12-20", "2027-01-28", 7_500_000, "High", "Open", "Construction"),
    ("External painting", "Envelope & Roofing", "Painting",
     "Farhana Akter", "2027-01-31", "2027-02-25", 4_000_000, "Normal", "Open", "Construction"),

    ("MEP Installation", "", "HVAC", "Tanvir Ahmed",
     "2026-11-01", "2027-04-15", 0, "High", "Open", "Phase"),
    ("Electrical first fix", "MEP Installation", "Electrical", "Tanvir Ahmed",
     "2026-11-01", "2027-01-14", 22_000_000, "High", "Open", "Construction"),
    ("Plumbing first fix", "MEP Installation", "Plumbing", "Tanvir Ahmed",
     "2026-11-15", "2027-01-28", 16_500_000, "High", "Open", "Construction"),
    ("HVAC ducting and chillers", "MEP Installation", "HVAC", "Tanvir Ahmed",
     "2027-01-03", "2027-03-11", 26_000_000, "High", "Open", "Construction"),
    ("Generator and substation", "MEP Installation", "Electrical", "Tanvir Ahmed",
     "2027-01-24", "2027-03-25", 19_500_000, "High", "Open", "Construction"),
    ("Fire protection system", "MEP Installation", "Fire Safety", "Tanvir Ahmed",
     "2027-02-14", "2027-04-15", 12_000_000, "High", "Open", "Construction"),

    ("Internal Finishing", "", "Tiling", "Imtiaz Rahman",
     "2027-01-03", "2027-05-13", 0, "High", "Open", "Phase"),
    ("Internal masonry and plaster", "Internal Finishing", "Masonry", "Imtiaz Rahman",
     "2027-01-03", "2027-02-18", 18_000_000, "High", "Open", "Construction"),
    ("Floor tiles and marble", "Internal Finishing", "Tiling", "Imtiaz Rahman",
     "2027-02-21", "2027-04-08", 24_000_000, "High", "Open", "Construction"),
    ("Doors and joinery", "Internal Finishing", "General", "Imtiaz Rahman",
     "2027-03-14", "2027-04-22", 15_500_000, "Normal", "Open", "Construction"),
    ("Operation theatre fit-out", "Internal Finishing", "HVAC", "Tanvir Ahmed",
     "2027-03-07", "2027-04-29", 18_000_000, "Urgent", "Open", "Construction"),
    ("Painting and finishing", "Internal Finishing", "Painting", "Imtiaz Rahman",
     "2027-04-11", "2027-05-13", 5_500_000, "Normal", "Open", "Construction"),

    ("Commissioning & Handover", "", "General", "Md. Rafiqul Islam",
     "2027-03-21", "2027-06-30", 0, "High", "Open", "Phase"),
    ("Lift installation and testing", "Commissioning & Handover", "Lifts",
     "Tanvir Ahmed", "2027-03-21", "2027-05-06", 14_000_000, "High", "Open", "Construction"),
    ("External works and landscaping", "Commissioning & Handover", "Earthworks",
     "Farhana Akter", "2027-04-04", "2027-05-27", 6_500_000, "Normal", "Open", "Construction"),
    ("Systems commissioning", "Commissioning & Handover", "HVAC",
     "Tanvir Ahmed", "2027-05-16", "2027-06-17", 6_000_000, "High", "Open", "Commissioning"),
    ("Handover documents and training", "Commissioning & Handover", "General",
     "Md. Rafiqul Islam", "2027-06-06", "2027-06-30", 2_500_000, "Normal", "Open", "Handover"),
]

# ── The team ─────────────────────────────────────────────────────────────
TEAM = [
    ("Md. Rafiqul Islam", "মোঃ রফিকুল ইসলাম", "rafiqul.islam@purbachalcon.example",
     "Project Director", "Super Admin", "Management", "01711-902345"),
    ("Nusrat Jahan", "নুসরাত জাহান", "nusrat.jahan@purbachalcon.example",
     "Construction Manager", "Project Manager", "Operations", "01711-902416"),
    ("Tanvir Ahmed", "তানভীর আহমেদ", "tanvir.ahmed@prokoushalseba.example",
     "MEP Lead", "Project Manager", "Engineering", "01711-902527"),
    ("Sabrina Chowdhury", "সাবরিনা চৌধুরী", "sabrina.chowdhury@purbachalcon.example",
     "Package Manager, Envelope", "Site Supervisor", "Operations", "01711-902638"),
    ("Shahidul Haque", "শহিদুল হক", "shahidul.haque@purbachalcon.example",
     "Site Manager", "Site Supervisor", "Operations", "01711-902749"),
    ("Farhana Akter", "ফারহানা আক্তার", "farhana.akter@purbachalcon.example",
     "Works Manager", "Site Supervisor", "Operations", "01711-902850"),
    ("Imtiaz Rahman", "ইমতিয়াজ রহমান", "imtiaz.rahman@sthapatyasangsad.example",
     "Lead Architect", "Viewer", "Design", "01711-902961"),
    ("Kamrul Hasan", "কামরুল হাসান", "kamrul.hasan@bhittieng.example",
     "Structural Engineer", "Viewer", "Engineering", "01711-903072"),
    ("Rumana Parveen", "রুমানা পারভীন", "rumana.parveen@hisabcons.example",
     "Quantity Surveyor", "Cost Manager", "Commercial", "01711-903183"),
    ("Dr. Anisur Rahman", "ডা. আনিসুর রহমান", "anisur.rahman@meghnahealth.example",
     "Client Representative", "Viewer", "Client", "01711-903294"),
]

# ── Procurement ──────────────────────────────────────────────────────────
PROCUREMENT = [
    ("Aluminium glazing units", "Brahmaputra Glass Ltd", "Glazing", 1_850, "sft", 3_400,
     "Requested", "2026-12-06", "",
     "12-week lead time from sample approval. Sample not yet approved."),
    ("Passenger and stretcher lifts - 4 no.", "Dhaleshwari Lift Company", "Lifts", 4, "unit",
     3_200_000, "Requested", "2027-03-21", "",
     "Imported, 16-week lead time. Order-by date has passed."),
    ("HVAC chiller units - 2 no.", "Surma Air Systems", "HVAC", 2, "unit", 8_600_000,
     "Ordered", "2027-01-03", "2026-08-11", "Factory acceptance test report required."),
    ("Diesel generator 600 kVA", "Karnaphuli Electricals", "Electrical", 1, "unit", 7_800_000,
     "Ordered", "2027-01-24", "2026-09-01", "Soundproof canopy included."),
    ("MS rod, Grade 60", "Turag Steel Industries", "Rebar", 420, "ton", 92_000,
     "Ordered", "2026-10-04", "2026-08-24", "For Levels 4 and 5."),
    ("Portland composite cement", "Shitalakshya Cement", "Concrete", 9_600, "bag", 560,
     "Ordered", "2026-10-04", "2026-09-07", ""),
    ("Vitrified floor tiles", "Teesta Tiles Ltd", "Tiling", 42_000, "sft", 185,
     "Quoted", "2027-02-21", "", "Anti-bacterial grade for the operation theatres."),
    ("Fire hydrant and sprinkler system", "Rupsha Building Products", "Fire Safety", 1,
     "package", 9_400_000, "Quoted", "2027-02-14", "",
     "Fire Service and Civil Defence approval required."),
]

# ── The cost plan, derived ───────────────────────────────────────────────
PHASE_ELEMENTS = [
    ("Site Preparation & Enabling", "Site preparation and enabling",
     "Site establishment, demolition and temporary services"),
    ("Piling & Foundation", "Piling and foundation",
     "Bored piles, pile caps, grade beams, drainage"),
    ("Superstructure", "Superstructure",
     "RCC frame, slabs to Level 5, stair and lift core"),
    ("Envelope & Roofing", "Envelope and roofing",
     "Masonry, aluminium glazing, waterproofing, external paint"),
    ("MEP Installation", "Mechanical and electrical services",
     "Electrical, plumbing, HVAC, generator, fire protection"),
    ("Internal Finishing", "Internal finishing",
     "Plaster, tiles, joinery, operation theatre fit-out"),
    ("Commissioning & Handover", "Commissioning, external works and handover",
     "Lifts, external works, commissioning, handover"),
]

def phase_total(phase: str) -> int:
    """What a phase costs, from its own tasks -- never entered twice."""
    return sum(row[6] for row in TASKS if row[1] == phase)


def build_cost_plan() -> list[tuple[str, str, str, int, str]]:
    rows = [("1.0", "Preliminaries",
             "Site management, welfare, insurance and security",
             PRELIMINARIES, "Preliminaries")]
    for index, (phase, label, detail) in enumerate(PHASE_ELEMENTS, start=2):
        rows.append((f"{index}.0", label, detail, phase_total(phase), "Construction"))
    following = len(rows) + 1
    rows.append((f"{following}.0", "Contingency",
                 "Design development and risk allowance", CONTINGENCY, "Contingency"))
    rows.append((f"{following + 1}.0", "Overhead and profit",
                 "Contractor overhead and profit", OVERHEAD_PROFIT, "Overhead"))
    return rows


COSTS = build_cost_plan()
CONTRACT_SUM = sum(row[3] for row in COSTS)

# ── Drawings ─────────────────────────────────────────────────────────────
DRAWINGS = [
    ("A-101", "Site plan and location", "C", "14 Jul 2026", "Sthapatya Sangsad", "Construction"),
    ("A-201", "Ground floor plan", "D", "02 Sep 2026", "Sthapatya Sangsad", "Construction"),
    ("A-202", "First floor plan", "C", "14 Jul 2026", "Sthapatya Sangsad", "Construction"),
    ("A-203", "Second floor - ICU and operation theatres", "C", "14 Jul 2026",
     "Sthapatya Sangsad", "Construction"),
    ("A-204", "Level 3-5 cabin plan", "B", "21 Jun 2026", "Sthapatya Sangsad", "Construction"),
    ("A-310", "North and east elevations", "C", "02 Sep 2026", "Sthapatya Sangsad", "Construction"),
    ("A-420", "Glazing typical details", "B", "16 Aug 2026", "Sthapatya Sangsad", "For approval"),
    ("S-101", "Pile layout", "D", "12 Apr 2026", "Bhitti Engineering", "Construction"),
    ("S-210", "Level 1-3 slab reinforcement", "C", "28 Jun 2026", "Bhitti Engineering",
     "Construction"),
    ("S-211", "Level 4-5 slab reinforcement", "B", "16 Aug 2026", "Bhitti Engineering",
     "Construction"),
    ("E-100", "Ground floor electrical layout", "B", "09 Aug 2026", "Prokoushal Seba",
     "Construction"),
    ("E-500", "Generator and substation", "A", "06 Sep 2026", "Prokoushal Seba", "For approval"),
    ("P-100", "Plumbing and sanitary layout", "B", "09 Aug 2026", "Prokoushal Seba",
     "Construction"),
    ("M-300", "HVAC chiller and duct route", "B", "09 Aug 2026", "Prokoushal Seba",
     "Construction"),
]

HEAD_FILL = PatternFill("solid", fgColor="1F2933")
HEAD_FONT = Font(color="FFFFFF", bold=True, size=11)
PHASE_FILL = PatternFill("solid", fgColor="EEF4F0")
BANGLA_XL = "Nirmala UI"


def autosize(sheet, widths):
    for index, width in enumerate(widths, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width


# ── Printing a document through Chrome ───────────────────────────────────

PAGE_CSS = """
  @page { size: A4; margin: 16mm 15mm; }
  body { font-family: %(bangla)s; color: %(ink)s; font-size: 10.5pt; line-height: 1.55; }
  h1 { font-size: 21pt; margin: 0 0 2px; letter-spacing: -0.2px; }
  h2 { font-size: 13pt; color: %(accent)s; margin: 22px 0 8px;
       border-bottom: 2px solid %(accent)s; padding-bottom: 4px; }
  h3 { font-size: 11pt; margin: 14px 0 5px; }
  .sub { color: #5a636b; font-size: 10pt; margin: 0 0 18px; }
  table { border-collapse: collapse; width: 100%%; margin: 10px 0 16px; font-size: 9.5pt; }
  th { background: %(ink)s; color: #fff; text-align: left; padding: 7px 9px;
       font-weight: 600; }
  td { border: 1px solid %(rule)s; padding: 6px 9px; vertical-align: top; }
  tr:nth-child(even) td { background: %(band)s; }
  ul { margin: 6px 0 14px; padding-left: 20px; }
  li { margin-bottom: 5px; }
  .note { background: %(band)s; border-left: 4px solid %(accent)s;
          padding: 10px 14px; margin: 12px 0; font-size: 10pt; }
  .right { text-align: right; }
  .big { font-size: 12pt; font-weight: 600; }
""" % {"bangla": BANGLA_STACK, "ink": INK, "accent": ACCENT, "rule": RULE, "band": BAND}


class Printer:
    """Headless Chrome, used as a typesetter.

    Bengali needs conjunct formation and vowel reordering that a PDF library
    cannot do; a browser does it correctly, and printToPDF embeds the shaped
    glyphs, so the result renders properly everywhere afterwards.
    """

    def __init__(self) -> None:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options

        options = Options()
        for flag in ("--headless=new", "--no-sandbox", "--disable-gpu",
                     "--hide-scrollbars", "--force-device-scale-factor=1"):
            options.add_argument(flag)
        self.browser = webdriver.Chrome(options=options)

    def write(self, target: Path, title: str, body: str) -> Path:
        page = ("<!doctype html><meta charset='utf-8'><title>" + title + "</title>"
                "<style>" + PAGE_CSS + "</style><body>" + body + "</body>")
        self.browser.get("data:text/html;charset=utf-8," + quote(page))
        result = self.browser.execute_cdp_cmd("Page.printToPDF", {
            "printBackground": True, "paperWidth": 8.27, "paperHeight": 11.69,
            "marginTop": 0, "marginBottom": 0, "marginLeft": 0, "marginRight": 0,
            "preferCSSPageSize": True})
        target.write_bytes(base64.b64decode(result["data"]))
        return target

    def close(self) -> None:
        self.browser.quit()


def rows_to_table(head: list[str], rows: list[list[str]]) -> str:
    header = "".join(f"<th>{cell}</th>" for cell in head)
    body = "".join("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>"
                   for row in rows)
    return f"<table><tr>{header}</tr>{body}</table>"


# ── 1. Project brief ─────────────────────────────────────────────────────

def project_brief(printer: Printer) -> Path:
    particulars = rows_to_table(
        ["Item", "Particulars"],
        [["Project", PROJECT_EN],
         ["Project code", CODE],
         ["Employer", f"{CLIENT_EN} ({CLIENT_BN})"],
         ["Contractor", f"{CONTRACTOR_EN} ({CONTRACTOR_BN})"],
         ["Site", SITE_EN],
         ["Gross internal area", f"{GIA_M2:,} m&sup2; (approx. {GIA_M2 * 10.764:,.0f} sft)"],
         ["Contract sum", f"<span class='big'>{taka(CONTRACT_SUM)}</span> ({crore(CONTRACT_SUM)})"],
         ["Date of commencement", "2 February 2026"],
         ["Date for completion", "30 June 2027"],
         ["Liquidated damages", LD_PERCENT_EN],
         ["Defects liability period", f"{DEFECTS_MONTHS} months from practical completion"],
         ["Retention", "10 per cent — 5% released at completion, 5% at the end of the "
                       "defects liability period"]])

    phases = rows_to_table(
        ["Phase", "Start", "Finish", "Value"],
        [[phase, min(r[4] for r in TASKS if r[1] == phase),
          max(r[5] for r in TASKS if r[1] == phase), taka(phase_total(phase))]
         for phase, _, _ in PHASE_ELEMENTS])

    team = rows_to_table(
        ["Role", "Organisation", "Principal contact"],
        [["Employer", CLIENT_EN, "Dr. Anisur Rahman"],
         ["Main contractor", CONTRACTOR_EN, "Md. Rafiqul Islam"],
         ["Architect", "Sthapatya Sangsad Ltd", "Imtiaz Rahman"],
         ["Structural engineer", "Bhitti Engineering", "Kamrul Hasan"],
         ["MEP consultant", "Prokoushal Seba Ltd", "Tanvir Ahmed"],
         ["Quantity surveyor", "Hisab Consultants", "Rumana Parveen"]])

    body = f"""
      <h1>{PROJECT_EN}</h1>
      <h1 style="font-size:15pt;color:#5a636b;font-weight:500">{PROJECT_BN}</h1>
      <p class="sub">Project Brief &nbsp;·&nbsp; {CODE} &nbsp;·&nbsp;
        Revision C &nbsp;·&nbsp; Issued 14 September 2026</p>

      <h2>1. Project particulars</h2>
      {particulars}

      <h2>2. Scope of works</h2>
      <ul>
        <li>Demolition of the existing single-storey block and site preparation.</li>
        <li>Construction of a six-storey RCC framed hospital extension of {GIA_M2:,} m&sup2;
            on 320 bored piles.</li>
        <li>Two modular operation theatres, an 18-bed intensive care unit and a
            12-bed emergency department.</li>
        <li>Full mechanical, electrical and public health installation, including
            chiller-based HVAC, a 600 kVA standby generator, and a fire hydrant and
            sprinkler system.</li>
        <li>Four lifts (two of them stretcher lifts), 42-space car parking and an
            ambulance drop-off.</li>
      </ul>

      <h2>3. Exclusions</h2>
      <ul>
        <li>Medical equipment supply and installation, purchased directly by the Employer.</li>
        <li>Active IT and telephony equipment beyond containment and outlets.</li>
        <li>Decanting of the existing outpatient department, which remains the
            Employer's responsibility.</li>
      </ul>

      <h2>4. Programme phases</h2>
      {phases}

      <h2>5. Project team</h2>
      {team}

      <h2>6. Key constraints</h2>
      <div class="note">
        <b>Monsoon — বর্ষা মৌসুম.</b> From June to September, slab casting and
        external works depend on the weather. The Contractor shall maintain adequate
        covering, pumping and temporary drainage throughout this period, and
        weather-delay claims are admissible only with Bangladesh Meteorological
        Department records.
      </div>
      <ul>
        <li>The adjoining outpatient department remains in clinical use. Noisy works are
            restricted to 09:00–17:00 on working days, and <b>Friday is the weekly
            holiday</b> with no work at all.</li>
        <li>Works must follow the RAJUK-approved drawings. The application for the
            occupancy certificate must be submitted 8 weeks before handover.</li>
        <li>The fire protection system cannot be commissioned without clearance from the
            Fire Service and Civil Defence Directorate.</li>
        <li>Lifts are imported with a 16-week lead time. The date for opening the letter
            of credit sits on the project's critical path.</li>
      </ul>
    """
    return printer.write(OUT / "01_Project-Brief.pdf",
                         f"{PROJECT_EN} — Project Brief", body)


# ── 2. Tender specification ──────────────────────────────────────────────

def specification(printer: Printer) -> Path:
    concrete = rows_to_table(
        ["Location", "Grade", "Cover", "Notes"],
        [["Piles and pile caps", "4000 psi (C30/37)", "75 mm",
          "Sulfate-resisting cement, slump 150–180 mm"],
         ["Grade beams", "4000 psi (C30/37)", "50 mm", "—"],
         ["Slabs and beams, Levels 1–5", "3500 psi (C25/30)", "25 mm", "To BNBC 2020"],
         ["Columns", "4000 psi (C30/37)", "40 mm", "—"],
         ["Blinding", "1500 psi", "—", "75 mm minimum thickness"]])

    hse = rows_to_table(
        ["Requirement", "Standard", "Frequency"],
        [["Site induction", "Every person before first access", "Once per person"],
         ["Toolbox talk", "Recorded, signed register", "Weekly"],
         ["Scaffold inspection", "Competent person, written record", "Every 7 days"],
         ["Work at height permit", "Above 3 metres", "Each occasion"],
         ["Accident reporting to the Employer", "Within 24 hours", "Each occurrence"],
         ["Dust and noise monitoring", "75 dB(A) at the boundary", "Continuous"]])

    handover = rows_to_table(
        ["Deliverable", "Due", "Format"],
        [["Draft O&amp;M manuals", "8 weeks before completion", "PDF, indexed"],
         ["Final O&amp;M manuals", "At completion", "PDF and 2 hard copies"],
         ["As-built drawings", "At completion", "PDF and native CAD"],
         ["Test and commissioning certificates", "2 weeks before completion", "PDF"],
         ["RAJUK occupancy certificate", "At completion", "Original"],
         ["Fire Service clearance", "Before commissioning", "Original"],
         ["Building user training", "2 weeks before completion", "4 sessions"]])

    body = f"""
      <h1>{PROJECT_EN}</h1>
      <h1 style="font-size:15pt;color:#5a636b;font-weight:500">Tender Specification &amp;
        Preliminaries &nbsp;·&nbsp; দরপত্র বিবরণী</h1>
      <p class="sub">{CODE} &nbsp;·&nbsp; Revision C &nbsp;·&nbsp;
        Issued 14 September 2026</p>

      <h2>1. Preliminaries and general conditions</h2>
      <h3>1.1 Working hours</h3>
      <p>Working hours on site are 08:00 to 18:00, Saturday to Thursday.
        <b>Friday is the weekly holiday</b> and no work is permitted on Friday or on
        public holidays. Noisy operations — anything above <b>75 dB(A) at the site
        boundary</b> — are further restricted to <b>09:00 to 17:00</b>, because the
        adjoining outpatient department remains in clinical use throughout the works.</p>

      <h3>1.2 Deliveries and site access</h3>
      <p>All deliveries shall be booked with the site office at least 48 hours in advance.
        The single site access is from Road 4, Sector 11. No deliveries are permitted
        between 07:30 and 09:00, when patients are arriving.</p>

      <h3>1.3 Monsoon provisions</h3>
      <p>From June to September the Contractor shall maintain adequate covering, pumping
        and temporary drainage for open slabs and castings. Claims for weather delay are
        admissible only with Bangladesh Meteorological Department records for the days
        claimed.</p>

      <h2>2. Information and communication</h2>
      <h3>2.1 Requests for information</h3>
      <p>The Contractor shall submit Requests for Information through the project
        information system. The consultant team shall respond within
        <b>{RFI_DAYS} working days</b>. An RFI that affects the critical path shall be
        marked <b>Urgent</b> and answered within <b>3 working days</b>. No extension of
        time arises from an RFI raised later than 15 working days before the information
        is required.</p>

      <h3>2.2 Samples and shop drawings</h3>
      <p>Shop drawings, product data and samples shall be submitted not less than 10
        working days before the material is required on site. The review period is 7
        working days. A submittal returned as 'Revise and Resubmit' restarts the review
        period in full.</p>

      <h3>2.3 Progress reporting</h3>
      <p>The Contractor shall issue a written progress report by the third working day of
        each month, covering progress against the accepted programme, procurement status,
        open RFIs, safety statistics, and any matter likely to give rise to a claim for
        additional time or money.</p>

      <h2>3. Materials and workmanship</h2>
      <h3>3.1 Concrete</h3>
      {concrete}
      <p>All concrete shall be supplied from a BSTI-accredited ready-mix plant. One set of
        cylinder tests shall be taken per 50 cubic metres or per pour, whichever is the
        more frequent, with 7-day and 28-day results issued to the consultant.</p>

      <h3>3.2 Aluminium glazing</h3>
      <p>The glazing system shall be thermally broken aluminium with 6 mm + 12 mm air gap
        + 6 mm double glazed units, tested for air permeability. A full-size <b>sample
        panel</b> shall be erected on site and approved in writing by the Architect before
        manufacture is released. <b>The manufacturing lead time is 12 weeks from written
        approval of the sample panel.</b></p>

      <h3>3.3 Operation theatres</h3>
      <p>The two modular operation theatres shall achieve <b>ISO 14644-1 Class 7</b>, with
        a minimum of <b>20 air changes per hour</b> and <b>+15 Pa positive pressure</b>
        relative to adjacent areas. HEPA filters shall be verified by an independent
        agency after installation and before handover.</p>

      <h2>4. Health, safety and environment</h2>
      {hse}

      <h2>5. Completion and handover</h2>
      <h3>5.1 Commissioning</h3>
      <p>All mechanical and electrical systems shall be commissioned to the relevant
        standards. Witnessed commissioning shall be completed not less than 4 weeks before
        the date for completion.</p>
      <h3>5.2 Handover documentation</h3>
      {handover}
      <h3>5.3 Practical completion</h3>
      <p>Practical completion shall not be certified until all commissioning is complete
        and the documentation above has been accepted. The date for completion is
        <b>30 June 2027</b>. {LD_PERCENT_EN} applies thereafter.</p>
    """
    return printer.write(OUT / "06_Tender-Specification.pdf",
                         f"{PROJECT_EN} — Tender Specification", body)


# ── 3. Drawing register ──────────────────────────────────────────────────

def drawing_register(printer: Printer) -> Path:
    table_html = rows_to_table(
        ["Sheet", "Title", "Rev", "Rev date", "Originator", "Status"],
        [list(row) for row in DRAWINGS])
    body = f"""
      <h1>{PROJECT_EN}</h1>
      <h1 style="font-size:15pt;color:#5a636b;font-weight:500">Drawing Register
        &nbsp;·&nbsp; নকশা তালিকা</h1>
      <p class="sub">{CODE} &nbsp;·&nbsp; Current at 14 September 2026</p>
      <p>Drawings issued for construction supersede all earlier revisions. A drawing marked
        'For approval' must not be used for construction. The Contractor shall confirm the
        current revision of any drawing before commencing the work it relates to.</p>
      {table_html}
      <div class="note">
        <b>Note on superseded revisions.</b> Sheet <b>A-201</b> was reissued at
        <b>Revision D</b> on 2 September 2026, relocating the emergency department entrance
        from grid C to grid D. <b>Revision C is superseded</b> and must be withdrawn from
        site. Sheet <b>S-211</b> Revision B incorporates the revised Level 4 and 5
        reinforcement following the loading review of 11 August 2026.
      </div>
    """
    return printer.write(OUT / "07_Drawing-Register.pdf",
                         f"{PROJECT_EN} — Drawing Register", body)


# ── 4. Architectural floor plan ──────────────────────────────────────────

ROOMS = [
    (40, 60, 210, 150, "Reception & Waiting", "অভ্যর্থনা"),
    (250, 60, 180, 150, "Emergency - 12 beds", "জরুরি বিভাগ"),
    (430, 60, 150, 150, "Triage", ""),
    (580, 60, 160, 150, "Pharmacy", ""),
    (40, 210, 140, 130, "Registration", ""),
    (180, 210, 120, 130, "Stair 1", ""),
    (300, 210, 120, 130, "Lift Lobby", ""),
    (420, 210, 160, 130, "Pathology Lab", ""),
    (580, 210, 160, 130, "Radiology / X-ray", ""),
    (40, 340, 200, 140, "OPD Rooms 1-4", "বহির্বিভাগ"),
    (240, 340, 180, 140, "Nurse Station", ""),
    (420, 340, 150, 140, "Toilets", ""),
    (570, 340, 170, 140, "Plant & Electrical", ""),
]


def floor_plan(printer: Printer) -> Path:
    shapes, labels = [], []
    for x, y, w, h, bn, en in ROOMS:
        shapes.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" '
                      f'fill="#f7faf8" stroke="{INK}" stroke-width="2"/>')
        second = (f'<br><span style="color:#5a636b;font-size:10px">{en}</span>'
                  if en else "")
        labels.append(
            f'<div style="position:absolute;left:{x + 8}px;top:{y + 10}px;'
            f'width:{w - 16}px;font-size:11px;line-height:1.35">'
            f'<b>{bn}</b>{second}'
            f'<br><span style="color:#8a939b;font-size:9px">{w * h // 100} m²</span></div>')

    grid = "".join(
        f'<line x1="{40 + i * 140}" y1="40" x2="{40 + i * 140}" y2="500" '
        f'stroke="{ACCENT}" stroke-width="0.8" stroke-dasharray="6 4"/>'
        f'<circle cx="{40 + i * 140}" cy="30" r="12" fill="none" stroke="{ACCENT}"/>'
        f'<text x="{40 + i * 140}" y="34" font-size="12" text-anchor="middle" '
        f'fill="{ACCENT}">{chr(65 + i)}</text>' for i in range(6))

    body = f"""
      <h1 style="font-size:17pt">{PROJECT_EN}</h1>
      <p class="sub">Ground Floor Plan · গ্রাউন্ড ফ্লোর প্ল্যান &nbsp;·&nbsp; A-201
        &nbsp;·&nbsp; Revision D &nbsp;·&nbsp; Scale 1:200 &nbsp;·&nbsp; Sthapatya Sangsad Ltd</p>
      <div style="position:relative;width:780px;height:520px">
        <svg width="780" height="520" style="position:absolute;left:0;top:0">
          <rect x="30" y="50" width="720" height="440" fill="none"
                stroke="{INK}" stroke-width="4"/>
          {grid}
          {''.join(shapes)}
          <path d="M 200 500 L 240 500" stroke="{ACCENT}" stroke-width="5"/>
          <text x="248" y="505" font-size="11" fill="{ACCENT}">Main entrance</text>
          <path d="M 640 500 L 690 500" stroke="{ACCENT}" stroke-width="5"/>
          <text x="470" y="505" font-size="11" fill="{ACCENT}">Ambulance entrance</text>
        </svg>
        {''.join(labels)}
      </div>
      <h2>Notes</h2>
      <ul>
        <li>All dimensions in millimetres; verify on site. Do not scale from this drawing.</li>
        <li>The emergency department entrance moved from grid C to grid D at Revision D.</li>
        <li>Escape routes are a minimum of 1500 mm wide, to BNBC 2020.</li>
        <li>The plant room houses the 600 kVA generator and main switchgear — see E-500.</li>
      </ul>
    """
    return printer.write(OUT / "08_Ground-Floor-Plan.pdf",
                         f"{PROJECT_EN} — Ground Floor Plan A-201", body)




# ── 5. Works programme (Excel) ───────────────────────────────────────────

def works_programme() -> Path:
    book = Workbook()
    sheet = book.active
    sheet.title = "Works Programme"

    sheet["A1"] = f"{PROJECT_EN} — Works Programme"
    sheet["A1"].font = Font(size=14, bold=True, color="1F2933", name=BANGLA_XL)
    sheet["A2"] = (f"Project code {CODE}   ·   Contract sum {taka(CONTRACT_SUM)}"
                   f"   ·   Revision C, issued 14 September 2026")
    sheet["A2"].font = Font(size=10, color="5A636B", name=BANGLA_XL)

    columns = ("Task", "Parent task", "Type", "Trade", "Assignee",
               "Start", "Finish", "Cost (BDT)", "Priority", "Status")
    for index, name in enumerate(columns, start=1):
        cell = sheet.cell(row=4, column=index, value=name)
        cell.fill, cell.font = HEAD_FILL, Font(color="FFFFFF", bold=True, size=11, name=BANGLA_XL)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    for offset, row in enumerate(TASKS):
        name, parent, trade, who, begins, ends, cost, priority, status, kind = row
        line = 5 + offset
        values = (name, parent, kind, trade, who, begins, ends,
                  cost if parent else None, priority, status)
        for index, value in enumerate(values, start=1):
            cell = sheet.cell(row=line, column=index, value=value)
            cell.font = Font(name=BANGLA_XL, bold=not parent)
            if not parent:
                cell.fill = PHASE_FILL
        sheet.cell(row=line, column=8).number_format = '#,##0'

    total = 5 + len(TASKS)
    sheet.cell(row=total, column=7, value="Total (tasks)").font = Font(bold=True, name=BANGLA_XL)
    cell = sheet.cell(row=total, column=8, value=f"=SUM(H5:H{total - 1})")
    cell.font, cell.number_format = Font(bold=True, name=BANGLA_XL), '#,##0'

    sheet.freeze_panes = "A5"
    autosize(sheet, (40, 30, 14, 14, 20, 13, 13, 16, 12, 14))
    path = OUT / "02_Works-Programme.xlsx"
    book.save(path)
    return path


# ── 6. Project team (Excel) ──────────────────────────────────────────────

def project_team() -> Path:
    book = Workbook()
    sheet = book.active
    sheet.title = "Project Team"
    sheet["A1"] = f"{PROJECT_EN} — Project Team and Access"
    sheet["A1"].font = Font(size=14, bold=True, color="1F2933", name=BANGLA_XL)
    sheet["A2"] = "The role type in column E is the access role each person should be granted."
    sheet["A2"].font = Font(size=10, color="5A636B", name=BANGLA_XL)

    columns = ("Full name", "নাম (Bangla)", "Email", "Designation",
               "Role type", "Department", "Mobile")
    for index, name in enumerate(columns, start=1):
        cell = sheet.cell(row=4, column=index, value=name)
        cell.fill, cell.font = HEAD_FILL, Font(color="FFFFFF", bold=True, size=11, name=BANGLA_XL)
        cell.alignment = Alignment(horizontal="center", wrap_text=True)

    for offset, person in enumerate(TEAM):
        for index, value in enumerate(person, start=1):
            sheet.cell(row=5 + offset, column=index, value=value).font = Font(name=BANGLA_XL)

    sheet.freeze_panes = "A5"
    autosize(sheet, (22, 22, 40, 28, 18, 16, 16))

    roles = book.create_sheet("Role Types")
    roles["A1"] = "Role types required on this project"
    roles["A1"].font = Font(size=13, bold=True, name=BANGLA_XL)
    for index, name in enumerate(("Role type", "Description"), start=1):
        cell = roles.cell(row=3, column=index, value=name)
        cell.fill, cell.font = HEAD_FILL, Font(color="FFFFFF", bold=True, name=BANGLA_XL)
    for offset, (name, detail) in enumerate([
            ("Project Manager", "Full project and task control, may approve costs"),
            ("Site Supervisor", "Task status and progress updates, no cost visibility"),
            ("Cost Manager", "Costs and procurement, read-only on tasks"),
            ("Viewer", "Read-only access to the project, no editing")]):
        roles.cell(row=4 + offset, column=1, value=name).font = Font(name=BANGLA_XL)
        roles.cell(row=4 + offset, column=2, value=detail).font = Font(name=BANGLA_XL)
    autosize(roles, (22, 58))

    path = OUT / "03_Project-Team.xlsx"
    book.save(path)
    return path


# ── 7. Procurement schedule (Excel) ──────────────────────────────────────

def procurement_schedule() -> Path:
    book = Workbook()
    sheet = book.active
    sheet.title = "Procurement"
    sheet["A1"] = f"{PROJECT_EN} — Procurement Schedule"
    sheet["A1"].font = Font(size=14, bold=True, color="1F2933", name=BANGLA_XL)
    sheet["A2"] = ("Items still marked Requested whose need-by date falls inside the lead "
                   "time require immediate action.")
    sheet["A2"].font = Font(size=10, color="B4472A", name=BANGLA_XL)

    columns = ("Item", "Supplier", "Trade", "Quantity", "Unit", "Unit cost (BDT)",
               "Status", "Needed by", "Ordered on", "Notes", "Line total (BDT)")
    for index, name in enumerate(columns, start=1):
        cell = sheet.cell(row=4, column=index, value=name)
        cell.fill, cell.font = HEAD_FILL, Font(color="FFFFFF", bold=True, size=11, name=BANGLA_XL)
        cell.alignment = Alignment(horizontal="center", wrap_text=True)

    for offset, row in enumerate(PROCUREMENT):
        for index, value in enumerate(row, start=1):
            cell = sheet.cell(row=5 + offset, column=index, value=value)
            cell.font = Font(name=BANGLA_XL)
            if index == 6:
                cell.number_format = '#,##0'
        total = sheet.cell(row=5 + offset, column=11, value=row[3] * row[5])
        total.number_format, total.font = '#,##0', Font(name=BANGLA_XL)

    sheet.freeze_panes = "A5"
    autosize(sheet, (36, 26, 14, 11, 10, 16, 12, 13, 13, 50, 17))
    path = OUT / "04_Procurement-Schedule.xlsx"
    book.save(path)
    return path


# ── 8. Cost plan (CSV) ───────────────────────────────────────────────────

def cost_plan() -> Path:
    path = OUT / "05_Cost-Plan.csv"
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow([f"{PROJECT_EN} — Elemental Cost Plan"])
        writer.writerow([f"Project code {CODE}", f"Contract sum BDT {CONTRACT_SUM}",
                         crore(CONTRACT_SUM), "Revision C", "14 September 2026"])
        writer.writerow([])
        writer.writerow(["Element", "Description", "Detail", "Amount (BDT)", "Cost type"])
        for row in COSTS:
            writer.writerow(row)
        writer.writerow([])
        writer.writerow(["", "TOTAL", "", sum(row[3] for row in COSTS), ""])
        writer.writerow(["", "Per square metre", "", round(CONTRACT_SUM / GIA_M2), ""])
    return path


# ── 9. Site instruction (Word) ───────────────────────────────────────────

def site_instruction() -> Path:
    doc = Document()
    normal = doc.styles["Normal"]
    normal.font.name = "Nirmala UI"
    normal.font.size = Pt(11)

    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title.add_run(CONTRACTOR_EN)
    run.font.size = Pt(16)
    run.font.bold = True
    run.font.color.rgb = RGBColor(0x1F, 0x29, 0x33)

    sub = doc.add_paragraph()
    sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
    srun = sub.add_run("Site Instruction SI-014")
    srun.font.size = Pt(12)
    srun.font.color.rgb = RGBColor(0x5A, 0x63, 0x6B)

    doc.add_paragraph()
    table = doc.add_table(rows=0, cols=2)
    table.style = "Light Grid Accent 1"
    for key, value in (("Project", PROJECT_EN),
                       ("Project code", CODE),
                       ("Date", "14 September 2026"),
                       ("Issued by", "Imtiaz Rahman, Lead Architect"),
                       ("To", "Md. Rafiqul Islam, Project Director"),
                       ("Related drawings", "A-201 Rev D, A-420 Rev B")):
        cells = table.add_row().cells
        cells[0].text, cells[1].text = key, value

    doc.add_heading("1  Instruction", level=1)
    doc.add_paragraph(
        "The emergency department entrance on the ground floor has been relocated from "
        "grid C to grid D, as shown on drawing A-201 Revision D. The Contractor shall "
        "work to the revised drawing and withdraw Revision C from site.")

    doc.add_heading("2  Reason", level=1)
    doc.add_paragraph(
        "The Fire Service and Civil Defence Directorate review requires direct access "
        "from the ambulance drop-off to the emergency department.")

    doc.add_heading("3  Cost and time impact", level=1)
    doc.add_paragraph(
        "The Contractor shall confirm in writing, within 7 working days, the likely cost "
        "and time impact of this instruction. A preliminary assessment suggests an "
        f"additional {taka(850000)} on internal masonry.")

    doc.add_heading("4  Glazing sample", level=1)
    doc.add_paragraph(
        "The aluminium glazing sample panel has still not been submitted for approval. "
        "Because manufacture takes 12 weeks from written approval, this now sits on the "
        "project's critical path. Please treat it as a priority.")

    path = OUT / "09_Site-Instruction_SI-014.docx"
    doc.save(path)
    return path


# ── 10. Pack README ──────────────────────────────────────────────────────

def readme(paths) -> Path:
    leaves = [row for row in TASKS if row[1]]
    phases = [row for row in TASKS if not row[1]]
    lines = [
        "# Demonstration project pack",
        "",
        f"A complete, fictional Bangladeshi construction project — **{PROJECT_EN}**",
        f"({PROJECT_BN}), {SITE_EN}. Nothing and nobody in it is real.",
        "",
        "Project information in the shape it arrives in a Dhaka site office: money in Taka",
        "with lakh/crore grouping, and the constraints that really bite here — monsoon",
        "casting limits, Friday closure, RAJUK approval, Fire Service clearance and",
        "imported lift lead times. The documents are in English, with a little Bangla where",
        "a real pack would carry it.",
        "",
        "| File | What it is | Demonstrates |",
        "| --- | --- | --- |",
        "| `01_Project-Brief.pdf` | Scope, parties, phases, constraints | PDF ingest, onboarding |",
        f"| `02_Works-Programme.xlsx` | {len(leaves)} tasks across {len(phases)} phases | Task and hierarchy extraction |",
        f"| `03_Project-Team.xlsx` | {len(TEAM)} people and the role each needs | User and role onboarding |",
        f"| `04_Procurement-Schedule.xlsx` | {len(PROCUREMENT)} lines, 2 of them long-lead | Procurement, risk flags |",
        f"| `05_Cost-Plan.csv` | {len(COSTS)}-element cost plan | Project-cost onboarding |",
        "| `06_Tender-Specification.pdf` | 3-page specification with clauses and tables | ColPali retrieval, cited answers |",
        f"| `07_Drawing-Register.pdf` | {len(DRAWINGS)} drawings with revisions and status | Superseded-revision discussion |",
        "| `08_Ground-Floor-Plan.pdf` | Architectural drawing A-201 Rev D | Visual retrieval from a drawing |",
        "| `09_Site-Instruction_SI-014.docx` | Entrance relocation instruction | Word ingest, change tracking |",
        "",
        "## Facts worth asking about",
        "",
        "Each is stated once, in one place, so a cited answer can be checked:",
        "",
        f"* The RFI response period is **{RFI_DAYS} working days** (specification 2.1).",
        "* Slabs are **3500 psi (C25/30)**; piles and pile caps **4000 psi** (3.1).",
        f"* Liquidated damages are **{LD_PERCENT_EN}** (contract particulars).",
        "* Glazing lead time is **12 weeks from sample approval** (3.2).",
        "* Operation theatres must reach **ISO 14644-1 Class 7**, 20 air changes/hour (3.3).",
        "* Noisy works are limited to **09:00–17:00**, and **Friday is closed** (1.1).",
        "* Practical completion is **30 June 2027** (5.3).",
        "* Drawing **A-201 Revision C is superseded**; D is current (drawing register).",
        "",
        "## Consistency",
        "",
        "The cost plan is generated *from* the programme, so the two cannot drift apart:",
        "each construction element is the sum of that phase's tasks, and the contract sum",
        f"({taka(CONTRACT_SUM)} = {crore(CONTRACT_SUM)}) is the sum of the elements.",
        f"Over {GIA_M2:,} m² that is {taka(CONTRACT_SUM / GIA_M2)} per square metre",
        f"(about {taka(CONTRACT_SUM / (GIA_M2 * 10.764))} per sft) — a credible rate for a",
        "specialised hospital.",
        "",
        "Two things are deliberately in trouble, so the analytics have something true to say:",
        "",
        "1. **Glazing sample panel approval** is blocked and past its date, with a 12-week",
        "   lead time behind it, so the envelope phase cannot start.",
        "2. **Lifts** are still Requested against a 16-week import lead time and a March 2027",
        "   need date, so the order-by date has already passed.",
        "",
        "Generated by `scripts/make_demo_pack.py`.",
    ]
    path = OUT / "README.md"
    path.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")
    return path


# ── Proving it reconciles ────────────────────────────────────────────────

def check() -> None:
    """The pack claims to reconcile; prove it before writing anything."""
    for row in TASKS:
        if row[1]:
            continue
        assert row[6] == 0, f"{row[0]}: a summary row must not carry its own cost"
        assert phase_total(row[0]), f"{row[0]}: phase has no tasks"
    parents = {row[0] for row in TASKS if not row[1]}
    for row in TASKS:
        if row[1]:
            assert row[1] in parents, f"{row[0]}: unknown parent {row[1]!r}"
    elements = sum(row[3] for row in COSTS if row[4] == "Construction")
    leaves = sum(row[6] for row in TASKS if row[1])
    assert elements == leaves, f"cost plan {elements:,} != task costs {leaves:,}"
    assert CONTRACT_SUM == sum(row[3] for row in COSTS)

    valid_priorities = {"Low", "Normal", "High", "Urgent"}
    valid_statuses = {"Open", "In Progress", "Blocked", "Completed"}
    valid_procurement = {"Requested", "Quoted", "Ordered", "Delivered", "Cancelled"}
    for row in TASKS:
        assert row[7] in valid_priorities, f"{row[0]}: bad priority {row[7]!r}"
        assert row[8] in valid_statuses, f"{row[0]}: bad status {row[8]!r}"
    for row in PROCUREMENT:
        assert row[6] in valid_procurement, f"{row[0]}: bad status {row[6]!r}"

    # (name, parent, trade, assignee, start, end, cost, priority, status, kind)
    assignees = {person[0] for person in TEAM}
    for row in TASKS:
        assert row[3] in assignees, f"{row[0]}: unknown assignee {row[3]!r}"
        assert row[4] <= row[5], f"{row[0]}: ends before it starts"


if __name__ == "__main__":
    check()
    OUT.mkdir(parents=True, exist_ok=True)
    made = [works_programme(), project_team(), procurement_schedule(),
            cost_plan(), site_instruction()]

    printer = Printer()
    try:
        made += [project_brief(printer), specification(printer),
                 drawing_register(printer), floor_plan(printer)]
    finally:
        printer.close()

    made.append(readme(made))
    for item in sorted(made, key=lambda p: p.name):
        print(f"{item.stat().st_size:>9,}  {item.name}")

    leaves = sum(row[6] for row in TASKS if row[1])
    print(f"\n{len(TASKS)} programme rows = "
          f"{len([r for r in TASKS if not r[1]])} phases + {len([r for r in TASKS if r[1]])} tasks")
    print(f"task costs     {taka(leaves)}  (= construction elements)")
    print(f"contract sum   {taka(CONTRACT_SUM)}  ({crore(CONTRACT_SUM)})")
    print(f"rate           {taka(CONTRACT_SUM / GIA_M2)} per m2 over {GIA_M2:,} m2")
