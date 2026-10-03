# Quality and repair

The pipeline separates objective checks from visual judgment. A successful build proves schema validity, source/font/asset identity, geometry bounds, non-overlap with preserved regions, complete glyph coverage, formula raster equivalence, preserved-region equivalence, output hashes, and bilingual page pairing. It does not prove translation quality or visual balance.

## Review

At 72 DPI, check normal reading size: text must be legible, columns must remain separate, and no paragraph may become an isolated fragment. At 144 DPI, compare formulas, headings, dense pages, tables, figures, links, headers, footers, and page numbers with the source.

Check these reported problem classes directly:

- subscripts, superscripts, fractions, and formula strokes retain their two-dimensional source form;
- inline mathematics shares the prose line rather than creating an empty line;
- each real Chinese/Japanese body paragraph starts at two em, while continuations and headings do not;
- headings of the same style have the same size and a visibly bold face;
- text contraction does not leave avoidable paragraph-sized holes, and expansion does not clip or overlap.

For abrupt whitespace, inspect `layout.json/column_regions` and preserved-region diagnostics before changing prose. `distributed_height` reports bounded spacing added to a clear column region; `remaining_tail` is space that would require excessive spacing or a different page-flow policy to fill. A retained English paragraph with `parse/formula-preserved` is a parsing problem. Inspect `parse/formula-vector-mask` crops at 144 DPI to confirm every source formula stroke is intact. Unchanged flows are listed in `retained_paragraphs` and must retain source ink and links. Formula boundaries must not carry citations or sentence endings to the wrong side. Use `build --layout-mode source` when source-oriented vertical correspondence takes priority over balanced reading.

Record concrete review notes, for example: `2 pages inspected at 72/144 DPI; both inline assets share their prose baselines; three H1 headings use the same bold face; no overlap or clipping.` Generic notes such as `looks good` do not provide useful evidence.

## Heading spacing

In balanced CJK layout, headings following prose use the following space before their first line, measured in the heading's font size:

| Boundary | Preferred base | Maximum with spare height |
| --- | ---: | ---: |
| Prose to section heading | 1.00em | 1.50em |
| Prose to subsection heading | 0.75em | 1.10em |
| Consecutive section/subsection headings | 0.55em | 0.55em |

Heading expansion takes priority over extra body leading. A heading at the start of a page does not receive a new top gap. At a region boundary after a fixed object, existing source spacing counts toward the preferred gap; already larger source gaps are not expanded. In a dense region, the preferred extra heading gap may fall back toward 0.55em to retain fit before any additional spacing is distributed. Fixed objects and page bounds remain unchanged.

Inspect `column_regions/heading_spacing` for the measured `before_gap` and `before_em`. Confirm visually that headings have a clear break from preceding prose, remain connected to their following text, and that consecutive heading levels remain a group.

## Repair boundary

Use `correct` only with a JSON list whose entries contain `id`, `field`, `value`, and `reason`. Supported fields are paragraph `role`, paragraph `continuation`, explicit `continuation_of` using a predecessor paragraph ID, and formula `placement` using an asset ID. A correction re-seals the document and re-runs the full schema.

Classify a failure before editing:

| Stage/code family | Change |
|---|---|
| `parse/*`, wrong role or flow | Correct classification/continuation, or retain the block when isolation is unsafe. |
| `translation/*` | Repair only the affected translation and immutable tokens. |
| `layout/overflow` | First verify paragraph boundaries and flow. Compact the wording only when structure is correct. |
| `layout/*overlap` | Correct structure; do not move sealed coordinates by hand. |
| `formula/*`, `asset/*` | Re-prepare from the original or stop; never recreate mathematics as plain text. |
| `artifact/*`, `review/*` | Rebuild or regenerate evidence from the current document. |

The job history stores error fingerprints. After two attempted fixes fail to improve the same objective errors, stop automatic repair, retain the job, and report the affected page/paragraph/formula plus the evidence. Visual corrections also stop after two unsuccessful rebuilds.
