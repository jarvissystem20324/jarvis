"""Money (10.0) — tracking only, never advice: budgets per category with
alerts, importing a bank statement, who owes who, and a no-spend challenge.

Everything builds on the 8.0 spending log (jarvis/spending.py): a statement
import adds ordinary entries to it (skipping ones already there), and the
budgets, alerts and challenge all read from it.
"""

from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime, timedelta
from pathlib import Path

from . import kit, spending

BUDGETS = kit.Store("budgets.json", {})
OWES = kit.Store("owes.json", [])
NOSPEND = kit.Store("nospend.json", {})

# --- budgets by category ---------------------------------------------------------------------------


def month_by_category(now: datetime | None = None) -> dict[str, float]:
    """This month's spending per category, in the home currency."""
    start, end, _ = spending.period("month", now)
    home = spending.default_currency()
    return spending.totals(spending.load(), start, end).get(home, {})


def budget_status(now: datetime | None = None) -> list[dict]:
    spent = month_by_category(now)
    rows = []
    for category, limit in sorted(BUDGETS.load().items()):
        used = spent.get(category, 0.0)
        rows.append({"category": category, "budget": float(limit), "spent": used,
                     "share": used / float(limit) if limit else 0.0})
    return rows


def set_budget(category: str, amount: float) -> None:
    budgets = BUDGETS.load()
    if amount <= 0:
        budgets.pop(category.lower(), None)
    else:
        budgets[category.lower()] = round(amount, 2)
    BUDGETS.save(budgets)


def category_alert(category: str, before: float, now: datetime | None = None) -> str:
    """A note when this spend took a category past 80% or 100% of its budget ('' otherwise)."""
    limit = BUDGETS.load().get(category)
    if not limit:
        return ""
    used = month_by_category(now).get(category, 0.0)
    home = spending.default_currency()
    for line, crossed in ((1.0, f"⚠ Over your {category} budget: {spending.money(used, home)} of "
                                f"{spending.money(limit, home)}."),
                          (0.8, f"Heads up: {used / limit * 100:.0f}% of your {category} budget used.")):
        if before < limit * line <= used:
            return crossed
    return ""


# --- bank statements -------------------------------------------------------------------------------

DATE_WORDS = ("tarih", "date", "işlem tarihi", "islem tarihi", "valör", "booking date", "transaction date")
TEXT_WORDS = ("açıklama", "aciklama", "description", "details", "işlem", "islem", "merchant", "payee", "narrative")
AMOUNT_WORDS = ("tutar", "amount", "işlem tutarı", "islem tutari", "value")
DEBIT_WORDS = ("borç", "borc", "debit", "çıkış", "cikis", "withdrawal")
CREDIT_WORDS = ("alacak", "credit", "giriş", "giris", "deposit")


def _read_text(path: Path) -> str:
    raw = Path(path).read_bytes()
    for encoding in ("utf-8-sig", "cp1254", "latin-1"):       # Turkish banks often export Windows-1254
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def _find(header: list[str], words: tuple[str, ...]) -> int | None:
    cells = [h.strip().lower() for h in header]
    for word in words:                     # exact names first, then names that contain the word
        if word in cells:
            return cells.index(word)
    for i, cell in enumerate(cells):
        if any(word in cell for word in words):
            return i
    return None


def read_statement(path: Path) -> list[dict]:
    """Spending rows from a bank's CSV export: {day, what, amount} with amount as a positive spend.
    Money coming in is left out — this logs spending, not income."""
    text = _read_text(path)
    # The delimiter is whatever the header line uses most. (csv.Sniffer
    # guessed "," from Turkish amounts like 1.250,50 and split every row wrong.)
    header_line = next((line for line in text.splitlines()[:30]
                        if any(word in line.lower() for word in DATE_WORDS)), text.splitlines()[0] if text else "")
    delimiter = max(";,\t|", key=header_line.count)
    rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
    start = next((i for i, row in enumerate(rows[:30]) if _find(row, DATE_WORDS) is not None and
                  (_find(row, AMOUNT_WORDS) is not None or _find(row, DEBIT_WORDS) is not None)), None)
    if start is None:
        raise ValueError("I couldn't find the date and amount columns. Is it the bank's CSV export?")
    header = rows[start]
    day_col, text_col = _find(header, DATE_WORDS), _find(header, TEXT_WORDS)
    amount_col, debit_col, credit_col = _find(header, AMOUNT_WORDS), _find(header, DEBIT_WORDS), \
        _find(header, CREDIT_WORDS)
    from .daily import parse_date

    # A bank account lists spending as negative; a credit card statement lists
    # purchases as positive (and payments to the card as negative). Either
    # way, spending is most of the rows, so the commoner sign is spending.
    signs = [("-" in row[amount_col]) for row in rows[start + 1:]
             if amount_col is not None and len(row) > amount_col and re.search(r"\d", row[amount_col])]
    card_style = debit_col is None and bool(signs) and signs.count(False) > signs.count(True)
    out = []
    for row in rows[start + 1:]:
        if not row or len(row) <= day_col or not row[day_col].strip():
            continue
        try:
            day = parse_date(row[day_col].strip().split()[0])
        except (ValueError, IndexError):
            continue
        try:
            if debit_col is not None and debit_col < len(row) and row[debit_col].strip():
                amount = abs(spending._number(re.sub(r"[^\d.,-]", "", row[debit_col])))
            elif amount_col is not None and amount_col < len(row) and row[amount_col].strip():
                value = spending._number(re.sub(r"[^\d.,-]", "", row[amount_col]).lstrip("-"))
                negative = "-" in row[amount_col] or row[amount_col].strip().endswith(("B", "b"))
                if negative == card_style:
                    continue                # money in (or a payment to the card)
                amount = value
            else:
                continue
        except ValueError:
            continue
        if amount <= 0:
            continue
        what = row[text_col].strip() if text_col is not None and text_col < len(row) else "bank"
        out.append({"day": day, "what": re.sub(r"\s+", " ", what)[:80], "amount": round(amount, 2)})
    return out


