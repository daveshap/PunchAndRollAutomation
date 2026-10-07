"""Command line: punchroll <command> ...

  punchroll models                     download the speech models once (about 480 MB)
  punchroll lines   --script ...       show the lines a section will be matched against
  punchroll clean   RAW... --script ...  edit and master a chapter
  punchroll verify  EDITED --script ...  re-transcribe a finished file and check it
  punchroll batch   project.toml         run clean for every chapter in a project file
  punchroll transcribe RAW...          just the word timings, as JSON
"""
from __future__ import annotations

import argparse
import glob
import json
import re
import sys
from pathlib import Path

from . import __version__
from .asr import Recognizer, transcribe
from .config import auto_threads, load_settings
from .models import transcripts_dir

PAUSED = 3


def _script_args(p):
    p.add_argument("--script", required=True, help="the narration script (.md, .txt, or .docx)")
    p.add_argument("--from", dest="start", help="start at the first heading containing this text")
    p.add_argument("--to", dest="end", help="stop before the next heading containing this text")
    p.add_argument("--lines", dest="line_range", help="use only these lines of a .md/.txt script, e.g. 115-143")


def _common(p):
    p.add_argument("--config", help="TOML file overriding the default settings")
    p.add_argument("--threads", type=int, default=0, help="speech recognition threads (default: automatic)")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="punchroll", description="Automatic punch-and-roll editing for audiobook narration.")
    ap.add_argument("--version", action="version", version=f"punchroll {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("models", help="download the speech models (once)")

    p = sub.add_parser("lines", help="print the script lines a section will be matched against")
    _script_args(p)

    p = sub.add_parser("clean", help="edit and master one chapter")
    p.add_argument("audio", nargs="+", help="recordings in the order you made them (pickups last)")
    _script_args(p)
    _common(p)
    p.add_argument("-o", "--out", default="edited", help="output folder (default: ./edited)")
    p.add_argument("--name", help="base name for the output files")
    p.add_argument("--no-mp3", action="store_true", help="write only the 24-bit WAV master")
    p.add_argument("--report-only", action="store_true", help="analyze and report, but don't render audio")
    p.add_argument("--max-minutes", type=float, help="stop transcribing after this long; run again to resume")
    p.add_argument("--no-level-match", action="store_true", help="don't match later takes' level to the first")

    p = sub.add_parser("verify", help="re-transcribe an edited file and check it against the script and ACX")
    p.add_argument("audio")
    _script_args(p)
    _common(p)
    p.add_argument("-o", "--out", default="edited")

    p = sub.add_parser("batch", help="run clean for every [[chapter]] in a project TOML")
    p.add_argument("project")
    p.add_argument("--only", help="run only chapters whose name contains this text")
    p.add_argument("--force", action="store_true", help="redo chapters that are already up to date")
    p.add_argument("--max-minutes", type=float, help="stop transcribing after this long; run again to resume")

    p = sub.add_parser("transcribe", help="word timings only")
    p.add_argument("audio", nargs="+")
    _common(p)
    p.add_argument("-o", "--out", default="edited")

    a = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):           # never crash on a console that can't print '−'
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    try:
        return _run(a)
    except (ValueError, FileNotFoundError, RuntimeError) as e:
        print(f"punchroll: {e}", file=sys.stderr)
        return 2
    except BrokenPipeError:               # e.g. punchroll lines ... | head
        return 0


def _settings(a):
    s = load_settings(getattr(a, "config", None))
    if getattr(a, "threads", 0):
        s.threads = a.threads
    if getattr(a, "no_level_match", False):
        s.level_match = False
    return s


