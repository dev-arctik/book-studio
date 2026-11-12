# manual/pipeline/wsl_reader.py
# Runs the OCR's llama-server inside WSL (Ubuntu, NVIDIA GPU via CUDA) instead of the Windows llama-server.exe.
# Why: Windows Smart App Control blocks the unsigned Windows build (2026-11-12) and has no per-program exception; turning it off was
# declined, and programs inside WSL are outside its checks. Switched on by tools/llama.cpp/wsl-reader.txt (git-ignored), whose
# first line is the llama.cpp folder inside WSL (e.g. ~/llama.cpp/b11623-cuda); the optional second line is the WSL distro (default Ubuntu).

import os
import socket
import subprocess
import time
import urllib.request
from contextlib import contextmanager
from pathlib import Path

import local_env

CONFIG = local_env.TOOLS_DIR / "llama.cpp" / "wsl-reader.txt"
LAUNCHER = Path(__file__).with_name("llama_wsl.sh")


def enabled() -> bool:
    return os.name == "nt" and CONFIG.is_file()


def wsl_path(path) -> str:
    """D:\\a\\b → /mnt/d/a/b (WSL's view of a Windows drive)."""
    p = Path(path).resolve()
    return f"/mnt/{p.drive[0].lower()}" + p.as_posix()[2:]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def healthy(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=3) as r:
            return r.status == 200
    except OSError:
        return False


@contextmanager
def wsl_server():
    """Start llama-server in WSL with the same arguments Surya gives its own server, point Surya at it, and stop it afterwards."""
    from surya.settings import settings

    lines = CONFIG.read_text(encoding="utf-8").split("\n")
    install, distro = lines[0].strip(), (lines[1].strip() if len(lines) > 1 and lines[1].strip() else "Ubuntu")
    parallel = settings.SURYA_INFERENCE_PARALLEL or 8
    ctx = settings.SURYA_INFERENCE_CTX_SIZE or max(16384, parallel * settings.SURYA_INFERENCE_CTX_PER_SLOT)
    port = free_port()
    args = ["-m", wsl_path(settings.SURYA_GGUF_LOCAL_MODEL_PATH), "--mmproj", wsl_path(settings.SURYA_GGUF_LOCAL_MMPROJ_PATH),
            "-ngl", str(settings.LLAMA_CPP_NGL), "--host", "127.0.0.1", "--port", str(port), "--parallel", str(parallel),
            "--ctx-size", str(ctx), "--alias", settings.SURYA_MODEL_CHECKPOINT, "--jinja", *(settings.LLAMA_CPP_EXTRA_ARGS or "").split()]
    log_path = Path("~/.cache/datalab/surya/llamacpp_server.log").expanduser()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    # -e runs the program directly: "wsl.exe --" would pass the line through the login shell, which re-expands and re-splits it
    cmd = ["wsl.exe", "-d", distro, "-e", "bash", wsl_path(LAUNCHER), install, *args]
    with open(log_path, "ab") as log:
        proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT)
    try:
        deadline = time.time() + settings.SURYA_INFERENCE_STARTUP_TIMEOUT
        while not healthy(port):
            if proc.poll() is not None:
                raise RuntimeError(f"WSL llama-server stopped while starting — see {log_path}")
            if time.time() > deadline:
                raise RuntimeError(f"WSL llama-server did not start in time — see {log_path}")
            time.sleep(2)
        settings.SURYA_INFERENCE_URL = f"http://127.0.0.1:{port}/v1"
        print(f"Page reader: llama-server in WSL ({distro}, port {port})", flush=True)
        yield
    finally:
        settings.SURYA_INFERENCE_URL = None
        # Killing wsl.exe alone can leave the Linux process (and the model in GPU memory) running, so stop it inside WSL too
        subprocess.run(["wsl.exe", "-d", distro, "-e", "pkill", "-f", f"llama-server .*--port {port} "], capture_output=True)
        proc.terminate()
