"""Selection regressions must inspect hidden operators, not just rendered PNGs."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

import pymupdf as fitz

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from layoutpdf.contracts import digest,read,seal,write
from layoutpdf.extract import prepare
from layoutpdf.pipeline import build,merge,compose_dual
from layoutpdf.selection import audit_selection,glyph_count,materialize_clip
from make_fixture import make_fixture
from test_pipeline import translate_document,canonical_text


class SelectionTests(unittest.TestCase):
    def test_nested_source_cleanup_precedes_all_bilingual_grafting(self):
        with tempfile.TemporaryDirectory() as folder,fitz.open() as original,fitz.open() as nested,fitz.open() as mono:
            for i in range(2):
                p=original.new_page(width=400,height=400)
                p.insert_text((20,40),"KEEP_LEFT")
                p.insert_text((270,260),"GHOST_RIGHT")
            for i in range(2):
                p=nested.new_page(width=200,height=400)
                p.show_pdf_page(p.rect,original,i,clip=fitz.Rect(0,0,200,400))
                mono.new_page(width=200,height=400).insert_text((20,40),"TRANSLATED")
            path=Path(folder)/"dual.pdf"
            compose_dual(nested,mono,path)
            with fitz.open(path) as dual:
                self.assertEqual(len(dual),2)
                for page in dual:
                    self.assertEqual(glyph_count(page),len("KEEP_LEFTTRANSLATED"))

    def test_rectangular_clip_is_not_a_selection_boundary(self):
        with fitz.open() as source, fitz.open() as asset:
            page=source.new_page(width=400,height=400)
            page.insert_text((30,40),"INVISIBLE_UNRELATED_PROSE")
            page.insert_text((200,220),"x",fontname="tiit",fontsize=10)
            target=asset.new_page(width=12,height=14)
            target.show_pdf_page(target.rect,source,0,clip=fitz.Rect(198,210,210,224))
            pixels=target.get_pixmap(matrix=fitz.Matrix(3,3)).samples
            self.assertGreater(glyph_count(target),20)
            _,errors=audit_selection(target,1,"fixture")
            self.assertIn("selection/glyph-count",[e["code"] for e in errors])
            materialize_clip(target)
            self.assertEqual(glyph_count(target),1)
            self.assertEqual(target.get_pixmap(matrix=fitz.Matrix(3,3)).samples,pixels)

    def test_prepared_assets_only_contain_formula_text(self):
        with tempfile.TemporaryDirectory() as folder:
            source,job=Path(folder)/"source.pdf",Path(folder)/"job"
            make_fixture(source);doc=prepare(source,job)
            for asset in doc["assets"].values():
                with fitz.open(job/asset["file"]) as pdf:
                    self.assertLess(glyph_count(pdf[0]),12)
                    all_text="".join(chr(c[0]) for s in pdf[0].get_texttrace() for c in s["chars"])
                    self.assertNotIn("Introduction",all_text)
                    self.assertNotIn("response",all_text)

    def test_legacy_assets_rebuild_without_changing_sealed_files(self):
        with tempfile.TemporaryDirectory() as folder:
            source,job=Path(folder)/"source.pdf",Path(folder)/"job"
            make_fixture(source);doc=prepare(source,job)
            # Model a job from the old engine: whole source text behind each
            # formula crop. This is test data, not a repair of sealed user files.
            for asset in doc["assets"].values():
                with fitz.open(source) as pdf,fitz.open() as legacy:
                    target=legacy.new_page(width=asset["width"],height=asset["height"])
                    target.show_pdf_page(target.rect,pdf,asset["page"],clip=fitz.Rect(asset["bbox"]))
                    legacy.save(job/asset["file"],garbage=4,deflate=True)
                asset["sha256"]=digest(job/asset["file"])
            seal(doc);write(job/"document.json",doc)
            path=Path(folder)/"batch.json";write(path,translate_document(doc));merge(job,path)
            hashes={a["file"]:digest(job/a["file"]) for a in doc["assets"].values()}
            result=build(job)
            self.assertTrue(result["ok"],result["diagnostics"])
            self.assertGreater(result["clipped_asset_glyphs_removed"],100)
            for a in doc["assets"].values():self.assertEqual(digest(job/a["file"]),hashes[a["file"]])
            self.assertTrue(all(c["glyphs"]==c["expected_glyphs"] for c in result["selection_checks"]))
            with fitz.open(Path(result["build"])/"translated.pdf") as mono,fitz.open(Path(result["build"])/"bilingual.pdf") as dual:
                # Search/copy coordinates of a translated paragraph match its ink.
                hits=mono[0].search_for("短段落")
                self.assertEqual(len(hits),1)
                copied=canonical_text(mono[0].get_textbox(hits[0]+(-2,-2,2,2)))
                self.assertIn("短段落",copied)
                self.assertEqual(glyph_count(dual[0]),glyph_count(mono[0])+glyph_count(fitz.open(source)[0]))
                chinese=canonical_text(mono[0].get_text())
                self.assertLess(chinese.index("1.引言"),chinese.index("本文研究"))
                self.assertLess(chinese.index("本文研究"),chinese.index("1.1.分析"))
                self.assertEqual(mono[0].get_text().count("Introduction"),0)


if __name__=="__main__":unittest.main()
