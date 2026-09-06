import copy
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import unicodedata
from pathlib import Path
from unittest.mock import patch

import pymupdf as fitz

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from layoutpdf.contracts import Failure, check_translation, digest, read, seal, validate, write
from layoutpdf.extract import prepare
from layoutpdf.fonts import load_document_font
from layoutpdf.layout import Typesetter, cjk_orphan_paragraphs
from layoutpdf.pipeline import build, correct, current, deliver, merge, review
import layoutpdf.extract as extract_module
from make_fixture import make_fixture


TRANSLATIONS = {
    "A Study": "稳定排版研究",
    "1. Introduction": "1. 引言",
    "This paper": "本文研究固定约束下简单模型的行为。结果同时保留原文含义与视觉结构。",
    "A short": "这是一个短段落。",
    "The value": "数值[[M0001]]控制模型的响应。",
    "The ratio": "比值[[M0001]]保留在这个句子内部，并保留原始分数线。",
    "1.1.": "1.1. 分析",
    "We define": "我们定义以下关系：",
    "where": "其中，变量表示归一化测量值。",
    "2. Conclusion": "2. 结论",
    "The same": "同一级标题的样式在全文中保持一致。",
    "Science": "科学[[M0001]]在这里继续。",
    "Visit": "访问[[P0001]]",
    "3. Further": "3. 更多结果",
    "The left": "左栏中的这个段落在跨栏后继续展开讨论，并且",
    "preserves": "保持相同含义。这是该段落的结尾。",
    "A second": "这是第二个短段落。",
    "A separate": "这是右栏的独立段落。",
}


def canonical_text(value):
    """Normalize compatibility mappings emitted by some subset CJK fonts."""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value))


def translate_document(doc):
    result = {}
    for p in doc["paragraphs"]:
        matches = [t for key, t in TRANSLATIONS.items() if p["source"].startswith(key)]
        if len(matches) != 1:
            raise AssertionError(f"Unexpected source: {p['source']}")
        result[p["id"]] = matches[0]
    return result


