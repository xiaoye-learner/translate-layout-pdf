"""A small deterministic source PDF exercising actual glyph geometry."""
from pathlib import Path
import pymupdf as fitz


def make_fixture(path):
    doc = fitz.open()
    page = doc.new_page(width=420, height=560)
    def text(x, y, value, size=10, font="tiro"):
        page.insert_text((x, y), value, fontsize=size, fontname=font)
    text(48, 40, "A Study of Stable Layout", 18, "tibo")
    text(48, 78, "1. Introduction", 13, "tibo")
    text(48, 105, "This paper studies the behavior of a simple model under a fixed")
    text(48, 118, "constraint. The results preserve both meaning and visual structure.")
    text(48, 153, "A short paragraph.")
    text(48, 190, "The value")
    text(93, 190, "x", 10, "tiit")
    text(98, 193, "i", 6, "tiit")
    text(98, 184, "2", 6)
    text(107, 190, "controls the response of the model.")
    text(48, 229, "The ratio")
    text(93, 224, "1", 6)
    text(93, 233, "n", 6, "tiit")
    page.draw_line((91, 226), (99, 226), width=.5)
    text(105, 229, "remains inside this sentence and retains its fraction bar.")
    text(48, 274, "1.1. Analysis", 11, "tibo")
    text(48, 300, "We define the following relationship:")
    text(160, 332, "x", 11, "tiit")
    text(166, 326, "2", 7)
    text(175, 332, "= 1", 11)
    text(350, 332, "(1)", 10)
    text(48, 365, "where the variable denotes a normalized measurement.")
    text(48, 403, "2. Conclusion", 13, "tibo")
    text(48, 430, "The same heading style should remain consistent throughout.")
    text(48, 465, "Science")
    text(82, 459, "1", 6)
    text(87, 465, "continues here.")
    text(48, 500, "Visit https://example.com/paper")
    text(203, 535, "1", 9)
    page.insert_link({"kind": fitz.LINK_URI, "from": fitz.Rect(70, 486, 195, 503), "uri": "https://example.com/paper"})
    page = doc.new_page(width=420, height=560)
    text(36, 50, "3. Further Results", 13, "tibo")
    text(36, 430, "The left column contains a")
    text(36, 443, "paragraph that continues with")
    text(36, 456, "additional discussion and")
    text(230, 85, "preserves the same meaning.")
    text(230, 98, "This is the end of the paragraph.")
    text(36, 85, "A second short paragraph.")
    text(230, 150, "A separate right paragraph.")
    text(203, 535, "2", 9)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    doc.save(path, no_new_id=True)
    doc.close()


if __name__ == "__main__":
    import sys
    make_fixture(sys.argv[1])
