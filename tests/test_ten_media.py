"""10.0 photo, video and audio: the edits are exact, so they are checked
exactly — sizes, colours, how much noise and silence is left."""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from jarvis.ten import media


def test_changes_in_words():
    ops = media.parse_ops("rotate 90, brightness +20%, grayscale and crop 10%")
    assert ops == [("rotate", 90.0), ("brightness", 1.2), ("grayscale", None), ("crop", 10.0)]
    assert media.parse_ops("darker")[0] == ("brightness", 0.8)
    with pytest.raises(media.MediaError):
        media.parse_ops("make it pop somehow")


def test_edits_change_the_picture_as_asked():
    image = Image.new("RGB", (100, 50), (200, 40, 40))
    assert media.apply_ops(image, [("rotate", 90)]).size == (50, 100)
    assert media.apply_ops(image, [("crop", 10)]).size == (80, 40)
    assert media.apply_ops(image, [("square", None)]).size == (50, 50)
    assert media.apply_ops(image, [("resize", 200)]).size == (200, 100)
    r, g, b = media.apply_ops(image, [("grayscale", None)]).getpixel((5, 5))
    assert r == g == b
    warm = media.apply_ops(Image.new("RGB", (4, 4), (100, 100, 100)), [("warm", None)]).getpixel((0, 0))
    assert warm[0] > 100 > warm[2]


def test_photoedit_saves_a_copy_and_leaves_the_original(base, tmp_path):
    source = tmp_path / "holiday.jpg"
    Image.new("RGB", (60, 40), (10, 120, 200)).save(source)
    reply = media.Media().photoedit_cmd(f"{source} | rotate 90, sepia")
    copy = tmp_path / "holiday_edited.jpg"
    assert str(copy) in reply and copy.exists()
    assert Image.open(copy).size == (40, 60) and Image.open(source).size == (60, 40)
    assert "rotate" in media.Media().photoedit_cmd("")


def test_faces_are_blurred_where_windows_found_them(base, tmp_path, monkeypatch):
    from jarvis import winrt

    picture = Image.new("RGB", (200, 120), "white")
    for x in range(40, 80, 4):          # a stripy "face" so blurring shows
        for y in range(30, 70):
            picture.putpixel((x, y), (0, 0, 0))
    source = tmp_path / "group.png"
    picture.save(source)
    monkeypatch.setattr(winrt, "faces", lambda path: [(40, 30, 40, 40)])
    target, count = media.blur_faces(source)
    out = Image.open(target).convert("RGB")
    assert count == 1 and out.size == (200, 120)
    assert out.getpixel((44, 50)) != (0, 0, 0)            # the face is no longer sharp
    assert out.getpixel((180, 100)) == (255, 255, 255)    # far away is untouched


def test_upright_after_blurring_a_phone_photo(base, tmp_path, monkeypatch):
    from jarvis import winrt

    source = tmp_path / "phone.jpg"
    exif = Image.Exif()
    exif[0x0112] = 6            # "rotate 90° clockwise to view", as phones save portrait shots
    Image.new("RGB", (80, 40), "gray").save(source, exif=exif)
    monkeypatch.setattr(winrt, "faces", lambda path: [])
    target, count = media.blur_faces(source)
    assert count == 0 and Image.open(target).size == (40, 80)
    assert not Image.open(target).getexif()


