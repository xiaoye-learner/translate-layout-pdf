from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

import pymupdf as fitz
from PIL import Image, ImageChops

from .contracts import Failure, check_translation, digest, engine_digest, issue, object_digest, read, require, seal, validate, write
from .fonts import register_document_font
from .layout import Typesetter


def load_job(job, translated=False):
    job = Path(job).resolve()
    doc = read(job / "document.json")
    require(validate(doc, translated, job))
    return job, doc


def merge(job, batch):
    job, doc = load_job(job)
    values = read(batch)
    if not isinstance(values, dict):
        raise Failure([issue("translation/batch-shape", str(batch), {}, ["use an ID-to-translation JSON object"])])
    by_id = {p["id"]: p for p in doc["paragraphs"]}
    errors = []
    for pid, text in values.items():
        if pid not in by_id:
            errors.append(issue("translation/unknown-id", pid, {}))
        else:
            errors.extend(check_translation(by_id[pid], text))
    require(errors)
    for pid, text in values.items():
        by_id[pid]["translation"] = text.strip()
    write(job / "document.json", doc)
    return {"merged": len(values), "remaining": sum(p["translation"] is None for p in doc["paragraphs"])}


def correct(job, patch):
    job, doc = load_job(job)
    changes = read(patch)
    if not isinstance(changes, list):
        raise Failure([issue("correction/shape", str(patch), {})])
    paragraphs = {p["id"]: p for p in doc["paragraphs"]}
    for change in changes:
        if not isinstance(change, dict) or not change.get("reason"):
            raise Failure([issue("correction/reason-required", str(patch), {})])
        pid, field, value = change.get("id"), change.get("field"), change.get("value")
        if field == "placement" and pid in doc["assets"] and value in {"inline", "display"}:
            doc["assets"][pid][field] = value
        elif pid in paragraphs and field == "continuation" and isinstance(value, bool):
            paragraphs[pid][field] = value
            if value:
                ordered = doc["paragraphs"]
                index = ordered.index(paragraphs[pid])
                if index == 0:
                    raise Failure([issue("correction/continuation-first", pid, {})])
                paragraphs[pid]["flow_id"] = ordered[index - 1]["flow_id"]
            else:
                paragraphs[pid]["flow_id"] = pid
        elif pid in paragraphs and field == "continuation_of" and value in paragraphs:
            p, predecessor = paragraphs[pid], paragraphs[value]
            if predecessor["style_id"] != p["style_id"] or predecessor["role"] != p["role"]:
                raise Failure([issue("correction/flow-style", pid, {"predecessor": value},
                                      ["correct roles before linking the flow"])])
            p["continuation"] = True
            p["flow_id"] = predecessor["flow_id"]
        elif pid in paragraphs and field == "role" and value in {"body", "heading", "subheading", "title", "caption", "footnote", "list", "affiliation", "table_cell"}:
            p = paragraphs[pid]
            old = doc["styles"][p["style_id"]]
            sid = f"corrected-{value}-{old['size']}"
            doc["styles"][sid] = dict(old, bold=value in {"title", "heading", "subheading"})
            p["role"], p["style_id"] = value, sid
        else:
            raise Failure([issue("correction/unsupported", str(pid), {"field": field},
                                 ["supported fields: paragraph role/continuation/continuation_of, formula placement"])])
    seal(doc)
    require(validate(doc, False, job))
    write(job / "document.json", doc)
    history_path = job / "corrections.json"
    history = read(history_path) if history_path.exists() else []
    history.extend(changes)
    write(history_path, history)
    return {"corrected": len(changes)}


def raster(page, bbox, size=None):
    pix = page.get_pixmap(matrix=fitz.Matrix(3, 3), clip=fitz.Rect(bbox), colorspace=fitz.csGRAY, alpha=False, annots=False)
    im = Image.frombytes("L", (pix.width, pix.height), pix.samples)
    return im.resize(size, Image.Resampling.BILINEAR) if size else im


def difference(a, b):
    if a.size != b.size:
        a = a.resize(b.size, Image.Resampling.BILINEAR)
    histogram = ImageChops.difference(a, b).histogram()
    return sum(histogram[65:]) / max(1, b.width * b.height)


