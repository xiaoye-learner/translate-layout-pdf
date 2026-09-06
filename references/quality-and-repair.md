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

Record concrete review notes, for example: `2 pages inspected at 72/144 DPI; both inline assets share their prose baselines; three H1 headings use the same bold face; no overlap or clipping.` Generic notes such as `looks good` do not provide useful evidence.

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
