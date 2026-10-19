# software/book_studio/engine.py
# First-time setup and the OCR engine: picks and downloads the right llama-server build for this computer (Metal on Mac,
# Vulkan with a CPU fallback on Windows/Linux), gets the Surya model (download or a copy from a folder/USB stick),
# makes the Desktop icon, and cleans up a llama-server left running after a crash.

import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable

from . import paths
from .store import Settings

sys.path.insert(0, str(paths.PIPELINE_DIR))
# The pipeline needs to know its folders before it is imported; inside Book Studio they are always the app's own
paths.ensure_dirs()
for _key, _value in paths.pipeline_env().items():
    os.environ.setdefault(_key, _value)
from local_env import find_llama_server  # noqa: E402  (shared with the manual pipeline)

LLAMA_TAG = "b11623"  # the llama.cpp release the 13 finished books were OCR'd with
MODEL_REPO = "datalab-to/surya-ocr-2-gguf"
MODEL_REVISION = "6a3a4c30e5e74446d4f8b6afd05b2f2da970f470"  # pinned: same model on every computer
NO_WINDOW = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW: no black console flashing up on Windows

Progress = Callable[[str, float], None]  # (what is happening, 0..1)


def engine_candidates() -> list[str]:
    """llama.cpp builds to try, best first. Vulkan uses any NVIDIA/AMD/Intel graphics card; the CPU build always works."""
    machine = platform.machine().lower()
    arm = machine in ("arm64", "aarch64")
    if sys.platform == "darwin":
        return ["macos-arm64" if arm else "macos-x64"]
    if os.name == "nt":
        return ["win-vulkan-arm64", "win-cpu-arm64"] if arm else ["win-vulkan-x64", "win-cpu-x64"]
    return ["ubuntu-vulkan-arm64", "ubuntu-arm64"] if arm else ["ubuntu-vulkan-x64", "ubuntu-x64"]


def engine_label(name: str) -> str:
    if name.startswith("macos"):
        return "Apple graphics chip (Metal)"
    if "vulkan" in name:
        return "Graphics card (Vulkan)"
    return "Processor only (no graphics card found — slower)" if name else "Not installed"


def llama_server() -> Path | None:
    return find_llama_server(paths.WORK_DIR / "tools")


def engine_ready() -> bool:
    return llama_server() is not None


def model_ready() -> bool:
    return all((paths.MODEL_DIR / f).is_file() and (paths.MODEL_DIR / f).stat().st_size > 1_000_000 for f in paths.MODEL_FILES)


def download(url: str, target: Path, progress: Progress, label: str) -> None:
    """Streams a file to disk, resuming a half-finished download (big model files over weak Wi-Fi)."""
    part = target.with_name(target.name + ".part")
    have = part.stat().st_size if part.exists() else 0
    request = urllib.request.Request(url, headers={"User-Agent": "BookStudio", **({"Range": f"bytes={have}-"} if have else {})})
    with urllib.request.urlopen(request, timeout=60) as response:
        if have and response.status != 206:  # server ignored the resume request: start over
            have = 0
        total = have + int(response.headers.get("Content-Length") or 0)
        with open(part, "ab" if have else "wb") as out:
            done = have
            while chunk := response.read(1 << 20):
                out.write(chunk)
                done += len(chunk)
                progress(f"{label} — {done / 1e6:,.0f} of {total / 1e6:,.0f} MB", done / total if total else 0)
    os.replace(part, target)


def _unpack(archive: Path, dest: Path) -> None:
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as z:
            z.extractall(dest)
    else:
        with tarfile.open(archive) as t:
            t.extractall(dest, filter="data")  # 'data' refuses paths that would escape dest


