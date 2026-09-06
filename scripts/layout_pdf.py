#!/usr/bin/env python3
"""Stable JSON CLI. Translation is supplied by the active Codex model."""
import argparse
import json
import sys
from pathlib import Path

from layoutpdf import VERSION
from layoutpdf.contracts import Failure, issue, require, validate
from layoutpdf.extract import font_pair, prepare
from layoutpdf.pipeline import build, correct, deliver, load_job, merge, review


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--version", action="version", version=VERSION)
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor")
    prep = sub.add_parser("prepare")
    prep.add_argument("input")
    prep.add_argument("job")
    prep.add_argument("--target-language", default="zh-CN")
    prep.add_argument("--font")
    prep.add_argument("--bold-font")
    for name in ("validate", "merge", "correct", "build", "review", "deliver"):
        command = sub.add_parser(name)
        command.add_argument("job")
        if name in {"merge", "correct"}:
            command.add_argument("batch")
        if name == "validate":
            command.add_argument("--translated", action="store_true")
        if name == "build":
            command.add_argument("--preflight", action="store_true")
        if name == "review":
            command.add_argument("--status", choices=["passed", "failed"])
            command.add_argument("--notes")
            command.add_argument("--evidence-hash")
        if name == "deliver":
            command.add_argument("output")
    return p


def main():
    args = parser().parse_args()
    try:
        if args.command == "doctor":
            import pymupdf
            result = dict(version=VERSION, engine="native-vector-v1", pymupdf=pymupdf.VersionBind, fonts=font_pair())
        elif args.command == "prepare":
            doc = prepare(args.input, args.job, args.target_language, args.font, args.bold_font)
            require(validate(doc, job=Path(args.job)))
            require(doc["diagnostics"])
            result = dict(job=str(Path(args.job).resolve()), paragraphs=len(doc["paragraphs"]), formulas=len(doc["assets"]), diagnostics=doc["diagnostics"])
        elif args.command == "validate":
            _, doc = load_job(args.job, args.translated)
            require(doc["diagnostics"])
            result = dict(paragraphs=len(doc["paragraphs"]), diagnostics=[])
        elif args.command in {"merge", "correct"}:
            result = (merge if args.command == "merge" else correct)(args.job, args.batch)
        elif args.command == "build":
            result = build(args.job, args.preflight)
        elif args.command == "review":
            result = review(args.job, args.status, args.notes, args.evidence_hash)
        else:
            result = deliver(args.job, args.output)
        result = dict(command=args.command, ok=True) | result
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["ok"] else 1
    except Failure as exc:
        print(json.dumps(dict(ok=False, command=args.command, diagnostics=exc.diagnostics), ensure_ascii=False, indent=2))
        return 1
    except Exception as exc:
        print(json.dumps(dict(ok=False, command=args.command, diagnostics=[issue("runtime/error", args.command,
              {"reason": str(exc)}, ["inspect the input and runtime; retain the job for recovery"])]), ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
