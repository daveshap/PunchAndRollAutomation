"""Command line: punchroll <command> ...

  punchroll transcript RAW...          write each recording's transcript, ready to be marked up
  punchroll cut RAW --markup FILE      cut the recording as its marked-up transcript says, and master it
  punchroll batch project.toml         do both for every recording in a project file
  punchroll standards EDITED...        check finished files against ACX and ElevenLabs
  punchroll scorecard project.toml     score every finished recording side by side
  punchroll picture FILE --at 3:08     a spectrogram of a passage, as a PNG
  punchroll models                     download the speech models once (about 480 MB)
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

from . import __version__
from .config import load_settings


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="punchroll", description="Cut and master narration from a marked-up transcript.")
    ap.add_argument("--version", action="version", version=f"punchroll {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("models", help="download the speech models (once)")

    p = sub.add_parser("transcript", help="write a recording's transcript, ready to be marked up")
    p.add_argument("audio", nargs="+", help="recordings, or finished files to read back")
    p.add_argument("-o", "--out", default="markup", help="folder for the transcripts (default: ./markup)")
    p.add_argument("--config", help="TOML file overriding the default settings")

    p = sub.add_parser("cut", help="cut a recording as its marked-up transcript says, and master it")
    p.add_argument("audio")
    p.add_argument("--markup", required=True, help="the marked-up transcript")
    p.add_argument("-o", "--out", default="edited", help="output folder (default: ./edited)")
    p.add_argument("--name", help="base name for the output files (default: the recording's)")
    p.add_argument("--config", help="TOML file overriding the default settings")
    p.add_argument("--no-mp3", action="store_true", help="write only the WAV master")
    p.add_argument("--report-only", action="store_true", help="list what the mark-up does, but render nothing")

    p = sub.add_parser("batch", help="transcribe, then cut and master, every recording in a project TOML")
    p.add_argument("project")
    p.add_argument("--only", help="run only recordings whose name contains this text")
    p.add_argument("--force", action="store_true", help="redo recordings that are already up to date")

    p = sub.add_parser("standards", help="check finished files against ACX and ElevenLabs voice-clone guidance")
    p.add_argument("audio", nargs="+", help="finished files (MP3 or WAV); wildcards are expanded")
    p.add_argument("-o", "--out", help="also write the report to this Markdown file")

    p = sub.add_parser("scorecard", help="score every finished recording of a project side by side")
    p.add_argument("project")
    p.add_argument("-o", "--out", help="Markdown file to write (default: scorecard.md in the project's output folder)")
    p.add_argument("--listener", action="store_true",
                   help='add a trained listener\'s estimate of each file (needs pip install -e ".[listen]")')

    p = sub.add_parser("picture", help="a spectrogram of a passage, as a PNG")
    p.add_argument("audio")
    p.add_argument("--at", default="0:00", help="where the passage starts, as M:SS or seconds (default: the start)")
    p.add_argument("--seconds", type=float, default=12.0, help="how long a passage (default: 12)")
    p.add_argument("--with", dest="other", help="a second file to show underneath, such as the raw recording")
    p.add_argument("--with-at", dest="other_at", help="where the same passage starts in the second file (default: --at)")
    p.add_argument("--top", type=float, default=10000.0, help="highest frequency shown, in Hz (default: 10000)")
    p.add_argument("-o", "--out", help="PNG to write (default: beside the file)")

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
    except BrokenPipeError:
        return 0


def _run(a) -> int:
    if a.cmd == "models":
        from .models import ensure_models, models_dir
        paths = ensure_models()
        print(f"Models ready in {models_dir()}")
        print(json.dumps({k: str(v) for k, v in paths.items()}, indent=1))
        return 0

    if a.cmd == "transcript":
        from .pipeline import transcript
        missing = [p for p in a.audio if not Path(p).is_file()]
        if missing:
            raise FileNotFoundError(f"not found: {', '.join(missing)}")
        for path in a.audio:
            transcript(path, Path(a.out) / f"{Path(path).stem}.transcript.md", load_settings(a.config))
        return 0

    if a.cmd == "cut":
        from .pipeline import cut_and_master
        for path in (a.audio, a.markup):
            if not Path(path).is_file():
                raise FileNotFoundError(f"not found: {path}")
        cut_and_master(a.audio, a.markup, a.out, a.name, load_settings(a.config), mp3=not a.no_mp3,
                       report_only=a.report_only)
        return 0

    if a.cmd == "batch":
        return _batch(a)

    if a.cmd == "standards":
        from .pipeline import natural
        from .standards import check_files, standards_markdown
        files = [f for pat in a.audio for f in (sorted(glob.glob(pat), key=natural) or [pat])]
        missing = [f for f in files if not Path(f).is_file()]
        if missing:
            raise FileNotFoundError(f"not found: {', '.join(missing)}")
        md = standards_markdown(check_files(files, log=lambda m: print(m, file=sys.stderr)))
        if a.out:
            Path(a.out).write_text(md, encoding="utf-8")
        print(md)
        return 0

    if a.cmd == "scorecard":
        from .scorecard import scorecard, scorecard_markdown
        rows = scorecard(a.project, listener=a.listener)
        if not rows:
            raise ValueError("no recording of this project has a finished WAV and an edit list yet")
        md = scorecard_markdown(rows)
        proj = _toml(a.project)
        dest = Path(a.out) if a.out else Path(a.project).parent / proj.get("out", "edited") / "scorecard.md"
        dest.write_text(md, encoding="utf-8")
        print(md)
        print(f"Scorecard: {dest}")
        return 0

    if a.cmd == "picture":
        from .audio import read_mono
        from .picture import match_loudness, passage, spectrogram_png
        x, sr = read_mono(a.audio)
        at = _seconds(a.at)
        panels = [(f"{Path(a.audio).name} from {a.at}", passage(x, sr, at, a.seconds), sr)]
        if a.other:
            y, ysr = read_mono(a.other)
            other_at = a.other_at or a.at
            seg = match_loudness(passage(y, ysr, _seconds(other_at), a.seconds), panels[0][1])
            panels.append((f"{Path(a.other).name} from {other_at}, brought to the same loudness", seg, ysr))
        dest = Path(a.out) if a.out else Path(a.audio).with_name(f"{Path(a.audio).stem} at {a.at.replace(':', '-')}.png")
        spectrogram_png(panels, dest, top_hz=a.top)
        print(f"Picture: {dest}")
        return 0
    return 1


def _toml(path) -> dict:
    if sys.version_info >= (3, 11):
        import tomllib
    else:  # pragma: no cover
        import tomli as tomllib
    return tomllib.loads(Path(path).read_text(encoding="utf-8"))


def _seconds(text: str) -> float:
    """'3:08.4' or '188.4' -> seconds."""
    parts = [float(p) for p in str(text).split(":")]
    return sum(p * 60 ** k for k, p in enumerate(reversed(parts)))


def _batch(a) -> int:
    from .pipeline import cut_and_master, finished, recording, transcript
    proj_path = Path(a.project)
    proj, base = _toml(proj_path), proj_path.parent
    config = base / proj["config"] if proj.get("config") else None
    settings = load_settings(config)
    out, marks_dir, mp3 = base / proj.get("out", "edited"), base / proj.get("markup", "markup"), proj.get("mp3", True)
    done, waiting = [], []
    for n, ch in enumerate(proj.get("chapter", []), 1):
        name = ch.get("name") or f"chapter-{n:02d}"
        if a.only and a.only not in name:
            continue
        if not ch.get("audio"):
            raise ValueError(f"[{name}] needs audio = \"...\"")
        audio = recording(base, name, ch["audio"])
        markup = base / ch["markup"] if ch.get("markup") else marks_dir / f"{name}.md"
        if not markup.is_file():
            if finished(out, name, [audio], mp3) and not a.force:
                print(f"=== {name} === finished earlier; no mark-up on file, left as it is")
                continue
            fresh = marks_dir / f"{name}.transcript.md"
            if not fresh.is_file() or fresh.stat().st_mtime < Path(audio).stat().st_mtime:
                print(f"\n=== {name} === writing the transcript")
                transcript(audio, fresh, settings)
            waiting.append((name, fresh, markup))
            continue
        if not a.force and finished(out, name, [audio, markup] + ([config] if config else []), mp3):
            print(f"=== {name} === up to date, skipped (--force redoes it)")
            continue
        print(f"\n=== {name} ===")
        done.append((name, cut_and_master(audio, markup, out, name, settings, mp3=mp3)["summary"]))
    if done:
        print("\nRecording                       recorded  edited  cuts")
        for name, s in done:
            print(f"{name[:30]:30s}  {s['raw_minutes']:7.1f}  {s['edited_minutes']:6.1f}  {s['cuts']:4d}")
    for name, fresh, markup in waiting:
        print(f"\nWaiting for mark-up: {name}\n  read    {fresh}\n  save as {markup}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