def _engine_works(server: Path, name: str) -> bool:
    """The build starts on this computer; for a Vulkan build, it also sees a graphics card."""
    if os.name != "nt":
        for f in server.parent.iterdir():
            if f.is_file() and (f.name.startswith("llama-") or f.suffix in ("", ".so", ".dylib")):
                f.chmod(0o755)
    try:
        flag = "--list-devices" if "vulkan" in name else "--version"
        result = subprocess.run([str(server), flag], capture_output=True, text=True, timeout=120, creationflags=NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and ("vulkan" not in name or "Vulkan" in result.stdout + result.stderr)


def install_engine(settings: Settings, progress: Progress) -> str:
    """Downloads the first llama.cpp build that runs here; returns its name (kept in settings)."""
    root = paths.WORK_DIR / "tools" / "llama.cpp"
    for name in engine_candidates():
        ext = "zip" if name.startswith("win") else "tar.gz"
        url = f"https://github.com/ggml-org/llama.cpp/releases/download/{LLAMA_TAG}/llama-{LLAMA_TAG}-bin-{name}.{ext}"
        shutil.rmtree(root, ignore_errors=True)
        root.mkdir(parents=True)
        archive = root / f"engine.{ext}"
        download(url, archive, progress, "Downloading the page reader")
        progress("Checking the page reader works on this computer…", 1.0)
        _unpack(archive, root / name)
        archive.unlink()
        server = llama_server()
        if server and _engine_works(server, name):
            settings.engine = name
            settings.save()
            return name
    shutil.rmtree(root, ignore_errors=True)
    raise RuntimeError("The page reader could not start on this computer.")


def download_model(progress: Progress) -> None:
    for i, name in enumerate(paths.MODEL_FILES, 1):
        url = f"https://huggingface.co/{MODEL_REPO}/resolve/{MODEL_REVISION}/{name}"
        download(url, paths.MODEL_DIR / name, progress, f"Downloading the reading model ({i} of {len(paths.MODEL_FILES)})")


def find_model_files(folder: Path) -> dict[str, Path]:
    """The two model files anywhere inside a folder (a USB copy, or another computer's Book Studio data)."""
    found = {}
    for name in paths.MODEL_FILES:
        match = next((p for p in folder.rglob(name) if p.is_file()), None)
        if match:
            found[name] = match
    return found


def copy_model(files: dict[str, Path], progress: Progress) -> None:
    total = sum(p.stat().st_size for p in files.values())
    done = 0
    for name, src in files.items():
        part = paths.MODEL_DIR / (name + ".part")
        with open(src, "rb") as fin, open(part, "wb") as fout:
            while chunk := fin.read(8 << 20):
                fout.write(chunk)
                done += len(chunk)
                progress(f"Copying the reading model — {done / 1e6:,.0f} of {total / 1e6:,.0f} MB", done / total)
        os.replace(part, paths.MODEL_DIR / name)


def worker_env(settings: Settings) -> dict:
    """Environment for a worker process: pipeline paths, the engine, and this computer's speed/memory choices."""
    env = dict(os.environ) | paths.pipeline_env()
    env["SURYA_INFERENCE_PARALLEL"] = str(settings.slots)
    env["LLAMA_CPP_EXTRA_ARGS"] = f"--cache-ram 0 --threads {settings.cores}"
    server = llama_server()
    if server:
        env["LLAMA_CPP_BINARY"] = str(server)
    env["SURYA_WITHOUT_TORCH"] = "1"  # OCR runs in llama-server; PyTorch is never loaded (Windows Smart App Control blocks it)
    env["HF_HUB_OFFLINE"] = "1"  # the model is already on disk: never reach for the internet while working on books
    env["PYTHONIOENCODING"] = "utf-8"  # diacritics in log lines on Windows consoles
    return env


def stop_stray_server() -> None:
    """Surya starts llama-server detached and stops it when the worker exits normally; after a forced stop, this cleans up."""
    sentinel = Path.home() / ".cache" / "datalab" / "surya" / "llamacpp_server.json"
    try:
        pid = json.loads(sentinel.read_text())["pid"]
    except (OSError, ValueError, KeyError):
        return
    try:
        os.kill(pid, 15)
    except OSError:
        pass
    sentinel.unlink(missing_ok=True)


# ---------- Desktop icon ----------

def launcher_script() -> Path:
    return paths.BUNDLE_DIR / ("Start Book Studio.bat" if os.name == "nt" else "start-book-studio.sh")


def _python_gui() -> Path:
    venv = paths.RUNTIME_DIR / "venv"
    return venv / "Scripts" / "pythonw.exe" if os.name == "nt" else venv / "bin" / "python"


def create_shortcuts() -> list[str]:
    """A 'Book Studio' icon on the Desktop (and in Applications / Start menu), made on this computer so it opens without warnings."""
    if not paths.IS_INSTALLED:
        return []
    if sys.platform == "darwin":
        return _mac_app()
    if os.name == "nt":
        return _windows_shortcuts()
    return _linux_desktop_files()


def _mac_app() -> list[str]:
    made = []
    for folder in (Path.home() / "Applications", Path.home() / "Desktop"):
        app = folder / "Book Studio.app"
        shutil.rmtree(app, ignore_errors=True)
        (app / "Contents" / "MacOS").mkdir(parents=True)
        (app / "Contents" / "Resources").mkdir()
        shutil.copy(paths.ASSETS_DIR / "icon.icns", app / "Contents" / "Resources" / "icon.icns")
        (app / "Contents" / "Info.plist").write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
            '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n<plist version="1.0"><dict>\n'
            "<key>CFBundleName</key><string>Book Studio</string>\n<key>CFBundleExecutable</key><string>BookStudio</string>\n"
            "<key>CFBundleIdentifier</key><string>org.iskcon.youthforum.bookstudio</string>\n"
            "<key>CFBundleIconFile</key><string>icon</string>\n<key>CFBundlePackageType</key><string>APPL</string>\n"
            "<key>NSHighResolutionCapable</key><true/>\n</dict></plist>\n", encoding="utf-8")
        exe = app / "Contents" / "MacOS" / "BookStudio"
        exe.write_text(f'#!/bin/sh\ncd "{paths.APP_DIR}"\nexec "{_python_gui()}" -m book_studio\n', encoding="utf-8")
        exe.chmod(0o755)
        made.append(str(app))
    return made


