"""Command line: punchroll <command> ...

  punchroll transcript RAW...          write each recording's transcript, ready to be marked up
  punchroll assemble PLAN -o FILE.wav  assemble explicit spans from recordings and pickups
  punchroll cut RAW --markup FILE      cut the recording as its marked-up transcript says, and master it
  punchroll batch project.toml         do both for every recording in a project file
  punchroll verify EDITED --script S   proof a finished file against its manuscript and ACX; writes no audio
  punchroll batch project.toml --proof   the same for every finished file in a project
  punchroll standards EDITED...        check finished files against ACX and ElevenLabs
  punchroll scorecard P.toml...        score every finished recording side by side, on the finished files alone;
                                       best first by fire (the delivery's lift, movement, range and brightness)
  punchroll readback EDITED --markup M check a finished file holds every word its mark-up kept, once and in order
  punchroll clicks RAW EDITED          trace each click counted in a finished file back to the mark-up
  punchroll declick MARKUP             strike clicks in a mark-up by the method; with --raw and --finished, the traced ones too
  punchroll markcheck MARKUP           the mark-up still matches its transcript; short sounds, pauses and gaps left to judge
  punchroll lost RAW EDITED            words cut from a recording that are never said again
  punchroll said draft|build P.toml    the finished transcripts: what the reader said on each recording
  punchroll said changes P.toml        every sentence the reader changed from the text he was given
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


def _script_args(p, required=False):
    p.add_argument("--script", required=required, help="the manuscript (.md, .txt, or .docx)"
                   + ("" if required else "; the report then also sets what was kept beside it"))
    p.add_argument("--from", dest="start", help="start at the first heading containing this text")
    p.add_argument("--to", dest="end", help="stop before the next heading containing this text")
    p.add_argument("--lines", dest="line_range", help="use only these lines of a .md/.txt manuscript, e.g. 115-143")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="punchroll", description="Cut and master narration from a marked-up transcript.")
    ap.add_argument("--version", action="version", version=f"punchroll {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("models", help="download the speech models (once)")

    p = sub.add_parser("transcript", help="write a recording's transcript, ready to be marked up")
    p.add_argument("audio", nargs="+", help="recordings, or finished files to read back")
    p.add_argument("-o", "--out", default="markup", help="folder for the transcripts (default: ./markup)")
    p.add_argument("--config", help="TOML file overriding the default settings")

    p = sub.add_parser("assemble", help="assemble explicit source ranges and pickups into an unmastered float WAV")
    p.add_argument("plan", help="JSON plan naming sources, clips, and sample_rate")
    p.add_argument("-o", "--out", required=True, help="WAV output; a source map is saved beside it as .assembly.json")

    p = sub.add_parser("cut", help="cut a recording as its marked-up transcript says, and master it")
    p.add_argument("audio")
    p.add_argument("--markup", required=True, help="the marked-up transcript")
    p.add_argument("-o", "--out", default="edited", help="output folder (default: ./edited)")
    p.add_argument("--name", help="base name for the output files (default: the recording's)")
    p.add_argument("--config", help="TOML file overriding the default settings")
    p.add_argument("--no-mp3", action="store_true", help="write only the WAV master")
    p.add_argument("--report-only", action="store_true", help="list what the mark-up does, but render nothing")
    _script_args(p)

    p = sub.add_parser("verify", help="proof a finished file against its manuscript and ACX; writes no audio")
    p.add_argument("audio", nargs="+", help="finished files (MP3 or WAV), whoever made them")
    _script_args(p, required=True)
    p.add_argument("-o", "--out", default="edited", help="folder for the reports (default: ./edited)")
    p.add_argument("--config", help="TOML file overriding the default settings")

    p = sub.add_parser("batch", help="transcribe, then cut and master, every recording in a project TOML")
    p.add_argument("project")
    p.add_argument("--only", help="run only recordings whose name contains this text")
    p.add_argument("--force", action="store_true", help="redo recordings that are already up to date")
    p.add_argument("--proof", action="store_true",
                   help="proof named finished outputs against the manuscript; if absent, use the entry's audio as finished input")
    p.add_argument("--report-only", action="store_true",
                   help="write the reports and render no audio (with --proof, which never renders, it changes nothing)")

    p = sub.add_parser("standards", help="check finished files against ACX and ElevenLabs voice-clone guidance")
    p.add_argument("audio", nargs="+", help="finished files (MP3 or WAV); wildcards are expanded")
    p.add_argument("-o", "--out", help="also write the report to this Markdown file")

    p = sub.add_parser("scorecard", help="score every finished recording of one or more projects side by side")
    p.add_argument("project", nargs="+", help="project files; their recordings are scored together")
    p.add_argument("-o", "--out",
                   help="Markdown file to write (default: scorecard.md in the first project's output folder)")
    p.add_argument("--listener", action="store_true",
                   help='add a trained listener\'s estimate of each file (needs pip install -e ".[listen]")')
    p.add_argument("--fire-reference",
                   help="the fire scale file (default: fire-reference.json beside the first project file)")
    p.add_argument("--calibrate-fire", action="store_true",
                   help="set the fire scale from these recordings and save it to the fire scale file")

    p = sub.add_parser("readback", help="check a finished file holds every word its mark-up kept, once and in order")
    p.add_argument("finished", help="the finished MP3 or WAV; its .edit.json beside it gives the joins")
    p.add_argument("--markup", required=True, help="the marked-up transcript it was cut from")
    p.add_argument("--config", help="TOML file overriding the default settings")

    p = sub.add_parser("clicks", help="trace each click counted in a finished file back to the recording and the mark-up")
    p.add_argument("raw", help="the recording")
    p.add_argument("finished", help="the finished WAV, with its .edit.json beside it")
    p.add_argument("--config", help="the settings the recording was cut with")
    p.add_argument("--within", type=float, default=30.0, help="clicks within this many dB of the file's level (default: 30)")

    p = sub.add_parser("declick", help="strike the clicks in a mark-up as docs/checking.md says, and those traced in its finished file")
    p.add_argument("markup", help="the marked-up transcript")
    p.add_argument("--transcript", help="its transcript (default: the mark-up's name with .transcript.md)")
    p.add_argument("--raw", help="the recording; with --finished, also strike the clicks traced to a kept pause or breath")
    p.add_argument("--finished", help="the finished WAV cut from this mark-up, with its .edit.json beside it")
    p.add_argument("--config", help="the settings the recording was cut with")
    p.add_argument("--within", type=float, default=30.0, help="clicks within this many dB of the file's level (default: 30)")
    p.add_argument("--write", action="store_true", help="write the changes into the mark-up (default: only list them)")

    p = sub.add_parser("markcheck", help="check a mark-up against its transcript, and list what is left to judge")
    p.add_argument("markup", help="the marked-up transcript")
    p.add_argument("--transcript", help="its transcript (default: the mark-up's name with .transcript.md)")

    p = sub.add_parser("lost", help="words cut from a recording that are never said again")
    p.add_argument("raw", help="the recording")
    p.add_argument("finished", help="the finished MP3 or WAV")
    p.add_argument("--config", help="TOML file overriding the default settings")

    p = sub.add_parser("said", help="the finished transcripts: what the reader said on each finished recording")
    p.add_argument("step", choices=("draft", "build", "changes"), help="draft: list where the words differ from the "
                   "reference; build: write the transcripts once every difference has a decision; changes: every "
                   "sentence the reader changed from the text he was given, from the transcripts")
    p.add_argument("project", nargs="+", help="project files, in the order the recordings should be listed")
    p.add_argument("--only", help="only recordings whose name contains this text")
    p.add_argument("--into", help="changes: write the counts and the log into this file, between its markers")
    p.add_argument("--config", help="TOML file overriding the default settings")

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
            dest = transcript(path, Path(a.out) / f"{Path(path).stem}.transcript.md", load_settings(a.config))
            print(f"Read the whole transcript: {dest}\nSave the marked copy as: {Path(a.out) / (Path(path).stem + '.md')}")
        return 0

    if a.cmd == "assemble":
        import soundfile as sf
        from .assembly import assemble_files, load_plan
        plan, out = Path(a.plan), Path(a.out)
        if out.suffix.lower() != ".wav":
            raise ValueError("assemble output must be a .wav file")
        sources, clips, sr = load_plan(plan)
        report = out.with_suffix(".assembly.json")
        for dest in (out, report):
            for source in (plan, *sources.values()):
                if (dest.resolve() == source.resolve()
                        or (dest.exists() and source.exists() and dest.samefile(source))):
                    raise ValueError(f"assembly output would overwrite an input: {source}")
        result = assemble_files(sources, clips, sr)
        audio = result.pop("audio")
        out.parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(out), audio, sr, subtype="FLOAT")
        result.update(plan=str(plan.resolve()), output=str(out.resolve()))
        report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(f"Unmastered assembly: {out}\nSource map: {report}")
        print(f"{result['summary']['clips']} clips, {result['summary']['seconds']:.3f} seconds. "
              "Transcribe this WAV to mark further edits, then cut and master it.")
        return 0

    if a.cmd == "cut":
        from .pipeline import cut_and_master
        for path in (a.audio, a.markup):
            if not Path(path).is_file():
                raise FileNotFoundError(f"not found: {path}")
        lines, desc = _manuscript(a.script, a.start, a.end, a.line_range)
        cut_and_master(a.audio, a.markup, a.out, a.name, load_settings(a.config), mp3=not a.no_mp3,
                       report_only=a.report_only, lines=lines, script=desc)
        return 0

    if a.cmd == "verify":
        missing = [f for f in a.audio if not Path(f).is_file()]
        if missing:
            raise FileNotFoundError(f"not found: {', '.join(missing)}")
        lines, desc = _manuscript(a.script, a.start, a.end, a.line_range)
        out = Path(a.out)
        out.mkdir(parents=True, exist_ok=True)
        rec = _recognizer(load_settings(a.config))
        for f in a.audio:
            print(_proof(f, lines, desc, out, rec))
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
        from .scorecard import scorecard, scorecard_csv, scorecard_markdown
        rows = scorecard(a.project, listener=a.listener, reference=a.fire_reference, calibrate_fire=a.calibrate_fire)
        if not rows:
            raise ValueError("no recording of these projects has a finished WAV yet")
        md = scorecard_markdown(rows)
        proj = _toml(a.project[0])
        dest = Path(a.out) if a.out else Path(a.project[0]).parent / proj.get("out", "edited") / "scorecard.md"
        dest.write_text(md, encoding="utf-8")
        table = dest.with_suffix(".csv")                 # the same table for a spreadsheet, beside the Markdown
        table.write_text(scorecard_csv(rows), encoding="utf-8-sig")
        print(md)
        print(f"Scorecard: {dest}\nAs a spreadsheet: {table}")
        return 0

    if a.cmd in ("readback", "clicks", "lost"):
        from . import checks
        for path in [p for p in (getattr(a, "markup", None), getattr(a, "raw", None), a.finished) if p]:
            if not Path(path).is_file():
                raise FileNotFoundError(f"not found: {path}")
        settings = load_settings(a.config)
        rec = _recognizer(settings)
        if a.cmd == "readback":
            markup = Path(a.markup).read_text(encoding="utf-8")
            words = checks.heard_words(a.finished, rec)
            rows = checks.readback(markup, words, checks.edit_map(a.finished).get("edl"))
            print(checks.readback_text(rows, len(checks.kept_words(markup)),
                                       sum(len(_toks(w["text"])) for w in words)))
        elif a.cmd == "clicks":
            print(checks.clicks_text(checks.trace_clicks(a.raw, a.finished, settings, a.within)))
        else:
            print(checks.lost_text(checks.lost_words(checks.heard_words(a.raw, rec), checks.heard_words(a.finished, rec))))
        return 0

    if a.cmd in ("declick", "markcheck"):
        from . import markfix
        markup_path = Path(a.markup)
        transcript_path = Path(a.transcript) if a.transcript else markup_path.with_name(markup_path.stem + ".transcript.md")
        for path in (markup_path, transcript_path):
            if not path.is_file():
                raise FileNotFoundError(f"not found: {path}")
        m = markfix.MarkedUp(markup_path.read_text(encoding="utf-8").replace("\r\n", "\n"),
                             transcript_path.read_text(encoding="utf-8").replace("\r\n", "\n"))
        if a.cmd == "markcheck":
            print(markfix.check_text(markfix.check(m)))
            return 0
        changes = markfix.strike_short_sounds(m)
        if a.raw or a.finished:
            if not (a.raw and a.finished):
                raise ValueError("--raw and --finished go together")
            from . import checks
            pieces: list = []
            rows = checks.trace_clicks(a.raw, a.finished, load_settings(a.config), a.within, pieces_out=pieces)
            changes += markfix.strike_traced(m, rows, pieces)
        for c in changes:
            print(c)
        print(f"{len(changes)} change(s)" + (", written" if a.write and changes else ""))
        if a.write and changes:
            markup_path.write_text(m.render(), encoding="utf-8", newline="\n")
        return 0

    if a.cmd == "said":
        from . import said
        rec = _recognizer(load_settings(a.config))
        if a.step == "changes":
            said.changes(a.project, a.into, a.only)
        elif a.step == "draft":
            left = said.draft(a.project, a.only, rec)
            print(f"{left} difference(s) to decide" if left else "Every difference has a decision: run `punchroll said build`.")
        else:
            said.build(a.project, a.only, rec)
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


def _manuscript(script, start=None, end=None, line_range=None):
    """The manuscript's lines for one recording and a line saying which part, or (None, "") if there is no script."""
    if not script:
        return None, ""
    from .text import load_script
    desc = (Path(script).name + (f" from '{start}'" if start else "") + (f" to '{end}'" if end else "")
            + (f" lines {line_range}" if line_range else ""))
    return load_script(script, start, end, line_range), desc


