"""Selectable text is a separate contract from correctly rendered pixels."""
from collections import Counter
import pymupdf as fitz
from PIL import Image,ImageChops

from .contracts import issue


def glyph_count(page):
    # Unlike get_text(), trace traverses text hidden by nested Form clip paths.
    return sum(len(span["chars"]) for span in page.get_texttrace())


def materialize_clip(page, verify=True):
    """Delete off-clip text operators; CropBox / show_pdf_page(clip=) only hide it.

    Keeps source font glyphs, strokes and vector paths, including nested masks.
    Also used in-memory for legacy assets; never rewrites sealed input files.
    """
    before = glyph_count(page)
    pixels = page.get_pixmap(matrix=fitz.Matrix(3,3),colorspace=fitz.csGRAY,alpha=False,annots=False) if verify else None
    page.clip_to_rect(page.rect)
    difference=0
    if pixels:
        after=page.get_pixmap(matrix=fitz.Matrix(3,3),colorspace=fitz.csGRAY,alpha=False,annots=False)
        a=Image.frombytes("L",(pixels.width,pixels.height),pixels.samples)
        b=Image.frombytes("L",(after.width,after.height),after.samples)
        histogram=ImageChops.difference(a,b).histogram()
        difference=sum(histogram[65:])/max(1,a.width*a.height)
    return dict(before=before, after=glyph_count(page),raster_difference=difference)


def audit_selection(page, expected_glyphs, subject):
    actual = glyph_count(page)
    diagnostics = []
    if actual != expected_glyphs:
        diagnostics.append(issue("selection/glyph-count", subject,
            dict(expected=expected_glyphs, actual=actual),
            ["physically trim formula assets before insertion; inspect hidden text operators"],stage="artifact"))
    bounds = page.rect + (-1,-1,1,1)
    outside = 0
    for span in page.get_texttrace():
        for char in span["chars"]:
            box = fitz.Rect(char[3])
            if not bounds.contains((box.tl+box.br)/2):
                outside += 1
    if outside:
        diagnostics.append(issue("selection/off-page", subject,dict(glyphs=outside),
            ["inspect nested clipping and form transforms"],stage="artifact"))
    return dict(glyphs=actual,expected_glyphs=expected_glyphs,off_page=outside),diagnostics


def audit_dual_selection(page, left, right):
    """No source glyph can leak into the translated half or vice versa."""
    expected_left,expected_right=glyph_count(left),glyph_count(right)
    counts=Counter()
    for span in page.get_texttrace():
        for char in span["chars"]:
            r=fitz.Rect(char[3])
            counts["left" if (r.x0+r.x1)/2 < left.rect.width else "right"] += 1
    errors=[]
    if counts["left"] != expected_left or counts["right"] != expected_right:
        errors.append(issue("selection/dual-half",dict(page=page.number+1),
            dict(left=counts["left"],expected_left=expected_left,right=counts["right"],expected_right=expected_right),
            ["remove clipped source text before bilingual composition"],stage="artifact"))
    return dict(page=page.number+1,left_glyphs=counts["left"],right_glyphs=counts["right"]),errors