def _run(a) -> int:
    if a.cmd == "models":
        from .models import ensure_models, models_dir
        paths = ensure_models()
        print(f"Models ready in {models_dir()}")
        print(json.dumps({k: str(v) for k, v in paths.items()}, indent=1))
        return 0

    if a.cmd == "lines":
        from .text import load_script
        for i, ln in enumerate(load_script(a.script, a.start, a.end, a.line_range), 1):
            print(f"{i:4d}  {'#' if ln.kind == 'heading' else ' '}  {ln.text}")
        return 0

    if a.cmd == "clean":
        from .pipeline import clean
        missing = [p for p in a.audio if not Path(p).is_file()]
        if missing:
            raise FileNotFoundError(f"not found: {', '.join(missing)}")
        res = clean(a.audio, a.script, a.out, a.name, a.start, a.end, a.line_range, _settings(a),
                    mp3=not a.no_mp3, report_only=a.report_only,
                    max_seconds=a.max_minutes * 60 if a.max_minutes else None)
        return PAUSED if res is None else 0

    if a.cmd == "verify":
        from .text import load_script
        from .verify import verify, verify_markdown
        s = _settings(a)
        lines = load_script(a.script, a.start, a.end, a.line_range)
        out = Path(a.out)
        out.mkdir(parents=True, exist_ok=True)
        v = verify(a.audio, lines, lambda: Recognizer(auto_threads(s.threads)), transcripts_dir(), s)
        stem = Path(a.audio).stem
        (out / f"{stem}.verify.json").write_text(json.dumps(v, indent=1), encoding="utf-8")
        (out / f"{stem}.verify.md").write_text(verify_markdown(v), encoding="utf-8")
        print(verify_markdown(v))
        return 0

    if a.cmd == "batch":
        return _batch(a)

    if a.cmd == "transcribe":
        from .audio import read_mono
        s = _settings(a)
        holder = {}

        def rec():                                 # load the model once, and only if needed
            if "r" not in holder:
                holder["r"] = Recognizer(auto_threads(s.threads))
            return holder["r"]

        out = Path(a.out)
        out.mkdir(parents=True, exist_ok=True)
        for path in a.audio:
            x, sr = read_mono(path)
            tr = transcribe(path, x, sr, rec, transcripts_dir())
            dest = out / f"{Path(path).stem}.words.json"
            dest.write_text(json.dumps(tr, indent=1), encoding="utf-8")
            print(f"{path}: {len(tr['words'])} words -> {dest}")
        return 0
    return 1


def _natural(s: str):
    """Sort key that puts ch01-2.wav before ch01-10.wav."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def _batch(a) -> int:
    import time

    from .pipeline import clean, describe, finished_report
    if sys.version_info >= (3, 11):
        import tomllib
    else:  # pragma: no cover
        import tomli as tomllib
    proj_path = Path(a.project)
    proj = tomllib.loads(proj_path.read_text(encoding="utf-8"))
    base = proj_path.parent
    config = base / proj["config"] if proj.get("config") else None
    settings = load_settings(config)
    out = base / proj.get("out", "edited")
    mp3 = proj.get("mp3", True)
    t0, summary = time.time(), []
    for n, ch in enumerate(proj.get("chapter", []), 1):
        name = ch.get("name") or f"chapter-{n:02d}"
        if a.only and a.only not in name:
            continue
        if not ch.get("audio") or not (ch.get("script") or proj.get("script")):
            raise ValueError(f"[{name}] needs audio = [...] and a script (set in the chapter or at the top)")
        files = []
        for pat in ch["audio"] if isinstance(ch["audio"], list) else [ch["audio"]]:
            hits = sorted(glob.glob(str(base / pat)), key=_natural)
            if not hits:
                raise FileNotFoundError(f"[{name}] no files match {pat}")
            files = [f for f in files if f not in hits] + hits   # a file named again later moves there
        script = base / (ch.get("script") or proj["script"])
        section = (ch.get("from"), ch.get("to"), ch.get("lines"))
        done = None if a.force else finished_report(out, name, files, script, describe(script, *section), mp3,
                                                    [config] if config else [])
        if done:
            print(f"\n=== {name} === up to date, skipped (--force redoes it)")
            summary.append((name, done["summary"], len(done["pickups"])))
            continue
        print(f"\n=== {name} ===")
        left = None if not a.max_minutes else a.max_minutes * 60 - (time.time() - t0)
        if left is not None and left <= 0:
            print("Time budget used; run the same command again to continue.")
            return PAUSED
        res = clean(files, script, out, name, *section, settings, mp3=mp3, max_seconds=left)
        if res is None:
            return PAUSED
        summary.append((name, res["summary"], len(res["pickups"])))
    print("\nChapter                         recorded  edited  pickups")
    for name, s, n in summary:
        print(f"{name[:30]:30s}  {s['raw_minutes']:7.1f}  {s['edited_minutes']:6.1f}  {n:7d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