def _recognizer(settings):
    """Loads the speech model once, and only if a file needs transcribing."""
    from .asr import Recognizer
    from .config import auto_threads
    holder = {}

    def rec():
        if "r" not in holder:
            holder["r"] = Recognizer(auto_threads(settings.threads))
        return holder["r"]
    return rec


def _proof(audio, lines, desc, out: Path, rec) -> str:
    """Proof one finished file, write its two reports, and return the Markdown."""
    from .models import transcripts_dir
    from .verify import verify, verify_markdown
    v = verify(audio, lines, rec, transcripts_dir())
    md = verify_markdown(v, desc)
    stem = Path(audio).stem
    (out / f"{stem}.verify.json").write_text(json.dumps(v, indent=1), encoding="utf-8")
    (out / f"{stem}.verify.md").write_text(md, encoding="utf-8")
    return md


def _toml(path) -> dict:
    if sys.version_info >= (3, 11):
        import tomllib
    else:  # pragma: no cover
        import tomli as tomllib
    return tomllib.loads(Path(path).read_text(encoding="utf-8"))


def _toks(text: str) -> list[str]:
    from .text import toks
    return toks(text)


def _seconds(text: str) -> float:
    """'3:08.4' or '188.4' -> seconds."""
    parts = [float(p) for p in str(text).split(":")]
    return sum(p * 60 ** k for k, p in enumerate(reversed(parts)))


