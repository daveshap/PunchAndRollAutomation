"""Download and locate the speech models. Everything runs offline after this.

Models come from the sherpa-onnx project's GitHub releases:
  - NVIDIA Parakeet TDT 0.6B v2 (English), int8 ONNX, about 480 MB
  - Silero voice activity detector, about 0.6 MB

Set PUNCHROLL_MODELS to keep them somewhere other than the default cache folder.
"""
from __future__ import annotations

import os
import sys
import tarfile
import time
import urllib.request
from pathlib import Path

RELEASE = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models"
ASR_NAME = "sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8"
ASR_URL = f"{RELEASE}/{ASR_NAME}.tar.bz2"
ASR_FILES = ("encoder.int8.onnx", "decoder.int8.onnx", "joiner.int8.onnx", "tokens.txt")
VAD_NAME = "silero_vad.onnx"
VAD_URL = f"{RELEASE}/{VAD_NAME}"


def models_dir() -> Path:
    env = os.environ.get("PUNCHROLL_MODELS")
    if env:
        return Path(env).expanduser()
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Caches"
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return base / "punchroll" / "models"


def transcripts_dir() -> Path:
    """Where finished and partial transcripts are cached, shared by every project."""
    env = os.environ.get("PUNCHROLL_CACHE")
    return Path(env).expanduser() if env else models_dir().parent / "transcripts"


def asr_dir() -> Path:
    return models_dir() / ASR_NAME


def vad_path() -> Path:
    return models_dir() / VAD_NAME


def have_models() -> bool:
    return vad_path().is_file() and all((asr_dir() / f).is_file() for f in ASR_FILES)


def _download(url: str, dest: Path, log=print) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "punchroll"})
    with urllib.request.urlopen(req) as r, open(part, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done, last = 0, 0.0
        while True:
            buf = r.read(1 << 20)
            if not buf:
                break
            f.write(buf)
            done += len(buf)
            if time.time() - last > 2:
                last = time.time()
                pct = f"{100 * done / total:.0f}%" if total else f"{done >> 20} MB"
                log(f"  downloading {dest.name}: {pct}")
    if total and done != total:
        raise IOError(f"download of {url} stopped early ({done} of {total} bytes); run again")
    part.replace(dest)


def _safe_extract(archive: Path, out_dir: Path) -> None:
    out = out_dir.resolve()
    with tarfile.open(archive, "r:bz2") as tar:
        for m in tar.getmembers():
            target = (out / m.name).resolve()
            if not str(target).startswith(str(out)) or m.issym() or m.islnk():
                raise IOError(f"refusing to extract suspicious path {m.name!r}")
            if m.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif m.isfile():
                target.parent.mkdir(parents=True, exist_ok=True)
                src = tar.extractfile(m)
                with open(target, "wb") as f:
                    while True:
                        buf = src.read(1 << 20)
                        if not buf:
                            break
                        f.write(buf)


def ensure_models(log=print) -> dict:
    """Download whatever is missing; return the paths."""
    root = models_dir()
    if not vad_path().is_file():
        log(f"Fetching the voice activity model into {root}")
        _download(VAD_URL, vad_path(), log)
    if not all((asr_dir() / f).is_file() for f in ASR_FILES):
        log(f"Fetching the speech recognition model (about 480 MB) into {root}")
        archive = root / f"{ASR_NAME}.tar.bz2"
        if not archive.is_file():
            _download(ASR_URL, archive, log)
        log("  unpacking ...")
        _safe_extract(archive, root)
        missing = [f for f in ASR_FILES if not (asr_dir() / f).is_file()]
        if missing:
            raise IOError(f"model archive is missing {missing}; delete {archive} and run again")
        archive.unlink()
    return {"asr_dir": asr_dir(), "vad": vad_path()}
