"""10.0 study: the exact tools are exact (chemistry, bases, geometry, GPA,
worksheets), the trackers keep their data, and the Study page works."""

from __future__ import annotations

from datetime import date, timedelta

import pytest


@pytest.fixture
def jarvis(base):
    from jarvis.assistant import Jarvis

    return Jarvis(voice_enabled=False)


def test_chemistry():
    from jarvis.ten import school

    assert school.parse_formula("Ca(OH)2") == {"Ca": 1, "O": 2, "H": 2}
    assert school.parse_formula("CuSO4·5H2O") == {"Cu": 1, "S": 1, "O": 9, "H": 10}
    total, _ = school.molar_mass("H2SO4")
    assert total == pytest.approx(98.07, abs=0.02)
    assert school.balance("Fe + O2 = Fe2O3") == "4Fe + 3O2 → 2Fe2O3"
    assert school.balance("C3H8 + O2 -> CO2 + H2O") == "C3H8 + 5O2 → 3CO2 + 4H2O"
    with pytest.raises(school.ChemError):
        school.parse_formula("Xy2")


def test_bases_and_geometry():
    from jarvis.ten import school

    found = school.convert_base("255")
    assert found["binary"] == "11111111" and found["hexadecimal"] == "FF"
    assert school.convert_base("0x1f")["decimal"] == "31"
    assert school.convert_base("777(8)")["decimal"] == "511"
    assert school.geometry("circle", [1])["area"] == pytest.approx(3.14159, abs=1e-4)
    tri = school.geometry("triangle", [3, 4, 5])
    assert tri["area"] == pytest.approx(6) and tri["angle C"] == pytest.approx(90)
    with pytest.raises(ValueError):
        school.geometry("triangle", [1, 1, 5])


def test_gpa_and_points():
    from jarvis.ten import school

    four, average, credits = school.gpa([{"grade": "92", "credits": 4}, {"grade": "BB", "credits": 3},
                                        {"grade": "C", "credits": 3}])
    assert credits == 10 and four == pytest.approx((4 * 4 + 3 * 3 + 2 * 3) / 10)
    assert average == pytest.approx(92)


def test_worksheets_have_right_answers():
    from fractions import Fraction

    from jarvis.ten import school

    for q, a in school.worksheet("multiplication", "medium", 30, seed=1):
        x, y = q.rstrip(" =").split(" × ")
        assert int(x) * int(y) == int(a)
    for q, a in school.worksheet("equations", "easy", 20, seed=2):
        left, right = q.split(" = ")
        x = int(a.split("= ")[1])
        assert eval(left.replace("x", f"*{x}").replace("−", "-")) == int(right)  # noqa: S307 — test-made text
    for q, a in school.worksheet("fractions", "easy", 20, seed=3):
        f1, op, f2 = q.rstrip(" =").split(" ")
        value = {"+": Fraction(f1) + Fraction(f2), "−": Fraction(f1) - Fraction(f2), "×": Fraction(f1) * Fraction(f2)}
        assert str(value[op]) == a


def test_study_log_streak_and_report(jarvis):
    from jarvis.ten import school

    log = [{"at": (date.today() - timedelta(days=d)).toordinal() and
            __import__("time").mktime((date.today() - timedelta(days=d)).timetuple()) + 3600, "minutes": 30,
            "subject": "Maths"} for d in range(3)]
    school.STUDY_LOG.save(log)
    assert school.streak(log) == 3
    out = jarvis.process("/studylog 25 Physics").text
    assert "streak 3" in out
    assert "Study this week" in jarvis.process("/studyreport").text


def test_trackers(jarvis):
    assert "Added Essay" in jarvis.process("/assignment add Essay | English | friday").text
    assert "Essay" in jarvis.process("/assignments").text
    soon = (date.today() + timedelta(days=10)).isoformat()
    assert "10 day(s)" in jarvis.process(f"/exam add Finals | {soon}").text
    assert "Added Maths" in jarvis.process("/timetable add mon 09:00-10:30 Maths @ B12").text
    assert "Maths" in jarvis.process("/timetable").text
    out = jarvis.process("/grade add Calculus | 85 | 4").text
    assert "GPA 3.50" in out


def test_plot_and_the_maths_commands(jarvis):
    out = jarvis.process("/plot y = x^2 - 3x ; y = sin(x) | -5, 5").text
    assert out.strip().endswith(".png")
    assert "⚗ 2H2 + O2 → 2H2O" in jarvis.process("/balance H2 + O2 = H2O").text
    assert "98.0" in jarvis.process("/molar H2SO4").text
    assert "answer key" in jarvis.process("/worksheet division | easy | 12").text


def test_noise_loops_are_seamless():
    import numpy as np

    from jarvis import noise

    for kind in noise.KINDS:
        loop = noise.make(kind, seconds=2, seed=1)
        assert loop.dtype == np.float32 and np.abs(loop).max() <= 1.0 and loop.std() > 0.05
        assert abs(float(loop[-1]) - float(loop[0])) < 0.5


from tests.test_gui import _display_available, app  # noqa: E402,F401


@pytest.mark.skipif(not _display_available(), reason="no display")
def test_the_study_page_timer_and_games(app):
    from jarvis.ten import school

    app._show_tab("study")
    app.update()
    page = app.pages["study"]
    page.subject.insert(0, "History")
    page.lengths.set("15 / 3")
    page.reset_timer()
    page.start_timer()
    page.left = 3 * 60              # pretend 12 minutes passed
    page.skip_phase()
    assert school.STUDY_LOG.load()[-1]["subject"] == "History"
    assert page.phase == "break"
    page.start_timer()
    games = [w for w in page.body.winfo_children()]
    assert games
