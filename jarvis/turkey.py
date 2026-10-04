"""Türkiye (10.0): KDV, Istanbul's live traffic index, the bayram calendar,
e-Devlet shortcuts, and Turkish home cooking.

Traffic comes from İBB's own traffic centre (the index Istanbul publishes,
0-100), holidays from Nager.Date (which carries both the national days and
the Ramazan and Kurban bayrams with their Turkish names), and every e-Devlet
link was checked to open the right service page — the site answers
"200 OK" even for pages that don't exist, so they were checked by title.
"""

from __future__ import annotations

from datetime import date, datetime

from . import kit

# --- KDV -------------------------------------------------------------------------------------------

KDV_RATES = (1, 10, 20)


def kdv(amount: float, rate: float = 20, included: bool = False) -> dict:
    """KDV on a price: added to a net price, or taken out of a gross one (KDV dahil)."""
    if included:
        net = amount / (1 + rate / 100)
        return {"net": round(net, 2), "kdv": round(amount - net, 2), "gross": round(amount, 2), "rate": rate}
    tax = amount * rate / 100
    return {"net": round(amount, 2), "kdv": round(tax, 2), "gross": round(amount + tax, 2), "rate": rate}


def tl(value: float) -> str:
    """1234.5 → '1.234,50 ₺', as Turkish prices are written."""
    whole, cents = f"{value:,.2f}".split(".")
    return f"{whole.replace(',', '.')},{cents} ₺"


# --- Istanbul traffic -------------------------------------------------------------------------------

TRAFFIC = "https://tkmservices.ibb.gov.tr/web/api/TrafficData/v1"


def traffic_now() -> dict:
    """{'now': 0-100, 'usual': what's typical for this time} from İBB."""
    data = kit.get_json(f"{TRAFFIC}/TrafficIndex_Sc1_Cont")
    return {"now": int(data.get("TI", 0)), "usual": int(data.get("TI_Av", 0) or 0)}


def traffic_history() -> list[tuple[datetime, int]]:
    """The last hours in 5-minute steps, oldest first."""
    rows = kit.get_json(f"{TRAFFIC}/TrafficIndexHistory/1/5M")
    out = []
    for row in rows if isinstance(rows, list) else []:
        try:
            out.append((datetime.fromisoformat(row["TrafficIndexDate"][:19]), int(row["TrafficIndex"])))
        except (KeyError, ValueError, TypeError):
            continue
    return sorted(out)


def traffic_words(index: int) -> str:
    return ("light" if index < 30 else "moderate" if index < 50 else "heavy" if index < 70 else "very heavy")


# --- bayrams ----------------------------------------------------------------------------------------

HOLIDAYS = kit.Store("tr_holidays.json", {})


def holidays(year: int) -> list[dict]:
    """[{'date', 'name' (Turkish), 'english'}], fetched once per year and kept."""
    cache = HOLIDAYS.load()
    if str(year) in cache:
        return cache[str(year)]
    rows = kit.get_json(f"https://date.nager.at/api/v3/PublicHolidays/{year}/TR")
    out = [{"date": r["date"], "name": r.get("localName") or r["name"], "english": r["name"]} for r in rows]
    cache[str(year)] = out
    HOLIDAYS.save(cache)
    return out


def upcoming(today: date | None = None, count: int = 6) -> list[dict]:
    """The next holidays, with a multi-day bayram shown once with its length."""
    today = today or date.today()
    rows = [r for y in (today.year, today.year + 1) for r in holidays(y) if date.fromisoformat(r["date"]) >= today]
    merged: list[dict] = []
    for row in rows:
        base = row["name"].split(" 1. Gün")[0].split(" 2. Gün")[0].split(" 3. Gün")[0].split(" 4. Gün")[0]
        day = date.fromisoformat(row["date"])
        if merged and merged[-1]["base"] == base and (day - merged[-1]["last"]).days == 1:
            merged[-1]["last"] = day
            merged[-1]["days"] += 1
            continue
        merged.append({"base": base, "first": day, "last": day, "days": 1, "english": row["english"]})
    for item in merged:
        item["in_days"] = (item["first"] - today).days
    return merged[:count]


# --- e-Devlet ---------------------------------------------------------------------------------------

EDEVLET = [
    ("e-Devlet Kapısı", "https://www.turkiye.gov.tr/", "🏛"),
    ("SGK Tescil ve Hizmet Dökümü", "https://www.turkiye.gov.tr/sgk-tescil-ve-hizmet-dokumu", "📋"),
    ("4A Hizmet Dökümü (son 6 ay)", "https://www.turkiye.gov.tr/4a-hizmet-dokumu", "🗂"),
    ("Adres Belgesi (İkametgâh)", "https://www.turkiye.gov.tr/nvi-yerlesim-yeri-ve-diger-adres-belgesi-sorgulama",
     "🏠"),
    ("Adli Sicil Kaydı", "https://www.turkiye.gov.tr/adli-sicil-kaydi", "⚖"),
    ("Araç Ceza Sorgulama", "https://www.turkiye.gov.tr/emniyet-arac-plakasina-yazilan-ceza-sorgulama", "🚗"),
    ("Tapu Bilgileri", "https://www.turkiye.gov.tr/tapu-bilgileri-sorgulama", "🏡"),
    ("Nüfus Kayıt Örneği", "https://www.turkiye.gov.tr/arama?aranan=n%C3%BCfus+kay%C4%B1t+%C3%B6rne%C4%9Fi", "👪"),
    ("Askerlik Durum Belgesi", "https://www.turkiye.gov.tr/arama?aranan=askerlik+durum+belgesi", "🎖"),
    ("Vergi Borcu (GİB)", "https://dijital.gib.gov.tr/", "🧾"),
    ("MHRS Randevu", "https://www.mhrs.gov.tr/", "🏥"),
    ("e-Nabız", "https://enabiz.gov.tr/", "💓"),
]


def edevlet_search(words: str) -> str:
    import urllib.parse

    return "https://www.turkiye.gov.tr/arama?aranan=" + urllib.parse.quote_plus(words)


# --- Turkish cooking ---------------------------------------------------------------------------------

DISHES = {
    "Çorbalar": ["Mercimek çorbası", "Ezogelin çorbası", "Tarhana çorbası", "Yayla çorbası", "Domates çorbası"],
    "Ana yemekler": ["Karnıyarık", "İmam bayıldı", "Hünkâr beğendi", "Kuru fasulye", "Etli nohut", "Musakka",
                     "Tavuk sote", "Izgara köfte", "İzmir köfte", "Mantı", "Lahmacun", "Etli taze fasulye"],
    "Pilavlar ve börekler": ["Pirinç pilavı", "Bulgur pilavı", "Su böreği", "Sigara böreği", "Gözleme"],
    "Zeytinyağlılar": ["Zeytinyağlı yaprak sarma", "Zeytinyağlı enginar", "Zeytinyağlı barbunya",
                       "Biber dolması", "Kısır", "Çoban salatası"],
    "Tatlılar": ["Sütlaç", "Revani", "İrmik helvası", "Kazandibi", "Aşure", "Baklava", "Şekerpare", "Kemalpaşa"],
    "Kahvaltılık": ["Menemen", "Sucuklu yumurta", "Çılbır", "Pişi", "Simit"],
}
