"""Search/copy must survive font aliases, without depending on the host fonts."""
from io import BytesIO
from pathlib import Path
import re
import sys
import unittest

import pymupdf as fitz
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from layoutpdf.fonts import normalize_generated_font_unicode, normalize_tounicode_cmap


class UnicodeTests(unittest.TestCase):
    def test_cmap_normalizes_canonical_aliases_and_utf16_destinations(self):
        data=b'''/CIDInit /ProcSet findresource begin
12 dict begin begincmap
1 begincodespacerange <0000> <FFFF> endcodespacerange
3 beginbfchar
<0001> <f918>
<0002> <20000>
<0003> <ff21>
endbfchar
2 beginbfrange
<0004> <0005> <0041>
<0006> <0007> [<f918> <d840dc00>]
endbfrange
endcmap end end'''
        result=normalize_tounicode_cmap(data).decode("ascii")
        entries={int(cid,16):bytes.fromhex(value).decode("utf-16-be")
                 for cid,value in re.findall(r"<([\da-f]+)> <([\da-f]+)>",result)
                 if cid!="0000"}
        self.assertEqual(entries,{1:"落",2:"𠀀",3:"Ａ",4:"A",5:"B",6:"落",7:"𠀀"})

    def test_alias_font_remains_visually_identical_and_searchable(self):
        # Synthetic font: 落 and 落 intentionally share one glyph, as in Noto.
        fb=FontBuilder(1000,isTTF=True)
        order=[".notdef","short","paragraph","fall","supplement"]
        fb.setupGlyphOrder(order)
        fb.setupCharacterMap({0x77ed:"short",0x6bb5:"paragraph",0x843d:"fall",
                              0xf918:"fall",0x20000:"supplement"})
        glyphs={}
        for name in order:
            pen=TTGlyphPen(None)
            pen.moveTo((50,0));pen.lineTo((550,0));pen.lineTo((550,700));pen.lineTo((50,700));pen.closePath()
            glyphs[name]=pen.glyph()
        fb.setupGlyf(glyphs)
        fb.setupHorizontalMetrics({name:(600,50) for name in order})
        fb.setupHorizontalHeader(ascent=800,descent=-200)
        fb.setupOS2(sTypoAscender=800,sTypoDescender=-200,usWinAscent=800,usWinDescent=200)
        fb.setupNameTable({"familyName":"AliasFixture","styleName":"Regular",
                           "psName":"AliasFixture-Regular"})
        fb.setupPost();fb.setupMaxp()
        font=BytesIO();fb.save(font)
        with fitz.open() as pdf:
            page=pdf.new_page(width=200,height=100)
            xref=page.insert_font(fontname="fixture",fontbuffer=font.getvalue())
            page.insert_text((20,40),"短段落𠀀",fontname="fixture",fontsize=12)
            pixels=page.get_pixmap().samples
            pdf.subset_fonts()
            normalize_generated_font_unicode(pdf,{xref})
            with fitz.open(stream=pdf.tobytes(),filetype="pdf") as reopened:
                self.assertEqual(reopened[0].get_text().strip(),"短段落𠀀")
                self.assertEqual(len(reopened[0].search_for("短段落")),1)
                self.assertEqual(reopened[0].get_pixmap().samples,pixels)


if __name__=="__main__":unittest.main()