def compose_dual(source, mono, path):
    dual = fitz.open()
    for i in range(len(source)):
        a, b = source[i].rect, mono[i].rect
        page = dual.new_page(width=a.width + b.width, height=max(a.height, b.height))
        page.show_pdf_page(fitz.Rect(0, 0, a.width, a.height), source, i)
        page.show_pdf_page(fitz.Rect(a.width, 0, a.width + b.width, b.height), mono, i)
        for source_page, offset in ((source[i], 0), (mono[i], a.width)):
            for link in source_page.get_links():
                entry = {k: v for k, v in link.items() if k not in {"xref", "id"}}
                entry["from"] = fitz.Rect(entry["from"]) + (offset, 0, offset, 0)
                if offset and entry.get("to") is not None and entry.get("kind") == fitz.LINK_GOTO:
                    entry["to"] = fitz.Point(entry["to"].x + offset, entry["to"].y)
                try:
                    page.insert_link(entry)
                except Exception:
                    # Unsupported link kinds stay visible in the flattened source page.
                    pass
    dual.save(path, garbage=4, deflate=True, no_new_id=True)
    dual.close()


def build(job, preflight=False, layout_mode="balanced"):
    job, doc = load_job(job, translated=not preflight)
    require(doc["diagnostics"])
    snapshot_hash = digest(job / "document.json")
    if preflight:
        for p in doc["paragraphs"]:
            p["translation"] = p["source"]
    plan = Typesetter(doc, preflight=preflight, layout_mode=layout_mode).compile()
    retained = set(plan["retained_paragraphs"])
    retained_assets = {token["asset"] for p in doc["paragraphs"] if p["id"] in retained
                       for token in p["tokens"].values() if token["kind"] == "math"}
    errors = list(plan["diagnostics"])
    build_dir = Path(tempfile.mkdtemp(prefix="build-", dir=job))
    write(build_dir / "document.json", doc)
    write(build_dir / "layout.json", plan)
    mono_path = build_dir / "translated.pdf"
    source = fitz.open(job / "source.pdf")
    mono = fitz.open(job / "source.pdf")
    assets = {k: fitz.open(job / a["file"]) for k, a in doc["assets"].items()}
    try:
        for page_index, page in enumerate(mono):
            original_links = source[page_index].get_links()
            erased = []
            for p in doc["paragraphs"]:
                if p["page"] == page_index and p["id"] not in retained:
                    for rect in p["erase"]:
                        erased.append(fitz.Rect(rect))
                        page.add_redact_annot(rect, fill=False, cross_out=False)
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE, graphics=fitz.PDF_REDACT_LINE_ART_NONE)
            for aid, a in doc["assets"].items():
                if a["page"] == page_index and aid not in retained_assets:
                    page.add_redact_annot(a["bbox"], fill=False, cross_out=False)
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE, graphics=fitz.PDF_REDACT_LINE_ART_REMOVE_IF_TOUCHED)
            page = mono.reload_page(page)
            current_links = page.get_links()
            for link in original_links:
                if any(not (fitz.Rect(link["from"]) & rect).is_empty for rect in erased):
                    continue
                if not any(link.get("uri") == other.get("uri") and link.get("from") == other.get("from") for other in current_links):
                    page.insert_link({k: v for k, v in link.items() if k not in {"xref", "id"}})
            for key, font in doc["fonts"].items():
                register_document_font(page, "lp" + key, font)
            # Consecutive text units are coalesced per baseline to preserve searchable text.
            items = [item for item in plan["placements"] if item["page"] == page_index]
            i = 0
            while i < len(items):
                item = items[i]
                if item["kind"] == "math":
                    page.show_pdf_page(fitz.Rect(item["bbox"]), assets[item["asset"]], 0, keep_proportion=False)
                    i += 1
                    continue
                text = item["text"]
                j = i + 1
                while j < len(items):
                    other = items[j]
                    if other["kind"] != "text" or any(other.get(k) != item.get(k) for k in ("paragraph", "line", "font", "size", "baseline", "link_uri")):
                        break
                    text += other["text"]
                    j += 1
                page.insert_text((item["x"], item["baseline"]), text, fontsize=item["size"], fontname="lp" + item["font"], color=(0, 0, 0))
                if item.get("link_uri"):
                    region = fitz.Rect(items[i]["bbox"])
                    for linked in items[i + 1:j]:
                        region |= fitz.Rect(linked["bbox"])
                    page.insert_link({"kind": fitz.LINK_URI, "from": region, "uri": item["link_uri"]})
                i = j
        mono.subset_fonts()
        mono.save(mono_path, garbage=4, deflate=True, no_new_id=True)
        mono.close()
        mono = fitz.open(mono_path)
        formula_checks = []
        for item in plan["placements"]:
            if item["kind"] == "math":
                asset = assets[item["asset"]]
                # Render the reference at the same size AND subpixel origin. Resizing a tight
                # crop otherwise reports false damage on small superscripts.
                with fitz.open() as reference:
                    bounds = mono[item["page"]].rect
                    refpage = reference.new_page(width=bounds.width, height=bounds.height)
                    refpage.show_pdf_page(fitz.Rect(item["bbox"]), asset, 0, keep_proportion=False)
                    diff = difference(raster(refpage, item["bbox"]), raster(mono[item["page"]], item["bbox"]))
                formula_checks.append(dict(asset=item["asset"], page=item["page"] + 1, bbox=item["bbox"], difference=diff))
                if diff > .08:
                    errors.append(issue("formula/render-mismatch", item["asset"], {"difference": diff, "bbox": item["bbox"]},
                                        ["inspect the formula source and target crops"], stage="artifact"))
        for aid in sorted(retained_assets):
            a = doc["assets"][aid]
            diff = difference(raster(source[a["page"]], a["bbox"]), raster(mono[a["page"]], a["bbox"]))
            formula_checks.append(dict(asset=aid, page=a["page"] + 1, bbox=a["bbox"], difference=diff))
            if diff > .08:
                errors.append(issue("formula/render-mismatch", aid, {"difference": diff}, stage="artifact"))
        for r in doc["preserved"]:
            diff = difference(raster(source[r["page"]], r["bbox"]), raster(mono[r["page"]], r["bbox"]))
            if diff > .02:
                errors.append(issue("artifact/preserved-changed", r, {"difference": diff}, stage="artifact"))
        for p in doc["paragraphs"]:
            if p["id"] not in retained:
                continue
            for rect in p["erase"]:
                diff = difference(raster(source[p["page"]], rect), raster(mono[p["page"]], rect))
                if diff > .02:
                    errors.append(issue("artifact/retained-changed", p["id"], {"difference": diff}, stage="artifact"))
        dual_path = build_dir / "bilingual.pdf"
        compose_dual(source, mono, dual_path)
        with fitz.open(dual_path) as dual:
            if len(dual) != len(mono) or any(abs(dual[i].rect.width - 2 * mono[i].rect.width) > .01 for i in range(len(mono))):
                errors.append(issue("artifact/dual-pages", "bilingual.pdf", {}, stage="artifact"))
        receipt = dict(schema="layout-receipt/v1", source_document_sha256=snapshot_hash,
                       engine_sha256=engine_digest(), snapshot_sha256=digest(build_dir / "document.json"),
                       layout_sha256=digest(build_dir / "layout.json"), preflight=preflight,
                       ok=not any(d["severity"] == "error" for d in errors), diagnostics=errors,
                       formulas=formula_checks, page_count=len(mono), visual_review="pending",
                       artifacts={"mono": {"file": "translated.pdf", "sha256": digest(mono_path)},
                                  "dual": {"file": "bilingual.pdf", "sha256": digest(dual_path)}})
        history_file = job / "history.json"
        history = read(history_file) if history_file.exists() else []
        fingerprint = sorted({(d["code"], json.dumps(d["subject"], sort_keys=True)) for d in errors})
        history.append(dict(build=build_dir.name, errors=len(fingerprint), fingerprint=fingerprint, ok=receipt["ok"]))
        write(history_file, history)
        write(job / "latest.json", {"build": build_dir.name})
        if len(history) >= 3:
            prior_best = min(x["errors"] for x in history[:-2])
            receipt["repair_stalled"] = all(x["errors"] >= prior_best and x["errors"] > 0 for x in history[-2:])
        write(build_dir / "receipt.json", receipt)
        return dict(build=str(build_dir), **receipt)
    finally:
        for asset in assets.values():
            asset.close()
        source.close()
        mono.close()


