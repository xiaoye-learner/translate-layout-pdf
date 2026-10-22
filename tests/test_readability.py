"""Regression tests for reading rhythm, semantic continuity and review cost."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"scripts"))
from layoutpdf.balance import balance_columns
from layoutpdf.contracts import Failure, read, write
from layoutpdf.extract import normalize_semantics, prepare
from layoutpdf.inspection import compact_result, review_plan
from layoutpdf.layout import Typesetter
from layoutpdf.pipeline import build, merge, review
from make_fixture import make_fixture
from test_pipeline import translate_document


class ReadabilityTests(unittest.TestCase):
    def test_short_heading_inherits_full_width_column(self):
        specs = [("a", "body", 20, 110, 360), ("h", "subheading", 112, 124, 180),
                 ("b", "body", 126, 230, 360)]
        paragraphs, items = [], []
        for pid, role, y0, y1, right in specs:
            paragraphs.append(dict(id=pid, role=role, page=0, bbox=[40,y0,right,y1],
                                   erase=[[40,y0,right,y1]]))
            for line in range(3 if role=="body" else 1):
                y = y0+line*12
                items.append(dict(paragraph=pid,page=0,line=line,kind="text",text="正文",size=10,
                                  baseline=y+8,bbox=[40,y,70,y+10]))
        doc = dict(pages=[dict(width=420,height=300)], paragraphs=paragraphs, preserved=[])
        regions = balance_columns(doc, items)
        self.assertEqual(len(regions), 1)
        self.assertEqual(regions[0]["paragraphs"], ["a","h","b"])
        self.assertGreaterEqual(regions[0]["heading_spacing"][0]["before_em"], 1.05)
        steps = regions[0]["baseline_steps_em"]
        self.assertTrue(all(1.50-.001 <= v <= 1.80+.001 for v in steps), steps)
        h = [i for i in items if i["paragraph"]=="h"]
        b = [i for i in items if i["paragraph"]=="b"]
        self.assertGreaterEqual(b[0]["bbox"][1]-h[-1]["bbox"][3], 6.5)

    def test_same_page_flow_is_composed_before_line_breaking(self):
        with tempfile.TemporaryDirectory() as folder:
            source, job = Path(folder)/"source.pdf", Path(folder)/"job"
            make_fixture(source)
            doc = prepare(source,job)
            for p in doc["paragraphs"]:
                p["translation"] = p["source"]
            a,b = [copy.deepcopy(p) for p in doc["paragraphs"] if p["source"].startswith(("This paper","A short"))]
            a["translation"], b["translation"] = "这是一段连续中文的前半句，", "后半句应当紧接在同一行，而不是另起一块。"
            b.update(flow_id=a["flow_id"],continuation=True,style_id=a["style_id"])
            doc["paragraphs"]=[a,b]
            frames=Typesetter(doc).flow_frames()
            self.assertEqual(len(frames),1)
            self.assertEqual(frames[0]["members"],[a["id"],b["id"]])
            result=Typesetter(doc).place(frames[0])
            visible="".join(i["text"] for i in result["placements"] if i["kind"]=="text").replace(" ","")
            self.assertEqual(visible,(a["translation"]+b["translation"]).replace(" ",""))
            self.assertEqual(len(Typesetter(doc,layout_mode="source").flow_frames()),2)
            # A fixed display equation prevents semantic material crossing it.
            doc["preserved"].append(dict(page=0,bbox=[40,130,360,135],reason="formula-or-numeric"))
            self.assertEqual(len(Typesetter(doc).flow_frames()),2)

    def test_common_block_splits_are_normalized_without_translation_edits(self):
        styles={"title":dict(size=17),"large":dict(size=17),"list":dict(size=10),"body":dict(size=10)}
        def p(pid,role,style,text,x,y,right):
            return dict(id=pid,page=0,role=role,style_id=style,source=text,flow_id=pid,
                        continuation=False,bbox=[x,y,right,y+10],erase=[[x,y,right,y+10]])
        doc=dict(pages=[dict(width=600,height=800)],styles=styles,preserved=[],paragraphs=[
            p("t1","title","title","A Long Academic Title",180,60,420),
            p("t2","heading","large","continued on the next line",200,75,400),
            p("l1","list","list","• A bullet split by the PDF",100,200,450),
            p("l2","body","body","producer into another text block.",110,213,450)])
        normalize_semantics(doc,10)
        self.assertEqual(doc["paragraphs"][1]["role"],"title")
        self.assertEqual(doc["paragraphs"][1]["style_id"],"title")
        self.assertEqual(doc["paragraphs"][3]["role"],"list")
        self.assertEqual(doc["paragraphs"][3]["flow_id"],"l1")

    def test_detail_review_is_bounded_but_unsafe_parsing_is_mandatory(self):
        doc=dict(pages=[{} for _ in range(30)],paragraphs=[],preserved=[],assets={},diagnostics=[])
        for page in range(30):
            doc["assets"][str(page)]=dict(page=page)
        doc["diagnostics"].append(dict(code="parse/formula-preserved",subject=dict(page=28)))
        selected=review_plan(doc,{})
        self.assertLessEqual(len(selected),6)
        self.assertIn(28,[r["page"] for r in selected])
        self.assertIn(1,[r["page"] for r in selected])

    def test_successful_formula_checks_do_not_flood_cli(self):
        receipt=dict(ok=True, formulas=[dict(asset=f"a{i}",difference=0) for i in range(200)],diagnostics=[])
        result=compact_result(receipt)
        self.assertEqual(result["formula_checks"],dict(count=200,failed=0))
        self.assertNotIn("formulas",result)
        self.assertLess(len(json.dumps(result)),500)

    def test_cff_metrics_resolve_subset_glyph_ids(self):
        from io import BytesIO
        from fontTools.fontBuilder import FontBuilder
        from fontTools.pens.t2CharStringPen import T2CharStringPen
        from layoutpdf.fonts import cff_metrics
        fb=FontBuilder(1000,isTTF=False)
        fb.setupGlyphOrder([".notdef","glyph00001"])
        fb.setupCharacterMap({65:"glyph00001"})
        empty=T2CharStringPen(600,None)
        pen=T2CharStringPen(600,None)
        pen.moveTo((30,0));pen.lineTo((550,0));pen.lineTo((300,700));pen.closePath()
        fb.setupCFF("TestSubset",{}, {".notdef":empty.getCharString(),"glyph00001":pen.getCharString()}, {})
        out=BytesIO();fb.font["CFF "].cff.compile(out,fb.font)
        bounds,advance=cff_metrics(out.getvalue())[("gid",1)]
        self.assertAlmostEqual(bounds.height,.7)
        self.assertAlmostEqual(advance,.6)

    def test_invalid_layout_stops_before_writing_pdfs(self):
        with tempfile.TemporaryDirectory() as folder:
            source,job=Path(folder)/"source.pdf",Path(folder)/"job"
            make_fixture(source);doc=prepare(source,job)
            batch=translate_document(doc)
            pid=next(p["id"] for p in doc["paragraphs"] if p["source"]=="A short paragraph.")
            batch[pid]="不可容纳的完整文字"*2000
            path=Path(folder)/"batch.json";write(path,batch);merge(job,path)
            result=build(job)
            self.assertFalse(result["ok"])
            self.assertEqual(result["stopped_at"],"layout")
            self.assertFalse((Path(result["build"])/"translated.pdf").exists())
            with self.assertRaises(Failure):review(job)

    def test_focused_evidence_remains_hash_bound_and_detects_unchanged_pages(self):
        with tempfile.TemporaryDirectory() as folder:
            source,job=Path(folder)/"source.pdf",Path(folder)/"job"
            make_fixture(source);doc=prepare(source,job)
            path=Path(folder)/"batch.json";write(path,translate_document(doc));merge(job,path)
            first=build(job);self.assertTrue(first["ok"],first["diagnostics"])
            report=review(job)
            evidence=read(Path(report["directory"])/"evidence.json")
            self.assertTrue(all(f"mono-72-p{page:04}.png" in evidence["images"] for page in (1,2)))
            self.assertLess(report["rendered_images"],12)
            self.assertFalse(any("mono-144" in name for name in evidence["images"]))
            # This fixture has objective geometry tests; the following is a
            # review-protocol test, not a human review claim for user artifacts.
            review(job,status="passed",notes="Synthetic review protocol fixture",evidence_hash=report["evidence_sha256"])
            build(job);second=review(job)
            self.assertEqual(second["changed_pages"],[])
            image=Path(second["directory"])/"mono-72-p0001.png"
            image.write_bytes(image.read_bytes()+b"tampered")
            with self.assertRaises(Failure):
                review(job,status="passed",notes="Protocol check",evidence_hash=second["evidence_sha256"])


if __name__=="__main__":
    unittest.main()
