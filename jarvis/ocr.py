"""Text from the screen or an image, read by Windows itself — offline.

Windows 10 and 11 ship an OCR engine (Windows.Media.Ocr). JARVIS reaches it
through PowerShell, so there is nothing to install and nothing leaves the
PC: no screenshot is uploaded, unlike /see which asks an AI to look.

Each recognizer is good at its own language and poor at others — the
English one reads "şimdi" as "9imdi", the Turkish one reads "Invoice" as
"ınvoice". So both are run and, line by line, the reading that suits the
line is kept.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

_SCRIPT = r'''
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics, ContentType = WindowsRuntime]
$null = [Windows.Globalization.Language, Windows.Globalization, ContentType = WindowsRuntime]
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, [Type]$type) {
    $task = $asTask.MakeGenericMethod($type).Invoke($null, @($op))
    $task.Wait(-1) | Out-Null
    $task.Result
}
$file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($args[0])) ([Windows.Storage.StorageFile])
$stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
$decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$tags = @([Windows.Media.Ocr.OcrEngine]::AvailableRecognizerLanguages | ForEach-Object { $_.LanguageTag })
$wanted = @('tr', 'en-US', 'en-GB') | Where-Object { $tags -contains $_ }
if ($wanted.Count -eq 0) { $wanted = @('profile') }
foreach ($tag in $wanted) {
    if ($tag -eq 'profile') { $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages() }
    else { $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage([Windows.Globalization.Language]::new($tag)) }
    if ($null -eq $engine) { continue }
    $result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
    "@@@ $tag"
    $result.Lines | ForEach-Object { $_.Text }
}
'''

TURKISH_ONLY = set("şğçŞĞÇ")


class OcrError(Exception):
    pass


def available() -> bool:
    return sys.platform == "win32"


def _parse(output: str) -> dict[str, list[str]]:
    readings: dict[str, list[str]] = {}
    current = None
    for line in output.splitlines():
        if line.startswith("@@@ "):
            current = line[4:].strip()
            readings[current] = []
        elif current is not None and line.strip():
            readings[current].append(line.rstrip())
    return readings


def _noise(line: str) -> int:
    """Signs of a misread: digits inside words, a dotless ı opening a word."""
    words = line.split()
    mixed = sum(1 for w in words if any(c.isdigit() for c in w) and sum(c.isalpha() for c in w) >= 2
                and not any(c in w for c in "-:/.,"))
    dotless = sum(1 for w in words if w.startswith("ı") and len(w) > 2)
    return mixed + dotless


def merge(readings: dict[str, list[str]]) -> str:
    """Pick, per line, whichever language's reading looks right."""
    turkish = readings.get("tr")
    english = readings.get("en-US") or readings.get("en-GB")
    if not turkish or not english:
        return "\n".join(next(iter(readings.values()), []))
    if len(turkish) != len(english):
        # Different segmentation: take the whole reading with less noise.
        tr_noise = sum(_noise(l) for l in turkish) - sum(1 for l in turkish if TURKISH_ONLY & set(l))
        en_noise = sum(_noise(l) for l in english)
        return "\n".join(turkish if tr_noise < en_noise else english)
    out = []
    for tr_line, en_line in zip(turkish, english):
        if TURKISH_ONLY & set(tr_line) or _noise(en_line) > _noise(tr_line):
            out.append(tr_line)
        else:
            out.append(en_line)
    return "\n".join(out)


def read_image(path: Path, timeout: int = 60) -> str:
    if not available():
        raise OcrError("Reading text from images uses Windows' built-in OCR, so it needs Windows.")
    script = Path(tempfile.gettempdir()) / "jarvis-ocr.ps1"
    script.write_text(_SCRIPT, encoding="utf-8-sig")
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-File", str(script), str(Path(path).resolve())],
            capture_output=True, timeout=timeout, creationflags=NO_WINDOW,
        )
    except subprocess.TimeoutExpired:
        raise OcrError("Windows OCR did not finish in time.") from None
    output = proc.stdout.decode("utf-8", "replace")
    if proc.returncode != 0 and "@@@" not in output:
        detail = proc.stderr.decode("utf-8", "replace").strip().splitlines()
        raise OcrError("Windows OCR failed: " + (detail[-1][:160] if detail else f"exit {proc.returncode}"))
    return merge(_parse(output)).strip()


def read_region(box: tuple[int, int, int, int] | None = None) -> str:
    """OCR part of the screen (x1, y1, x2, y2), or all of it."""
    from PIL import ImageGrab

    return read_image_from(ImageGrab.grab(bbox=box, all_screens=True))


def read_image_from(image) -> str:
    """OCR a PIL image — a screenshot, or a box cut out of one."""
    image = image.convert("RGB")
    # Small text reads far better enlarged; the engine is tuned for ~30px glyphs.
    if image.width < 1600:
        scale = min(3, max(1, 1600 // max(1, image.width)))
        image = image.resize((image.width * scale, image.height * scale))
    path = Path(tempfile.gettempdir()) / "jarvis-ocr.png"
    image.save(path)
    try:
        return read_image(path)
    finally:
        try:
            path.unlink()
        except OSError:
            pass
