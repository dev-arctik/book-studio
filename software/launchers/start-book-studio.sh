#!/bin/sh
# start-book-studio.sh — Book Studio launcher for Mac and Linux (the Mac's "Start Book Studio.command" runs this).
# First start: downloads uv (the installer tool), which installs Python and the exact locked packages into ./runtime — nothing
# is installed system-wide. Every start: applies a downloaded update if one is waiting, checks packages, opens the window.
# Options: --apply-update (used by the app itself)   --setup-only (install everything, don't open the window)

set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
APP="$HERE/app"
RUNTIME="$HERE/runtime"
UV_VERSION="0.13.1"
export UV_CACHE_DIR="$RUNTIME/uv-cache"
export UV_PYTHON_INSTALL_DIR="$RUNTIME/python"
export UV_PROJECT_ENVIRONMENT="$RUNTIME/venv"
export UV_PYTHON_PREFERENCE="only-managed"
mkdir -p "$RUNTIME"

# A finished update download waits in runtime/update/app: swap it in now that the window is closed
if [ "$1" = "--apply-update" ]; then
  sleep 3
  if [ -f "$RUNTIME/update/app/book_studio/__init__.py" ]; then
    rm -rf "$RUNTIME/app.old"
    mv "$APP" "$RUNTIME/app.old"
    mv "$RUNTIME/update/app" "$APP"
    rm -rf "$RUNTIME/update" "$RUNTIME/app.old"
  fi
fi

if [ ! -x "$RUNTIME/uv/uv" ]; then
  echo ""
  echo "  Book Studio — first-time setup"
  echo "  This needs the internet once and takes about 5–10 minutes. Please leave this window open."
  echo ""
  echo "  Step 1 of 2: downloading the installer tool…"
  case "$(uname -s)-$(uname -m)" in
    Darwin-arm64) TARGET="aarch64-apple-darwin" ;;
    Darwin-x86_64) TARGET="x86_64-apple-darwin" ;;
    Linux-x86_64) TARGET="x86_64-unknown-linux-gnu" ;;
    Linux-aarch64) TARGET="aarch64-unknown-linux-gnu" ;;
    *) echo "  Sorry, this computer type ($(uname -s) $(uname -m)) is not supported."; exit 1 ;;
  esac
  URL="https://github.com/astral-sh/uv/releases/download/$UV_VERSION/uv-$TARGET.tar.gz"
  mkdir -p "$RUNTIME/uv"
  if command -v curl >/dev/null 2>&1; then
    curl -LsSf "$URL" | tar xz -C "$RUNTIME/uv" --strip-components 1
  else
    wget -qO- "$URL" | tar xz -C "$RUNTIME/uv" --strip-components 1
  fi
  echo "  Step 2 of 2: installing Book Studio's parts (about 500 MB)…"
fi

# Installs exactly what uv.lock lists; when nothing changed this takes a moment and needs no internet
"$RUNTIME/uv/uv" sync --frozen --project "$APP"

if [ "$1" = "--setup-only" ]; then
  echo "  Book Studio is installed."
  exit 0
fi

cd "$APP"
if [ -t 1 ]; then
  # Started from a terminal window (the first time): open the window on its own so this terminal can be closed
  nohup "$RUNTIME/venv/bin/python" -m book_studio >"$RUNTIME/last-start.log" 2>&1 &
  sleep 4
  if ! kill -0 $! 2>/dev/null; then
    echo ""
    echo "  Book Studio could not open. Details:"
    tail -20 "$RUNTIME/last-start.log"
    case "$(cat "$RUNTIME/last-start.log")" in
      *xcb*) echo ""; echo "  On Ubuntu/Debian this usually fixes it:  sudo apt install libxcb-cursor0" ;;
    esac
    exit 1
  fi
  echo ""
  echo "  Book Studio is open. You can close this window."
  echo "  Next time, use the Book Studio icon on your Desktop."
else
  exec "$RUNTIME/venv/bin/python" -m book_studio
fi
