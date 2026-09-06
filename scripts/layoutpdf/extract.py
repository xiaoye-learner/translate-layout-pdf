from __future__ import annotations

import re
import shutil
import statistics
from collections import Counter
from pathlib import Path

import pymupdf as fitz

from .contracts import Failure, digest, issue, seal, write
from .fonts import annotate_ink

MATH_FONT = re.compile(r"CMMI|CMSY|CMEX|MSAM|MSBM|math|symbol|STIX.*(?:Italic|Symbols)", re.I)
MATH_SYMBOLS = set("=+−×÷±≤≥≠≈∑∫√∂∇∞∈∉⊂⊆∪∩→↦∀∃∏∝⊗⊕′″ˆ")
ROMAN_MATH_OPERATORS = ("argmin", "argmax", "min", "max", "sin", "cos", "tan", "log", "exp")
PROTECT = re.compile(r"https?://\S+|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|\b10\.\d{4,9}/\S+|\[(?:\d+[ ,;–-]*)+\]")
HEADING = re.compile(r"^(?P<num>\d+(?:\.\d+)*\.?|[IVX]+\.|[A-Z](?:\.\d+)*\.)\s+\S")


def rect_union(rects):
    r = fitz.Rect(rects[0])
    for other in rects[1:]:
        r |= fitz.Rect(other)
    return [round(x, 4) for x in r]


def overlap_fraction(a, b):
    a, b = fitz.Rect(a), fitz.Rect(b)
    intersection = a & b
    area = max(0, intersection.width) * max(0, intersection.height)
    return area / max(.01, min(a.width * a.height, b.width * b.height))


def trim_erase_edges(rects, preserved, threshold=.05):
    """Trim tiny top/bottom contacts so redaction cannot touch preserved math."""
    trimmed = []
    for value in rects:
        rect = fitz.Rect(value)
        for entry in preserved:
            protected = fitz.Rect(entry["bbox"])
            if overlap_fraction(rect, protected) >= threshold:
                continue
            intersection = rect & protected
            if intersection.is_empty:
                continue
            if protected.y1 <= rect.y0 + rect.height * .2:
                rect.y0 = max(rect.y0, protected.y1 + .02)
            elif protected.y0 >= rect.y1 - rect.height * .2:
                rect.y1 = min(rect.y1, protected.y0 - .02)
        if rect.height > .1:
            trimmed.append(list(rect))
    return trimmed


