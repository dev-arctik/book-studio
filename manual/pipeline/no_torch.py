# manual/pipeline/no_torch.py
# A tiny stand-in for PyTorch, so Surya's OCR runs where PyTorch can't (Windows Smart App Control blocks its unsigned DLLs)
# or isn't installed (Book Studio no longer ships it). Surya imports torch only to ask which device and number type its own
# local models would use; our OCR runs in llama-server, so "no GPU, default types, no-op inference mode" is all it needs.

import contextlib
import os
import sys
import types


def needed() -> bool:
    """True when Surya must run without PyTorch: Book Studio asks for that, or PyTorch won't load here."""
    if os.environ.get("SURYA_WITHOUT_TORCH"):
        return True
    try:
        import torch
    except (ImportError, OSError):  # not installed, or e.g. "An Application Control policy has blocked this file"
        return True
    # An empty leftover folder (e.g. after torch was uninstalled) imports as a namespace with no __file__: not PyTorch
    return getattr(torch, "__file__", None) is None


def install() -> None:
    """Puts the stand-in where `import torch` finds it. Call before importing anything from surya."""
    torch = types.ModuleType("torch")
    torch.__version__ = "0+not-installed"
    torch.dtype = type("dtype", (), {})  # used in Surya's type hints
    torch.float32, torch.float16, torch.bfloat16 = torch.dtype(), torch.dtype(), torch.dtype()
    torch.cuda = types.SimpleNamespace(is_available=lambda: False, device_count=lambda: 0)
    torch.backends = types.SimpleNamespace(mps=types.SimpleNamespace(is_available=lambda: False))
    torch.inference_mode = contextlib.nullcontext
    for name in [m for m in sys.modules if m == "torch" or m.startswith("torch.")]:  # leftovers of a failed real import
        del sys.modules[name]
    sys.modules["torch"] = torch
