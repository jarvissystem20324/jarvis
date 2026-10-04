"""Windows' own engines, reached through PowerShell (10.0).

ocr.py showed the way: Windows 10 and 11 ship engines for things that would
otherwise mean a large dependency, and PowerShell can call them with nothing
installed. This module adds four:

  * Windows.Data.Pdf      — PDF pages as pictures (page thumbnails, placing a
                             signature, importing PDF pages into a design)
  * FaceAnalysis          — where the faces are, to blur them
  * Media.Transcoding     — any audio Windows can play, to WAV / MP3 / M4A
  * Storage thumbnails    — Explorer's thumbnails, for videos in the gallery

Each runs as one short PowerShell process. Nothing leaves the PC.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

PRELUDE = r'''
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Storage.StorageFolder, Windows.Storage, ContentType = WindowsRuntime]
$methods = [System.WindowsRuntimeSystemExtensions].GetMethods()
$asTask = ($methods | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
$asTaskAction = ($methods | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncAction' })[0]
$asTaskProgress = ($methods | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncActionWithProgress`1' })[0]
function Await($op, [Type]$type) {
    $task = $asTask.MakeGenericMethod($type).Invoke($null, @($op))
    $task.Wait(-1) | Out-Null
    $task.Result
}
function AwaitAction($op) {
    $task = $asTaskAction.Invoke($null, @($op))
    $task.Wait(-1) | Out-Null
}
function AwaitProgress($op, [Type]$type) {
    $task = $asTaskProgress.MakeGenericMethod($type).Invoke($null, @($op))
    $task.Wait(-1) | Out-Null
}
function OpenFile($path) { Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($path)) ([Windows.Storage.StorageFile]) }
function OpenFolder($path) { Await ([Windows.Storage.StorageFolder]::GetFolderFromPathAsync($path)) ([Windows.Storage.StorageFolder]) }
'''

PDF = PRELUDE + r'''
$null = [Windows.Data.Pdf.PdfDocument, Windows.Data.Pdf, ContentType = WindowsRuntime]
$file = OpenFile $args[0]
$doc = Await ([Windows.Data.Pdf.PdfDocument]::LoadFromFileAsync($file)) ([Windows.Data.Pdf.PdfDocument])
"COUNT $($doc.PageCount)"
if ($args.Count -lt 2) { exit 0 }
$folder = OpenFolder $args[1]
$width = [int]$args[2]
$wanted = @()
if ($args[3] -eq 'all') { $wanted = 0..($doc.PageCount - 1) } else { $wanted = $args[3].Split(',') | ForEach-Object { [int]$_ } }
foreach ($i in $wanted) {
    if ($i -lt 0 -or $i -ge $doc.PageCount) { continue }
    $page = $doc.GetPage([uint32]$i)
    $name = "page_{0:D4}.png" -f ($i + 1)
    $out = Await ($folder.CreateFileAsync($name, [Windows.Storage.CreationCollisionOption]::ReplaceExisting)) ([Windows.Storage.StorageFile])
    $stream = Await ($out.OpenAsync([Windows.Storage.FileAccessMode]::ReadWrite)) ([Windows.Storage.Streams.IRandomAccessStream])
    $options = New-Object Windows.Data.Pdf.PdfPageRenderOptions
    $options.DestinationWidth = [uint32]$width
    AwaitAction ($page.RenderToStreamAsync($stream, $options))
    $stream.Dispose()
    "PAGE $($i + 1) $($page.Size.Width) $($page.Size.Height) $name"
    $page.Dispose()
}
'''

FACES = PRELUDE + r'''
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics, ContentType = WindowsRuntime]
$null = [Windows.Media.FaceAnalysis.FaceDetector, Windows.Media.FaceAnalysis, ContentType = WindowsRuntime]
$file = OpenFile $args[0]
$stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
$decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
$gray = [Windows.Graphics.Imaging.SoftwareBitmap]::Convert($bitmap, [Windows.Graphics.Imaging.BitmapPixelFormat]::Gray8)
$detector = Await ([Windows.Media.FaceAnalysis.FaceDetector]::CreateAsync()) ([Windows.Media.FaceAnalysis.FaceDetector])
$faces = Await ($detector.DetectFacesAsync($gray)) ([System.Collections.Generic.IList[Windows.Media.FaceAnalysis.DetectedFace]])
"SIZE $($gray.PixelWidth) $($gray.PixelHeight)"
foreach ($f in $faces) { "FACE $($f.FaceBox.X) $($f.FaceBox.Y) $($f.FaceBox.Width) $($f.FaceBox.Height)" }
'''

AUDIO = PRELUDE + r'''
$null = [Windows.Media.Transcoding.MediaTranscoder, Windows.Media.Transcoding, ContentType = WindowsRuntime]
$null = [Windows.Media.MediaProperties.MediaEncodingProfile, Windows.Media.MediaProperties, ContentType = WindowsRuntime]
$source = OpenFile $args[0]
$folder = OpenFolder $args[1]
$out = Await ($folder.CreateFileAsync($args[2], [Windows.Storage.CreationCollisionOption]::ReplaceExisting)) ([Windows.Storage.StorageFile])
$quality = [Windows.Media.MediaProperties.AudioEncodingQuality]::High
switch ($args[3]) {
  'mp3' { $profile = [Windows.Media.MediaProperties.MediaEncodingProfile]::CreateMp3($quality) }
  'm4a' { $profile = [Windows.Media.MediaProperties.MediaEncodingProfile]::CreateM4a($quality) }
  default { $profile = [Windows.Media.MediaProperties.MediaEncodingProfile]::CreateWav($quality) }
}
$transcoder = New-Object Windows.Media.Transcoding.MediaTranscoder
$prepared = Await ($transcoder.PrepareFileTranscodeAsync($source, $out, $profile)) ([Windows.Media.Transcoding.PrepareTranscodeResult])
if (-not $prepared.CanTranscode) { "FAIL $($prepared.FailureReason)"; exit 0 }
AwaitProgress ($prepared.TranscodeAsync()) ([double])
"DONE"
'''


THUMBS = PRELUDE + r'''
$null = [Windows.Storage.FileProperties.StorageItemThumbnail, Windows.Storage, ContentType = WindowsRuntime]
$size = [uint32]$args[2]
$i = 0
foreach ($path in [System.IO.File]::ReadAllLines($args[0], [System.Text.Encoding]::UTF8)) {
    try {
        $file = OpenFile $path
        $thumb = Await ($file.GetThumbnailAsync([Windows.Storage.FileProperties.ThumbnailMode]::VideosView, $size)) ([Windows.Storage.FileProperties.StorageItemThumbnail])
        $target = Join-Path $args[1] ("thumb_{0:D4}.img" -f $i)
        $in = [System.IO.WindowsRuntimeStreamExtensions]::AsStreamForRead([Windows.Storage.Streams.IInputStream]$thumb)
        $out = [System.IO.File]::Create($target)
        $in.CopyTo($out)
        $out.Close(); $in.Close()
        "THUMB $i $target"
    } catch { "SKIP $i" }
    $i++
}
'''


class WinRTError(Exception):
    pass


def available() -> bool:
    return sys.platform == "win32"


def run(script: str, *args: str, timeout: int = 120, name: str = "winrt") -> str:
    if not available():
        raise WinRTError("This uses an engine built into Windows, so it needs Windows 10 or 11.")
    path = Path(tempfile.gettempdir()) / f"jarvis-{name}.ps1"
    path.write_text(script, encoding="utf-8-sig")
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(path), *args],
            capture_output=True, timeout=timeout, creationflags=NO_WINDOW,
        )
    except subprocess.TimeoutExpired:
        raise WinRTError("Windows took too long to answer.") from None
    out = proc.stdout.decode("utf-8", "replace")
    if proc.returncode != 0 and not out.strip():
        err = proc.stderr.decode("utf-8", "replace").strip().splitlines()
        raise WinRTError((err[0] if err else "Windows could not do that.")[:300])
    return out


def pdf_page_count(path: Path) -> int:
    out = run(PDF, str(Path(path).resolve()), name="pdf")
    for line in out.splitlines():
        if line.startswith("COUNT "):
            return int(line.split()[1])
    raise WinRTError("Windows could not open that PDF (is it password-protected?).")


def pdf_pages(path: Path, out_dir: Path, pages: list[int] | None = None, width: int = 900) -> list[dict]:
    """Render pages (1-based; None = all) to PNGs. Returns [{page, path, width_pt, height_pt}]."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    wanted = "all" if not pages else ",".join(str(p - 1) for p in pages)
    out = run(PDF, str(Path(path).resolve()), str(out_dir.resolve()), str(int(width)), wanted, name="pdf",
              timeout=300)
    found = []
    for line in out.splitlines():
        if line.startswith("PAGE "):
            _, number, w, h, name = line.split(maxsplit=4)
            found.append({"page": int(number), "path": out_dir / name.strip(), "width_pt": float(w) * 0.75,
                          "height_pt": float(h) * 0.75})
    if not found and "COUNT" not in out:
        raise WinRTError("Windows could not open that PDF (is it password-protected?).")
    return found