def _tone(seconds, rate, freq=440.0, level=0.5):
    t = np.arange(int(seconds * rate)) / rate
    return (level * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def test_noise_reduction_quietens_hiss_and_keeps_the_voice():
    rate = 16000
    rng = np.random.default_rng(1)
    clean = np.concatenate([np.zeros(rate // 2, np.float32), _tone(2, rate)])
    noisy = clean + rng.normal(0, 0.05, len(clean)).astype(np.float32)
    out = media.denoise(noisy, rate)
    assert len(out) == len(noisy)
    hiss_before = np.sqrt(np.mean(noisy[: rate // 2] ** 2))
    hiss_after = np.sqrt(np.mean(out[: rate // 2] ** 2))
    assert hiss_after < hiss_before / 3
    tone = slice(rate, 2 * rate)
    assert np.sqrt(np.mean(out[tone] ** 2)) > 0.8 * np.sqrt(np.mean(clean[tone] ** 2))


def test_long_pauses_are_cut_short():
    rate = 8000
    audio = np.concatenate([_tone(1, rate), np.zeros(2 * rate, np.float32), _tone(1, rate)])
    shorter, removed = media.remove_silences(audio, rate, min_pause=0.6, keep=0.2)
    assert 1.7 < removed < 1.85
    assert abs(len(shorter) / rate - (4 - removed)) < 0.01
    untouched, none = media.remove_silences(_tone(2, rate), rate)
    assert none == 0 and len(untouched) == 2 * rate


def test_a_ringtone_is_the_loud_part_faded_in_and_out():
    rate = 8000
    song = np.concatenate([_tone(10, rate, level=0.1), _tone(12, rate, level=0.9), _tone(10, rate, level=0.1)])
    clip, start = media.ringtone(song, rate, None, seconds=10)
    assert 9 <= start <= 12 and len(clip) == 10 * rate
    assert abs(clip[0]) < 1e-6 and abs(clip[-1]) < 0.01
    chosen, at = media.ringtone(song, rate, 2.0, seconds=5)
    assert at == 2.0 and len(chosen) == 5 * rate
    assert media.parse_time("1:05") == 65 and media.parse_time("") is None


def test_ringtone_command_writes_the_file(base, tmp_path, monkeypatch):
    from jarvis import audiofile

    song = tmp_path / "song.mp3"
    song.write_bytes(b"not really an mp3")
    saved = []
    monkeypatch.setattr(audiofile, "load", lambda path: (_tone(40, 8000), 8000))
    monkeypatch.setattr(audiofile, "save", lambda samples, rate, path: (saved.append(path), path.write_bytes(b"x"))[0])
    reply = media.Media().ringtone_cmd(f"{song} | 0:05 | 20 | iphone")
    assert "20 s ringtone from 0:05" in reply and saved and saved[0].suffix == ".m4a"
    assert reply.strip().endswith(".m4r")
    assert "audio file" in media.Media().ringtone_cmd("nothing-here.mp3")


def test_the_gallery_lists_newest_first(base, tmp_path):
    import os
    import time

    folder = tmp_path / "Pictures"
    (folder / "trip").mkdir(parents=True)
    old, new, clip = folder / "old.jpg", folder / "trip" / "new.png", folder / "clip.mp4"
    for i, path in enumerate((old, new, clip)):
        path.write_bytes(b"x")
        os.utime(path, (time.time() - 100 + i * 10,) * 2)
    (folder / "notes.txt").write_text("not media")
    assert media.media_files(folder) == [clip, new, old]
    assert media.media_files(folder, "photos") == [new, old]
    assert media.media_files(folder, "videos") == [clip]
    reply = media.Media().gallery_cmd(str(folder))
    assert "2 photo(s) and 1 video(s)" in reply


from tests.test_gui import _display_available, app  # noqa: E402,F401
from tests.test_ten_ui import inline  # noqa: E402,F401


@pytest.mark.skipif(not _display_available(), reason="no display")
def test_the_media_page_shows_the_gallery_and_edits_a_copy(app, inline, tmp_path, monkeypatch):
    folder = tmp_path / "Pictures"
    folder.mkdir()
    for i, colour in enumerate(("red", "green", "blue")):
        Image.new("RGB", (300, 200), colour).save(folder / f"p{i}.jpg")
    monkeypatch.setattr(media, "default_folder", lambda: folder)
    app._show_tab("media")
    app.update()
    page = app.pages["media"]
    assert len(page.files) == 3 and len(page.grid_box.winfo_children()) == 3
    assert page._thumbs, "the photos got thumbnails"
    page.chose(folder / "p0.jpg")
    page.turn(90)
    page.sliders["brightness"].set(1.4)
    page.filter_var.set("sepia")
    assert page.ops() == [("rotate", 90.0), ("brightness", 1.4), ("sepia", None)]
    page.draw()
    page.save()
    copy = folder / "p0_edited.jpg"
    assert copy.exists() and Image.open(copy).size == (200, 300)
    page.filter.set("Videos")
    page.set_kind("Videos")
    assert "No videos" in page.status.cget("text")
