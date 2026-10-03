from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

import pymupdf as fitz

from .contracts import TOKEN, issue
from .fonts import load_document_font
from .balance import balance_columns

ALPHABET = r"A-Za-z0-9\u00c0-\u02ff\u0370-\u052f"
WORDS = re.compile(rf"[{ALPHABET}]+(?:[.'’_-][{ALPHABET}]+)*|\s+|.", re.S)
CJK = re.compile(r"[\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af]")
CLOSING = set("，。；：！？、）》】」』,.!?;:%")
OPENING = set("（《【「『([{")


def overlap_fraction(a, b):
    a, b = fitz.Rect(a), fitz.Rect(b)
    intersection = a & b
    area = max(0, intersection.width) * max(0, intersection.height)
    return area / max(.01, min(a.width * a.height, b.width * b.height))


def cjk_orphan_paragraphs(items):
    """Return paragraphs whose final wrapped line contains only one CJK character."""
    grouped = {}
    for item in items:
        if item["kind"] == "text":
            grouped.setdefault(item["paragraph"], {}).setdefault(item["line"], []).append(item["text"])
    orphaned = []
    for paragraph, lines in grouped.items():
        if len(lines) < 2:
            continue
        counts = [len(CJK.findall("".join(lines[line]))) for line in sorted(lines)]
        if sum(counts) >= 4 and counts[-1] == 1:
            orphaned.append(paragraph)
    return orphaned


