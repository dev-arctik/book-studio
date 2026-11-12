# manual/pipeline/llama_wsl.sh
# Runs the Linux llama-server inside WSL for the Windows OCR (wsl_reader.py starts it through wsl.exe).
# Used where Windows Smart App Control blocks the unsigned Windows llama-server.exe: WSL is outside its checks, so it stays on.
# $1 = the llama.cpp install folder in WSL (official ubuntu-cuda build + its cudart pack + libgomp unpacked into sysroot/); the rest pass through.

D="${1/#\~/$HOME}"; shift  # "~/llama.cpp/…" from the config: wsl.exe -e runs no shell, so ~ is expanded here
# The official build has no ready GTX 1650 (sm_75) code, so the driver compiles it on first use; a 4 GB cache keeps it (the 256 MB default is too small for llama.cpp)
export CUDA_CACHE_MAXSIZE=4294967296
export LD_LIBRARY_PATH="$D/sysroot/usr/lib/x86_64-linux-gnu:$(dirname "$(find "$D" -name llama-server -type f | head -1)"):$(dirname "$(find "$D" -name 'libcudart.so*' | head -1)"):/usr/lib/wsl/lib:$LD_LIBRARY_PATH"
exec "$(find "$D" -name llama-server -type f | head -1)" "$@"
