# software/book_studio/updater.py
# Self-update from GitHub Releases: asks for the newest release (only a version number goes out — never book data),
# downloads BookStudio-<version>.zip, unpacks its app/ folder into runtime/update/, then hands over to the launcher,
# which swaps the program folder while the window is closed and installs any new packages. Books and settings are untouched.

import json
import os
import shutil
import subprocess
import urllib.request
import zipfile

from . import UPDATE_REPO, __version__, paths
from .engine import NO_WINDOW, Progress, download, launcher_script


def _version(tag: str) -> tuple[int, ...]:
    try:
        return tuple(int(x) for x in tag.lstrip("vV").split("."))
    except ValueError:
        return (0,)


def check() -> tuple[str, dict | None]:
    """Asks GitHub for the newest release: ("newer", release), ("current", newest) or ("offline", None) when it can't tell."""
    request = urllib.request.Request(f"https://api.github.com/repos/{UPDATE_REPO}/releases/latest",
                                     headers={"User-Agent": "BookStudio", "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            release = json.load(response)
    except (OSError, ValueError):
        return "offline", None
    asset = next((a for a in release.get("assets", []) if a["name"].startswith("BookStudio-") and a["name"].endswith(".zip")), None)
    info = {"version": release.get("tag_name", "").lstrip("vV"), "notes": release.get("body") or "",
            "url": asset["browser_download_url"] if asset else "", "page": release.get("html_url", "")}
    if not asset or _version(release.get("tag_name", "")) <= _version(__version__):
        return "current", info
    return "newer", info


def latest_release() -> dict | None:
    """The newest release if it is newer than this copy, else None (also when offline) — the quiet check on opening."""
    status, info = check()
    return info if status == "newer" else None


def prepare(release: dict, progress: Progress) -> None:
    """Downloads and unpacks the new program into runtime/update/app, checking it really is a Book Studio program folder."""
    staging = paths.RUNTIME_DIR / "update"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    archive = staging / "update.zip"
    download(release["url"], archive, progress, f"Downloading Book Studio {release['version']}")
    with zipfile.ZipFile(archive) as z:
        for name in z.namelist():
            if name.startswith("BookStudio/app/") and ".." not in name.split("/"):
                z.extract(name, staging)
    archive.unlink()
    new_app = staging / "BookStudio" / "app"
    if not (new_app / "book_studio" / "__init__.py").exists():
        shutil.rmtree(staging, ignore_errors=True)
        raise RuntimeError("The downloaded update is not a Book Studio program.")
    os.replace(new_app, staging / "app")
    shutil.rmtree(staging / "BookStudio", ignore_errors=True)


def apply_and_restart() -> None:
    """Starts the launcher in 'apply update' mode, detached; the caller then quits so the old files are free to replace."""
    script = launcher_script()
    log = open(paths.LOGS_DIR / "update.log", "a", encoding="utf-8")
    if os.name == "nt":
        subprocess.Popen(["cmd", "/c", str(script), "--apply-update"], cwd=paths.BUNDLE_DIR, stdout=log, stderr=log,
                         creationflags=NO_WINDOW | 0x00000008)  # DETACHED_PROCESS: survives this window closing
    else:
        subprocess.Popen(["/bin/sh", str(script), "--apply-update"], cwd=paths.BUNDLE_DIR, stdout=log, stderr=log,
                         start_new_session=True)
