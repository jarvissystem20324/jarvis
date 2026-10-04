"""10.0 photo, video and audio: a gallery of your pictures and videos, a photo
editor, blurring the faces in a photo, and cleaning up recordings — noise
reduction, cutting out silences, and ringtones.

Everything runs on the PC. Pictures are edited with Pillow. Faces are found by
Windows' own face detector (winrt.faces). Audio is decoded and encoded by
Windows' media engine (audiofile), and the editing in between is numpy, so
none of this needs ffmpeg or uploads anything.
"""

from __future__ import annotations

import re
import time
from pathlib import Path

import numpy as np

from .. import kit
from ..registry import command, field, split

G = "Media"
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tif", ".tiff"}
VIDEO_EXT = {".mp4", ".mov", ".mkv", ".avi", ".wmv", ".m4v", ".webm", ".3gp"}
AUDIO_EXT = {".mp3", ".wav", ".m4a", ".wma", ".aac", ".flac", ".ogg"}
PICTURE_TYPES = (("Pictures", "*.jpg *.jpeg *.png *.webp *.bmp *.gif *.tif *.tiff"),)
AUDIO_TYPES = (("Audio", "*.mp3 *.wav *.m4a *.wma *.aac *.flac *.ogg"),)


class MediaError(ValueError):
    pass


# --- the gallery -------------------------------------------------------------------------------

def default_folder() -> Path:
    from ..pc import known_folder

    return known_folder("pictures") or Path.home() / "Pictures"


def media_files(folder: Path, kind: str = "all", limit: int = 600, depth: int = 3) -> list[Path]:
    """Pictures and/or videos under `folder`, newest first.

    A few levels deep, not the whole disk: Pictures holds camera-roll
    folders, and a gallery that walked everything would take minutes.
    """
    wanted = {"photos": IMAGE_EXT, "videos": VIDEO_EXT}.get(kind, IMAGE_EXT | VIDEO_EXT)
    folder = Path(folder)
    found: list[tuple[float, Path]] = []

    def walk(path: Path, level: int) -> None:
        try:
            entries = list(path.iterdir())
        except OSError:
            return
        for entry in entries:
            try:
                if entry.is_dir():
                    if level < depth and not entry.name.startswith("."):
                        walk(entry, level + 1)
                elif entry.suffix.lower() in wanted:
                    found.append((entry.stat().st_mtime, entry))
            except OSError:
                continue

    walk(folder, 0)
    found.sort(key=lambda item: -item[0])
    return [p for _, p in found[:limit]]


def kind_of(path: Path) -> str:
    ext = Path(path).suffix.lower()
    return "photo" if ext in IMAGE_EXT else "video" if ext in VIDEO_EXT else "audio" if ext in AUDIO_EXT else ""


# --- the photo editor ----------------------------------------------------------------------------

FILTERS = ("grayscale", "sepia", "vivid", "warm", "cool", "fade", "invert")
OP_WORDS = {
    "rotate": "rotate", "turn": "rotate", "döndür": "rotate",
    "flip": "flip", "mirror": "flip", "aynala": "flip", "flipv": "flipv", "upside": "flipv",
    "brightness": "brightness", "bright": "brightness", "brighter": "brightness", "darker": "brightness",
    "parlaklık": "brightness", "contrast": "contrast", "kontrast": "contrast",
    "saturation": "saturation", "colour": "saturation", "color": "saturation", "doygunluk": "saturation",
    "sharpen": "sharpen", "sharp": "sharpen", "keskin": "sharpen", "blur": "blur", "bulanık": "blur",
    "crop": "crop", "kırp": "crop", "resize": "resize", "boyut": "resize", "auto": "auto", "otomatik": "auto",
    "square": "square", "kare": "square",
    **{name: name for name in FILTERS}, "bw": "grayscale", "black": "grayscale", "siyah": "grayscale",
}