class Typesetter:
    def __init__(self, document, preflight=False, layout_mode="balanced"):
        self.doc = document
        self.preflight = preflight
        self.layout_mode = layout_mode
        self.fonts = {k: load_document_font(v) for k, v in document["fonts"].items()}

    def units(self, paragraph):
        text = paragraph["translation"]
        parts = TOKEN.split(text)
        tokens = TOKEN.findall(text)
        units = []
        for index, part in enumerate(parts):
            units.extend(dict(kind="text", text=t) for t in WORDS.findall(part))
            if index < len(tokens):
                entry = paragraph["tokens"][tokens[index]]
                if entry["kind"] == "math":
                    units.append(dict(kind="math", asset=entry["asset"], token=tokens[index]))
                else:
                    uri = entry["text"] if re.match(r"https?://", entry["text"]) else None
                    units.extend(dict(kind="text", text=t, link_uri=uri) for t in WORDS.findall(entry["text"]))
        # Source extraction spaces around a protected formula must not become full CJK gaps.
        clean = []
        for i, u in enumerate(units):
            if u["kind"] == "text" and u["text"].isspace():
                before = units[i - 1] if i else None
                after = units[i + 1] if i + 1 < len(units) else None
                if not before or not after:
                    continue
                is_cjk = lambda v: v["kind"] == "text" and bool(CJK.search(v["text"]))
                if (is_cjk(before) and is_cjk(after)) or (before["kind"] == "math" and is_cjk(after)) or (after["kind"] == "math" and is_cjk(before)):
                    continue
                u = dict(kind="text", text=" ")
            clean.append(u)
        # Bind punctuation before line breaking, including consecutive closing marks.
        # This also prevents an accented name from being split in the middle of a word.
        bound = []
        for unit in clean:
            if (unit["kind"] == "text" and unit["text"] and all(c in CLOSING for c in unit["text"])
                    and bound and bound[-1]["kind"] == "text" and not bound[-1]["text"].isspace()):
                bound[-1]["text"] += unit["text"]
            elif (bound and bound[-1]["kind"] == "text" and all(c in OPENING for c in bound[-1]["text"])
                  and unit["kind"] == "text" and not unit["text"].isspace()):
                bound[-1]["text"] += unit["text"]
            else:
                bound.append(dict(unit))
        for i, unit in enumerate(bound):
            j = i + 1
            while j < len(bound) and bound[j]["kind"] == "text" and bound[j]["text"].isspace():
                j += 1
            if j >= len(bound) or bound[j]["kind"] != "math":
                continue
            latin = unit["kind"] == "text" and bool(re.fullmatch(rf"[{ALPHABET}]+", unit["text"]))
            inline = unit["kind"] == "math" and self.doc["assets"][unit["asset"]]["placement"] == "inline"
            if (latin or inline) and self.doc["assets"][bound[j]["asset"]]["placement"] == "inline":
                for member in bound[i:j]:
                    member["keep_with_next"] = True
        return bound

    def place(self, paragraph, factor=1.0, input_units=None, continuation=None):
        style = self.doc["styles"][paragraph["style_id"]]
        size = style["size"] * factor
        font_key = "bold" if style["bold"] else "regular"
        font = self.fonts[font_key]
        box = fitz.Rect(paragraph["bbox"])
        units = input_units if input_units is not None else self.units(paragraph)
        first_indent = size * 2 if not self.preflight and paragraph["role"] == "body" and not (
            paragraph["continuation"] if continuation is None else continuation) and self.doc["target_language"].startswith(("zh", "ja")) else 0
        cjk_body_leading = (1.06 if not self.preflight and paragraph["role"] == "body"
                            and self.doc["target_language"].startswith(("zh", "ja")) else 1.0)
        lines, current, width = [], [], first_indent
        indent = first_indent

        def finish():
            nonlocal current, width, indent
            while current and current[-1]["kind"] == "text" and current[-1]["text"] == " ":
                width -= current.pop()["width"]
            if current:
                lines.append(dict(units=current, width=width, indent=indent, display=False))
            current, width, indent = [], 0, 0

        for index, raw in enumerate(units):
            u = dict(raw, index=index)
            if u["kind"] == "math":
                asset = self.doc["assets"][u["asset"]]
                u.update(width=asset["width"] * factor, ascent=asset["ascent"] * factor,
                         descent=asset["descent"] * factor)
                if asset["placement"] == "display":
                    finish()
                    lines.append(dict(units=[u], width=u["width"], indent=0, display=True))
                    continue
            else:
                u.update(width=font.text_length(u["text"], fontsize=size),
                         ascent=font.ascender * size, descent=-font.descender * size)
            if not current and u["kind"] == "text" and u["text"] == " ":
                continue
            required_width = u["width"]
            cursor = index
            while units[cursor].get("keep_with_next") and cursor + 1 < len(units):
                cursor += 1
                following = units[cursor]
                required_width += (self.doc["assets"][following["asset"]]["width"] * factor
                                   if following["kind"] == "math" else font.text_length(following["text"], fontsize=size))
            if width + required_width > box.width + .01 and current and not current[-1].get("keep_with_next"):
                # Move the preceding unit with closing punctuation, rather than starting a line with it.
                if u["kind"] == "text" and u["text"] in CLOSING and len(current) > 1:
                    tail = current.pop()
                    width -= tail["width"]
                    finish()
                    current.append(tail)
                    width = tail["width"]
                else:
                    finish()
                if u["kind"] == "text" and u["text"] == " ":
                    continue
            current.append(u)
            width += u["width"]
        finish()

        # Fix a one-character CJK final line inside the paragraph instead of
        # shrinking every paragraph that shares the style.  Moving the final
        # CJK unit from the preceding line is deterministic, keeps reading
        # order intact, and leaves the source font size available to the rest
        # of the page.
        if len(lines) >= 2:
            final_cjk = sum(len(CJK.findall(u.get("text", ""))) for u in lines[-1]["units"]
                            if u["kind"] == "text")
            total_cjk = sum(len(CJK.findall(u.get("text", ""))) for line in lines for u in line["units"]
                            if u["kind"] == "text")
            previous = lines[-2]
            if final_cjk == 1 and total_cjk >= 4 and len(previous["units"]) > 1:
                candidate = previous["units"][-1]
                if (candidate["kind"] == "text" and CJK.search(candidate["text"])
                        and lines[-1]["width"] + candidate["width"] <= box.width + .01):
                    previous["units"].pop()
                    previous["width"] -= candidate["width"]
                    lines[-1]["units"].insert(0, candidate)
                    lines[-1]["width"] += candidate["width"]

        y = box.y0
        placements, consumed = [], 0
        overflow = False
        for n, line in enumerate(lines):
            ascent = max(u["ascent"] for u in line["units"])
            descent = max(u["descent"] for u in line["units"])
            glyph_height = ascent + descent
            advance = max(glyph_height, size * style["leading"] * cjk_body_leading)
            if line["display"]:
                y += size * .12
            if y + glyph_height > box.y1 + .05 or line["width"] > box.width + .05:
                overflow = True
                break
            baseline = y + ascent
            x = box.x0 + line["indent"]
            if style["align"] == "center" or line["display"]:
                x = box.x0 + (box.width - line["width"]) / 2
            elif style["align"] == "right":
                x = box.x1 - line["width"]
            for u in line["units"]:
                bbox = [x, baseline - u["ascent"], x + u["width"], baseline + u["descent"]]
                placements.append({k: v for k, v in u.items() if k not in {"ascent", "descent", "width"}} |
                                  dict(x=x, baseline=baseline, bbox=bbox, size=size, font=font_key,
                                       line=n, scale=factor, paragraph=paragraph["id"], page=paragraph["page"]))
                x += u["width"]
                consumed = max(consumed, u["index"] + 1)
            y += advance + (size * .12 if line["display"] else 0)
        return dict(placements=placements, overflow=overflow, consumed=consumed,
                    remaining=units[consumed:] if overflow else [], used_height=y - box.y0)

    def compile(self):
        # Style-wide scale search keeps all paragraphs of the same style consistent.
        chosen, diagnostics, placements = {}, [], []
        groups = {}
        for p in self.doc["paragraphs"]:
            groups.setdefault(p["flow_id"], []).append(p)
        segmented = {}
        for key, group in groups.items():
            part = 0
            previous = None
            for p in group:
                if previous and previous["page"] == p["page"]:
                    prior_bottom = max(rect[3] for rect in previous["erase"])
                    source_top = min(rect[1] for rect in p["erase"])
                    if any(r["page"] == p["page"] and r["reason"] == "formula-or-numeric"
                           and r["bbox"][1] >= prior_bottom - .1 and r["bbox"][3] <= source_top + .1
                           and min(r["bbox"][2], p["bbox"][2], previous["bbox"][2])
                               > max(r["bbox"][0], p["bbox"][0], previous["bbox"][0])
                           for r in self.doc["preserved"]):
                        # Keep semantic text on its own side of a fixed display
                        # equation; proportional flow splitting can move a
                        # citation or colon into the following explanation.
                        part += 1
                segmented.setdefault((key, part), []).append(p)
                previous = p
        groups = segmented
        retained = {p["id"] for group in groups.values()
                    if not self.preflight and all(p["translation"] == p["source"] for p in group)
                    for p in group}
        groups = {key: group for key, group in groups.items() if group[0]["id"] not in retained}
        retained_boxes = [(p["page"], p["id"], rect) for p in self.doc["paragraphs"]
                          if p["id"] in retained for rect in p["erase"]]
        style_factors = {s: 1.0 for s in self.doc["styles"]}
        paragraph_scales = {}

        def run_group(group, factor):
            combined = []
            for p in group:
                if combined:
                    combined.append(dict(kind="text", text=" "))
                combined.extend(self.units(p))
            out = []
            for i, p in enumerate(group):
                # Preserve occupancy across source columns/pages even when the translation is shorter.
                if i + 1 < len(group) and len(combined) > len(group) - i:
                    weights = [max(1, len(q["source"])) for q in group[i:]]
                    count = max(1, min(len(combined) - (len(group) - i - 1), round(len(combined) * weights[0] / sum(weights))))
                    selected, tail = combined[:count], combined[count:]
                else:
                    selected, tail = combined, []
                result = self.place(p, factor, selected, continuation=p["continuation"] if i == 0 else True)
                out.extend(result["placements"])
                combined = result["remaining"] + tail
                if not combined:
                    break
            return out, combined

        def reflow_body(items, sid):
            """Use the shared lane until the next heading/object, then test total fit."""
            by_paragraph = {}
            for item in items:
                by_paragraph.setdefault(item["paragraph"], []).append(item)
            previous = []
            fit = True
            ordered = sorted((p for p in self.doc["paragraphs"] if p["style_id"] == sid),
                             key=lambda p: (p["page"], p["erase"][0][1], p["bbox"][0]))
            for p in ordered:
                current = by_paragraph.get(p["id"], [])
                if not current:
                    continue
                source_top = min(r[1] for r in p["erase"])
                candidates = [q for q in previous if q["page"] == p["page"]
                              and max(r[3] for r in q["erase"]) <= source_top + .1
                              and min(p["bbox"][2], q["bbox"][2]) - max(p["bbox"][0], q["bbox"][0])
                                  > min(p["bbox"][2]-p["bbox"][0], q["bbox"][2]-q["bbox"][0]) * .55]
                if candidates:
                    q = max(candidates, key=lambda q: max(r[3] for r in q["erase"]))
                    prior_bottom = max(r[3] for r in q["erase"])
                    gap = source_top - prior_bottom
                    blockers = [r for r in self.doc["preserved"] if r["page"] == p["page"]
                                and r["bbox"][3] >= prior_bottom and r["bbox"][1] <= source_top
                                and min(r["bbox"][2], p["bbox"][2]) > max(r["bbox"][0], p["bbox"][0])]
                    semantic_blockers = [other for other in self.doc["paragraphs"]
                        if other["page"] == p["page"] and other["role"] != "body"
                        and min(r[1] for r in other["erase"]) >= prior_bottom - .1
                        and max(r[3] for r in other["erase"]) <= source_top + .1
                        and min(other["bbox"][2], p["bbox"][2]) > max(other["bbox"][0], p["bbox"][0])]
                    if gap < current[0]["size"] * 3 and not blockers and not semantic_blockers and by_paragraph.get(q["id"]):
                        destination = max(x["bbox"][3] for x in by_paragraph[q["id"]]) + max(current[0]["size"] * .3, min(gap, current[0]["size"]))
                        delta = destination - min(x["bbox"][1] for x in current)
                        for item in current:
                            item["bbox"][1] += delta
                            item["bbox"][3] += delta
                            item["baseline"] += delta
                if max(x["bbox"][3] for x in current) > p["bbox"][3] + .05:
                    fit = False
                previous.append(p)
            return fit

        for sid, style in self.doc["styles"].items():
            selected = [g for g in groups.values() if g[0]["style_id"] == sid]
            floor = (.65 if self.preflight else
                     .95 if any(g[0]["role"] in {"title", "heading", "subheading"} for g in selected) else .85)
            # CJK translations are often substantially shorter at the source point size.
            # Search upward first for body text, but choose one factor for the whole style.
            # This fills the source frame without creating per-paragraph size drift.
            expandable = (not self.preflight and self.doc["target_language"].startswith(("zh", "ja")) and selected
                          and all(g[0]["role"] in {"title", "heading", "subheading", "body"} for g in selected))
            expandable_body = expandable and all(g[0]["role"] == "body" for g in selected)
            lower = [.97, .95] if floor == .95 else [.97, .94, .90, .85]
            attempts = ([1.0, .97, .94, .90, .85, .80, .75, .70, .65] if self.preflight else
                        [1.20, 1.15, 1.10, 1.05, 1.0] + lower if expandable_body else
                        [1.50, 1.45, 1.40, 1.35, 1.30, 1.25, 1.20, 1.15, 1.10, 1.05, 1.0] + lower if expandable else
                        [1.0, .97, .95] if floor == .95 else [1.0, .97, .94, .90, .85])
            for factor in attempts:
                results = [run_group(g, factor) for g in selected]
                exceptions = {}
                # A short source frame or a formula-only frame can be the only
                # member that cannot use a useful CJK expansion.  Permit a
                # small, explicit set of per-paragraph fallbacks so one such
                # frame does not shrink every body paragraph in the document.
                if expandable_body and factor > 1:
                    adjusted = []
                    for group, result in zip(selected, results):
                        items, remaining = result
                        if remaining or cjk_orphan_paragraphs(items):
                            replacement = None
                            for local_factor in [1.15, 1.10, 1.05, 1.0, .97, .94, .90, .85]:
                                if local_factor >= factor:
                                    continue
                                local = run_group(group, local_factor)
                                if not local[1] and not cjk_orphan_paragraphs(local[0]):
                                    replacement = local
                                    exceptions[group[0]["id"]] = local_factor
                                    break
                            adjusted.append(replacement or result)
                        else:
                            adjusted.append(result)
                    if len(exceptions) <= max(2, (len(selected) + 11) // 12):
                        results = adjusted
                    else:
                        exceptions = {}
                candidate = [item for items, _ in results for item in items]
                fits_lane = reflow_body(candidate, sid) if selected and all(g[0]["role"] == "body" for g in selected) else True
                orphaned = cjk_orphan_paragraphs(candidate) if expandable else []
                if not any(remaining for _, remaining in results) and fits_lane and not orphaned:
                    break
            style_factors[sid] = factor
            paragraph_scales.update(exceptions)
            placements.extend(candidate)
            for group, (items, remaining) in zip(selected, results):
                if remaining:
                    diagnostics.append(issue("layout/overflow", group[0]["id"],
                        {"remaining_units": len(remaining), "font_size": style["size"] * factor, "scale": factor},
                        ["check paragraph structure", "submit a meaning-preserving compact translation"], stage="layout"))
            if not fits_lane:
                diagnostics.append(issue("layout/lane-overflow", sid,
                    {"font_size": style["size"] * factor, "scale": factor},
                    ["check paragraph boundaries", "use a more compact translation"], stage="layout"))
            if orphaned:
                diagnostics.append(issue("layout/cjk-orphan-line", sid,
                    {"paragraphs": orphaned, "font_size": style["size"] * factor, "scale": factor},
                    ["use a slightly smaller style scale", "submit a meaning-preserving compact translation"], stage="layout"))
        # Compact neighboring paragraphs within the same source column and obstacle-free
        # text run. Text contraction must not turn each original paragraph into a blank island.
        by_paragraph = {}
        for item in placements:
            by_paragraph.setdefault(item["paragraph"], []).append(item)
        compacted = {}
        previous = []
        for p in sorted(self.doc["paragraphs"], key=lambda p: (p["page"], p["erase"][0][1], p["bbox"][0])):
            items = by_paragraph.get(p["id"], [])
            if not items:
                continue
            source_top = min(r[1] for r in p["erase"])
            size = items[0]["size"]
            candidates = [q for q in previous if q["page"] == p["page"]
                          and max(r[3] for r in q["erase"]) <= source_top + .1
                          and min(p["bbox"][2], q["bbox"][2]) - max(p["bbox"][0], q["bbox"][0])
                              > min(p["bbox"][2]-p["bbox"][0], q["bbox"][2]-q["bbox"][0]) * .55]
            if candidates:
                q = max(candidates, key=lambda q: max(r[3] for r in q["erase"]))
                prior_bottom = max(r[3] for r in q["erase"])
                source_gap = source_top - prior_bottom
                blockers = [r for r in self.doc["preserved"] if r["page"] == p["page"]
                            and r["bbox"][3] >= prior_bottom and r["bbox"][1] <= source_top
                            and min(r["bbox"][2], p["bbox"][2]) > max(r["bbox"][0], p["bbox"][0])]
                blockers += [rect for page, _, rect in retained_boxes if page == p["page"]
                             and rect[3] >= prior_bottom and rect[1] <= source_top
                             and min(rect[2], p["bbox"][2]) > max(rect[0], p["bbox"][0])]
                if source_gap < size * 3 and not blockers:
                    gap = max(size * (.55 if p["role"] in {"title", "heading", "subheading"} else .3), min(source_gap, size))
                    destination = max(x["bbox"][3] for x in by_paragraph[q["id"]]) + gap
                    delta = min(0, destination - min(x["bbox"][1] for x in items))
                    if delta < -.01:
                        compacted[p["id"]] = delta
                        for item in items:
                            item["bbox"][1] += delta
                            item["bbox"][3] += delta
                            item["baseline"] += delta
            previous.append(p)
        # Balance whole source column regions instead of leaving contraction
        # inside independently anchored paragraph boxes.
        regions = (balance_columns(self.doc, placements) if not self.preflight and self.layout_mode == "balanced"
                   and self.doc["target_language"].startswith(("zh", "ja")) else [])
        # Validate actual geometry, not ink-density proxies.
        for item in placements:
            bounds = self.doc["pages"][item["page"]]
            r = fitz.Rect(item["bbox"])
            if not fitz.Rect(0, 0, bounds["width"], bounds["height"]).contains(r):
                diagnostics.append(issue("layout/page-overflow", item["paragraph"], {"bbox": item["bbox"]}, stage="layout"))
            for preserved in self.doc["preserved"]:
                if preserved["page"] == item["page"] and overlap_fraction(r, preserved["bbox"]) >= .05:
                    diagnostics.append(issue("layout/preserved-overlap", item["paragraph"], {"bbox": preserved["bbox"]}, stage="layout"))
            for page, pid, rect in retained_boxes:
                if page == item["page"] and overlap_fraction(r, rect) >= .05:
                    diagnostics.append(issue("layout/retained-overlap", item["paragraph"], {"other": pid}, stage="layout"))
        # Sweep only vertically overlapping items on the same page. Scanning
        # every glyph against every later glyph made whole-paper builds slow.
        by_page = defaultdict(list)
        for item in placements:
            if item["kind"] != "text" or not item["text"].isspace():
                by_page[item["page"]].append(item)
        for page_items in by_page.values():
            active = []
            for item in sorted(page_items, key=lambda item: (item["bbox"][1], item["bbox"][0])):
                active = [other for other in active if other["bbox"][3] > item["bbox"][1]]
                for other in active:
                    if item["paragraph"] == other["paragraph"]:
                        continue
                    overlap = fitz.Rect(item["bbox"]) & fitz.Rect(other["bbox"])
                    if overlap.width * overlap.height > .5:
                        diagnostics.append(issue("layout/paragraph-overlap", item["paragraph"], {"other": other["paragraph"]}, stage="layout"))
                        break
                active.append(item)
        # Font availability is checked against actual translated characters.
        missing = set()
        for item in placements:
            if item["kind"] == "text":
                for c in item["text"]:
                    if not self.fonts[item["font"]].has_glyph(ord(c)):
                        missing.add(c)
        if missing:
            diagnostics.append(issue("font/missing-glyph", "fonts", {"characters": sorted(missing)}, stage="layout"))
        return dict(schema="layout-plan/v1", styles=style_factors, paragraph_scales=paragraph_scales,
                    layout_mode=self.layout_mode,
                    cjk_body_leading=1.06 if not self.preflight and self.doc["target_language"].startswith(("zh", "ja")) else 1.0,
                    vertical_shifts=compacted,
                    column_regions=regions,
                    retained_paragraphs=sorted(retained),
                    placements=placements, diagnostics=diagnostics)