def _windows_shortcuts() -> list[str]:
    script = (
        "$shell = New-Object -ComObject WScript.Shell; "
        "$places = @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs')); "
        "foreach ($p in $places) { $s = $shell.CreateShortcut((Join-Path $p 'Book Studio.lnk')); "
        f"$s.TargetPath = '{_python_gui()}'; $s.Arguments = '-m book_studio'; $s.WorkingDirectory = '{paths.APP_DIR}'; "
        f"$s.IconLocation = '{paths.ASSETS_DIR / 'icon.ico'}'; $s.Save(); Write-Output (Join-Path $p 'Book Studio.lnk') }}"
    )
    result = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                            capture_output=True, text=True, creationflags=NO_WINDOW)
    return result.stdout.split()


def _linux_desktop_files() -> list[str]:
    entry = (f"[Desktop Entry]\nType=Application\nName=Book Studio\nComment=Clean PDFs and EPUBs from scanned books\n"
             f'Exec="{_python_gui()}" -m book_studio\nPath={paths.APP_DIR}\nIcon={paths.ASSETS_DIR / "icon.png"}\n'
             "Terminal=false\nCategories=Office;Publishing;\n")
    made = []
    for folder in (Path.home() / ".local" / "share" / "applications", Path.home() / "Desktop"):
        if folder.parent.exists():
            folder.mkdir(parents=True, exist_ok=True)
            f = folder / "book-studio.desktop"
            f.write_text(entry, encoding="utf-8")
            f.chmod(0o755)
            made.append(str(f))
    return made