def faces(image: Path) -> list[tuple[int, int, int, int]]:
    """Face boxes (x, y, w, h) in pixels of the image as stored."""
    out = run(FACES, str(Path(image).resolve()), name="faces")
    boxes = []
    for line in out.splitlines():
        if line.startswith("FACE "):
            boxes.append(tuple(int(float(v)) for v in line.split()[1:5]))
    return boxes  # type: ignore[return-value]


def thumbnails(files: list[Path], out_dir: Path, size: int = 256) -> dict[Path, Path]:
    """Explorer's own thumbnails, for videos above all (Pillow can't read them).

    One PowerShell run for the whole list. Files Windows has no thumbnail for
    are simply missing from the result.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    listing = out_dir / "files.txt"
    files = [Path(f).resolve() for f in files]
    listing.write_text("\n".join(str(f) for f in files), encoding="utf-8")
    out = run(THUMBS, str(listing), str(out_dir.resolve()), str(size), name="thumbs", timeout=30 + 3 * len(files))
    found = {}
    for line in out.splitlines():
        if line.startswith("THUMB "):
            _, index, target = line.split(" ", 2)
            if 0 <= int(index) < len(files):
                found[files[int(index)]] = Path(target.strip())
    return found


def transcode(source: Path, target: Path) -> Path:
    """Convert audio Windows can play into .wav, .mp3 or .m4a (by target's suffix)."""
    target = Path(target)
    kind = target.suffix.lower().lstrip(".")
    if kind not in {"wav", "mp3", "m4a"}:
        raise WinRTError("I can write .wav, .mp3 or .m4a.")
    target.parent.mkdir(parents=True, exist_ok=True)
    out = run(AUDIO, str(Path(source).resolve()), str(target.parent.resolve()), target.name, kind, name="audio",
              timeout=600)
    if "DONE" not in out:
        reason = next((l[5:] for l in out.splitlines() if l.startswith("FAIL ")), "unsupported file")
        raise WinRTError(f"Windows couldn't convert that audio ({reason.strip()}).")
    return target