def current(job):
    job = Path(job).resolve()
    build_dir = (job / read(job / "latest.json")["build"]).resolve()
    if not build_dir.is_relative_to(job):
        raise Failure([issue("artifact/path", str(build_dir), {})])
    receipt = read(build_dir / "receipt.json")
    if receipt.get("engine_sha256") != engine_digest():
        raise Failure([issue("artifact/engine-changed", "engine", {}, ["build with the current engine before review or delivery"])])
    if digest(build_dir / "document.json") != receipt["snapshot_sha256"]:
        raise Failure([issue("artifact/snapshot-changed", "document.json", {})])
    if digest(job / "document.json") != receipt["source_document_sha256"]:
        raise Failure([issue("artifact/stale", "document.json", {}, ["build after the last edit"])])
    if digest(build_dir / "layout.json") != receipt["layout_sha256"]:
        raise Failure([issue("artifact/layout-changed", "layout.json", {})])
    for item in receipt["artifacts"].values():
        if digest(build_dir / item["file"]) != item["sha256"]:
            raise Failure([issue("artifact/changed", item["file"], {})])
    return build_dir, receipt


def review(job, status=None, notes=None, evidence_hash=None):
    build_dir, receipt = current(job)
    if status:
        evidence = read(build_dir / "evidence.json")
        if evidence_hash != object_digest(evidence) or not notes or not notes.strip():
            raise Failure([issue("review/evidence-required", "review", {}, ["inspect current evidence and supply its hash and specific notes"])])
        for file, expected in evidence["images"].items():
            if digest(build_dir / file) != expected:
                raise Failure([issue("review/evidence-changed", file, {})])
        record = dict(status=status, notes=notes, artifact_hashes=receipt["artifacts"], evidence_sha256=evidence_hash,
                      pages=list(range(1, receipt["page_count"] + 1)))
        write(build_dir / "review.json", record)
        return record
    images = {}
    for kind, item in receipt["artifacts"].items():
        pdf = fitz.open(build_dir / item["file"])
        for dpi in (72, 144):
            thumbs = []
            for i, page in enumerate(pdf):
                path = build_dir / f"{kind}-{dpi}-p{i + 1:04d}.png"
                pix = page.get_pixmap(dpi=dpi, alpha=False)
                pix.save(path)
                images[path.name] = digest(path)
                image = Image.open(path).convert("RGB")
                image.thumbnail((480, 640))
                thumbs.append(image)
            # Bounded sheets retain useful size on long documents.
            for start in range(0, len(thumbs), 6):
                chunk = thumbs[start:start + 6]
                sheet = Image.new("RGB", (960, 660 * ((len(chunk) + 1) // 2)), "#dddddd")
                for j, im in enumerate(chunk):
                    sheet.paste(im, ((j % 2) * 480, (j // 2) * 660))
                path = build_dir / f"{kind}-{dpi}-sheet-{start // 6 + 1}.png"
                sheet.save(path)
                images[path.name] = digest(path)
        pdf.close()
    evidence = dict(artifacts=receipt["artifacts"], images=images, pages=receipt["page_count"], status="pending")
    write(build_dir / "evidence.json", evidence)
    return dict(directory=str(build_dir), evidence_sha256=object_digest(evidence), visual_review="pending")


def deliver(job, output):
    _, doc = load_job(job, translated=True)
    build_dir, receipt = current(job)
    if not receipt["ok"] or receipt["preflight"]:
        raise Failure([issue("delivery/not-accepted", str(build_dir), {}, ["resolve diagnostics and build the translation"])])
    record = read(build_dir / "review.json") if (build_dir / "review.json").exists() else {}
    if record.get("status") != "passed" or record.get("artifact_hashes") != receipt["artifacts"]:
        raise Failure([issue("delivery/review-required", str(build_dir), {}, ["inspect and record current visual review"])])
    output = Path(output).resolve()
    if output.exists():
        raise Failure([issue("delivery/exists", str(output), {}, ["choose a new versioned output directory"])])
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".delivery-", dir=output.parent))
    try:
        for name in ("translated.pdf", "bilingual.pdf", "receipt.json", "review.json"):
            shutil.copy2(build_dir / name, stage / name)
        write(stage / "complete.json", dict(schema="layout-delivery/v1", artifacts=receipt["artifacts"],
                                            source_sha256=doc["source_sha256"], document_sha256=receipt["source_document_sha256"]))
        os.rename(stage, output)
    finally:
        if stage.exists():
            # Stage was just created here and cannot be the source or final directory.
            shutil.rmtree(stage)
    return dict(output=str(output), artifacts=receipt["artifacts"], visual_review="passed")
