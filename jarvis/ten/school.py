"""10.0 study and school: study time and streaks, grades and GPA, the class
timetable, assignments and exam countdowns, maths and chemistry tools, tests,
worksheets, writing feedback, and tools for teachers.

The exact things are computed, not asked: GPA, molar masses, balanced
equations, base conversions, geometry, worksheets and their answer keys. The
AI writes only what needs writing (feedback, questions, plans), and shows its
working where it can.
"""

from __future__ import annotations

import math
import random
import re
import time
from datetime import date, datetime, timedelta
from fractions import Fraction
from pathlib import Path

from .. import alerts, kit, reminders, security, shield
from ..registry import command, field, split

G = "Study"
STUDY_LOG = kit.Store("study_log.json", [])
STUDY_GOAL = kit.Store("study_goal.json", {"daily": 60})
GRADES = kit.Store("grades.json", [])
TIMETABLE = kit.Store("timetable.json", [])
ASSIGNMENTS = kit.Store("assignments.json", [])
EXAMS = kit.Store("exams.json", [])
FOCUS_APPS = kit.Store("focus_apps.json", {"apps": ["discord.exe", "steam.exe", "epicgameslauncher.exe",
                                                    "battle.net.exe", "riotclientservices.exe", "spotify.exe"]})
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
DAY_WORDS = {"mon": 0, "monday": 0, "pzt": 0, "pazartesi": 0, "tue": 1, "tuesday": 1, "sal": 1, "salı": 1,
             "wed": 2, "wednesday": 2, "çar": 2, "çarşamba": 2, "thu": 3, "thursday": 3, "per": 3, "perşembe": 3,
             "fri": 4, "friday": 4, "cum": 4, "cuma": 4, "sat": 5, "saturday": 5, "cmt": 5, "cumartesi": 5,
             "sun": 6, "sunday": 6, "paz": 6, "pazar": 6}

# --- study time ---------------------------------------------------------------------------


def log_study(minutes: float, subject: str = "") -> dict:
    entry = {"at": time.time(), "minutes": round(float(minutes), 1), "subject": subject.strip() or "General"}
    log = STUDY_LOG.load()
    log.append(entry)
    STUDY_LOG.save(log[-5000:])
    return entry


def minutes_by_day(log: list[dict], days: int = 7, today: date | None = None) -> list[tuple[date, float]]:
    today = today or date.today()
    out = []
    for back in range(days - 1, -1, -1):
        day = today - timedelta(days=back)
        start = datetime.combine(day, datetime.min.time()).timestamp()
        out.append((day, sum(e["minutes"] for e in log if start <= e["at"] < start + 86400)))
    return out


def streak(log: list[dict], today: date | None = None, minimum: float = 1.0) -> int:
    today = today or date.today()
    studied = {datetime.fromtimestamp(e["at"]).date() for e in log if e.get("minutes", 0) >= minimum}
    count = 0
    day = today if today in studied else today - timedelta(days=1)
    while day in studied:
        count += 1
        day -= timedelta(days=1)
    return count


# --- grades ----------------------------------------------------------------------------------

LETTER_POINTS = {"A+": 4.0, "A": 4.0, "A-": 3.7, "B+": 3.3, "B": 3.0, "B-": 2.7, "C+": 2.3, "C": 2.0, "C-": 1.7,
                 "D+": 1.3, "D": 1.0, "F": 0.0, "AA": 4.0, "BA": 3.5, "BB": 3.0, "CB": 2.5, "CC": 2.0, "DC": 1.5,
                 "DD": 1.0, "FD": 0.5, "FF": 0.0}


def points(grade: str) -> float:
    """A letter (A-, BA) or a 0-100 mark, on the 4-point scale."""
    text = str(grade).strip().upper()
    if text in LETTER_POINTS:
        return LETTER_POINTS[text]
    mark = float(text.replace(",", "."))
    for low, value in ((90, 4.0), (85, 3.5), (80, 3.0), (75, 2.5), (70, 2.0), (65, 1.5), (60, 1.0), (50, 0.5)):
        if mark >= low:
            return value
    return 0.0


def gpa(rows: list[dict]) -> tuple[float, float, float]:
    """(GPA on 4, credit-weighted average of numeric marks, total credits)."""
    credits = sum(float(r.get("credits") or 1) for r in rows) or 1.0
    weighted = sum(points(r["grade"]) * float(r.get("credits") or 1) for r in rows)
    marks = [(float(r["grade"]), float(r.get("credits") or 1)) for r in rows
             if re.fullmatch(r"\d+(?:[.,]\d+)?", str(r["grade"]).strip())]
    average = sum(m * c for m, c in marks) / sum(c for _, c in marks) if marks else 0.0
    return weighted / credits, average, credits


# --- chemistry ----------------------------------------------------------------------------------

MASSES = dict(zip(
    "H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn Ga Ge As Se Br Kr Rb Sr Y Zr "
    "Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe Cs Ba La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir Pt "
    "Au Hg Tl Pb Bi Po At Rn Fr Ra Ac Th Pa U Np Pu".split(),
    [1.008, 4.0026, 6.94, 9.0122, 10.81, 12.011, 14.007, 15.999, 18.998, 20.180, 22.990, 24.305, 26.982, 28.085,
     30.974, 32.06, 35.45, 39.948, 39.098, 40.078, 44.956, 47.867, 50.942, 51.996, 54.938, 55.845, 58.933, 58.693,
     63.546, 65.38, 69.723, 72.630, 74.922, 78.971, 79.904, 83.798, 85.468, 87.62, 88.906, 91.224, 92.906, 95.95, 98.0,
     101.07, 102.91, 106.42, 107.87, 112.41, 114.82, 118.71, 121.76, 127.60, 126.90, 131.29, 132.91, 137.33, 138.91,
     140.12, 140.91, 144.24, 145.0, 150.36, 151.96, 157.25, 158.93, 162.50, 164.93, 167.26, 168.93, 173.05, 174.97,
     178.49, 180.95, 183.84, 186.21, 190.23, 192.22, 195.08, 196.97, 200.59, 204.38, 207.2, 208.98, 209.0, 210.0,
     222.0, 223.0, 226.0, 227.0, 232.04, 231.04, 238.03, 237.0, 244.0]))


class ChemError(ValueError):
    pass


def parse_formula(formula: str) -> dict[str, int]:
    """'Ca(OH)2·2H2O' → {'Ca': 1, 'O': 4, 'H': 6}."""
    formula = formula.strip().replace(" ", "").replace("·", ".").replace("*", ".")
    total: dict[str, int] = {}
    for part in formula.split("."):
        if not part:
            continue
        m = re.match(r"^(\d+)(.*)$", part)
        mult = int(m.group(1)) if m else 1
        body = m.group(2) if m else part
        for element, count in _parse_group(body).items():
            total[element] = total.get(element, 0) + count * mult
    if not total:
        raise ChemError(f"I can't read {formula!r} as a formula.")
    return total


def _parse_group(text: str) -> dict[str, int]:
    stack: list[dict[str, int]] = [{}]
    i = 0
    while i < len(text):
        ch = text[i]
        if ch in "([":
            stack.append({})
            i += 1
        elif ch in ")]":
            i += 1
            m = re.match(r"\d+", text[i:])
            mult = int(m.group(0)) if m else 1
            i += len(m.group(0)) if m else 0
            group = stack.pop()
            if not stack:
                raise ChemError("Brackets don't match.")
            for k, v in group.items():
                stack[-1][k] = stack[-1].get(k, 0) + v * mult
        else:
            m = re.match(r"([A-Z][a-z]?)(\d*)", text[i:])
            if not m:
                raise ChemError(f"Unexpected {text[i]!r} in the formula.")
            element = m.group(1)
            if element not in MASSES:
                raise ChemError(f"{element} is not an element.")
            stack[-1][element] = stack[-1].get(element, 0) + int(m.group(2) or 1)
            i += len(m.group(0))
    if len(stack) != 1:
        raise ChemError("Brackets don't match.")
    return stack[0]


