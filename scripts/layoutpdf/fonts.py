"""Source ink bounds, including embedded Type 1 fonts with font-wide MuPDF bounds."""
from pathlib import Path
import tempfile

import pymupdf as fitz
from fontTools.agl import toUnicode
from fontTools.pens.boundsPen import BoundsPen
from fontTools.t1Lib import T1Font


def type1_metrics(buffer):
    # PDF font streams may omit the standard eexec trailer present in PFA files.
    if b"cleartomark" not in buffer[-1024:]:
        buffer += b"\n" + b"0" * 512 + b"\ncleartomark\n"
    with tempfile.TemporaryDirectory(prefix="layout-font-") as folder:
        path = Path(folder) / "font.pfa"
        path.write_bytes(buffer)
        font = T1Font(str(path))
        glyphs = font.getGlyphSet()
        matrix = font["FontMatrix"]
        if matrix[1] or matrix[2] or matrix[4] or matrix[5]:
            return {}
        metrics = {}
        for name, glyph in glyphs.items():
            char = toUnicode(name)
            if len(char) != 1:
                continue
            pen = BoundsPen(glyphs)
            glyph.draw(pen)
            if pen.bounds and glyph.width:
                x0, y0, x1, y1 = pen.bounds
                metrics[char] = (fitz.Rect(x0 * matrix[0], y0 * matrix[3],
                                           x1 * matrix[0], y1 * matrix[3]), glyph.width * matrix[0])
        return metrics


def annotate_ink(document, page, raw):
    font_map = {}
    for info in page.get_fonts(full=True):
        try:
            buffer = document.extract_font(info[0])[3]
            font = fitz.Font(fontbuffer=buffer) if buffer else fitz.Font(info[3])
            metrics = type1_metrics(buffer) if buffer and info[1] == "pfa" else {}
            font_map[info[3].split("+")[-1]] = (font, metrics)
        except Exception:
            # Unknown source encodings keep conservative PDF bounds; crop validation stays active.
            continue
    for block in raw["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                entry = font_map.get(span["font"])
                if entry is None:
                    continue
                font, metrics = entry
                for char in span["chars"]:
                    c = char["c"]
                    if not c.strip():
                        continue
                    if c in metrics:
                        glyph, advance = metrics[c]
                    elif font.has_glyph(ord(c)):
                        glyph, advance = font.glyph_bbox(ord(c)), font.glyph_advance(ord(c))
                        if glyph == font.bbox:
                            continue
                    else:
                        continue
                    size = span["size"]
                    sx = (char["bbox"][2] - char["bbox"][0]) / (advance * size) if advance > .001 else 1
                    x, y = char["origin"]
                    ink = [x + glyph.x0 * size * sx, y - glyph.y1 * size,
                           x + glyph.x1 * size * sx, y - glyph.y0 * size]
                    if ink[2] > ink[0] and ink[3] > ink[1]:
                        char["ink_bbox"] = ink