def _batch(a) -> int:
    from .pipeline import cut_and_master, finished, latest_transcript, recording, recordings, transcript
    proj_path = Path(a.project)
    proj, base = _toml(proj_path), proj_path.parent
    config = base / proj["config"] if proj.get("config") else None
    settings = load_settings(config)
    out, marks_dir, mp3 = base / proj.get("out", "edited"), base / proj.get("markup", "markup"), proj.get("mp3", True)
    done, waiting, proofed = [], [], []
    rec = _recognizer(settings)

    def manuscript(ch, always=False):
        """A recording is set beside the manuscript when its entry names its part of it (`from`, `to`, `lines`) or a
        script of its own. A script named only at the top of the file is the default file, not a request to compare."""
        script = ch.get("script") or proj.get("script")
        if not script or not (always or ch.get("script") or ch.get("from") or ch.get("to") or ch.get("lines")):
            return None, ""
        return _manuscript(base / script, ch.get("from"), ch.get("to"), ch.get("lines"))

    for n, ch in enumerate(proj.get("chapter", []), 1):
        name = ch.get("name") or f"chapter-{n:02d}"
        if a.only and a.only not in name:
            continue
        if not ch.get("audio"):
            raise ValueError(f"[{name}] needs audio = \"...\"")
        if a.proof:                                # finished audio: recognize, compare, report; write no audio
            lines, desc = manuscript(ch, always=True)
            masters = [out / f"{name}.{ext}" for ext in (("mp3", "wav") if mp3 else ("wav",))]
            finished_audio = next((p for p in masters if p.is_file()), None)
            files = [str(finished_audio)] if finished_audio else recordings(base, ch["audio"])
            if lines is None or not files:
                raise ValueError(f"[{name}] --proof needs a script (in the entry or at the top) and audio that exists")
            print(f"\n=== {name} ===")
            out.mkdir(parents=True, exist_ok=True)
            for f in files:
                print(f"Proofing: {f}")
                _proof(f, lines, desc, out, rec)
                v = json.loads((out / f"{Path(f).stem}.verify.json").read_text(encoding="utf-8"))
                proofed.append((Path(f).name, v))
            continue
        audio = recording(base, name, ch["audio"])
        markup = base / ch["markup"] if ch.get("markup") else marks_dir / f"{name}.md"
        lines, desc = manuscript(ch)
        ch_config = base / ch["config"] if ch.get("config") else config      # an entry can have settings of its own
        ch_settings = load_settings(ch_config) if ch.get("config") else settings
        if a.report_only:                          # what each mark-up does, and how it stands against the manuscript: no audio
            if markup.is_file():
                print(f"\n=== {name} ===")
                done.append((name, cut_and_master(audio, markup, out, name, ch_settings, mp3=mp3, report_only=True,
                                                  lines=lines, script=desc)["summary"]))
            else:
                print(f"=== {name} === no mark-up at {markup}, so nothing to report")
            continue
        made_from = [audio, proj_path] + ([ch_config] if ch_config else [])
        if lines is not None:                      # reports also depend on the selected manuscript
            made_from.append(base / (ch.get("script") or proj["script"]))
        if not markup.is_file():
            if finished(out, name, made_from, mp3) and not a.force:
                print(f"=== {name} === finished earlier; no mark-up on file, left as it is")
                continue
            destination = marks_dir / f"{name}.transcript.md"
            fresh = latest_transcript(destination)
            if not fresh.is_file() or fresh.stat().st_mtime < Path(audio).stat().st_mtime:
                print(f"\n=== {name} === writing the transcript")
                fresh = transcript(audio, destination, ch_settings)
            waiting.append((name, fresh, markup))
            continue
        made_from.append(markup)
        if not a.force and finished(out, name, made_from, mp3):
            print(f"=== {name} === up to date, skipped (--force redoes it)")
            continue
        print(f"\n=== {name} ===")
        done.append((name, cut_and_master(audio, markup, out, name, ch_settings, mp3=mp3, lines=lines, script=desc)["summary"]))
    if a.proof:
        print("\nFile                             length  pickups  small  not found    RMS  true peak  noise floor")
        for fname, v in proofed:
            m = v["acx"]
            print(f"{fname[:30]:30s}  {v['duration']:>7s}  {len(v['pickups']):7d}  {len(v['small']):5d}  {len(v['not_found']):9d}  "
                  f"{m['rms_db']:5.1f}  {m['true_peak_db']:9.2f}  {m['noise_floor_db']:11.1f}")
        print(f"Reports: {out}")
        return 0
    if done:
        print("\nRecording                       recorded  edited  cuts")
        for name, s in done:
            print(f"{name[:30]:30s}  {s['raw_minutes']:7.1f}  {s['edited_minutes']:6.1f}  {s['cuts']:4d}")
    for name, fresh, markup in waiting:
        print(f"\nWaiting for mark-up: {name}\n  read the whole transcript: {fresh}\n  save the marked copy as:   {markup}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