def import_statement(path: Path) -> tuple[int, int]:
    """(added, already there). Entries get a category from their description."""
    rows = read_statement(path)
    entries = spending.load()
    currency = spending.default_currency(entries)
    seen = {(datetime.fromtimestamp(e["at"]).date().isoformat(), round(float(e["amount"]), 2), e["what"].lower())
            for e in entries}
    added = skipped = 0
    for row in rows:
        key = (row["day"].isoformat(), row["amount"], row["what"].lower())
        if key in seen:
            skipped += 1
            continue
        seen.add(key)
        entries.append({"amount": row["amount"], "currency": currency, "what": row["what"],
                        "category": spending.guess_category(row["what"]),
                        "at": datetime.combine(row["day"], datetime.min.time()).replace(hour=12).timestamp(),
                        "source": Path(path).name})
        added += 1
    if added:
        spending._save(entries)
    return added, skipped


# --- who owes who -----------------------------------------------------------------------------------

def owe_add(payer: str, amount: float, people: list[str], what: str = "") -> dict:
    """`payer` paid `amount` for `people` (who may include the payer), shared evenly."""
    entry = {"payer": payer.strip().title(), "amount": round(amount, 2),
             "for": [p.strip().title() for p in people if p.strip()], "what": what.strip(),
             "at": datetime.now().isoformat(timespec="minutes")}
    rows = OWES.load()
    rows.append(entry)
    OWES.save(rows)
    return entry


def balances(rows: list[dict] | None = None) -> dict[str, float]:
    """Each person's net: positive = is owed money, negative = owes."""
    net: dict[str, float] = {}
    for row in OWES.load() if rows is None else rows:
        share = row["amount"] / max(1, len(row["for"]))
        net[row["payer"]] = net.get(row["payer"], 0) + row["amount"]
        for person in row["for"]:
            net[person] = net.get(person, 0) - share
    return {k: round(v, 2) for k, v in net.items() if abs(v) >= 0.01}


def settle(net: dict[str, float]) -> list[tuple[str, str, float]]:
    """The fewest payments that square everyone: (who pays, whom, how much)."""
    owers = sorted(([n, -v] for n, v in net.items() if v < 0), key=lambda x: -x[1])
    owed = sorted(([n, v] for n, v in net.items() if v > 0), key=lambda x: -x[1])
    out = []
    i = j = 0
    while i < len(owers) and j < len(owed):
        pay = round(min(owers[i][1], owed[j][1]), 2)
        if pay >= 0.01:
            out.append((owers[i][0], owed[j][0], pay))
        owers[i][1] -= pay
        owed[j][1] -= pay
        if owers[i][1] < 0.01:
            i += 1
        if owed[j][1] < 0.01:
            j += 1
    return out


# --- the no-spend challenge -------------------------------------------------------------------------

def nospend_start(days: int, allowed: list[str], today: date | None = None) -> dict:
    state = {"start": (today or date.today()).isoformat(), "days": days,
             "allowed": [a.strip().lower() for a in allowed if a.strip()]}
    NOSPEND.save(state)
    return state


def nospend_status(today: date | None = None) -> dict | None:
    state = NOSPEND.load()
    if not state.get("start"):
        return None
    today = today or date.today()
    start = date.fromisoformat(state["start"])
    end = start + timedelta(days=state["days"] - 1)
    allowed = set(state.get("allowed", []))
    slips: dict[str, list[str]] = {}
    for e in spending.load():
        day = datetime.fromtimestamp(e["at"]).date()
        if start <= day <= min(today, end) and (e.get("category") or "other") not in allowed:
            slips.setdefault(day.isoformat(), []).append(e["what"])
    elapsed = max(0, (min(today, end) - start).days + 1)
    return {"start": start, "end": end, "days": state["days"], "elapsed": elapsed, "allowed": sorted(allowed),
            "clean": elapsed - len(slips), "slips": slips, "finished": today > end}