def font_pair(regular=None, bold=None):
    pairs = [(regular, bold)] if regular or bold else [
        ("C:/Windows/Fonts/Deng.ttf", "C:/Windows/Fonts/Dengb.ttf"),
        ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"),
        ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/msyhbd.ttc")]
    for r, b in pairs:
        if r and b and Path(r).is_file() and Path(b).is_file():
            # Both faces must load before any PDF is changed.
            fitz.Font(fontfile=r)
            fitz.Font(fontfile=b)
            return {key: {"path": str(Path(p).resolve()), "sha256": digest(p)}
                    for key, p in [("regular", r), ("bold", b)]}
    raise Failure([issue("font/pair-unavailable", "fonts", {},
                         ["supply --font and --bold-font with a static CJK font pair"], stage="prepare")])


def glyphs(block):
    out = []
    for line in block.get("lines", []):
        for span in line.get("spans", []):
            for c in span.get("chars", []):
                if c["c"].strip():
                    out.append({"text": c["c"], "bbox": list(c["bbox"]),
                                "ink_bbox": list(c.get("ink_bbox", c["bbox"])),
                                "x": c["origin"][0], "y": c["origin"][1],
                                "size": span["size"], "font": span["font"], "flags": span["flags"]})
    return out


def visual_lines(block):
    """Associate script/fraction fragments before flattening text."""
    lines = []
    for raw in block.get("lines", []):
        gs = glyphs({"lines": [raw]})
        if gs:
            lines.append({"glyphs": gs, "bbox": rect_union([g["bbox"] for g in gs])})
    lines.sort(key=lambda x: (x["bbox"][1], x["bbox"][0]))
    groups = []
    for line in lines:
        chosen = None
        for group in reversed(groups):
            a, b = fitz.Rect(group["bbox"]), fitz.Rect(line["bbox"])
            overlap = max(0, min(a.y1, b.y1) - max(a.y0, b.y0))
            if overlap / max(1, min(a.height, b.height)) > .42:
                chosen = group
                break
        if chosen is None:
            groups.append(line)
        else:
            chosen["glyphs"].extend(line["glyphs"])
            chosen["bbox"] = rect_union([chosen["bbox"], line["bbox"]])
    for group in groups:
        gs = group["glyphs"]
        prose = [g for g in gs if not MATH_FONT.search(g["font"])]
        candidates = prose or gs
        counts = Counter(round(g["y"], 1) for g in candidates)
        group["baseline"] = counts.most_common(1)[0][0]
        regular = [g["size"] for g in candidates if abs(g["y"] - group["baseline"]) < 1]
        group["size"] = statistics.median(regular or [g["size"] for g in candidates])
        group["glyphs"].sort(key=lambda g: (g["x"], g["y"]))
    return groups


def join_touching_blocks(blocks):
    """PDF text-show operations may split scripts and surrounding prose into blocks."""
    pending = [dict(b, lines=list(b["lines"])) for b in blocks]
    changed = True
    while changed:
        changed = False
        for i, a in enumerate(pending):
            ar = fitz.Rect(a["bbox"])
            for j in range(i + 1, len(pending)):
                b = pending[j]
                br = fitz.Rect(b["bbox"])
                overlap = max(0, min(ar.y1, br.y1) - max(ar.y0, br.y0))
                gap = max(0, max(ar.x0, br.x0) - min(ar.x1, br.x1))
                if overlap / max(1, min(ar.height, br.height)) > .42 and gap < 14.5:
                    a["lines"].extend(b["lines"])
                    a["bbox"] = rect_union([a["bbox"], b["bbox"]])
                    pending.pop(j)
                    changed = True
                    break
            if changed:
                break
    return pending


def split_wide_gaps(blocks):
    """A producer may store two columns or a row of cells in one PDF block."""
    result = []
    for block in blocks:
        buckets = []
        for raw in block["lines"]:
            gs = sorted(glyphs({"lines": [raw]}), key=lambda g: g["x"])
            pieces = []
            for g in gs:
                if not pieces or g["bbox"][0] - pieces[-1][-1]["bbox"][2] > max(22, g["size"] * 2.5):
                    pieces.append([])
                pieces[-1].append(g)
            for piece in pieces:
                bbox = rect_union([g["bbox"] for g in piece])
                target = next((b for b in buckets if min(b["bbox"][2], bbox[2]) > max(b["bbox"][0], bbox[0])
                               or abs(b["bbox"][0] - bbox[0]) < 12), None)
                spans = [dict(size=g["size"], font=g["font"], flags=g["flags"],
                              chars=[dict(c=g["text"], bbox=g["bbox"], ink_bbox=g["ink_bbox"], origin=(g["x"], g["y"]))]) for g in piece]
                line = dict(spans=spans, bbox=bbox, dir=raw.get("dir", (1, 0)))
                if target is None:
                    buckets.append(dict(type=0, bbox=bbox, lines=[line]))
                else:
                    target["lines"].append(line)
                    target["bbox"] = rect_union([target["bbox"], bbox])
        result.extend(buckets)
    return result


def plain_text(gs):
    result = ""
    prev = None
    for g in sorted(gs, key=lambda g: g["x"]):
        if prev and g["bbox"][0] - prev["bbox"][2] > min(prev["size"], g["size"]) * .13:
            result += " "
        result += g["text"]
        prev = g
    return result


def math_groups(line):
    gs = line["glyphs"]
    marked = set()
    for i, g in enumerate(gs):
        shifted = abs(g["y"] - line["baseline"]) > line["size"] * .18 and g["size"] <= line["size"] * .88
        if MATH_FONT.search(g["font"]) or g["text"] in MATH_SYMBOLS or shifted:
            marked.add(i)
        if shifted and i:
            # A raised footnote marker after a prose word does not make the last letter mathematical.
            word = []
            for prev in reversed(gs[:i]):
                if not prev["text"].isalpha() or (word and word[-1]["bbox"][0] - prev["bbox"][2] > line["size"] * .15):
                    break
                word.append(prev)
            if len(word) >= 3 and all(not MATH_FONT.search(x["font"]) for x in word):
                continue
            # The base belongs to the same protected unit as its scripts.
            j = i - 1
            while j >= 0 and gs[j]["x"] >= g["x"] - line["size"] * .9:
                marked.add(j)
                if abs(gs[j]["y"] - line["baseline"]) < line["size"] * .15:
                    break
                j -= 1
    # Single italic identifiers are mathematical candidates; italic prose is not.
    for i, g in enumerate(gs):
        if not (g["flags"] & 2) or not g["text"].isalpha():
            continue
        left = i == 0 or g["bbox"][0] - gs[i - 1]["bbox"][2] > g["size"] * .12
        right = i == len(gs) - 1 or gs[i + 1]["bbox"][0] - g["bbox"][2] > g["size"] * .12
        if left and right:
            marked.add(i)
    # TeX emits operators such as "min" in a roman font. Mark their baseline
    # letters as one mathematical sequence while leaving ordinary prose alone.
    baseline_letters = [(i, g) for i, g in enumerate(gs) if g["text"].isalpha()
                        and abs(g["y"] - line["baseline"]) < line["size"] * .15]
    for start in range(len(baseline_letters)):
        for operator in ROMAN_MATH_OPERATORS:
            sequence = baseline_letters[start:start + len(operator)]
            if len(sequence) != len(operator) or "".join(g["text"] for _, g in sequence).lower() != operator:
                continue
            attached_left = (start > 0 and sequence[0][1]["bbox"][0]
                             - baseline_letters[start - 1][1]["bbox"][2] < line["size"] * .35)
            attached_right = (start + len(operator) < len(baseline_letters)
                              and baseline_letters[start + len(operator)][1]["bbox"][0]
                              - sequence[-1][1]["bbox"][2] < line["size"] * .35)
            if (not attached_left and not attached_right
                    and all(sequence[j + 1][1]["bbox"][0] - sequence[j][1]["bbox"][2] < line["size"] * .35
                            for j in range(len(sequence) - 1))):
                marked.update(i for i, _ in sequence)
    # Include neighboring punctuation/digits in a formula, without swallowing prose words.
    changed = True
    while changed:
        changed = False
        for i, g in enumerate(gs):
            if i in marked or not (g["text"].isdigit() or g["text"] in "()[]{}.,/|^-_"):
                continue
            if any(j in marked and abs(gs[j]["x"] - g["x"]) < line["size"] * .85
                   for j in (i - 1, i + 1) if 0 <= j < len(gs)):
                marked.add(i)
                changed = True
    groups = []
    for i in sorted(marked):
        if groups and i == groups[-1][-1] + 1 and gs[i]["bbox"][0] - gs[groups[-1][-1]]["bbox"][2] < line["size"] * 1.2:
            groups[-1].append(i)
        else:
            groups.append([i])
    # Sentence punctuation belongs to prose when another word follows. Keeping it in
    # the vector asset would duplicate localized punctuation after the token.
    for group in groups:
        while (group and gs[group[-1]]["text"] in ",.;:"
               and group[-1] + 1 < len(gs) and gs[group[-1] + 1]["text"].isalpha()):
            group.pop()
    groups = [group for group in groups if group]
    return groups


def split_paragraphs(lines):
    groups = []
    x0 = min(x["bbox"][0] for x in lines)
    for line in lines:
        text = plain_text(line["glyphs"])
        prev = groups[-1][-1] if groups else None
        new = not prev
        if prev:
            prev_text = plain_text(prev["glyphs"])
            numeric_line = lambda value: not re.search(r"[A-Za-z\u3400-\u9fff]{2,}", value)
            new = (line["bbox"][1] - prev["bbox"][3] > line["size"] * .6 or
                   (line["bbox"][0] - x0 > line["size"] * .65 and prev["bbox"][0] - x0 < line["size"] * .5) or
                   bool(re.match(r"^[•▪‣]\s*", text)) or
                   numeric_line(prev_text) != numeric_line(text))
            def heading_line(item):
                return len(plain_text(item["glyphs"])) < 100 and sum(bool(g["flags"] & 16) for g in item["glyphs"]) / len(item["glyphs"]) > .8
            if heading_line(prev) != heading_line(line):
                new = True
        if new:
            groups.append([])
        groups[-1].append(line)
    return groups


def make_asset(doc, page_index, group, baseline, placement, assets, job, page_glyphs, diagnostics):
    bbox = fitz.Rect(rect_union([g["ink_bbox"] for g in group]))
    bbox.x0 -= .15
    bbox.x1 += .15
    # Tight academic layouts can leave only hundredths of a point between a
    # summation sign and the preceding line's descenders. Ink bounds already
    # include the glyph; a small vertical antialias margin avoids importing
    # unrelated text from the adjacent line.
    bbox.y0 -= .03
    bbox.y1 += .03
    for drawing in doc[page_index].get_drawings():
        dr = fitz.Rect(drawing["rect"])
        padded = dr + (-.2, -.2, .2, .2)
        if not (padded & bbox).is_empty and dr.width < max(bbox.width * 3, 20) and dr.height < max(bbox.height * 1.4, 5):
            bbox |= padded
    # Reject a clip that contains unrelated source glyphs. A successful crop alone proves nothing.
    identities = {(g["x"], g["y"], g["text"]) for g in group}
    others = [g for g in page_glyphs if (g["x"], g["y"], g["text"]) not in identities
              and overlap_fraction(g["ink_bbox"], bbox) >= .02]
    if others:
        raise Failure([issue("parse/formula-ambiguous", {"page": page_index + 1, "bbox": list(bbox)},
                             {"overlapping_text": plain_text(others)},
                             ["inspect source formula boundaries before translating"], stage="prepare")])
    asset_id = f"m{len(assets) + 1:04d}"
    out = fitz.open()
    target = out.new_page(width=bbox.width, height=bbox.height)
    target.show_pdf_page(target.rect, doc, page_index, clip=bbox)
    file = f"assets/{asset_id}.pdf"
    out.save(job / file, garbage=4, deflate=True, no_new_id=True)
    out.close()
    # A superscript's reference baseline can be below its ink: signed descent preserves that offset.
    assets[asset_id] = dict(file=file, sha256=digest(job / file), bbox=list(bbox), page=page_index,
                            width=bbox.width, height=bbox.height, ascent=baseline - bbox.y0,
                            descent=bbox.y1 - baseline, placement=placement)
    return asset_id


def absorb_split_formula_fragments(doc, document, job, raw_pages):
    """Fold overlapping numeric sub-blocks back into their containing formula asset."""
    absorbed = set()
    transferred = 0
    for index, preserved in enumerate(document["preserved"]):
        if preserved["reason"] != "formula-or-numeric":
            continue
        protected = fitz.Rect(preserved["bbox"])
        matches = []
        for asset_id, asset in document["assets"].items():
            if asset["page"] != preserved["page"]:
                continue
            asset_box = fitz.Rect(asset["bbox"])
            intersection = asset_box & protected
            horizontal = max(0, intersection.width) / max(.01, protected.width)
            if not intersection.is_empty and intersection.height > 0 and horizontal >= .8:
                matches.append((asset_id, asset))
        if len(matches) != 1:
            continue
        asset_id, asset = matches[0]
        old_box = fitz.Rect(asset["bbox"])
        baseline = old_box.y0 + asset["ascent"]
        bbox = old_box | protected
        out = fitz.open()
        target = out.new_page(width=bbox.width, height=bbox.height)
        target.show_pdf_page(target.rect, doc, asset["page"], clip=bbox)
        path = job / asset["file"]
        out.save(path, garbage=4, deflate=True, no_new_id=True)
        out.close()
        asset.update(sha256=digest(path), bbox=list(bbox), width=bbox.width, height=bbox.height,
                     ascent=baseline - bbox.y0, descent=bbox.y1 - baseline)
        page_glyphs = [g for b in raw_pages[asset["page"]]["blocks"] if b["type"] == 0 for g in glyphs(b)]
        count = sum(overlap_fraction(g["bbox"], protected) >= .5 for g in page_glyphs)
        transferred += count
        absorbed.add(index)
        document["diagnostics"].append(issue(
            "parse/formula-fragment-absorbed", {"page": asset["page"] + 1, "asset": asset_id},
            {"bbox": list(protected)}, severity="warning", stage="prepare"))
    if absorbed:
        document["preserved"] = [r for index, r in enumerate(document["preserved"]) if index not in absorbed]
        document["coverage"]["preserved_characters"] -= transferred
        document["coverage"]["translated_characters"] += transferred


def prepare(source, job, target_language="zh-CN", regular=None, bold=None):
    job = Path(job).resolve()
    if job.exists():
        raise Failure([issue("job/already-exists", str(job), {}, ["resume this job or use a new job directory"], stage="prepare")])
    fonts = font_pair(regular, bold)
    pdf = fitz.open(source)
    if pdf.needs_pass:
        raise Failure([issue("input/encrypted", str(source), {}, ["provide an unlocked PDF"], stage="prepare")])
    job.mkdir(parents=True)
    (job / "assets").mkdir()
    shutil.copy2(source, job / "source.pdf")
    raw_pages = [p.get_text("rawdict") for p in pdf]
    for page, raw in zip(pdf, raw_pages):
        annotate_ink(pdf, page, raw)
    all_blocks = [join_touching_blocks(split_wide_gaps([b for b in raw["blocks"] if b["type"] == 0])) for raw in raw_pages]
    sizes = [round(g["size"] * 2) / 2 for blocks in all_blocks for b in blocks for g in glyphs(b)
             if g["text"].isalpha() and not MATH_FONT.search(g["font"])]
    body_size = Counter(sizes).most_common(1)[0][0] if sizes else 10.0
    document = dict(schema="translate-layout-pdf/v5", engine="native-vector-v1", source_sha256=digest(source),
                    structure_sha256="0" * 64, target_language=target_language,
                    pages=[dict(width=p.rect.width, height=p.rect.height) for p in pdf],
                    fonts=fonts, styles={}, assets={}, paragraphs=[], preserved=[], diagnostics=[],
                    coverage=dict(source_characters=0, translated_characters=0, preserved_characters=0))
    for page_index, blocks in enumerate(all_blocks):
        page = pdf[page_index]
        image_regions = [list(b["bbox"]) for b in raw_pages[page_index]["blocks"] if b["type"] == 1]
        table_regions = []
        try:
            candidates = [list(table.bbox) for table in page.find_tables().tables]
            # Borderless benchmark tables often expose only a final horizontal rule to
            # the default detector. Text columns plus horizontal rules recover their
            # full extent without treating ordinary two-column prose as a table.
            mixed = [list(table.bbox) for table in page.find_tables(
                vertical_strategy="text", horizontal_strategy="lines").tables]
            for r in mixed:
                if r[1] <= page.rect.height * .06 or r[3] - r[1] <= body_size * 2.5:
                    continue
                if r[0] < page.rect.width / 2 and r[2] < page.rect.width / 2:
                    r[2] = page.rect.width / 2 - 12
                candidates.append(r)
            for r in candidates:
                target = next((current for current in table_regions
                               if not (fitz.Rect(current) & fitz.Rect(r)).is_empty), None)
                if target is None:
                    table_regions.append(r)
                else:
                    target[:] = list(fitz.Rect(target) | fitz.Rect(r))
        except Exception:
            # Table discovery is advisory; unsupported producers still retain their vector art.
            pass
        figure_regions = []
        for candidate in blocks:
            candidate_glyphs = glyphs(candidate)
            if not candidate_glyphs:
                continue
            candidate_text = " ".join(plain_text(line["glyphs"])
                                      for line in visual_lines(candidate)).strip()
            if not re.match(r"^(?:Figure|Fig\.?)\s*\d", candidate_text, re.I):
                continue
            caption = fitz.Rect(rect_union([g["bbox"] for g in candidate_glyphs]))
            related = [fitz.Rect(r) for r in image_regions
                       if r[3] <= caption.y0 + 3 and caption.y0 - r[3] < page.rect.height * .4
                       and min(caption.x1, r[2]) > max(caption.x0, r[0])]
            if related:
                top = max(0, min(r.y0 for r in related) - body_size * 2)
                figure_regions.append([caption.x0, top, caption.x1, caption.y0 - 1])
        if table_regions:
            document["preserved"].extend(dict(page=page_index, bbox=r, reason="table") for r in table_regions)
            document["diagnostics"].append(issue("parse/table-preserved", {"page": page_index + 1},
                {"tables": len(table_regions)}, ["visually inspect preserved table content"],
                severity="warning", stage="prepare"))
        document["preserved"].extend(dict(page=page_index, bbox=r, reason="image") for r in image_regions)
        document["preserved"].extend(dict(page=page_index, bbox=r, reason="figure") for r in figure_regions)
        for drawing in page.get_drawings():
            for item in drawing["items"]:
                if item[0] == "l":
                    a, b = item[1:3]
                    if (abs(a.y - b.y) < .5 and abs(a.x - b.x) > page.rect.width * .08) or (abs(a.x - b.x) < .5 and abs(a.y - b.y) > page.rect.height * .08):
                        pad = max(.2, (drawing.get("width") or .5) / 2)
                        r = fitz.Rect(min(a.x,b.x)-pad, min(a.y,b.y)-pad, max(a.x,b.x)+pad, max(a.y,b.y)+pad)
                        document["preserved"].append(dict(page=page_index, bbox=list(r), reason="rule"))
        page_glyphs = [g for b in blocks for g in glyphs(b)]
        front_end = min((b["bbox"][1] for b in blocks if any(plain_text(glyphs({"lines": [line]})).strip() in {"Abstract", "摘要"}
                        for line in b["lines"])), default=0)
        title_candidates = [b for b in blocks if b["bbox"][1] < page.rect.height * .2
                            and any(g["size"] >= body_size * 1.25 for g in glyphs(b))]
        title_box = min(title_candidates, key=lambda b: b["bbox"][1])["bbox"] if title_candidates else None
        title_end = title_box[3] if title_box else 0
        document["coverage"]["source_characters"] += len(page_glyphs)
        if not page_glyphs:
            document["diagnostics"].append(issue("parse/no-text", {"page": page_index + 1}, {},
                                                 ["provide a text PDF or an OCRed copy"], stage="prepare"))
        # Stable visual reading order for ordinary one/two-column documents.
        full = [b for b in blocks if b["bbox"][2] - b["bbox"][0] > page.rect.width * .55]
        top_full = max((b["bbox"][3] for b in full if b["bbox"][1] < page.rect.height * .35), default=0)
        blocks.sort(key=lambda b: (0 if b["bbox"][1] < top_full else 1,
                                   0 if b["bbox"][0] < page.rect.width / 2 else 1, b["bbox"][1]))
        for block in blocks:
            gs = glyphs(block)
            if not gs:
                continue
            lines = visual_lines(block)
            text = " ".join(plain_text(line["glyphs"]) for line in lines)
            bbox = rect_union([g["bbox"] for g in gs])
            rotated = any(abs(l.get("dir", (1, 0))[1]) > .1 for l in block["lines"])
            any_math = any(math_groups(l) for l in lines)
            nonmath_text = " ".join(plain_text([g for i, g in enumerate(l["glyphs"]) if i not in {j for group in math_groups(l) for j in group}]) for l in lines)
            only_math = any_math and not re.search(r"[A-Za-z\u3400-\u9fff]{2,}", nonmath_text)
            prose_letters = sum(c.isalpha() for c in nonmath_text)
            display_equation = (any_math and len(lines) <= 3 and ("=" in text or "∈" in text)
                                and fitz.Rect(bbox).width < page.rect.width * .68
                                and prose_letters <= 8)
            numeric = not re.search(r"[A-Za-z\u3400-\u9fff]{2,}", text) and not re.search(r"[A-Za-z]{1,}", text)
            front_matter = page_index == 0 and front_end > title_end > 0 and bbox[1] >= title_end - .2 and bbox[3] <= front_end + .2
            marginal = bbox[1] > page.rect.height * .94 or bbox[1] < page.rect.height * .025
            in_table = any((fitz.Rect(bbox) & fitz.Rect(r)).width * (fitz.Rect(bbox) & fitz.Rect(r)).height
                           >= fitz.Rect(bbox).width * fitz.Rect(bbox).height * .8 for r in table_regions)
            in_figure = any((fitz.Rect(bbox) & fitz.Rect(r)).width * (fitz.Rect(bbox) & fitz.Rect(r)).height
                            >= fitz.Rect(bbox).width * fitz.Rect(bbox).height * .8 for r in figure_regions)
            near_image = any(min(abs(bbox[3] - r[1]), abs(r[3] - bbox[1])) < body_size * 1.7
                             and min(bbox[2], r[2]) > max(bbox[0], r[0]) for r in image_regions)
            if rotated or only_math or display_equation or numeric or front_matter or marginal or in_table or in_figure or near_image:
                reason = ("table-text" if in_table else "figure-label" if in_figure or near_image else "header-footer" if marginal
                          else "front-matter" if front_matter else "rotated" if rotated else "formula-or-numeric")
                document["preserved"].append(dict(page=page_index, bbox=bbox, reason=reason))
                document["coverage"]["preserved_characters"] += len(gs)
                continue
            for group_lines in split_paragraphs(lines):
                group_gs = [g for l in group_lines for g in l["glyphs"]]
                pbbox = rect_union([l["bbox"] for l in group_lines])
                ptext = " ".join(plain_text(l["glyphs"]) for l in group_lines)
                group_numeric = not re.search(r"[A-Za-z\u3400-\u9fff]{2,}", ptext)
                if group_numeric:
                    document["preserved"].append(dict(page=page_index, bbox=pbbox, reason="formula-or-numeric"))
                    document["coverage"]["preserved_characters"] += len(group_gs)
                    continue
                page_preserved = [r for r in document["preserved"] if r["page"] == page_index]
                touching = [r for r in page_preserved
                            if (fitz.Rect(r["bbox"]) & fitz.Rect(pbbox)).width
                            * (fitz.Rect(r["bbox"]) & fitz.Rect(pbbox)).height > .5]
                overlaps = [r for r in touching if overlap_fraction(pbbox, r["bbox"]) >= .05]
                if overlaps:
                    document["preserved"].append(dict(page=page_index, bbox=pbbox, reason="source-overlap"))
                    document["coverage"]["preserved_characters"] += len(group_gs)
                    document["diagnostics"].append(issue(
                        "parse/paragraph-preserved", {"page": page_index + 1, "bbox": pbbox},
                        {"source": ptext, "overlap_reasons": sorted({r["reason"] for r in overlaps})},
                        ["visually inspect the preserved source paragraph"], severity="warning", stage="prepare"))
                    continue
                size = statistics.median(l["size"] for l in group_lines)
                bold_fraction = sum(bool(g["flags"] & 16 or re.search("bold|demi", g["font"], re.I)) for g in group_gs) / len(group_gs)
                numbered = HEADING.match(ptext)
                role = "body"
                if page_index == 0 and title_box and abs(pbbox[1] - title_box[1]) < 1 and size >= body_size * 1.25:
                    role = "title"
                elif len(group_lines) <= 3 and (size > body_size * 1.15 or (bold_fraction > .75 and len(ptext) < 100)):
                    role = ("subheading" if (numbered and numbered["num"].rstrip(".").count("."))
                            or size <= body_size * 1.05 else "heading")
                elif re.match(r"^(?:Figure|Fig\.?|Table)\s*\d", ptext, re.I):
                    role = "caption"
                elif re.match(r"^[•▪‣]", ptext):
                    role = "list"
                elif size < body_size * .88 or (size < body_size * .97 and pbbox[1] > page.rect.height * .82):
                    role = "footnote"
                align = "center" if role == "title" and abs((pbbox[0] + pbbox[2]) / 2 - page.rect.width / 2) < page.rect.width * .12 else "left"
                style_id = f"{role}-{round(size * 2) / 2:g}-{align}"
                size = max(5, round(size * 2) / 2)
                if role == "heading":
                    size = max(size, body_size * 1.15)
                elif role == "subheading" and numbered:
                    size = max(size, body_size * 1.05)
                leading = 1.0 if role in {"title", "heading", "subheading"} else 1.18
                document["styles"].setdefault(style_id, dict(size=size, bold=role in {"title", "heading", "subheading"}, align=align, leading=leading))
                tokens, parts = {}, []
                asset_keys_before = set(document["assets"])
                try:
                    for line in group_lines:
                        mgroups = math_groups(line)
                        indices = {i for group in mgroups for i in group}
                        nonmath = [g for i, g in enumerate(line["glyphs"]) if i not in indices]
                        inline = any(g["text"].isalpha() for g in nonmath)
                        starts = {group[0]: group for group in mgroups}
                        line_parts, run = [], []
                        for i, g in enumerate(line["glyphs"]):
                            if i in starts:
                                if run:
                                    line_parts.append(plain_text(run))
                                    run = []
                                math_gs = [line["glyphs"][j] for j in starts[i]]
                                aid = make_asset(pdf, page_index, math_gs, line["baseline"], "inline" if inline else "display",
                                                 document["assets"], job, page_glyphs, document["diagnostics"])
                                token = f"[[M{len(tokens) + 1:04d}]]"
                                tokens[token] = dict(kind="math", asset=aid)
                                line_parts.append(token)
                            elif i not in indices:
                                run.append(g)
                        if run:
                            line_parts.append(plain_text(run))
                        parts.append(" ".join(line_parts))
                except Failure as exc:
                    if not exc.diagnostics or any(d["code"] != "parse/formula-ambiguous" for d in exc.diagnostics):
                        raise
                    # A rectangular vector crop cannot safely isolate this formula. Roll the
                    # paragraph back as one unit and retain the source region without alteration.
                    for aid in set(document["assets"]) - asset_keys_before:
                        asset_file = job / document["assets"][aid]["file"]
                        if asset_file.is_file():
                            asset_file.unlink()
                        del document["assets"][aid]
                    document["preserved"].append(dict(page=page_index, bbox=pbbox, reason="formula-ambiguous"))
                    document["coverage"]["preserved_characters"] += len(group_gs)
                    document["diagnostics"].append(issue(
                        "parse/formula-preserved", {"page": page_index + 1, "bbox": pbbox},
                        {"source": ptext, "ambiguities": [d.get("evidence", {}) for d in exc.diagnostics]},
                        ["visually inspect the preserved formula paragraph"], severity="warning", stage="prepare"))
                    continue
                source_text = " ".join(parts)
                def protected(match):
                    token = f"[[P{len(tokens) + 1:04d}]]"
                    tokens[token] = dict(kind="protected", text=match[0])
                    return token
                source_text = PROTECT.sub(protected, source_text)
                pid = f"p{page_index + 1:04d}-{len(document['paragraphs']) + 1:04d}"
                erase = trim_erase_edges([l["bbox"] for l in group_lines], touching)
                document["paragraphs"].append(dict(id=pid, page=page_index, bbox=pbbox,
                    erase=erase, role=role, style_id=style_id,
                    source=source_text, translation=None, tokens=tokens, continuation=False, flow_id=pid))
                document["coverage"]["translated_characters"] += len(group_gs)
    absorb_split_formula_fragments(pdf, document, job, raw_pages)
    # Room is a container constraint, not the ink's tight bounding box. Expand only into clear space.
    paragraphs = document["paragraphs"]
    for p in paragraphs:
        page = pdf[p["page"]]
        box = fitz.Rect(p["bbox"])
        source_box = fitz.Rect(box)
        if p["role"] in {"body", "list", "footnote", "caption"}:
            neighbor_widths = [fitz.Rect(q["bbox"]).x1 for q in paragraphs if q["page"] == p["page"]
                               and abs(q["bbox"][0] - box.x0) < body_size * 2 and q["bbox"][2] - box.x0 > page.rect.width * .25]
            if neighbor_widths:
                box.x1 = max(box.x1, statistics.median(neighbor_widths))
        obstacles = []
        for q in paragraphs:
            if q is p or q["page"] != p["page"]:
                continue
            qr = fitz.Rect(rect_union(q["erase"]))
            same_lane_body = (p["role"] == q["role"] == "body"
                              and min(box.x1, qr.x1) - max(box.x0, qr.x0)
                                  > min(box.width, qr.width) * .55)
            if not same_lane_body:
                obstacles.append(list(qr))
        obstacles += [r["bbox"] for r in document["preserved"] if r["page"] == p["page"]]
        obstacles += [b["bbox"] for b in raw_pages[p["page"]]["blocks"] if b["type"] == 1]
        next_y = min((b[1] for b in obstacles if b[1] >= source_box.y1 - .5 and min(box.x1, b[2]) > max(box.x0, b[0])), default=page.rect.height - 25)
        box.y1 = min(next_y - 1.5, max(box.y1, source_box.y1 + body_size * 2))
        if box.y1 <= box.y0:
            box.y1 = source_box.y1
        p["bbox"] = list(box)
    for prev, p in zip(paragraphs, paragraphs[1:]):
        if prev["role"] == p["role"] == "body" and prev["style_id"] == p["style_id"] and not re.search(r"[.!?:。！？：][\]\)\"']?$", prev["source"]):
            a, b = prev["bbox"], p["bbox"]
            if p["page"] != prev["page"] or b[0] > a[0] + body_size * 5:
                p["continuation"] = True
                p["flow_id"] = prev["flow_id"]
            same_lane = (p["page"] == prev["page"]
                         and min(b[2], a[2]) - max(b[0], a[0])
                             > min(fitz.Rect(b).width, fitz.Rect(a).width) * .55)
            nearby = p["erase"][0][1] - prev["erase"][-1][3] < body_size * 4
            if same_lane and nearby and re.match(r"^\[\[M\d{4}\]\]", p["source"]):
                p["continuation"] = True
                p["flow_id"] = prev["flow_id"]
        if p["role"] == "body" and re.match(r"^(?:where|with|and|in which|across)\b", p["source"]):
            between = [r for r in document["preserved"] if r["page"] == p["page"] and r["reason"] == "formula-or-numeric"
                       and 0 < p["erase"][0][1] - r["bbox"][3] < body_size * 4]
            same_lane = (p["page"] == prev["page"]
                         and min(p["bbox"][2], prev["bbox"][2]) - max(p["bbox"][0], prev["bbox"][0])
                             > min(fitz.Rect(p["bbox"]).width, fitz.Rect(prev["bbox"]).width) * .55)
            adjacent_across = (p["source"].startswith("across") and same_lane
                               and p["erase"][0][1] - prev["erase"][-1][3] < body_size * 4)
            if between or adjacent_across:
                p["continuation"] = True
                p["flow_id"] = prev["flow_id"]
    merged = []
    token_pattern = re.compile(r"\[\[([MP])\d{4}\]\]")
    for p in paragraphs:
        if merged:
            prev = merged[-1]
            overlap = fitz.Rect(prev["bbox"]) & fitz.Rect(p["bbox"])
            same_flow = (p["continuation"] and p["flow_id"] == prev["flow_id"]
                         and p["page"] == prev["page"] and p["style_id"] == prev["style_id"]
                         and p["role"] == prev["role"]
                         and sum(c.isalpha() for c in token_pattern.sub("", prev["source"])) >= 10)
            if same_flow and overlap.height > .5 and overlap.width > min(fitz.Rect(prev["bbox"]).width, fitz.Rect(p["bbox"]).width) * .55:
                rename = {}
                def renumber(match):
                    old = match.group(0)
                    if old not in rename:
                        new = f"[[{match.group(1)}{len(prev['tokens']) + 1:04d}]]"
                        rename[old] = new
                        prev["tokens"][new] = p["tokens"][old]
                    return rename[old]
                prev["source"] += " " + token_pattern.sub(renumber, p["source"])
                prev["bbox"] = list(fitz.Rect(prev["bbox"]) | fitz.Rect(p["bbox"]))
                prev["erase"].extend(p["erase"])
                continue
        merged.append(p)
    paragraphs = merged
    document["paragraphs"] = paragraphs
    if not document["styles"]:
        document["styles"]["body"] = dict(size=body_size, bold=False, align="left", leading=1.18)
    seal(document)
    write(job / "document.json", document)
    write(job / "batches.json", [dict(id=p["id"], flow_id=p["flow_id"], role=p["role"], source=p["source"],
                                     translation=None) for p in paragraphs])
    pdf.close()
    return document