def molar_mass(formula: str) -> tuple[float, list[tuple[str, int, float]]]:
    counts = parse_formula(formula)
    rows = [(el, n, MASSES[el] * n) for el, n in counts.items()]
    return sum(r[2] for r in rows), rows


def balance(equation: str) -> str:
    """'Fe + O2 = Fe2O3' → '4Fe + 3O2 → 2Fe2O3'."""
    import sympy

    text = equation.replace("→", "=").replace("->", "=").replace("=>", "=")
    if "=" not in text:
        raise ChemError("Write it with = or →, e.g. H2 + O2 = H2O")
    left, right = text.split("=", 1)
    lhs = [s.strip() for s in left.split("+") if s.strip()]
    rhs = [s.strip() for s in right.split("+") if s.strip()]
    lhs = [re.sub(r"^\d+\s*", "", s) for s in lhs]
    rhs = [re.sub(r"^\d+\s*", "", s) for s in rhs]
    species = [parse_formula(s) for s in lhs + rhs]
    elements = sorted({e for s in species for e in s})
    matrix = sympy.Matrix([[s.get(e, 0) * (1 if i < len(lhs) else -1) for i, s in enumerate(species)]
                           for e in elements])
    null = matrix.nullspace()
    if not null:
        raise ChemError("That equation can't be balanced — check the formulas.")
    vector = null[0]
    lcm = sympy.ilcm(*[term.q for term in vector])
    coefficients = [int(term * lcm) for term in vector]
    if any(c < 0 for c in coefficients):
        coefficients = [-c for c in coefficients]
    if any(c <= 0 for c in coefficients):
        raise ChemError("That equation can't be balanced with whole numbers — check the formulas.")
    g = math.gcd(*coefficients)
    coefficients = [c // g for c in coefficients]

    def side(names, coefs):
        return " + ".join(f"{c if c != 1 else ''}{n}" for n, c in zip(names, coefs))

    return f"{side(lhs, coefficients[:len(lhs)])} → {side(rhs, coefficients[len(lhs):])}"


# --- maths ---------------------------------------------------------------------------------------

def convert_base(text: str) -> dict[str, str]:
    raw = text.strip().lower().replace("_", "").replace(" ", "")
    base = 10
    m = re.match(r"^(0x|0b|0o)(.+)$", raw)
    if m:
        base = {"0x": 16, "0b": 2, "0o": 8}[m.group(1)]
        raw = m.group(2)
    m = re.match(r"^(.+)\((\d+)\)$", raw) or re.match(r"^(.+)base(\d+)$", raw)
    if m:
        raw, base = m.group(1), int(m.group(2))
    negative = raw.startswith("-")
    value = int(raw.lstrip("-"), base) * (-1 if negative else 1)

    def to(b: int) -> str:
        digits = "0123456789abcdefghijklmnopqrstuvwxyz"
        n = abs(value)
        out = ""
        while True:
            out = digits[n % b] + out
            n //= b
            if n == 0:
                break
        return ("-" if value < 0 else "") + out

    found = {"decimal": str(value), "binary": to(2), "octal": to(8), "hexadecimal": to(16).upper(),
             "base 36": to(36).upper()}
    if -128 <= value < 0:
        found["8-bit two's complement"] = format(value & 0xFF, "08b")
    elif -32768 <= value < 0:
        found["16-bit two's complement"] = format(value & 0xFFFF, "016b")
    return found


SHAPES = {
    "circle": (("r",), lambda r: {"area": math.pi * r * r, "circumference": 2 * math.pi * r}),
    "square": (("a",), lambda a: {"area": a * a, "perimeter": 4 * a, "diagonal": a * math.sqrt(2)}),
    "rectangle": (("a", "b"), lambda a, b: {"area": a * b, "perimeter": 2 * (a + b), "diagonal": math.hypot(a, b)}),
    "triangle": (("a", "b", "c"), None),
    "righttriangle": (("a", "b"), lambda a, b: {"hypotenuse": math.hypot(a, b), "area": a * b / 2,
                                                "perimeter": a + b + math.hypot(a, b)}),
    "trapezoid": (("a", "b", "h"), lambda a, b, h: {"area": (a + b) / 2 * h}),
    "parallelogram": (("b", "h"), lambda b, h: {"area": b * h}),
    "sphere": (("r",), lambda r: {"volume": 4 / 3 * math.pi * r ** 3, "surface": 4 * math.pi * r * r}),
    "cylinder": (("r", "h"), lambda r, h: {"volume": math.pi * r * r * h, "surface": 2 * math.pi * r * (r + h),
                                           "side area": 2 * math.pi * r * h}),
    "cone": (("r", "h"), lambda r, h: {"volume": math.pi * r * r * h / 3,
                                       "surface": math.pi * r * (r + math.hypot(r, h)),
                                       "slant height": math.hypot(r, h)}),
    "cube": (("a",), lambda a: {"volume": a ** 3, "surface": 6 * a * a, "diagonal": a * math.sqrt(3)}),
    "box": (("a", "b", "c"), lambda a, b, c: {"volume": a * b * c, "surface": 2 * (a * b + b * c + a * c),
                                              "diagonal": math.sqrt(a * a + b * b + c * c)}),
    "pyramid": (("base_area", "h"), lambda s, h: {"volume": s * h / 3}),
}
SHAPE_WORDS = {"daire": "circle", "çember": "circle", "kare": "square", "dikdörtgen": "rectangle",
               "üçgen": "triangle", "dik": "righttriangle", "yamuk": "trapezoid", "küre": "sphere",
               "silindir": "cylinder", "koni": "cone", "küp": "cube", "prizma": "box", "piramit": "pyramid",
               "rect": "rectangle", "right": "righttriangle", "cuboid": "box", "prism": "box"}


def geometry(shape: str, values: list[float]) -> dict[str, float]:
    shape = SHAPE_WORDS.get(shape.lower(), shape.lower())
    if shape not in SHAPES:
        raise ValueError(f"Shapes I know: {', '.join(SHAPES)}")
    names, fn = SHAPES[shape]
    if len(values) < len(names):
        raise ValueError(f"A {shape} needs {', '.join(names)}.")
    if shape == "triangle":
        a, b, c = values[:3]
        if a + b <= c or a + c <= b or b + c <= a:
            raise ValueError("Those sides can't make a triangle.")
        s = (a + b + c) / 2
        area = math.sqrt(s * (s - a) * (s - b) * (s - c))
        angle = lambda x, y, z: math.degrees(math.acos((y * y + z * z - x * x) / (2 * y * z)))  # noqa: E731
        return {"area": area, "perimeter": a + b + c, "angle A": angle(a, b, c), "angle B": angle(b, a, c),
                "angle C": angle(c, a, b)}
    return fn(*values[:len(names)])


def plot(functions: list[str], x_min: float = -10, x_max: float = 10, size=(900, 600)):
    """A graph of y = f(x) for each function, as a Pillow image."""
    import numpy as np
    import sympy
    from PIL import Image, ImageDraw

    from ..charts import _font, nice_ticks, short

    x = sympy.symbols("x")
    xs = np.linspace(x_min, x_max, 1200)
    curves = []
    for text in functions:
        expr_text = text.split("=", 1)[1] if "=" in text else text
        from sympy.parsing.sympy_parser import (convert_xor, implicit_multiplication_application, parse_expr,
                                                standard_transformations)

        expr_text = expr_text.replace("√", "sqrt").replace("π", "pi").strip()
        expr = parse_expr(expr_text, local_dict={"ln": sympy.log, "e": sympy.E, "x": x},
                          transformations=standard_transformations + (implicit_multiplication_application, convert_xor))
        f = sympy.lambdify(x, expr, modules=["numpy"])
        with np.errstate(all="ignore"):
            ys = np.asarray(f(xs), dtype=float) * np.ones_like(xs)
        ys[~np.isfinite(ys)] = np.nan
        curves.append((text.strip(), ys))
    finite = np.concatenate([c[1][np.isfinite(c[1])] for c in curves] or [np.array([0.0])])
    if finite.size:
        lo, hi = np.percentile(finite, 2), np.percentile(finite, 98)
    else:
        lo, hi = -10, 10
    if hi - lo < 1e-9:
        lo, hi = lo - 1, hi + 1
    pad = (hi - lo) * 0.1
    y_min, y_max = lo - pad, hi + pad
    s = 2
    w, h = size[0] * s, size[1] * s
    image = Image.new("RGB", (w, h), "white")
    draw = ImageDraw.Draw(image)
    left, right, top, bottom = 60 * s, w - 20 * s, 20 * s, h - 40 * s

    def px(xv):
        return left + (xv - x_min) / (x_max - x_min) * (right - left)

    def py(yv):
        return bottom - (yv - y_min) / (y_max - y_min) * (bottom - top)

    font = _font(14 * s)
    for t in nice_ticks(x_min, x_max, 10):
        if x_min <= t <= x_max:
            draw.line((px(t), top, px(t), bottom), fill="#eceff4", width=s)
            draw.text((px(t), bottom + 6 * s), short(t), fill="#555", font=font, anchor="ma")
    for t in nice_ticks(y_min, y_max, 8):
        if y_min <= t <= y_max:
            draw.line((left, py(t), right, py(t)), fill="#eceff4", width=s)
            draw.text((left - 6 * s, py(t)), short(t), fill="#555", font=font, anchor="rm")
    if x_min <= 0 <= x_max:
        draw.line((px(0), top, px(0), bottom), fill="#333", width=2 * s)
    if y_min <= 0 <= y_max:
        draw.line((left, py(0), right, py(0)), fill="#333", width=2 * s)
    colours = ["#1f6feb", "#e5534b", "#2da44e", "#a371f7", "#d29922"]
    for k, (label, ys) in enumerate(curves):
        colour = colours[k % len(colours)]
        segment = []
        for xv, yv in zip(xs, ys):
            if np.isfinite(yv) and y_min - (y_max - y_min) <= yv <= y_max + (y_max - y_min):
                segment.append((px(xv), py(yv)))
            else:
                if len(segment) > 1:
                    draw.line(segment, fill=colour, width=3 * s)
                segment = []
        if len(segment) > 1:
            draw.line(segment, fill=colour, width=3 * s)
        draw.text((left + 12 * s, top + (10 + 22 * k) * s), f"y = {label.split('=')[-1].strip()}", fill=colour,
                  font=_font(16 * s, True))
    return image.reduce(s)


def worksheet(topic: str, level: str = "easy", count: int = 20, seed: int | None = None) -> list[tuple[str, str]]:
    """Problems with answers, made by rule — every answer is right."""
    rng = random.Random(seed)
    big = {"easy": 10, "medium": 100, "hard": 1000}.get(level, 10)
    problems: list[tuple[str, str]] = []
    topic = topic.lower()
    for _ in range(count):
        if topic.startswith(("add", "topla")):
            a, b = rng.randint(1, big), rng.randint(1, big)
            problems.append((f"{a} + {b} =", str(a + b)))
        elif topic.startswith(("sub", "çıkar")):
            a, b = sorted((rng.randint(1, big), rng.randint(1, big)), reverse=True)
            problems.append((f"{a} − {b} =", str(a - b)))
        elif topic.startswith(("mul", "times", "çarp")):
            top = {"easy": 10, "medium": 12, "hard": 99}.get(level, 10)
            a, b = rng.randint(2, top), rng.randint(2, 12 if level != "hard" else top)
            problems.append((f"{a} × {b} =", str(a * b)))
        elif topic.startswith(("div", "böl")):
            top = {"easy": 10, "medium": 12, "hard": 25}.get(level, 10)
            b, q = rng.randint(2, top), rng.randint(2, top)
            problems.append((f"{b * q} ÷ {b} =", str(q)))
        elif topic.startswith(("frac", "kesir")):
            d = {"easy": 6, "medium": 10, "hard": 16}.get(level, 6)
            f1, f2 = Fraction(rng.randint(1, d), rng.randint(2, d)), Fraction(rng.randint(1, d), rng.randint(2, d))
            op = rng.choice("+−×")
            value = f1 + f2 if op == "+" else f1 - f2 if op == "−" else f1 * f2
            problems.append((f"{f1} {op} {f2} =", str(value)))
        elif topic.startswith(("equ", "denk", "linear")):
            a = rng.randint(2, 9 if level == "easy" else 15)
            x = rng.randint(-10, 12)
            b = rng.randint(-20, 20)
            problems.append((f"{a}x {'+' if b >= 0 else '−'} {abs(b)} = {a * x + b}", f"x = {x}"))
        elif topic.startswith(("percent", "yüzde")):
            p = rng.choice([5, 10, 15, 20, 25, 30, 40, 50, 75])
            n = rng.randint(2, 40) * 10
            problems.append((f"{p}% of {n} =", f"{p * n / 100:g}"))
        else:
            raise ValueError("Topics: addition, subtraction, multiplication, division, fractions, equations, percent")
    return problems


def worksheet_pdf(title: str, problems: list[tuple[str, str]]) -> Path:
    from fpdf import FPDF

    from .office import _latin

    pdf = FPDF()
    pdf.set_auto_page_break(True, 15)
    pdf.add_page()
    pdf.set_font("helvetica", "B", 18)
    pdf.cell(0, 12, _latin(title), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("helvetica", size=10)
    pdf.cell(0, 8, "Name: ______________________    Date: ____________    Score: ____ / " + str(len(problems)),
             new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    pdf.set_font("helvetica", size=14)
    half = (len(problems) + 1) // 2
    for i in range(half):
        left = f"{i + 1}.  {_ascii(problems[i][0])}  ______"
        right = f"{i + 1 + half}.  {_ascii(problems[i + half][0])}  ______" if i + half < len(problems) else ""
        pdf.cell(95, 12, left)
        pdf.cell(95, 12, right, new_x="LMARGIN", new_y="NEXT")
    pdf.add_page()
    pdf.set_font("helvetica", "B", 16)
    pdf.cell(0, 12, "Answer key", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("helvetica", size=12)
    for i, (_q, a) in enumerate(problems, 1):
        pdf.cell(0, 8, f"{i}.  {_ascii(a)}", new_x="LMARGIN", new_y="NEXT")
    path = kit.output_dir("documents") / f"worksheet_{kit.slug(title)}_{kit.stamp()}.pdf"
    pdf.output(str(path))
    return path


def _ascii(text: str) -> str:
    from .office import _latin

    return _latin(text.replace("−", "-").replace("×", "x").replace("÷", "/"))


# --- spelling ----------------------------------------------------------------------------------

SPELLING = {
    "easy": "apple friend school because people water house happy little bird garden family yellow window "
            "orange pencil summer winter animal sister brother doctor",
    "medium": "beautiful necessary separate believe February library environment government restaurant tomorrow "
              "knowledge calendar exercise surprise address beginning committee definitely Wednesday rhythm",
    "hard": "accommodate conscientious embarrass entrepreneur fluorescent maintenance millennium mischievous "
            "occurrence pharaoh questionnaire rhythm surveillance unnecessary bureaucracy chrysanthemum "
            "onomatopoeia pneumonia silhouette",
    "tr": "öğretmen kütüphane şemsiye çiçekçi bilgisayar yağmurluk gökkuşağı ayakkabı sözcük çikolata "
          "buzdolabı kahvaltı penguen yeryüzü değerlendirme",
}


class School:
    # --- study time -------------------------------------------------------------------------
    @command("studylog", "studied", group=G, usage="/studylog <minutes> [subject] · /studylog",
             help="log study time (the Pomodoro timer does it for you)", title="Log study time", icon="⏱",
             page="study", fields=(field("minutes", "number", "Minutes", "25"),
                                   field("subject", "text", "Subject", optional=True)))
    def studylog_cmd(self, args: str, routed: bool = False):
        text = args.replace("|", " ").strip()
        m = re.match(r"(\d+(?:\.\d+)?)\s*(?:m|min|minutes|dk)?\s*(.*)$", text)
        if not m:
            return self.studyreport_cmd("")
        log_study(float(m.group(1)), m.group(2))
        log = STUDY_LOG.load()
        today = minutes_by_day(log, 1)[0][1]
        goal = STUDY_GOAL.load().get("daily", 60)
        return f"⏱ Logged {float(m.group(1)):g} min. Today: {today:g}/{goal} min · streak {streak(log)} day(s)."

    @command("studygoal", group=G, usage="/studygoal <minutes a day>", help="your daily study goal",
             title="Daily study goal", icon="🎯", page="study", fields=(field("minutes", "number", "Minutes a day", "60"),))
    def studygoal_cmd(self, args: str, routed: bool = False):
        m = re.search(r"\d+", args)
        if not m:
            return f"Your daily goal is {STUDY_GOAL.load().get('daily', 60)} minutes. /studygoal 90 changes it."
        STUDY_GOAL.save({"daily": int(m.group(0))})
        return f"🎯 Daily study goal: {int(m.group(0))} minutes."

    @command("studyreport", group=G, usage="/studyreport", help="your study week: minutes per day and subject, streak",
             title="Weekly study report", icon="📈", page="study")
    def studyreport_cmd(self, args: str, routed: bool = False):
        from .. import charts

        log = STUDY_LOG.load()
        days = minutes_by_day(log, 7)
        total = sum(m for _, m in days)
        week_start = datetime.combine(days[0][0], datetime.min.time()).timestamp()
        subjects: dict[str, float] = {}
        for e in log:
            if e["at"] >= week_start:
                subjects[e["subject"]] = subjects.get(e["subject"], 0) + e["minutes"]
        goal = STUDY_GOAL.load().get("daily", 60)
        hit = sum(1 for _, m in days if m >= goal)
        lines = [f"📈 Study this week: {total / 60:.1f} h · streak {streak(log)} day(s) · goal met {hit}/7 days"]
        lines += [f"  {d:%a %d}  {'█' * int(min(20, m / max(1, goal) * 10))} {m:g} min" for d, m in days]
        if subjects:
            lines.append("By subject: " + ", ".join(f"{s} {m / 60:.1f} h" for s, m in
                                                  sorted(subjects.items(), key=lambda x: -x[1])))
        image = charts.render("column", [f"{d:%a}" for d, _ in days], {"Minutes": [m for _, m in days]},
                              title="Study minutes this week", size=(800, 420))
        path = kit.output_dir("documents") / f"study-week_{kit.stamp()}.png"
        image.save(path)
        lines.append(str(path))
        return "\n".join(lines)

    # --- grades -------------------------------------------------------------------------------
    @command("grade", "grades", "gpa", group=G, usage="/grade add <course> | <grade or mark> | <credits> · /gpa",
             help="your grades with GPA (4.0) and a credit-weighted average", title="Grade tracker and GPA", icon="🅰",
             page="study", fields=(field("course", "text", "Course"), field("grade", "text", "Grade (A-, BA or 0-100)"),
                                   field("credits", "number", "Credits", "3")),
             template="add {course} | {grade} | {credits}")
    def grade_cmd(self, args: str, routed: bool = False):
        text = args.strip()
        rows = GRADES.load()
        verb, _, rest = text.partition(" ")
        if verb.lower() == "add":
            course, grade, credits = split(rest, 3)
            if not course or not grade:
                return "Usage: /grade add Calculus | 85 | 4"
            try:
                points(grade)
                credit_value = float(credits or 1)
            except ValueError:
                return "A grade is a letter (A-, BB) or a mark from 0 to 100; credits is a number."
            rows.append({"course": course, "grade": grade.strip(), "credits": credit_value, "at": time.time()})
            GRADES.save(rows)
        elif verb.lower() in {"delete", "remove"} and rest.strip().isdigit():
            index = int(rest) - 1
            if 0 <= index < len(rows):
                rows.pop(index)
                GRADES.save(rows)
        if not rows:
            return "No grades yet. /grade add Calculus | 85 | 4"
        four, average, credits = gpa(rows)
        lines = ["🅰 Your grades:"] + [f"  {i}. {r['course']}: {r['grade']} ({r.get('credits', 1):g} cr) → "
                                      f"{points(r['grade']):.1f}" for i, r in enumerate(rows, 1)]
        lines.append(f"GPA {four:.2f} / 4.00 over {credits:g} credits" +
                     (f" · weighted average {average:.1f} / 100" if average else ""))
        return "\n".join(lines)

    # --- timetable ------------------------------------------------------------------------------
    @command("timetable", "classes", "dersprogramı", group=G,
             usage="/timetable add mon 09:00-10:30 Maths @ B12 · /timetable · /timetable next",
             help="your weekly class timetable, and what's next", title="Class timetable", icon="🗓", page="study",
             fields=(field("day", "choice", "Day", "mon", tuple(DAYS)), field("time", "text", "Time", "09:00-10:30"),
                     field("subject", "text", "Subject"), field("room", "text", "Room", optional=True)),
             template="add {day} {time} {subject} @ {room}")
    def timetable_cmd(self, args: str, routed: bool = False):
        text = args.strip()
        rows = TIMETABLE.load()
        verb, _, rest = text.partition(" ")
        if verb.lower() == "add":
            m = re.match(r"(\w+)\s+(\d{1,2}[:.]\d{2})\s*[-–]\s*(\d{1,2}[:.]\d{2})\s+(.+?)(?:\s*@\s*(.*))?$", rest.strip())
            if not m or m.group(1).lower() not in DAY_WORDS:
                return "Usage: /timetable add mon 09:00-10:30 Maths @ B12"
            rows.append({"day": DAY_WORDS[m.group(1).lower()], "start": m.group(2).replace(".", ":"),
                         "end": m.group(3).replace(".", ":"), "subject": m.group(4).strip(),
                         "room": (m.group(5) or "").strip()})
            rows.sort(key=lambda r: (r["day"], r["start"]))
            TIMETABLE.save(rows)
            return f"🗓 Added {m.group(4).strip()} on {DAYS[DAY_WORDS[m.group(1).lower()]].capitalize()}."
        if verb.lower() in {"clear"}:
            TIMETABLE.save([])
            return "Timetable cleared."
        if not rows:
            return "No classes yet. /timetable add mon 09:00-10:30 Maths @ B12"
        if verb.lower() == "next":
            now = datetime.now()
            for offset in range(8):
                day = (now.weekday() + offset) % 7
                for r in rows:
                    if r["day"] == day and (offset or r["start"] > now.strftime("%H:%M")):
                        when = "today" if offset == 0 else "tomorrow" if offset == 1 else DAYS[day].capitalize()
                        return f"Next: {r['subject']} {when} at {r['start']}" + (f" in {r['room']}" if r["room"] else "")
        lines = ["🗓 Timetable:"]
        for d in range(7):
            today = [r for r in rows if r["day"] == d]
            if today:
                lines.append(f"  {DAYS[d].capitalize()}: " + " · ".join(
                    f"{r['start']}-{r['end']} {r['subject']}" + (f" ({r['room']})" if r["room"] else "") for r in today))
        return "\n".join(lines)

    # --- assignments and exams ---------------------------------------------------------------------
    @command("assignment", "assignments", "ödev", group=G, usage="/assignment add <title> | <subject> | <due date> · /assignments · /assignment done <n>",
             help="homework and assignments with due dates (reminded the day before)", title="Assignment tracker",
             icon="📚", page="study", fields=(field("title", "text", "What"), field("subject", "text", "Subject"),
                                              field("due", "text", "Due", hint="friday 23:59 or 2026-10-20")),
             template="add {title} | {subject} | {due}")
    def assignment_cmd(self, args: str, routed: bool = False):
        from ..life import parse_when

        text = args.strip()
        rows = ASSIGNMENTS.load()
        verb, _, rest = text.partition(" ")
        if verb.lower() == "add":
            title, subject, due_text = split(rest, 3)
            due, _ = parse_when(due_text, default_hour=23) if due_text else (None, "")
            if not title:
                return "Usage: /assignment add Essay | English | friday"
            rows.append({"title": title, "subject": subject, "due": due.timestamp() if due else 0, "done": False})
            ASSIGNMENTS.save(rows)
            if due and due.timestamp() - 86400 > time.time():
                reminders.board.add("reminder", f"Due tomorrow: {title}", due.timestamp() - 86400)
            return f"📚 Added {title}" + (f", due {due:%a %d %b %H:%M}" if due else "") + "."
        if verb.lower() == "done" and rest.strip().isdigit():
            open_rows = [r for r in rows if not r.get("done")]
            index = int(rest) - 1
            if 0 <= index < len(open_rows):
                open_rows[index]["done"] = True
                ASSIGNMENTS.save(rows)
                return f"✔ {open_rows[index]['title']} done."
        open_rows = sorted((r for r in rows if not r.get("done")), key=lambda r: r.get("due") or 9e12)
        if not open_rows:
            return "No assignments due. 🎉 /assignment add <title> | <subject> | <due>"
        lines = ["📚 Assignments:"]
        for i, r in enumerate(open_rows, 1):
            due = r.get("due") or 0
            left = f" — {max(0, int((due - time.time()) // 86400))} day(s) left" if due else ""
            late = " ⚠ late" if due and due < time.time() else ""
            lines.append(f"  {i}. {r['title']} ({r.get('subject') or '—'})" +
                         (f", due {datetime.fromtimestamp(due):%a %d %b}" if due else "") + left + late)
        return "\n".join(lines)

    @command("exam", "exams", "sınav", group=G, usage="/exam add <name> | <date> · /exams",
             help="exam countdowns", title="Exam countdowns", icon="⏳", page="study",
             fields=(field("name", "text", "Exam"), field("date", "date", "Date")), template="add {name} | {date}")
    def exam_cmd(self, args: str, routed: bool = False):
        text = args.strip()
        rows = EXAMS.load()
        verb, _, rest = text.partition(" ")
        if verb.lower() == "add":
            name, when = split(rest, 2)
            try:
                day = date.fromisoformat(when.strip())
            except ValueError:
                from ..life import parse_when

                moment, _ = parse_when(when)
                if moment is None:
                    return "Usage: /exam add YKS | 2027-06-19"
                day = moment.date()
            rows.append({"name": name, "date": day.isoformat()})
            rows.sort(key=lambda r: r["date"])
            EXAMS.save(rows)
        elif verb.lower() in {"delete", "remove"} and rest.strip().isdigit():
            index = int(rest) - 1
            if 0 <= index < len(rows):
                rows.pop(index)
                EXAMS.save(rows)
        upcoming = [r for r in rows if date.fromisoformat(r["date"]) >= date.today()]
        if not upcoming:
            return "No exams coming up. /exam add YKS | 2027-06-19"
        return "⏳ Exams:\n" + "\n".join(
            f"  {i}. {r['name']}: {(date.fromisoformat(r['date']) - date.today()).days} day(s) "
            f"({date.fromisoformat(r['date']):%d %b %Y})" for i, r in enumerate(upcoming, 1))

    @command("focusapps", group=G, usage="/focusapps · /focusapps add <app.exe> · /focusapps remove <app.exe> · /focusapps close",
             help="apps to close while you study (asks before closing)", title="Close distracting apps", icon="🚫",
             page="study", fields=(field("action", "text", "add discord.exe · remove steam.exe · close", optional=True),))
    def focusapps_cmd(self, args: str, routed: bool = False):
        import psutil

        text = args.strip()
        data = FOCUS_APPS.load()
        apps = [a.lower() for a in data.get("apps", [])]
        verb, _, rest = text.partition(" ")
        name = rest.strip().lower()
        if name and not name.endswith(".exe"):
            name += ".exe"
        if verb.lower() == "add" and name:
            apps = sorted(set(apps) | {name})
            FOCUS_APPS.save({"apps": apps})
            return f"🚫 Will close {name} during study sessions."
        if verb.lower() == "remove" and name:
            apps = [a for a in apps if a != name]
            FOCUS_APPS.save({"apps": apps})
            return f"OK — {name} stays open."
        if verb.lower() == "close":
            running = [p for p in psutil.process_iter(["name"]) if (p.info.get("name") or "").lower() in apps]
            if not running:
                return "None of your distracting apps are running. 👍"
            names = sorted({p.info["name"] for p in running})
            if not security.permissions.ask(security.RUN_COMMAND, "close " + ", ".join(names), context="/focusapps"):
                return "Left them open."
            for p in running:
                try:
                    p.terminate()
                except Exception:
                    pass
            security.audit.record("focusapps", ", ".join(names))
            return f"🚫 Closed {', '.join(names)}. Focus time."
        return "🚫 Closed during study sessions: " + (", ".join(apps) or "none") + \
            "\n/focusapps add <app.exe> · /focusapps remove <app.exe> · /focusapps close"

    # --- maths and science ---------------------------------------------------------------------------
    @command("plot", "graph", group=G, usage="/plot y = x^2 - 3x ; y = sin(x) | [-10, 10]",
             help="graphs of functions", title="Graph plotter", icon="📉", page="study",
             fields=(field("functions", "text", "y = … (separate several with ;)", "y = x^2 - 3x"),
                     field("range", "text", "x from, to", "-10, 10")))
    def plot_cmd(self, args: str, routed: bool = False):
        functions, span = split(args, 2)
        if not functions:
            return "Usage: /plot y = x^2 - 3x ; y = sin(x) | -10, 10"
        try:
            low, high = (float(v) for v in re.findall(r"-?\d+(?:\.\d+)?", span)[:2]) if span else (-10.0, 10.0)
        except ValueError:
            low, high = -10.0, 10.0
        try:
            image = plot([f for f in functions.split(";") if f.strip()], min(low, high), max(low, high))
        except Exception as exc:
            return f"I couldn't draw that: {exc}"
        path = kit.output_dir("documents") / f"graph_{kit.stamp()}.png"
        image.save(path)
        return f"📉 {functions}\n{path}"

    @command("geometry", "geo", group=G, usage="/geometry <shape> <values>   e.g. /geometry cylinder 3 10",
             help="area, perimeter, volume and more for common shapes", title="Geometry helper", icon="📐",
             page="study", fields=(field("shape", "choice", "Shape", "circle", tuple(SHAPES)),
                                   field("values", "text", "Measurements", hint="circle: r · rectangle: a b · "
                                                                               "triangle: a b c · cylinder: r h")),
             template="{shape} {values}")
    def geometry_cmd(self, args: str, routed: bool = False):
        parts = args.replace("|", " ").replace(",", " ").split()
        if not parts:
            return "Usage: /geometry <shape> <values>. Shapes: " + ", ".join(SHAPES)
        try:
            values = [float(v) for v in parts[1:]]
            result = geometry(parts[0], values)
        except ValueError as exc:
            return str(exc)
        shape = SHAPE_WORDS.get(parts[0].lower(), parts[0].lower())
        names = SHAPES[shape][0]
        given = ", ".join(f"{n} = {v:g}" for n, v in zip(names, values))
        return f"📐 {shape} ({given}):\n" + "\n".join(f"  {k}: {v:,.4f}".rstrip("0").rstrip(".") +
                                                    ("°" if k.startswith("angle") else "") for k, v in result.items())

    @command("base", "bases", group=G, usage="/base 255 · /base 0xff · /base 1011b(2)",
             help="a number in binary, octal, decimal and hex", title="Number base converter", icon="🔣", page="study",
             fields=(field("number", "text", "Number", hint="255 · 0xff · 0b1011 · 777(8)"),))
    def base_cmd(self, args: str, routed: bool = False):
        try:
            found = convert_base(args)
        except ValueError:
            return "Usage: /base 255 · /base 0xff · /base 0b1011 · /base 777(8)"
        return "🔣 " + "\n   ".join(f"{k}: {v}" for k, v in found.items())

    @command("balance", group=G, usage="/balance Fe + O2 = Fe2O3", help="balances a chemical equation",
             title="Balance chemical equations", icon="⚗", page="study",
             fields=(field("equation", "text", "Equation", "C3H8 + O2 = CO2 + H2O"),), keywords="chemistry kimya denklem")
    def balance_cmd(self, args: str, routed: bool = False):
        if not args.strip():
            return "Usage: /balance C3H8 + O2 = CO2 + H2O"
        try:
            return f"⚗ {balance(args)}"
        except (ChemError, ValueError) as exc:
            return str(exc)

    @command("molar", "molarmass", group=G, usage="/molar H2SO4", help="molar mass with a breakdown by element",
             title="Molar mass calculator", icon="🧪", page="study", fields=(field("formula", "text", "Formula", "H2SO4"),),
             keywords="chemistry mol kütle")
    def molar_cmd(self, args: str, routed: bool = False):
        if not args.strip():
            return "Usage: /molar H2SO4"
        try:
            total, rows = molar_mass(args)
        except ChemError as exc:
            return str(exc)
        return (f"🧪 {args.strip()}: {total:.3f} g/mol\n" + "\n".join(
            f"  {el} × {n}: {mass:.3f} ({100 * mass / total:.1f}%)" for el, n, mass in rows))

    @command("biodiagram", "diagramimage", group=G, usage="/biodiagram <cell|heart|leaf|…>",
             help="a labelled diagram from Wikimedia Commons (with its licence)", title="Labelled biology diagrams",
             icon="🫀", page="study", fields=(field("topic", "text", "Topic", "animal cell"),))
    def biodiagram_cmd(self, args: str, routed: bool = False):
        import urllib.request

        from .. import net

        topic = args.strip()
        if not topic:
            return "Usage: /biodiagram animal cell"
        try:
            data = kit.get_json("https://commons.wikimedia.org/w/api.php", {
                "action": "query", "format": "json", "generator": "search", "gsrnamespace": 6, "gsrlimit": 8,
                "gsrsearch": f"{topic} diagram labeled", "prop": "imageinfo", "iiprop": "url|extmetadata|mime",
                "iiurlwidth": 1600})
        except kit.KitError as exc:
            return f"Wikimedia Commons didn't answer: {exc}"
        pages = sorted((data.get("query") or {}).get("pages", {}).values(), key=lambda p: p.get("index", 99))
        for page in pages:
            info = (page.get("imageinfo") or [{}])[0]
            if info.get("mime") not in {"image/png", "image/jpeg", "image/svg+xml"}:
                continue
            url = info.get("thumburl") or info.get("url")
            meta = info.get("extmetadata") or {}
            licence = (meta.get("LicenseShortName") or {}).get("value", "see the file page")
            artist = re.sub(r"<[^>]+>", "", (meta.get("Artist") or {}).get("value", "")).strip()
            path = kit.output_dir("documents") / f"diagram_{kit.slug(topic)}_{kit.stamp()}.png"
            try:
                request = urllib.request.Request(url, headers={"User-Agent": net.DEFAULT_USER_AGENT})
                with net.urlopen(request, timeout=30) as response:
                    path.write_bytes(response.read())
            except Exception:
                continue
            return (f"🫀 {page.get('title', '').replace('File:', '')}\n{path}\n"
                    f"Licence: {licence}" + (f" · by {artist[:80]}" if artist else "") +
                    f"\nSource: https://commons.wikimedia.org/wiki/{page.get('title', '').replace(' ', '_')}")
        return f"No labelled diagram of {topic} found on Wikimedia Commons."

    # --- tests and practice ------------------------------------------------------------------------
    def _source(self, text: str) -> tuple[str, str]:
        from .office import text_of

        if kit.path_arg(text) is not None:
            path = kit.path_arg(text)
            if not security.permissions.ask(security.READ_FILE, str(path), context="study"):
                raise PermissionError("Denied. The file was not read.")
            return text_of(text)
        return "", text

    @command("practicetest", "testmaker", group=G, usage="/practicetest <topic or file> | [20 questions] | [mixed]",
             help="a printable practice test with an answer key, from your notes or a topic", title="Practice test",
             icon="📝", page="study",
             fields=(field("source", "text", "Topic, or your notes file", hint="photosynthesis · C:\\notes.pdf"),
                     field("count", "number", "Questions", "15"),
                     field("kind", "choice", "Question types", "mixed", ("mixed", "multiple choice", "true/false",
                                                                          "short answer"))))
    def practicetest_cmd(self, args: str, routed: bool = False):
        source, count, kind = split(args, 3)
        if not source:
            return "Usage: /practicetest <topic or file> | 15 | mixed"
        try:
            label, material = self._source(source)
        except PermissionError as exc:
            return str(exc)
        wrapped = shield.wrap(material[:40000], label)[0] if label else ""
        n = max(3, min(50, int(count or 15)))
        with kit.more_room(self.brain):
            data = kit.ask_json(self.brain, (
                f"Write a practice test with {n} {kind or 'mixed'} questions "
                + (f"based only on this material:\n{shield.RULE}\n{wrapped}\n" if label else f"about: {material}\n")
                + "JSON only: {\"title\": str, \"questions\": [{\"type\": \"mc\"|\"tf\"|\"short\", \"q\": str, "
                  "\"options\": [4 strings, mc only], \"answer\": str}]}"))
        questions = data.get("questions") if isinstance(data, dict) else None
        if not questions:
            return "No test came back — try again or with more notes."
        title = data.get("title") or f"Practice test: {label or material}"
        lines = [f"# {title}", "", "Name: ____________________   Date: __________", ""]
        key = ["", "## Answer key", ""]
        for i, q in enumerate(questions, 1):
            lines.append(f"**{i}.** {q.get('q')}")
            if q.get("type") == "mc":
                lines += [f"   {chr(65 + j)}) {o}" for j, o in enumerate(q.get("options", [])[:4])]
            elif q.get("type") == "tf":
                lines.append("   True / False")
            else:
                lines.append("   ________________________________________")
            lines.append("")
            key.append(f"{i}. {q.get('answer')}")
        from .. import writer

        paths = writer.save("\n".join(lines + key), ("docx", "pdf"))
        return f"📝 {title} — {len(questions)} questions with an answer key\n" + "\n".join(f"  {p}" for p in paths)

    @command("ytquiz", group=G, usage="/ytquiz <YouTube link>", help="a quiz on a YouTube video, in the chat",
             title="Quiz from a YouTube video", icon="▶", page="study", chat=True,
             fields=(field("url", "text", "YouTube link"),))
    def ytquiz_cmd(self, args: str, routed: bool = False):
        url = args.strip()
        if "youtu" not in url:
            return "Usage: /ytquiz <YouTube link>"
        try:
            from .. import youtube

            transcript = youtube.transcript_text(url) if hasattr(youtube, "transcript_text") else None
        except Exception as exc:
            return f"I couldn't get that video's captions: {exc}"
        if not transcript:
            try:
                from youtube_transcript_api import YouTubeTranscriptApi

                video = re.search(r"(?:v=|youtu\.be/|shorts/)([\w-]{11})", url).group(1)
                fetched = YouTubeTranscriptApi().fetch(video, languages=["en", "tr", "de", "fr", "es"])
                transcript = " ".join(s.text for s in fetched)
            except Exception as exc:
                return f"That video has no captions I can read ({type(exc).__name__})."
        path = kit.output_dir("documents") / f"video-transcript_{kit.stamp()}.txt"
        path.write_text(transcript, encoding="utf-8")
        return self.start_quiz(str(path))

    @command("lecturenotes", group=G, usage="/lecturenotes <audio file>",
             help="notes (Word) from a recording you already have", title="Lecture recording to notes", icon="🎙",
             page="study", fields=(field("file", "file", "Recording", types=(("Audio", "*.mp3 *.m4a *.wav *.wma *.aac"),)),))
    def lecturenotes_cmd(self, args: str, routed: bool = False):
        from .. import audiofile, recorder, winrt, writer

        path = kit.path_arg(args)
        if path is None or not path.is_file():
            return "Usage: /lecturenotes <audio file>   (to record live: /record)"
        if not self.voice.stt_available():
            return "Nothing can transcribe speech yet: add a GROQ_API_KEY (free) in Settings."
        if not security.permissions.ask(security.READ_FILE, str(path), context="/lecturenotes"):
            return "Denied."
        try:
            transcript = audiofile.transcribe(self.voice, path)
        except (winrt.WinRTError, RuntimeError) as exc:
            return f"Couldn't transcribe it: {exc}"
        if not transcript.strip():
            return "I couldn't hear any speech in that recording."
        with kit.more_room(self.brain, 8000):
            answer = self.brain.ask_once(recorder.NOTES_PROMPT.format(transcript=transcript[:150_000]))
        markdown = writer.clean_markdown(answer) + f"\n\n---\n\n## Transcript\n\n{transcript}\n"
        paths = writer.save(markdown, ("docx",))
        return f"🎙 Notes from {path.name} ({len(transcript.split()):,} words heard):\n" + \
            "\n".join(f"  {p}" for p in paths)

    @command("formulasheet", "cheatsheet", group=G, usage="/formulasheet <subject or topic>",
             help="a one-page formula sheet (Word and PDF)", title="Formula sheet maker", icon="∑", page="study",
             fields=(field("topic", "text", "Subject or topic", "trigonometry"),))
    def formulasheet_cmd(self, args: str, routed: bool = False):
        topic = args.strip()
        if not topic:
            return "Usage: /formulasheet <topic>"
        return self.make_document(
            f"a one-page formula sheet for {topic}: grouped headings, each formula on its own line in plain "
            "text maths (x² , √, ∫, Σ, π), with a 3-6 word note of what it is for and units. No long prose.",
            ("docx", "pdf"))

    # --- writing -------------------------------------------------------------------------------
    @command("essaygrade", group=G, usage="/essaygrade <essay text or file> | [level, e.g. 10th grade]",
             help="a grade with a rubric, strengths and what to fix", title="Essay grader with feedback", icon="🖍",
             page="study", fields=(field("essay", "long", "Essay text or file"),
                                   field("level", "text", "Level", "high school", optional=True)))
    def essaygrade_cmd(self, args: str, routed: bool = False):
        essay, level = split(args, 2)
        try:
            label, text = self._source(essay)
        except PermissionError as exc:
            return str(exc)
        if len(text.split()) < 60:
            return "Paste the whole essay (60+ words), or give the file."
        wrapped, _ = shield.wrap(text[:30000], label or "the essay")
        data = kit.ask_json(self.brain, (
            f"{shield.RULE}\nGrade this essay for a {level or 'high school'} student, kindly but honestly. JSON only: "
            "{\"scores\": {\"thesis\": 1-5, \"structure\": 1-5, \"evidence\": 1-5, \"language\": 1-5, \"mechanics\": 1-5}, "
            "\"overall\": str (a grade like B+ and /100), \"strengths\": [str], \"fix\": [str], "
            "\"line_edits\": [{\"quote\": str, \"better\": str}]}\n\n" + wrapped))
        if not isinstance(data, dict) or "scores" not in data:
            return "No feedback came back — try again."
        lines = [f"🖍 Overall: {data.get('overall', '?')}"]
        lines += [f"  {k.capitalize():<10} {'●' * int(v) + '○' * (5 - int(v))} {v}/5"
                  for k, v in data["scores"].items() if str(v).isdigit()]
        lines += ["", "Strengths:"] + [f"  + {s}" for s in data.get("strengths", [])]
        lines += ["", "To improve:"] + [f"  → {s}" for s in data.get("fix", [])]
        if data.get("line_edits"):
            lines += ["", "Line edits:"] + [f"  “{e.get('quote')}” → “{e.get('better')}”" for e in data["line_edits"][:8]]
        return "\n".join(lines)

    @command("essaycheck", group=G, usage="/essaycheck <essay text or file>",
             help="checks the shape of an essay: thesis, topic sentences, transitions, conclusion",
             title="Essay structure checker", icon="🧱", page="study", fields=(field("essay", "long", "Essay text or file"),))
    def essaycheck_cmd(self, args: str, routed: bool = False):
        try:
            label, text = self._source(args)
        except PermissionError as exc:
            return str(exc)
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        if len(paragraphs) < 2:
            return "Paste the essay with blank lines between paragraphs."
        transitions = re.compile(r"^(however|moreover|furthermore|in addition|therefore|consequently|first|second|"
                                 r"finally|in conclusion|on the other hand|for example|ayrıca|ancak|bu nedenle|"
                                 r"sonuç olarak|öncelikle|bununla birlikte|örneğin)\b", re.I)
        lengths = [len(p.split()) for p in paragraphs]
        lines = [f"🧱 {len(paragraphs)} paragraphs, {sum(lengths)} words (avg {sum(lengths) // len(paragraphs)} per "
                 "paragraph)"]
        if lengths[0] > 1.6 * (sum(lengths) / len(lengths)):
            lines.append("  • The introduction is long — keep it to the hook, context and thesis.")
        linked = sum(1 for p in paragraphs[1:] if transitions.match(p))
        lines.append(f"  • {linked} of {len(paragraphs) - 1} body/closing paragraphs open with a transition.")
        short = [i + 1 for i, n in enumerate(lengths) if n < 40]
        if short:
            lines.append(f"  • Thin paragraph(s): {', '.join(map(str, short))} — develop with evidence or merge.")
        wrapped, _ = shield.wrap("\n\n".join(paragraphs)[:20000], label or "the essay")
        verdict = self.brain.ask_once(
            f"{shield.RULE}\nFor this essay answer in 5 short lines: 1) the thesis sentence (quote it, or say there "
            "is none), 2) does each body paragraph start with a topic sentence that supports it (list paragraph "
            "numbers that don't), 3) does the conclusion restate and extend it, 4) the weakest link between "
            f"paragraphs, 5) one fix with the biggest effect.\n\n{wrapped}")
        return "\n".join(lines) + "\n\n" + verdict.strip()

    @command("gradelevel", "simplify", group=G, usage="/gradelevel <grade 1-12 or A2/B1> | <text or file>",
             help="rewrites a text for a reading level, with the score before and after",
             title="Rewrite for my grade level", icon="🎚", page="study",
             fields=(field("level", "text", "Grade or level", "7th grade"), field("text", "long", "Text or file")))
    def gradelevel_cmd(self, args: str, routed: bool = False):
        from .office import readability

        level, source = split(args, 2)
        try:
            label, text = self._source(source)
        except PermissionError as exc:
            return str(exc)
        if not text.strip():
            return "Usage: /gradelevel 7th grade | <text>"
        wrapped, _ = shield.wrap(text[:15000], label or "the text")
        with kit.more_room(self.brain):
            out = self.brain.ask_once(
                f"{shield.RULE}\nRewrite this for a reader at {level}. Keep every fact; shorter sentences, everyday "
                f"words, same language as the original. Return only the rewrite.\n\n{wrapped}")
        before, after = readability(text), readability(out)
        return f"🎚 {before['score']} → {after['score']} ({after['band']})\n\n{out.strip()}"

    @command("comprehension", group=G, usage="/comprehension <text or file> | [8 questions]",
             help="reading comprehension questions with answers", title="Reading comprehension questions", icon="❔",
             page="study", fields=(field("text", "long", "Text or file"), field("count", "number", "Questions", "8")))
    def comprehension_cmd(self, args: str, routed: bool = False):
        source, count = split(args, 2)
        try:
            label, text = self._source(source)
        except PermissionError as exc:
            return str(exc)
        if len(text.split()) < 40:
            return "Give a passage (40+ words) or a file."
        wrapped, _ = shield.wrap(text[:20000], label or "the passage")
        return "❔ " + self.brain.ask_once(
            f"{shield.RULE}\nWrite {count or 8} reading comprehension questions on this passage: some literal, some "
            "inferential, one vocabulary-in-context and one about the author's purpose. Number them, then give an "
            f"answer key at the end.\n\n{wrapped}").strip()

    @command("bookreport", group=G, usage="/bookreport <book title> | [grade]",
             help="a book report plan: outline, questions to answer and a template (you write it)",
             title="Book report helper", icon="📕", page="study",
             fields=(field("book", "text", "Book"), field("grade", "text", "Grade", optional=True)))
    def bookreport_cmd(self, args: str, routed: bool = False):
        book, grade = split(args, 2)
        if not book:
            return "Usage: /bookreport <book title> | <grade>"
        return "📕 " + self.brain.ask_once(
            f"Help a {grade or 'middle school'} student plan a book report on '{book}' without writing it for them: "
            "a 5-part outline with what goes in each part, 8 thinking questions to answer while reading, useful "
            "sentence starters, and a checklist. If you are not sure of the book's details, say so.").strip()

    @command("vocab", "vocabulary", group=G, usage="/vocab add <word> [language] · /vocab",
             help="new words with meanings and examples, added to your flashcards", title="Vocabulary builder",
             icon="🔤", page="study", fields=(field("word", "text", "Word"),
                                             field("language", "text", "Language", "English", optional=True)),
             template="add {word} {language}")
    def vocab_cmd(self, args: str, routed: bool = False):
        from ..study import CARDS

        text = args.strip()
        verb, _, rest = text.partition(" ")
        decks = CARDS.load()
        deck = decks.get("Vocabulary", [])
        if verb.lower() == "add" and rest.strip():
            word, _, language = rest.strip().partition(" ")
            data = kit.ask_json(self.brain, (
                f"For the {language or 'English'} word '{word}', JSON only: {{\"meaning\": str (short, in English), "
                "\"turkish\": str, \"example\": str, \"part\": str}}"))
            if not isinstance(data, dict) or not data.get("meaning"):
                return f"I couldn't look up '{word}'."
            back = f"{data['meaning']} ({data.get('part', '')})\nTR: {data.get('turkish', '')}\n“{data.get('example', '')}”"
            deck.append({"front": word, "back": back, "due": date.today().toordinal(), "interval": 0, "ease": 2.5})
            decks["Vocabulary"] = deck
            CARDS.save(decks)
            return f"🔤 {word}: {data['meaning']}\n   “{data.get('example', '')}”\nAdded to the Vocabulary deck " \
                   f"({len(deck)} words) — /cards review Vocabulary"
        if not deck:
            return "No words yet. /vocab add serendipity"
        return f"🔤 Vocabulary ({len(deck)}): " + ", ".join(c["front"] for c in deck[-40:]) + \
            "\n/cards review Vocabulary to practise."

    @command("worksheet", group=G, usage="/worksheet <addition|subtraction|multiplication|division|fractions|equations|percent> | [easy|medium|hard] | [20]",
             help="a printable maths worksheet with an answer key — every answer computed",
             title="Math worksheet generator", icon="➗", page="study",
             fields=(field("topic", "choice", "Topic", "multiplication", ("addition", "subtraction", "multiplication",
                                                                         "division", "fractions", "equations", "percent")),
                     field("level", "choice", "Level", "easy", ("easy", "medium", "hard")),
                     field("count", "number", "Problems", "20")),
             template="{topic} | {level} | {count}")
    def worksheet_cmd(self, args: str, routed: bool = False):
        topic, level, count = split(args, 3)
        try:
            problems = worksheet(topic or "multiplication", level or "easy", max(4, min(60, int(count or 20))))
        except ValueError as exc:
            return str(exc)
        path = worksheet_pdf(f"{(topic or 'multiplication').capitalize()} ({level or 'easy'})", problems)
        return f"➗ {len(problems)} problems with an answer key:\n  {path}"

    @command("sciencefair", group=G, usage="/sciencefair <grade, what you like>", help="science fair project ideas",
             title="Science fair project ideas", icon="🔬", page="study",
             fields=(field("about", "text", "Grade and interests", "8th grade, plants and music"),))
    def sciencefair_cmd(self, args: str, routed: bool = False):
        return "🔬 " + self.brain.ask_once(
            f"Suggest 5 science fair projects for: {args or 'middle school'}. For each: a testable question, "
            "hypothesis, independent/dependent variables, materials (cheap, easy to get), 5 short steps, and a "
            "safety note. Keep them doable at home or school.").strip()

    @command("labreport", group=G, usage="/labreport <the experiment>", help="a lab report template to fill in (Word)",
             title="Lab report template", icon="🧫", page="study",
             fields=(field("experiment", "text", "Experiment", "the effect of temperature on enzyme activity"),))
    def labreport_cmd(self, args: str, routed: bool = False):
        experiment = args.strip() or "an experiment"
        return self.make_document(
            f"a lab report template for {experiment}: Title, Aim, Hypothesis, Variables (table), Materials, Method "
            "(numbered), Results (an empty table with sensible columns and units), Analysis questions, Conclusion "
            "prompts, Evaluation and Sources. Give short guidance in italics in each section for the student to "
            "replace.", ("docx",))

    # --- teachers --------------------------------------------------------------------------------
    @command("lessonplan", group=G, usage="/lessonplan <subject, grade, topic, minutes>",
             help="a lesson plan with objectives and timed activities (Word)", title="Teacher: lesson plan",
             icon="👩\u200d🏫", page="study", fields=(field("about", "text", "Subject, grade, topic, minutes",
                                                    "Science, 6th grade, the water cycle, 40 minutes"),))
    def lessonplan_cmd(self, args: str, routed: bool = False):
        return self.make_document(
            f"a lesson plan for: {args or 'a 40-minute lesson'}. Objectives (measurable), materials, a timed "
            "activities table (minutes, teacher does, students do), differentiation, assessment, homework.",
            ("docx",))

    @command("teacherworksheet", group=G, usage="/teacherworksheet <topic, grade, question types>",
             help="a classroom worksheet with an answer key (Word)", title="Teacher: worksheet maker", icon="📄",
             page="study", fields=(field("about", "text", "Topic, grade, question types",
                                         "fractions, 5th grade, fill-in and word problems"),))
    def teacherworksheet_cmd(self, args: str, routed: bool = False):
        return self.make_document(
            f"a classroom worksheet: {args or 'general'}. Title, name/date line, instructions, 12-20 numbered "
            "questions mixing the requested types with space to answer, then an answer key on a new page.",
            ("docx",))

    @command("rubric", group=G, usage="/rubric <assignment> | [criteria] | [4 levels]",
             help="a grading rubric table (Word)", title="Teacher: rubric maker", icon="📊", page="study",
             fields=(field("assignment", "text", "Assignment", "persuasive essay"),
                     field("criteria", "text", "Criteria (optional)", optional=True),
                     field("levels", "choice", "Levels", "4", ("3", "4", "5"))))
    def rubric_cmd(self, args: str, routed: bool = False):
        assignment, criteria, levels = split(args, 3)
        return self.make_document(
            f"a grading rubric for {assignment or 'an assignment'} as a table: rows are criteria "
            f"({criteria or 'choose 4-6 sensible ones'}), columns are {levels or 4} performance levels with points, "
            "each cell a concrete descriptor. Add a total-points line and a short note on how to use it.", ("docx",))


def register_watchers(jarvis, watchers) -> None:
    """Exam mornings: a nudge on the day before and the day of each exam."""
    state = {"day": ""}

    def check():
        today = date.today().isoformat()
        if state["day"] == today or datetime.now().hour < 8:
            return
        state["day"] = today
        for exam in EXAMS.load():
            days = (date.fromisoformat(exam["date"]) - date.today()).days
            if days in (0, 1, 7):
                alerts.post(f"{exam['name']} {'today' if days == 0 else 'tomorrow' if days == 1 else 'in a week'}",
                            "Good luck!" if days == 0 else "Time for a last review.", page="study")

    watchers.add("exams", 600, check)