def parse_ops(text: str) -> list[tuple[str, float | None]]:
    """'rotate 90, brightness 1.2, grayscale, crop 10%' → [("rotate", 90), ("brightness", 1.2), …].

    Words a person would use work too: "brighter" means brightness 1.2,
    "darker" 0.8; a percentage after brightness, contrast or saturation is
    read as a change ("+20%" → 1.2).
    """
    ops: list[tuple[str, float | None]] = []
    for part in re.split(r"[,;\n]+|\band\b|\bve\b", text.lower()):
        words = part.split()
        if not words:
            continue
        name = next((OP_WORDS[w] for w in words if w in OP_WORDS), None)
        if name is None:
            raise MediaError(f"I don't know how to {part.strip()!r}. Try: rotate 90, brightness 1.2, contrast 1.1, "
                             f"saturation 0.8, sharpen, blur 2, crop 10%, square, resize 1080, auto, "
                             f"or a filter: {', '.join(FILTERS)}.")
        m = re.search(r"([+-]?\d+(?:[.,]\d+)?)\s*(%)?", part)
        value = None
        if m:
            value = float(m.group(1).replace(",", "."))
            if m.group(2) and name in {"brightness", "contrast", "saturation"}:
                value = 1 + value / 100
        if name == "brightness" and value is None:
            value = 0.8 if "darker" in words else 1.2
        ops.append((name, value))
    if not ops:
        raise MediaError("Say what to change, for example: rotate 90, brightness 1.2, grayscale.")
    return ops