class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(tempfile.mkdtemp(prefix="layout-v5-tests-"))
        cls.source = cls.root / "source.pdf"
        make_fixture(cls.source)
        cls.job = cls.root / "job"
        cls.doc = prepare(cls.source, cls.job)
        cls.batch = cls.root / "batch.json"
        write(cls.batch, translate_document(cls.doc))
        merge(cls.job, cls.batch)
        cls.doc = read(cls.job / "document.json")
        cls.result = build(cls.job)
        cls.build_dir = Path(cls.result["build"])
        cls.plan = read(cls.build_dir / "layout.json")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root)

    def test_end_to_end_artifact_passes(self):
        self.assertTrue(self.result["ok"], self.result["diagnostics"])
        self.assertEqual(len(self.result["formulas"]), 3)
        self.assertEqual(self.result["visual_review"], "pending")

    def test_source_reconstruction_preflight_passes(self):
        job = self.root / "preflight-job"
        shutil.copytree(self.job, job)
        result = build(job, preflight=True)
        self.assertTrue(result["ok"], result["diagnostics"])

    def test_inline_scripts_and_fraction_stay_inline(self):
        self.assertEqual(len(self.doc["assets"]), 3)
        self.assertTrue(all(a["placement"] == "inline" for a in self.doc["assets"].values()))
        for p in self.doc["paragraphs"]:
            if not any(x["kind"] == "math" for x in p["tokens"].values()):
                continue
            items = [x for x in self.plan["placements"] if x["paragraph"] == p["id"]]
            math = next(x for x in items if x["kind"] == "math")
            text = [x for x in items if x["kind"] == "text"]
            self.assertTrue(any(x["line"] == math["line"] for x in text))
            self.assertTrue(any(abs(x["baseline"] - math["baseline"]) < .001 for x in text))

    def test_formula_asset_does_not_swallow_sentence_punctuation(self):
        p = next(p for p in self.doc["paragraphs"] if p["source"].startswith("The value"))
        asset_id = next(x["asset"] for x in p["tokens"].values() if x["kind"] == "math")
        self.assertNotIn(",", fitz.open(self.job / self.doc["assets"][asset_id]["file"])[0].get_text())

    def test_roman_math_operator_and_hat_join_formula_group(self):
        def glyph(text, x0, x1, y=10, size=10, font="CMR10", flags=0):
            return {"text": text, "bbox": [x0, y - size, x1, y + 2],
                    "ink_bbox": [x0, y - size, x1, y + 2], "x": x0, "y": y,
                    "size": size, "font": font, "flags": flags}
        line = {"baseline": 10, "size": 10, "glyphs": [
            glyph("m", 0, 5), glyph("θ", 5, 8, y=12, size=7, font="CMMI7", flags=2),
            glyph("i", 5, 7), glyph("n", 7, 12),
            glyph("a", 20, 25, font="CMMI10", flags=2), glyph("ˆ", 22, 24),
            glyph("t", 25, 29, font="CMMI10", flags=2),
        ]}
        groups = [set(group) for group in extract_module.math_groups(line)]
        self.assertTrue(any({0, 1, 2, 3}.issubset(group) for group in groups))
        self.assertTrue(any({4, 5, 6}.issubset(group) for group in groups))

    def test_raised_footnote_keeps_signed_baseline_offset(self):
        p = next(p for p in self.doc["paragraphs"] if p["source"].startswith("Science"))
        asset = self.doc["assets"][next(x["asset"] for x in p["tokens"].values() if x["kind"] == "math")]
        self.assertLess(asset["descent"], 0)

    def test_short_paragraph_actual_pdf_indent(self):
        p = next(p for p in self.doc["paragraphs"] if p["source"] == "A short paragraph.")
        with fitz.open(self.build_dir / "translated.pdf") as pdf:
            spans = [s for b in pdf[0].get_text("dict")["blocks"] if b["type"] == 0 for l in b["lines"] for s in l["spans"]]
            span = next(s for s in spans if "这是一个短段落" in canonical_text(s["text"]))
            self.assertAlmostEqual(span["origin"][0] - p["bbox"][0], 2 * span["size"], delta=.2)

    def test_cjk_body_uses_explicit_extra_leading(self):
        p = next(p for p in self.doc["paragraphs"] if p["source"].startswith("This paper"))
        items = [x for x in self.plan["placements"] if x["paragraph"] == p["id"] and x["kind"] == "text"]
        baselines = sorted({round(x["baseline"], 6) for x in items})
        self.assertGreaterEqual(len(baselines), 2)
        font = load_document_font(self.doc["fonts"][items[0]["font"]])
        size = items[0]["size"]
        requested = size * self.doc["styles"][p["style_id"]]["leading"] * 1.06
        expected = max(size * (font.ascender - font.descender), requested)
        self.assertAlmostEqual(baselines[1] - baselines[0], expected, delta=.02)
        self.assertEqual(self.plan["cjk_body_leading"], 1.06)

    def test_collection_font_uses_target_language_face(self):
        for metadata in self.doc["fonts"].values():
            if Path(metadata["path"]).suffix.lower() in {".ttc", ".otc"} and "NotoSansCJK" in metadata["path"]:
                self.assertIn("CJKsc", metadata.get("font_name", ""))

    def test_headings_use_same_real_bold_face(self):
        with fitz.open(self.build_dir / "translated.pdf") as pdf:
            headings = [s for page in pdf for b in page.get_text("dict")["blocks"] if b["type"] == 0
                        for line in b["lines"] for s in line["spans"] if any(t in canonical_text(s["text"]) for t in ("1.引言", "2.结论", "3.更多结果"))]
            self.assertEqual(len(headings), 3)
            self.assertEqual(len({round(s["size"], 2) for s in headings}), 1)
            self.assertTrue(all("bold" in s["font"].lower() for s in headings))

    def test_display_equation_is_preserved(self):
        preserved = [r for r in self.doc["preserved"] if r["reason"] == "formula-or-numeric" and 300 < r["bbox"][1] < 340]
        self.assertTrue(preserved)
        self.assertFalse(any(p["source"].startswith("[[M") for p in self.doc["paragraphs"]))

    def test_formula_following_continuation_has_no_indent(self):
        p = next(p for p in self.doc["paragraphs"] if p["source"].startswith("where"))
        self.assertTrue(p["continuation"])
        first = next(x for x in self.plan["placements"] if x["paragraph"] == p["id"])
        self.assertAlmostEqual(first["x"], p["bbox"][0], delta=.01)

    def test_tiny_formula_edge_contact_trims_redaction_instead_of_preserving_paragraph(self):
        paragraph = [0, 19.7, 100, 60]
        formula = {"bbox": [0, 10, 100, 20], "reason": "formula-or-numeric"}
        self.assertLess(extract_module.overlap_fraction(paragraph, formula["bbox"]), .05)
        trimmed = extract_module.trim_erase_edges([[0, 19.7, 100, 30]], [formula])
        self.assertAlmostEqual(trimmed[0][1], 20.02, places=2)

    def test_layout_ignores_tiny_preserved_edge_contact(self):
        from layoutpdf.layout import overlap_fraction

        self.assertLess(overlap_fraction([0, 9.98, 100, 20], [0, 0, 100, 10]), .05)
        self.assertGreaterEqual(overlap_fraction([0, 9, 100, 20], [0, 0, 100, 10]), .05)

    def test_overlapping_numeric_fragment_is_absorbed_into_formula_asset(self):
        source = self.root / "split-formula.pdf"
        job = self.root / "split-formula-job"
        with fitz.open() as pdf:
            page = pdf.new_page(width=300, height=220)
            page.insert_text((30, 50), "The metric is", fontsize=10)
            page.insert_text((95, 50), "x", fontsize=12, fontname="tiro")
            page.insert_text((98, 55), "1", fontsize=6)
            page.insert_text((105, 50), "for evaluation.", fontsize=10)
            pdf.save(source)
        doc = prepare(source, job)
        self.assertEqual(doc["coverage"]["source_characters"],
                         doc["coverage"]["translated_characters"] + doc["coverage"]["preserved_characters"])

    def test_formula_followed_by_prose_is_not_preserved_as_display_equation(self):
        source = self.root / "mixed-formula-prose.pdf"
        job = self.root / "mixed-formula-prose-job"
        with fitz.open() as pdf:
            page = pdf.new_page(width=300, height=220)
            page.insert_text((30, 50), "x = 1. AUC reflects average performance.", fontsize=10)
            pdf.save(source)
        doc = prepare(source, job)
        self.assertTrue(any("AUC reflects average performance" in p["source"] for p in doc["paragraphs"]))

    def test_cross_column_flow_is_linked(self):
        first = next(p for p in self.doc["paragraphs"] if p["source"].startswith("The left"))
        second = next(p for p in self.doc["paragraphs"] if p["source"].startswith("preserves"))
        self.assertEqual(first["flow_id"], second["flow_id"])
        self.assertTrue(second["continuation"])

    def test_source_coverage_is_accounted(self):
        c = self.doc["coverage"]
        self.assertEqual(c["source_characters"], c["translated_characters"] + c["preserved_characters"])

    def test_schema_rejects_empty_stub(self):
        self.assertTrue(validate({"schema": "translate-layout-pdf/v5", "paragraphs": []}))

    def test_source_geometry_cannot_be_silently_edited(self):
        doc = copy.deepcopy(self.doc)
        doc["paragraphs"][0]["bbox"][0] += 20
        self.assertIn("document/structure-changed", [x["code"] for x in validate(doc)])

    def test_formula_order_and_duplicate_guard(self):
        p = dict(id="p", source="A [[M0001]] B [[M0002]]")
        self.assertTrue(check_translation(p, "甲[[M0002]]乙[[M0001]]"))
        self.assertTrue(check_translation(p, "甲[[M0001]][[M0001]]"))

    def test_paragraph_boundary_cannot_be_created_by_translation(self):
        p = dict(id="p", source="First paragraph.")
        self.assertTrue(check_translation(p, "第一段。\n\n另一段。"))

    def test_bad_batch_does_not_partially_commit(self):
        batch = self.root / "bad.json"
        before = digest(self.job / "document.json")
        pid = self.doc["paragraphs"][0]["id"]
        write(batch, {pid: "替换标题", "unknown": "不存在的段落"})
        with self.assertRaises(Failure):
            merge(self.job, batch)
        self.assertEqual(before, digest(self.job / "document.json"))

    def test_repeated_layout_is_deterministic(self):
        self.assertEqual(Typesetter(self.doc).compile(), Typesetter(self.doc).compile())

    def test_shorter_cjk_styles_use_one_bounded_expansion(self):
        factors = {self.plan["styles"][p["style_id"]] for p in self.doc["paragraphs"] if p["role"] == "body"}
        self.assertTrue(all(.85 <= factor <= 1.50 for factor in factors))
        self.assertFalse(cjk_orphan_paragraphs(self.plan["placements"]))
        headings = [p for p in self.doc["paragraphs"] if p["role"] in {"heading", "subheading"}]
        self.assertTrue(all(self.plan["styles"][p["style_id"]] >= 1 for p in headings))

    def test_cjk_single_character_final_line_is_rejected(self):
        items = [
            {"kind": "text", "paragraph": "p1", "line": 0, "text": "这是较长正文的一部"},
            {"kind": "text", "paragraph": "p1", "line": 1, "text": "分。"},
            {"kind": "text", "paragraph": "p2", "line": 0, "text": "正常的"},
            {"kind": "text", "paragraph": "p2", "line": 1, "text": "末行文本。"},
        ]
        self.assertEqual(cjk_orphan_paragraphs(items), ["p1"])

    def test_cjk_single_character_final_line_is_rebalanced(self):
        doc = copy.deepcopy(self.doc)
        paragraph = next(p for p in doc["paragraphs"] if p["role"] == "body")
        paragraph.update(
            id="orphan-rebalance",
            translation="这是较长正文的一部",
            bbox=[0, 0, 50, 100],
            erase=[[0, 0, 50, 100]],
            continuation=False,
            tokens={},
        )
        result = Typesetter(doc).place(paragraph)
        self.assertFalse(result["overflow"])
        self.assertFalse(cjk_orphan_paragraphs(result["placements"]))
        final_line = max(item["line"] for item in result["placements"])
        final_text = "".join(item["text"] for item in result["placements"]
                             if item["kind"] == "text" and item["line"] == final_line)
        self.assertGreaterEqual(len(re.findall(r"[\u3400-\u9fff]", final_text)), 2)

    def test_oversized_translation_fails(self):
        doc = copy.deepcopy(self.doc)
        doc["paragraphs"][0]["translation"] = "过长的标题" * 80
        plan = Typesetter(doc).compile()
        self.assertIn("layout/overflow", [x["code"] for x in plan["diagnostics"]])

    def test_delivery_requires_visual_review(self):
        with self.assertRaises(Failure):
            deliver(self.job, self.root / "unreviewed")
        self.assertFalse((self.root / "unreviewed").exists())

    def test_tampered_artifact_is_rejected(self):
        path = self.build_dir / "translated.pdf"
        data = path.read_bytes()
        try:
            path.write_bytes(data + b"\nchanged")
            with self.assertRaises(Failure):
                current(self.job)
        finally:
            path.write_bytes(data)

    def test_links_and_dual_pairing_survive(self):
        with fitz.open(self.build_dir / "translated.pdf") as mono, fitz.open(self.build_dir / "bilingual.pdf") as dual:
            self.assertEqual(len(mono), len(dual))
            self.assertTrue(any(l.get("uri") == "https://example.com/paper" for l in mono[0].get_links()))
            links = [l for l in dual[0].get_links() if l.get("uri") == "https://example.com/paper"]
            self.assertEqual(len(links), 2)
            self.assertLess(links[0]["from"].x0, mono[0].rect.width)
            self.assertGreater(links[1]["from"].x0, mono[0].rect.width)
            self.assertAlmostEqual(dual[0].rect.width, mono[0].rect.width * 2)
            target = [l for l in mono[0].get_links() if l.get("uri") == "https://example.com/paper"][0]["from"]
            word = mono[0].search_for("https://example.com/paper")[0]
            self.assertGreater((target & word).width, word.width * .9)

    def test_detected_table_is_conservatively_preserved(self):
        source = self.root / "table.pdf"
        job = self.root / "table-job"
        with fitz.open() as pdf:
            page = pdf.new_page(width=300, height=300)
            page.insert_text((30, 35), "Table example", fontsize=14, fontname="tibo")
            for y in (80, 110, 140):
                page.draw_line((30, y), (270, y))
            for x in (30, 150, 270):
                page.draw_line((x, 80), (x, 140))
            page.insert_text((50, 101), "alpha")
            page.insert_text((170, 101), "1")
            page.insert_text((50, 131), "beta")
            page.insert_text((170, 131), "2")
            pdf.save(source)
        doc = prepare(source, job)
        self.assertTrue(any(r["reason"] == "table" for r in doc["preserved"]))
        self.assertTrue(any(d["code"] == "parse/table-preserved" for d in doc["diagnostics"]))
        self.assertFalse(any("alpha" in p["source"] or "beta" in p["source"] for p in doc["paragraphs"]))

    def test_ambiguous_formula_preserves_semantic_paragraph_and_rolls_back_assets(self):
        source = self.root / "ambiguous.pdf"
        job = self.root / "ambiguous-job"
        make_fixture(source)
        real_make_asset = extract_module.make_asset
        calls = 0

        def ambiguous_after_write(*args, **kwargs):
            nonlocal calls
            asset_id = real_make_asset(*args, **kwargs)
            calls += 1
            if calls == 1:
                raise Failure([{
                    "code": "parse/formula-ambiguous", "severity": "error", "stage": "prepare",
                    "subject": {"page": 1, "bbox": [90, 180, 106, 195]},
                    "evidence": {"overlapping_text": "′"},
                    "supportedFixes": ["inspect source formula boundaries before translating"],
                }])
            return asset_id

        with patch("layoutpdf.extract.make_asset", side_effect=ambiguous_after_write):
            doc = prepare(source, job)
        self.assertFalse(any(p["source"].startswith("The value") for p in doc["paragraphs"]))
        self.assertTrue(any(r["reason"] == "formula-ambiguous" for r in doc["preserved"]))
        warning = next(d for d in doc["diagnostics"] if d["code"] == "parse/formula-preserved")
        self.assertEqual(warning["severity"], "warning")
        self.assertEqual(warning["evidence"]["ambiguities"][0]["overlapping_text"], "′")
        asset_files = {p.name for p in (job / "assets").glob("*.pdf")}
        self.assertEqual(asset_files, {Path(a["file"]).name for a in doc["assets"].values()})
        coverage = doc["coverage"]
        self.assertEqual(coverage["source_characters"],
                         coverage["translated_characters"] + coverage["preserved_characters"])

    def test_explicit_nonadjacent_flow_correction(self):
        job = self.root / "flow-correction-job"
        shutil.copytree(self.job, job)
        doc = read(job / "document.json")
        bodies = [p for p in doc["paragraphs"] if p["page"] == 1 and p["role"] == "body"]
        target, predecessor = bodies[-1], bodies[0]
        patch = self.root / "flow-correction.json"
        write(patch, [{"id": target["id"], "field": "continuation_of", "value": predecessor["id"],
                       "reason": "verified source reading flow crosses another detected block"}])
        correct(job, patch)
        updated = read(job / "document.json")
        now = next(p for p in updated["paragraphs"] if p["id"] == target["id"])
        self.assertTrue(now["continuation"])
        self.assertEqual(now["flow_id"], predecessor["flow_id"])


if __name__ == "__main__":
    unittest.main()
