"""The documents library: indexing a folder and finding the right passage."""

from __future__ import annotations

import pytest

from jarvis import library


@pytest.fixture
def folder(tmp_path):
    root = tmp_path / "docs"
    root.mkdir()
    (root / "robot.md").write_text(
        "# Line follower\nThe line follower robot uses two infrared sensors and a PID "
        "controller. Kp is 0.8 and Kd is 2.1 after tuning on the competition track.",
        encoding="utf-8",
    )
    (root / "budget.txt").write_text(
        "Teknofest budget: motors 1200 TL, battery 650 TL, frame 400 TL.",
        encoding="utf-8",
    )
    (root / "ignored.exe").write_bytes(b"MZ\x00\x00")
    return root


def test_indexes_readable_files_only(base, folder):
    data = library.build(folder)
    assert data["files"] == 2
    files = {p[0] for p in data["passages"]}
    assert files == {"robot.md", "budget.txt"}


def test_the_right_passage_wins(base, folder):
    data = library.build(folder)
    top = library.search(data, "what are the PID values for the line follower")[0]
    assert top.file == "robot.md"
    top = library.search(data, "how much did the battery cost")[0]
    assert top.file == "budget.txt"


def test_nothing_matches_returns_nothing(base, folder):
    data = library.build(folder)
    assert library.search(data, "quantum chromodynamics") == []


def test_the_index_is_kept_on_disk(base, folder):
    library.build(folder)
    assert library.load(folder)["files"] == 2


def test_long_documents_become_overlapping_passages(base, tmp_path):
    root = tmp_path / "long"
    root.mkdir()
    (root / "book.txt").write_text(" ".join(f"word{i}" for i in range(1000)), encoding="utf-8")
    data = library.build(root)
    assert len(data["passages"]) > 5


def test_docx_is_read(base, tmp_path):
    import zipfile

    root = tmp_path / "w"
    root.mkdir()
    with zipfile.ZipFile(root / "notes.docx", "w") as z:
        z.writestr("word/document.xml",
                   "<w:document><w:body><w:p><w:r><w:t>The servo angle is 90 degrees</w:t>"
                   "</w:r></w:p></w:body></w:document>")
    data = library.build(root)
    assert library.search(data, "servo angle")[0].file == "notes.docx"