def apply_ops(image, ops: list[tuple[str, float | None]]):
    """The picture with each change applied in order (Pillow image in, image out)."""
    from PIL import Image, ImageEnhance, ImageFilter, ImageOps

    image = ImageOps.exif_transpose(image)
    if image.mode not in {"RGB", "RGBA"}:
        image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
    for name, value in ops:
        if name == "rotate":
            image = image.rotate(-(value if value is not None else 90), expand=True)   # clockwise, as people say it
        elif name == "flip":
            image = ImageOps.mirror(image)
        elif name == "flipv":
            image = ImageOps.flip(image)
        elif name in {"brightness", "contrast", "saturation"}:
            factor = max(0.0, value if value is not None else 1.2)
            enhancer = {"brightness": ImageEnhance.Brightness, "contrast": ImageEnhance.Contrast,
                        "saturation": ImageEnhance.Color}[name]
            image = enhancer(image).enhance(factor)
        elif name == "sharpen":
            image = ImageEnhance.Sharpness(image).enhance(value if value is not None else 2.0)
        elif name == "blur":
            image = image.filter(ImageFilter.GaussianBlur(value if value is not None else 2))
        elif name == "crop":
            share = min(45.0, max(0.0, value if value is not None else 10)) / 100
            w, h = image.size
            image = image.crop((round(w * share), round(h * share), round(w * (1 - share)), round(h * (1 - share))))
        elif name == "square":
            side = min(image.size)
            w, h = image.size
            image = image.crop(((w - side) // 2, (h - side) // 2, (w - side) // 2 + side, (h - side) // 2 + side))
        elif name == "resize":
            scale = int(value or 1080) / max(image.size)       # the longest side, up or down
            image = image.resize((max(1, round(image.width * scale)), max(1, round(image.height * scale))),
                                 Image.LANCZOS)
        elif name == "auto":
            rgb = image.convert("RGB")
            image = ImageOps.autocontrast(rgb, cutoff=1)
            image = ImageEnhance.Color(image).enhance(1.1)
        else:
            image = apply_filter(image, name)
    return image


def apply_filter(image, name: str):
    from PIL import ImageEnhance, ImageOps

    alpha = image.getchannel("A") if image.mode == "RGBA" else None
    rgb = image.convert("RGB")
    if name == "grayscale":
        out = ImageOps.grayscale(rgb).convert("RGB")
    elif name == "sepia":
        out = ImageOps.colorize(ImageOps.grayscale(rgb), "#2b1d0e", "#f3e3c3", mid="#a1784f")
    elif name == "vivid":
        out = ImageEnhance.Contrast(ImageEnhance.Color(rgb).enhance(1.45)).enhance(1.1)
    elif name in {"warm", "cool"}:
        from PIL import Image

        r, g, b = rgb.split()
        red, blue = (1.08, 0.9) if name == "warm" else (0.92, 1.08)
        out = Image.merge("RGB", (r.point(lambda v: min(255, int(v * red))), g,
                                  b.point(lambda v: min(255, int(v * blue)))))
    elif name == "fade":
        out = ImageEnhance.Contrast(ImageEnhance.Color(rgb).enhance(0.7)).enhance(0.85)
    elif name == "invert":
        out = ImageOps.invert(rgb)
    else:
        raise MediaError(f"No filter called {name}.")
    if alpha is not None:
        out = out.convert("RGBA")
        out.putalpha(alpha)
    return out


def edited_path(source: Path, tag: str = "edited", suffix: str | None = None) -> Path:
    """Next to the original, never over it: photo_edited.jpg, photo_edited-2.jpg…"""
    source = Path(source)
    suffix = suffix or (source.suffix if source.suffix.lower() in IMAGE_EXT else ".png")
    folder = source.parent
    try:
        probe = folder / ".jarvis-write-test"
        probe.touch()
        probe.unlink()
    except OSError:
        folder = kit.output_dir("images")
    path = folder / f"{source.stem}_{tag}{suffix}"
    n = 2
    while path.exists():
        path = folder / f"{source.stem}_{tag}-{n}{suffix}"
        n += 1
    return path


def save_picture(image, path: Path) -> Path:
    if path.suffix.lower() in {".jpg", ".jpeg"} and image.mode == "RGBA":
        image = image.convert("RGB")
    options = {"quality": 92} if path.suffix.lower() in {".jpg", ".jpeg", ".webp"} else {}
    image.save(path, **options)
    return path


# --- faces ----------------------------------------------------------------------------------------

def blur_regions(image, boxes: list[tuple[int, int, int, int]], strength: float = 1.0, pad: float = 0.18):
    """Each box blurred inside a soft-edged oval, so it reads as a face, not a sticker."""
    from PIL import Image, ImageDraw, ImageFilter

    out = image.copy()
    for x, y, w, h in boxes:
        grow_w, grow_h = w * pad, h * pad * 1.3
        left, top = max(0, int(x - grow_w)), max(0, int(y - grow_h))
        right, bottom = min(image.width, int(x + w + grow_w)), min(image.height, int(y + h + grow_h))
        if right - left < 2 or bottom - top < 2:
            continue
        region = out.crop((left, top, right, bottom))
        radius = max(4, int(max(w, h) * 0.12 * strength))
        blurred = region.filter(ImageFilter.GaussianBlur(radius))
        mask = Image.new("L", region.size, 0)
        ImageDraw.Draw(mask).ellipse((0, 0, region.width - 1, region.height - 1), fill=255)
        mask = mask.filter(ImageFilter.GaussianBlur(max(2, radius // 3)))
        region.paste(blurred, (0, 0), mask)
        out.paste(region, (left, top))
    return out


def blur_faces(path: Path, strength: float = 1.0) -> tuple[Path, int]:
    """(the blurred copy, how many faces). The copy keeps no camera metadata."""
    from PIL import Image

    from .. import winrt

    boxes = winrt.faces(path)
    with Image.open(path) as image:
        image.load()
        # Windows reports boxes in the pixels as stored, before the EXIF
        # rotation a phone photo carries, so blur first and turn it upright after.
        picture = image.convert("RGBA" if image.mode in {"RGBA", "LA", "P"} else "RGB")
        orientation = image.getexif().get(0x0112, 1)
    out = blur_regions(picture, boxes, strength)
    turn = {2: Image.Transpose.FLIP_LEFT_RIGHT, 3: Image.Transpose.ROTATE_180, 4: Image.Transpose.FLIP_TOP_BOTTOM,
            5: Image.Transpose.TRANSPOSE, 6: Image.Transpose.ROTATE_270, 7: Image.Transpose.TRANSVERSE,
            8: Image.Transpose.ROTATE_90}.get(orientation)
    if turn is not None:
        out = out.transpose(turn)
    target = edited_path(Path(path), "faces-blurred")
    return save_picture(out, target), len(boxes)


# --- audio ----------------------------------------------------------------------------------------

def _frames(samples: np.ndarray, size: int, hop: int) -> np.ndarray:
    pad = (-(len(samples) - size) % hop) if len(samples) > size else size - len(samples)
    padded = np.concatenate([np.zeros(size // 2, np.float32), samples, np.zeros(pad + size // 2, np.float32)])
    count = 1 + (len(padded) - size) // hop
    index = np.arange(size)[None, :] + hop * np.arange(count)[:, None]
    return padded[index]


def denoise(samples: np.ndarray, rate: int, strength: float = 1.0) -> np.ndarray:
    """Spectral noise reduction: learn the steady hiss from the quietest
    moments, then turn each frequency down by how much of it is that hiss.

    The gain is smoothed over neighbouring frames and kept above a floor,
    which is what stops the "underwater" warble cruder subtraction leaves.
    """
    if len(samples) < rate // 4:
        return samples.copy()
    size = 2048 if rate >= 32000 else 1024
    hop = size // 4
    window = np.hanning(size).astype(np.float32)
    frames = _frames(samples.astype(np.float32), size, hop) * window
    spectrum = np.fft.rfft(frames, axis=1)
    magnitude = np.abs(spectrum)
    energy = magnitude.sum(axis=1)
    quiet = magnitude[energy <= np.percentile(energy, 15)]
    noise = (quiet if len(quiet) else magnitude).mean(axis=0) * (1.0 + 0.6 * strength)
    gain = np.clip(1.0 - (noise[None, :] / np.maximum(magnitude, 1e-9)) ** 2, 0.0, 1.0)
    gain = np.sqrt(gain)
    kernel = np.ones(5) / 5
    gain = np.apply_along_axis(lambda column: np.convolve(column, kernel, mode="same"), 0, gain)
    floor = max(0.04, 0.25 - 0.1 * strength)
    gain = floor + (1 - floor) * gain
    cleaned = np.fft.irfft(spectrum * gain, n=size, axis=1) * window
    out = np.zeros(hop * (len(cleaned) - 1) + size, np.float32)
    norm = np.zeros_like(out)
    for i, frame in enumerate(cleaned):
        out[i * hop:i * hop + size] += frame
        norm[i * hop:i * hop + size] += window ** 2
    out = out / np.maximum(norm, 1e-6)
    start = size // 2
    return out[start:start + len(samples)].astype(np.float32)


def remove_silences(samples: np.ndarray, rate: int, min_pause: float = 0.6, keep: float = 0.2,
                    threshold_db: float = -32.0) -> tuple[np.ndarray, float]:
    """(shorter audio, seconds taken out). Pauses longer than min_pause are cut
    down to `keep` seconds, so speech still breathes; "silence" is anything
    `threshold_db` below the recording's own loud level, not an absolute value,
    so a quiet recording isn't all cut away."""
    hop = max(1, int(rate * 0.02))
    count = len(samples) // hop
    if count < 3:
        return samples.copy(), 0.0
    rms = np.sqrt(np.mean(samples[:count * hop].reshape(count, hop) ** 2, axis=1) + 1e-12)
    loud = np.percentile(rms, 95)
    silent = rms < loud * 10 ** (threshold_db / 20)
    keep_frames = max(1, int(keep / 0.02))
    min_frames = max(keep_frames + 1, int(min_pause / 0.02))
    pieces, removed, i = [], 0, 0
    last = 0
    while i < count:
        if silent[i]:
            j = i
            while j < count and silent[j]:
                j += 1
            if j - i >= min_frames:
                half = keep_frames // 2
                cut_from, cut_to = (i + half) * hop, (j - (keep_frames - half)) * hop
                pieces.append(samples[last:cut_from])
                removed += cut_to - cut_from
                last = cut_to
            i = j
        else:
            i += 1
    pieces.append(samples[last:])
    return np.concatenate(pieces).astype(np.float32), removed / rate


def loudest_window(samples: np.ndarray, rate: int, seconds: float) -> float:
    """Where the loudest `seconds` start — usually the chorus, for a ringtone."""
    length = int(seconds * rate)
    if len(samples) <= length:
        return 0.0
    hop = max(1, rate // 10)
    energy = np.add.reduceat(samples ** 2, np.arange(0, len(samples), hop))
    span = max(1, length // hop)
    running = np.convolve(energy, np.ones(span), mode="valid")
    # Skip the first and last few seconds: intros and fade-outs are rarely the hook.
    margin = min(len(running) // 4, int(5 * rate / hop))
    best = margin + int(np.argmax(running[margin:len(running) - margin])) if len(running) > 2 * margin else 0
    return best * hop / rate


def ringtone(samples: np.ndarray, rate: int, start: float | None, seconds: float = 30.0,
             fade: float = 1.0) -> tuple[np.ndarray, float]:
    """(the clip, where it starts). Faded in and out so it doesn't click."""
    seconds = max(3.0, min(40.0, seconds))
    if start is None:
        start = loudest_window(samples, rate, seconds)
    first = int(max(0.0, start) * rate)
    clip = samples[first:first + int(seconds * rate)].astype(np.float32).copy()
    if not len(clip):
        raise MediaError("That start time is past the end of the song.")
    ramp = min(len(clip) // 2, int(fade * rate))
    if ramp:
        curve = np.linspace(0.0, 1.0, ramp, dtype=np.float32)
        clip[:ramp] *= curve
        clip[-ramp:] *= curve[::-1]
    peak = float(np.max(np.abs(clip))) or 1.0
    return clip * min(1.0, 0.95 / peak) if peak > 0.95 else clip, first / rate


def parse_time(text: str) -> float | None:
    """'1:05' → 65.0, '75' → 75.0, '' → None."""
    text = (text or "").strip().lower().rstrip("s")
    if not text:
        return None
    if ":" in text:
        minutes, _, seconds = text.partition(":")
        return int(minutes or 0) * 60 + float(seconds or 0)
    return float(text.replace(",", "."))


def audio_out(source: Path, tag: str, suffix: str = ".mp3") -> Path:
    folder = kit.output_dir("audio")
    return folder / f"{kit.slug(Path(source).stem)}_{tag}_{kit.stamp()}{suffix}"


def _audio_arg(path_text: str) -> Path:
    path = kit.path_arg(path_text)
    if path is None or path.suffix.lower() not in AUDIO_EXT | VIDEO_EXT:
        raise MediaError("Give an audio file (MP3, WAV, M4A, WMA…) — or pick one on the Media page.")
    return path


class Media:
    @command("gallery", "photos", group=G, usage="/gallery [folder]", help="your newest photos and videos",
             title="Photo and video gallery", icon="🖼", page="media",
             fields=(field("folder", "folder", "Folder", optional=True, hint="Pictures"),))
    def gallery_cmd(self, args: str, routed: bool = False):
        folder = kit.path_arg(args) or default_folder()
        if not folder.is_dir():
            return f"I can't find the folder {folder}."
        files = media_files(folder)
        photos = [f for f in files if f.suffix.lower() in IMAGE_EXT]
        videos = [f for f in files if f.suffix.lower() in VIDEO_EXT]
        if not files:
            return f"🖼 No photos or videos in {folder}."
        lines = [f"🖼 {len(photos)} photo(s) and {len(videos)} video(s) in {folder} (newest first). "
                 f"The Media page shows them all."]
        lines += [str(p) for p in photos[:3]]
        return "\n".join(lines)

    @command("photoedit", "editphoto", group=G, usage="/photoedit <photo> | <changes>",
             help="edit a photo in words: rotate, brightness, contrast, crop, filters — saved as a copy",
             title="Photo editor", icon="🎨", page="media",
             fields=(field("photo", "file", "Photo", types=PICTURE_TYPES),
                     field("changes", "text", "Changes", "auto", hint="rotate 90, brightness 1.2, sepia")))
    def photoedit_cmd(self, args: str, routed: bool = False):
        path_text, changes = split(args, 2)
        path = kit.path_arg(path_text)
        if path is None:
            return ("Usage: /photoedit C:/photo.jpg | rotate 90, brightness 1.2, sepia\n"
                    f"Changes: rotate, flip, brightness, contrast, saturation, sharpen, blur, crop 10%, square, "
                    f"resize 1080, auto; filters: {', '.join(FILTERS)}.")
        from PIL import Image

        try:
            ops = parse_ops(changes or "auto")
            with Image.open(path) as image:
                image.load()
                out = apply_ops(image, ops)
        except MediaError as exc:
            return str(exc)
        except OSError:
            return "I can't open that as a picture."
        target = save_picture(out, edited_path(path))
        return f"🎨 Edited ({', '.join(n + (f' {v:g}' if v is not None else '') for n, v in ops)}) — saved a copy:\n{target}"

    @command("blurfaces", group=G, usage="/blurfaces <photo> [| strength 1-3]",
             help="blurs every face in a photo before you share it (a copy, without location data)",
             title="Blur faces in photos", icon="😶", page="media",
             fields=(field("photo", "file", "Photo", types=PICTURE_TYPES),
                     field("strength", "choice", "Blur", "1", ("1", "2", "3"))))
    def blurfaces_cmd(self, args: str, routed: bool = False):
        path_text, strength = split(args, 2)
        path = kit.path_arg(path_text)
        if path is None:
            return "Usage: /blurfaces C:/photo.jpg — I'll blur every face and save a copy."
        from .. import winrt

        try:
            target, count = blur_faces(path, float(strength or 1))
        except winrt.WinRTError as exc:
            return f"😶 {exc}"
        except (OSError, ValueError):
            return "I can't open that as a picture."
        if not count:
            return f"😶 I found no faces in {path.name}. (Very small or sideways faces can be missed.)\n{target}"
        return f"😶 Blurred {count} face(s). The copy has no location or camera data:\n{target}"

    @command("denoise", "noisereduce", group=G, usage="/denoise <audio> [| low|medium|high]",
             help="takes the hiss and hum out of a recording", title="Noise reduction", icon="🎚", page="media",
             fields=(field("audio", "file", "Recording", types=AUDIO_TYPES),
                     field("strength", "choice", "Strength", "medium", ("low", "medium", "high"))))
    def denoise_cmd(self, args: str, routed: bool = False):
        from .. import audiofile, winrt

        path_text, level = split(args, 2)
        try:
            path = _audio_arg(path_text)
            samples, rate = audiofile.load(path)
            strength = {"low": 0.5, "high": 1.6}.get(level.strip().lower(), 1.0)
            started = time.time()
            cleaned = denoise(samples, rate, strength)
            target = audiofile.save(cleaned, rate, audio_out(path, "clean", ".mp3"))
        except (MediaError, winrt.WinRTError) as exc:
            return f"🎚 {exc}"
        return (f"🎚 Cleaned {audiofile.duration(samples, rate):.0f} s of audio in {time.time() - started:.1f} s "
                f"({level.strip() or 'medium'}):\n{target}")

    @command("cutsilence", "removesilence", group=G, usage="/cutsilence <audio> [| longest pause to keep, seconds]",
             help="cuts the long pauses out of a recording", title="Remove silences", icon="✂", page="media",
             fields=(field("audio", "file", "Recording", types=AUDIO_TYPES),
                     field("pause", "number", "Cut pauses longer than (s)", "0.6")))
    def cutsilence_cmd(self, args: str, routed: bool = False):
        from .. import audiofile, winrt

        path_text, pause = split(args, 2)
        try:
            path = _audio_arg(path_text)
            samples, rate = audiofile.load(path)
            shorter, removed = remove_silences(samples, rate, min_pause=float(pause or 0.6))
            if removed < 0.5:
                return f"✂ {path.name} has no long pauses to cut."
            target = audiofile.save(shorter, rate, audio_out(path, "tight", ".mp3"))
        except (MediaError, winrt.WinRTError, ValueError) as exc:
            return f"✂ {exc}"
        before = audiofile.duration(samples, rate)
        return (f"✂ Cut {removed:.1f} s of silence: {before:.0f} s → {before - removed:.0f} s.\n{target}")

    @command("ringtone", group=G, usage="/ringtone <song> [| start m:ss] [| seconds] [| iphone|android]",
             help="a ringtone from any song: the catchiest 30 s, or the part you choose, faded in and out",
             title="Ringtone maker", icon="🔔", page="media",
             fields=(field("song", "file", "Song", types=AUDIO_TYPES),
                     field("start", "text", "Start (m:ss)", optional=True, hint="the loudest part"),
                     field("seconds", "number", "Length (s)", "30"),
                     field("phone", "choice", "Phone", "android", ("android", "iphone"))))
    def ringtone_cmd(self, args: str, routed: bool = False):
        from .. import audiofile, winrt

        path_text, start_text, seconds, phone = split(args, 4)
        try:
            path = _audio_arg(path_text)
            start = parse_time(start_text)
            samples, rate = audiofile.load(path)
            clip, began = ringtone(samples, rate, start, float(seconds or 30))
            iphone = phone.strip().lower() == "iphone"
            target = audio_out(path, "ringtone", ".m4a" if iphone else ".mp3")
            audiofile.save(clip, rate, target)
            if iphone:
                target = target.rename(target.with_suffix(".m4r"))
        except (MediaError, winrt.WinRTError, ValueError) as exc:
            return f"🔔 {exc}"
        where = "the loudest part" if start is None else "where you chose"
        return (f"🔔 A {len(clip) / rate:.0f} s ringtone from {int(began // 60)}:{int(began % 60):02d} ({where})"
                + (" — for iPhone, add it through Finder or iTunes." if iphone else ".") + f"\n{target}")
