"""Small reports for decisions; full sealed data stays in the job on disk."""
from collections import Counter, defaultdict


def diagnostic_summary(diagnostics, limit=8):
    counts = Counter(d["code"] for d in diagnostics)
    groups = []
    for code, count in counts.items():
        examples = [dict(subject=d["subject"], evidence=d.get("evidence", {}),
                         supportedFixes=d.get("supportedFixes", []))
                    for d in diagnostics if d["code"] == code][:2]
        groups.append(dict(code=code, count=count, examples=examples))
    return dict(counts=dict(counts), groups=groups[:limit], omitted_groups=max(0, len(groups)-limit))


def inspect_document(doc, pages=None):
    selected = set(pages or ())
    records = []
    for i, page in enumerate(doc["pages"]):
        paragraphs = [p for p in doc["paragraphs"] if p["page"] == i]
        record = dict(page=i+1, roles=dict(Counter(p["role"] for p in paragraphs)),
                      formulas=sum(a["page"] == i for a in doc["assets"].values()),
                      preserved=dict(Counter(r["reason"] for r in doc["preserved"] if r["page"] == i)))
        if i+1 in selected:
            record["paragraphs"] = [dict(id=p["id"], role=p["role"], flow_id=p["flow_id"],
                                         continuation=p["continuation"], source=p["source"],
                                         translation=p.get("translation")) for p in paragraphs]
        records.append(record)
    return dict(pages=len(doc["pages"]), paragraphs=len(doc["paragraphs"]),
                untranslated=sum(not p.get("translation") for p in doc["paragraphs"]),
                page_map=[r for r in records if not selected or r["page"] in selected],
                diagnostics=diagnostic_summary(doc["diagnostics"]))


def review_plan(doc, plan, limit=6):
    """All pages get contact-sheet review; choose detail by risk and diversity."""
    reasons, scores, mandatory = defaultdict(set), Counter(), set()
    for p in doc["paragraphs"]:
        page = p["page"]+1
        if p["role"] in {"title", "heading", "subheading"}:
            reasons[page].add("heading hierarchy")
            scores[page] += 2
        if len(p["source"]) > 1400:
            reasons[page].add("dense prose")
            scores[page] += 2
    for a in doc["assets"].values():
        page = a["page"]+1
        reasons[page].add("inline mathematics")
        scores[page] += 1
    for r in doc["preserved"]:
        if r["reason"] in {"table", "figure", "figure-label", "image"}:
            page = r["page"]+1
            reasons[page].add("fixed figures/tables")
            scores[page] += 1
    for d in doc["diagnostics"] + plan.get("diagnostics", []):
        subject = d.get("subject", {})
        if isinstance(subject, dict) and "page" in subject and d["code"] in {
                "parse/formula-preserved", "parse/paragraph-preserved"}:
            page = subject["page"]
            mandatory.add(page)
            reasons[page].add(d["code"])
        elif isinstance(subject, dict) and "page" in subject and d["code"] == "parse/formula-vector-mask":
            reasons[subject["page"]].add("source crop mask")
            scores[subject["page"]] += 2
    for region in plan.get("column_regions", []):
        if region.get("status") == "constrained":
            reasons[region["page"]].add("constrained region")
            mandatory.add(region["page"])
        steps = region.get("baseline_steps_em", [])
        if steps and min(steps) < 1.35:
            reasons[region["page"]].add("constrained line spacing")
            scores[region["page"]] += 4
    for page in mandatory:
        scores[page] += 100
    chosen = set(mandatory)
    if doc["pages"]:
        chosen.add(1)
        reasons[1].add("first page")
    # Cover distinct structures before taking additional pages of the same type.
    for feature in ("heading hierarchy", "inline mathematics", "fixed figures/tables", "dense prose"):
        candidates = [p for p, labels in reasons.items() if feature in labels]
        if candidates and not any(feature in reasons[p] for p in chosen):
            chosen.add(max(candidates, key=lambda p: (scores[p], -p)))
    for page in sorted(scores, key=lambda p: (-scores[p], p)):
        if len(chosen) >= max(limit, len(mandatory)):
            break
        chosen.add(page)
    return [dict(page=p, reasons=sorted(reasons[p])) for p in sorted(chosen)]


def compact_result(result):
    """Do not send hundreds of successful formula checks back through the model."""
    result = dict(result)
    if "formulas" in result and isinstance(result["formulas"], list):
        checks = result.pop("formulas")
        result["formula_checks"] = dict(count=len(checks), failed=sum(c["difference"] > .08 for c in checks))
    if isinstance(result.get("selection_checks"),list):
        checks=result.pop("selection_checks")
        result["selection_summary"]=dict(pages=len(checks),
            glyphs=sum(c["glyphs"] for c in checks),
            mismatched_pages=sum(c["glyphs"]!=c["expected_glyphs"] for c in checks),
            off_page=sum(c["off_page"] for c in checks))
    diagnostics = result.pop("diagnostics", None)
    if isinstance(diagnostics, list):
        result["diagnostic_summary"] = diagnostic_summary(diagnostics)
        result["details"] = "See document.json, layout.json and receipt.json in the reported job/build directory."
    elif diagnostics is not None:
        result["diagnostics"] = diagnostics
    # Review records carry per-page hashes on disk; the CLI needs the decision.
    for key in ("artifact_hashes", "artifacts"):
        if key in result:
            result.pop(key)
    return result
