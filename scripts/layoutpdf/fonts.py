"""Source ink bounds, including embedded Type 1 fonts with font-wide MuPDF bounds."""
from functools import lru_cache
from io import BytesIO
from pathlib import Path
import re
import tempfile

import pymupdf as fitz
from fontTools.agl import toUnicode
from fontTools.pens.boundsPen import BoundsPen
from fontTools.t1Lib import T1Font
from fontTools.ttLib import TTCollection, TTFont
from fontTools.cffLib import CFFFontSet


COLLECTION_REGIONS = {
    "zh-cn": ("SC",),
    "zh-sg": ("SC",),
    "zh-hans": ("SC",),
    "zh-tw": ("TC",),
    "zh-hant": ("TC",),
    "zh-hk": ("HK", "TC"),
    "zh-mo": ("HK", "TC"),
    "ja": ("JP",),
    "ko": ("KR",),
}


def collection_face(path, target_language):
    """Return the target-language face in a TTC/OTC instead of its first face."""
    path = Path(path)
    if path.suffix.lower() not in {".ttc", ".otc"} or not target_language:
        return None
    language = target_language.lower().replace("_", "-")
    regions = next((value for key, value in COLLECTION_REGIONS.items()
                    if language == key or language.startswith(key + "-")), ())
    if not regions:
        return None
    collection = TTCollection(str(path), lazy=True)
    try:
        names = [(index, font["name"].getDebugName(6) or font["name"].getDebugName(1) or "")
                 for index, font in enumerate(collection.fonts)]
        for region in regions:
            match = next(((index, name) for index, name in names
                          if re.search(rf"CJK{region}(?:-|$)", name, re.I)), None)
            if match:
                return match
    finally:
        collection.close()
    return None


@lru_cache(maxsize=8)
def _collection_buffer(path, index, sha256):
    """Extract one collection face in memory; the source hash keys the cache."""
    collection = TTCollection(path, lazy=False)
    try:
        output = BytesIO()
        collection.fonts[index].save(output, reorderTables=False)
        return output.getvalue()
    finally:
        collection.close()


def font_buffer(metadata):
    if "collection_index" not in metadata:
        return None
    return _collection_buffer(metadata["path"], metadata["collection_index"], metadata["sha256"])


def load_document_font(metadata):
    buffer = font_buffer(metadata)
    return fitz.Font(fontbuffer=buffer) if buffer is not None else fitz.Font(fontfile=metadata["path"])


def register_document_font(page, fontname, metadata):
    buffer = font_buffer(metadata)
    if buffer is not None:
        return page.insert_font(fontname=fontname, fontbuffer=buffer)
    return page.insert_font(fontname=fontname, fontfile=metadata["path"])


@lru_cache(maxsize=128)
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


@lru_cache(maxsize=128)
def cff_metrics(buffer):
    cff = CFFFontSet()
    cff.decompile(BytesIO(buffer), TTFont())
    top = cff[cff.fontNames[0]]
    matrix = top.FontMatrix
    if matrix[1] or matrix[2] or matrix[4] or matrix[5]:
        return {}
    metrics = {}
    for gid, name in enumerate(top.charset):
        char = toUnicode(name)
        glyph = top.CharStrings[name]
        pen = BoundsPen(None)
        glyph.draw(pen)
        if pen.bounds and glyph.width:
            x0, y0, x1, y1 = pen.bounds
            metric = (fitz.Rect(x0 * matrix[0], y0 * matrix[3],
                                x1 * matrix[0], y1 * matrix[3]), glyph.width * matrix[0])
            metrics[("gid", gid)] = metric
            if len(char) == 1:
                metrics[char] = metric
    return metrics


def annotate_ink(document, page, raw):
    font_map = {}
    trace_gids = {(span["font"].split("+")[-1], round(c[2][0], 3), round(c[2][1], 3)): c[1]
                  for span in page.get_texttrace() for c in span["chars"]}
    for info in page.get_fonts(full=True):
        try:
            buffer = document.extract_font(info[0])[3]
            font = fitz.Font(fontbuffer=buffer) if buffer else fitz.Font(info[3])
            metrics = (type1_metrics(buffer) if buffer and info[1] == "pfa" else
                       cff_metrics(buffer) if buffer and info[1] == "cff" else {})
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
                    gid = trace_gids.get((span["font"], round(char["origin"][0], 3), round(char["origin"][1], 3)))
                    if ("gid", gid) in metrics:
                        glyph, advance = metrics[("gid", gid)]
                    elif c in metrics:
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
