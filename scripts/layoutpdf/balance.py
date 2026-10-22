"""Bounded vertical typesetting within obstacle-free source column regions."""
from collections import defaultdict

import pymupdf as fitz


FLOW_ROLES = {"body", "list", "heading", "subheading", "caption"}
HEADING_BEFORE = {"heading": (1.35, 1.80), "subheading": (1.05, 1.50)}
# Baseline distances, not arbitrary increases to nominal font boxes. Fonts with
# tall ascender/descender metrics must never acquire *less* line clearance.
BODY_LEADING = (1.50, 1.80)
CAPTION_LEADING = (1.30, 1.50)


def source_box(paragraph):
    box = fitz.Rect(paragraph["erase"][0])
    for rect in paragraph["erase"][1:]:
        box |= fitz.Rect(rect)
    return box


def balance_columns(document, placements):
    """Pack semantic paragraphs, then share spare height through bounded leading.

    Formula dimensions, baselines within each line, reading order, font sizes,
    source page/column assignment and all fixed objects are unchanged.
    """
    by_paragraph = defaultdict(list)
    for item in placements:
        by_paragraph[item["paragraph"]].append(item)
    lanes = defaultdict(list)
    for p in document["paragraphs"]:
        if p["role"] not in FLOW_ROLES or not by_paragraph[p["id"]]:
            continue
        if p.get("translation") is not None and p.get("translation") == p.get("source"):
            continue
        width = document["pages"][p["page"]]["width"]
        box = fitz.Rect(p["bbox"])
        # A short heading has the column width of its following text, not its
        # own ink width. Otherwise every heading becomes a false fixed obstacle
        # splitting a full-width text column into independently anchored islands.
        anchors = [q for q in document["paragraphs"] if q["page"] == p["page"]
                   and q["role"] in {"body", "list"} and q["bbox"][2]-q["bbox"][0] > width*.30
                   and abs(q["bbox"][0]-box.x0) < width*.08]
        anchor = min(anchors, key=lambda q: (abs(q["bbox"][0]-box.x0), abs(q["bbox"][1]-box.y0))) if anchors else p
        column = fitz.Rect(anchor["bbox"])
        lane = "wide" if max(column.width, box.width) > width * .55 else "left" if (column.x0 + column.x1) / 2 < width / 2 else "right"
        lanes[p["page"], lane].append(p)

    records = []
    for (page, lane), paragraphs in lanes.items():
        paragraphs.sort(key=lambda p: (source_box(p).y0, source_box(p).x0))
        x0 = min(p["bbox"][0] for p in paragraphs)
        x1 = max(p["bbox"][2] for p in paragraphs)
        paragraph_ids = {p["id"] for p in paragraphs}
        fixed = [fitz.Rect(r["bbox"]) for r in document["preserved"] if r["page"] == page]
        fixed += [source_box(p) for p in document["paragraphs"]
                  if p["page"] == page and p["id"] not in paragraph_ids]
        fixed += [fitz.Rect(item["bbox"]) for item in placements
                  if item["page"] == page and item["paragraph"] not in paragraph_ids]
        fixed = [r for r in fixed if min(r.x1, x1) - max(r.x0, x0) > .1]
        regions, region = [], []
        for p in paragraphs:
            current = source_box(p)
            previous = source_box(region[-1]) if region else None
            if previous and any(r.y0 >= previous.y1 - .1 and r.y1 <= current.y0 + .1 for r in fixed):
                regions.append(region)
                region = []
            region.append(p)
        if region:
            regions.append(region)

        for region in regions:
            first, last = source_box(region[0]), source_box(region[-1])
            top, bottom = first.y0, last.y1
            after = [r.y0 for r in fixed if r.y0 >= bottom - .1]
            # A following fixed object defines the end of the same text region;
            # never use the page footer as permission to fill an intentional tail.
            if after:
                next_top = min(after)
                footer = document["pages"][page]["height"] * .93
                if next_top < footer:
                    bottom = max(bottom, next_top - 2)
            entries = []
            for p_index, p in enumerate(region):
                items = by_paragraph[p["id"]]
                lines = defaultdict(list)
                for item in items:
                    lines[item["line"]].append(item)
                previous = None
                previous_baseline = None
                for line in sorted(lines):
                    current = lines[line]
                    y0 = min(item["bbox"][1] for item in current)
                    y1 = max(item["bbox"][3] for item in current)
                    size = current[0]["size"]
                    heading = p["role"] in HEADING_BEFORE and previous is None
                    existing_before = 0
                    minimum_gap = None
                    baseline = max(item["baseline"] for item in current)
                    if previous is not None:
                        gap = max(0, y0 - previous)
                        preferred, maximum = (BODY_LEADING if p["role"] in {"body", "list"}
                                              else CAPTION_LEADING if p["role"] == "caption" else (0, 0))
                        if preferred:
                            # Keep formula clearances from the measured layout;
                            # only add whitespace when this region can afford it.
                            offset = baseline - y0
                            minimum = max(gap, preferred * size - (previous - previous_baseline) - offset)
                            allowance = max(0, maximum * size - (previous - previous_baseline) - offset - minimum)
                            minimum_gap = gap
                            gap = minimum
                        else:
                            allowance = 0
                    elif p_index:
                        prior = region[p_index - 1]
                        if heading and prior["role"] not in HEADING_BEFORE:
                            base, maximum = HEADING_BEFORE[p["role"]]
                            gap, allowance, minimum_gap = size * base, size * (maximum - base), size * .55
                        elif heading:
                            # Consecutive section/subsection headings form one
                            # group rather than two expandable paragraph gaps.
                            gap, allowance = size * .55, 0
                        elif prior["role"] in HEADING_BEFORE:
                            gap, allowance, minimum_gap = size * .65, size * .25, size * .30
                        elif p.get("continuation") and p.get("flow_id") == prior.get("flow_id"):
                            gap, allowance = 0, 0
                        else:
                            gap, allowance = size * .45, size * .15 if p["role"] in {"body", "list"} else 0
                            minimum_gap = size * .30
                        if prior["role"] == "list" and p["role"] == "body":
                            gap = 0
                    else:
                        gap = allowance = 0
                        if heading:
                            before = [r.y1 for r in fixed if r.y1 <= top + .1]
                            if before:
                                existing_before = max(0, top - max(before))
                                base, maximum = HEADING_BEFORE[p["role"]]
                                gap = max(0, size * base - existing_before)
                                allowance = max(0, size * maximum - existing_before - gap)
                                minimum_gap = 0
                    entries.append(dict(items=current, y0=y0, height=y1 - y0,
                                        gap=gap, allowance=allowance, heading=heading,
                                        existing_before=existing_before, minimum_gap=minimum_gap,
                                        baseline_offset=baseline-y0, role=p["role"]))
                    previous = y1
                    previous_baseline = baseline
            packed_height = sum(e["height"] + e["gap"] for e in entries)
            available = bottom - top
            if packed_height > available + .05:
                reducible = sum(max(0, e["gap"] - e["minimum_gap"]) for e in entries if e["minimum_gap"] is not None)
                reduction = min(1, (packed_height - available) / reducible) if reducible else 0
                for entry in entries:
                    if entry["minimum_gap"] is not None:
                        entry["gap"] -= max(0, entry["gap"] - entry["minimum_gap"]) * reduction
                packed_height = sum(e["height"] + e["gap"] for e in entries)
            if packed_height > available + .05:
                # The existing layout still receives its normal geometry checks.
                # Do not alter a dense region that cannot use bounded balancing.
                records.append(dict(page=page+1,lane=lane,paragraphs=[p["id"] for p in region],
                                    status="constrained", source_top=round(top,4),source_bottom=round(bottom,4),
                                    packed_height=round(packed_height,4),available_height=round(available,4)))
                continue
            spare = max(0, available - packed_height)
            heading_allowance = sum(e["allowance"] for e in entries if e["heading"])
            heading_added = min(spare, heading_allowance)
            heading_ratio = heading_added / heading_allowance if heading_allowance else 0
            allowance = sum(e["allowance"] for e in entries if not e["heading"])
            ratio = min(1, max(0, spare - heading_added) / allowance) if allowance else 0
            cursor = top
            shifts = {}
            baseline_steps = []
            prior_entry = None
            heading_spacing = []
            paragraph_gaps = []
            for entry in entries:
                added = entry["allowance"] * (heading_ratio if entry["heading"] else ratio)
                cursor += entry["gap"] + added
                if entry["heading"]:
                    before_gap = entry["existing_before"] + entry["gap"] + added
                    heading_spacing.append(dict(paragraph=entry["items"][0]["paragraph"],
                                                before_gap=round(before_gap, 4),
                                                before_em=round(before_gap / entry["items"][0]["size"], 4)))
                if prior_entry and entry["items"][0]["paragraph"] != prior_entry["items"][0]["paragraph"]:
                    paragraph_gaps.append(dict(paragraph=entry["items"][0]["paragraph"],role=entry["role"],
                                               gap_em=round((entry["gap"]+added)/entry["items"][0]["size"],4)))
                if prior_entry and entry["items"][0]["paragraph"] == prior_entry["items"][0]["paragraph"]:
                    baseline_steps.append(round((cursor + entry["baseline_offset"] - prior_entry["placed_baseline"])
                                                / entry["items"][0]["size"], 4))
                entry["placed_baseline"] = cursor + entry["baseline_offset"]
                delta = cursor - entry["y0"]
                for item in entry["items"]:
                    item["bbox"][1] += delta
                    item["bbox"][3] += delta
                    item["baseline"] += delta
                    shifts[item["paragraph"]] = round(delta, 4)
                cursor += entry["height"]
                prior_entry = entry
            records.append(dict(page=page + 1, lane=lane, paragraphs=[p["id"] for p in region],
                                status="balanced",
                                source_top=round(top, 4), source_bottom=round(bottom, 4),
                                packed_height=round(packed_height, 4), distributed_height=round(heading_added + allowance * ratio, 4),
                                remaining_tail=round(max(0, bottom - cursor), 4),
                                line_gap_expansion=round(ratio, 4), heading_expansion=round(heading_ratio, 4),
                                heading_spacing=heading_spacing, paragraph_gaps=paragraph_gaps,
                                baseline_steps_em=baseline_steps, shifts=shifts))
    return records
