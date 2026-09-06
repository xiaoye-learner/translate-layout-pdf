from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from collections import Counter
from pathlib import Path

import jsonschema

TOKEN = re.compile(r"\[\[(?:M|P)\d{4,}\]\]")
ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def object_digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".writing-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
        os.replace(tmp, path)
    finally:
        if Path(tmp).exists():
            Path(tmp).unlink()


def issue(code, subject, evidence, fixes=(), severity="error", stage="validate"):
    return dict(code=code, severity=severity, stage=stage, subject=subject,
                evidence=evidence, supportedFixes=list(fixes))


def structure_digest(doc):
    structural = {k: v for k, v in doc.items() if k not in {"structure_sha256", "paragraphs"}}
    structural["paragraphs"] = [{k: v for k, v in p.items() if k != "translation"}
                                for p in doc["paragraphs"]]
    return object_digest(structural)


def seal(doc):
    doc["structure_sha256"] = structure_digest(doc)


def engine_digest():
    files = sorted((ROOT / "scripts").rglob("*.py")) + sorted((ROOT / "schemas").glob("*.json"))
    return object_digest({str(p.relative_to(ROOT)): digest(p) for p in files})


def check_translation(p, text):
    out = []
    if not isinstance(text, str) or not text.strip():
        return [issue("translation/missing", p["id"], {}, ["translate this paragraph"])]
    expected, actual = Counter(TOKEN.findall(p["source"])), Counter(TOKEN.findall(text))
    if expected != actual:
        out.append(issue("translation/tokens", p["id"], {"expected": dict(expected), "actual": dict(actual)},
                         ["restore each protected token exactly once"]))
    math_order = lambda s: [t for t in TOKEN.findall(s) if t.startswith("[[M")]
    if math_order(text) != math_order(p["source"]):
        out.append(issue("translation/math-order", p["id"], {}, ["restore formula order"]))
    if "\n" in text or "\r" in text:
        out.append(issue("translation/paragraph-boundary", p["id"], {},
                         ["submit one semantic paragraph without manual line breaks"]))
    if "```" in text:
        out.append(issue("translation/markdown-fence", p["id"], {}, ["remove Markdown fences"]))
    return out


def validate(doc, require_translations=False, job=None):
    schema = read(ROOT / "schemas/document.schema.json")
    errors = [issue("schema/invalid", "/" + "/".join(map(str, e.absolute_path)),
                    {"reason": e.message}, ["prepare a v5 document from the original PDF"])
              for e in jsonschema.Draft202012Validator(schema).iter_errors(doc)]
    if errors:
        return errors
    if structure_digest(doc) != doc["structure_sha256"]:
        errors.append(issue("document/structure-changed", "document", {},
                            ["use the supported correct command; do not hand-edit source geometry"]))
    coverage = doc["coverage"]
    if coverage["source_characters"] != coverage["translated_characters"] + coverage["preserved_characters"]:
        errors.append(issue("document/coverage", "coverage", coverage))
    for obj in doc["paragraphs"] + list(doc["assets"].values()) + doc["preserved"]:
        rects = [obj["bbox"]] + obj.get("erase", [])
        if any(not all(math.isfinite(x) for x in r) or r[0] >= r[2] or r[1] >= r[3] for r in rects):
            errors.append(issue("document/geometry", obj.get("id", "region"), {}))
        if obj["page"] >= len(doc["pages"]):
            errors.append(issue("document/page-range", obj.get("id", "region"), {}))
    for aid, asset in doc["assets"].items():
        if abs(asset["ascent"] + asset["descent"] - asset["height"]) > .01:
            errors.append(issue("asset/baseline", aid, {}))
    seen = set()
    for p in doc["paragraphs"]:
        if p["id"] in seen:
            errors.append(issue("document/duplicate-id", p["id"], {}))
        seen.add(p["id"])
        if p["style_id"] not in doc["styles"]:
            errors.append(issue("document/style-missing", p["id"], {}))
        if p["page"] >= len(doc["pages"]):
            errors.append(issue("document/page-range", p["id"], {}))
        for token in TOKEN.findall(p["source"]):
            if token not in p["tokens"]:
                errors.append(issue("document/token-unbound", p["id"], {"token": token}))
        for token, entry in p["tokens"].items():
            if p["source"].count(token) != 1 or not TOKEN.fullmatch(token):
                errors.append(issue("document/token-binding", p["id"], {"token": token}))
            if entry["kind"] == "math" and entry["asset"] not in doc["assets"]:
                errors.append(issue("document/asset-missing", p["id"], {"token": token}))
        if require_translations or p["translation"] is not None:
            errors.extend(check_translation(p, p["translation"]))
    flows = {}
    for p in doc["paragraphs"]:
        flows.setdefault(p["flow_id"], []).append(p)
    for fid, group in flows.items():
        if len({p["style_id"] for p in group}) > 1 or any(not p["continuation"] for p in group[1:]):
            errors.append(issue("document/flow-inconsistent", fid, {}, ["correct paragraph roles and flow boundaries"]))
    if job is not None:
        job = Path(job)
        source = job / "source.pdf"
        if not source.is_file() or digest(source) != doc["source_sha256"]:
            errors.append(issue("document/source-changed", "source.pdf", {}))
        for key, a in doc["assets"].items():
            asset_path = (job / a["file"]).resolve()
            if not asset_path.is_relative_to(job.resolve()):
                errors.append(issue("asset/path", key, {}))
            elif not asset_path.is_file() or digest(asset_path) != a["sha256"]:
                errors.append(issue("asset/changed", key, {}))
        for kind, font in doc["fonts"].items():
            if not Path(font["path"]).is_file() or digest(font["path"]) != font["sha256"]:
                errors.append(issue("font/changed", kind, {}, ["prepare with an available static font pair"]))
    return errors


class Failure(Exception):
    def __init__(self, diagnostics):
        self.diagnostics = diagnostics
        super().__init__(diagnostics[0]["code"] if diagnostics else "failure")


def require(errors):
    if any(x["severity"] == "error" for x in errors):
        raise Failure(errors)
