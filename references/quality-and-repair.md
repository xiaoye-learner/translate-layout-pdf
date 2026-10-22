# Quality and repair

Objective checks cover schema, source/font/asset identity, tokens, bounds, overlap, glyph coverage, formula raster equivalence, preserved source ink, links, hashes and bilingual pairing. Keep them global. Visual review assesses reading rhythm and translation; it is not the primary layout solver.

## Typography policy

Allocate space in obstacle-free column regions, including captions and short headings. A heading inherits the neighboring text column; its ink width does not define another column. Same-page continuations share a frame before wrapping. Pages, columns and fixed display equations remain boundaries.

| Property | Preferred | Upper bound with spare room |
| --- | ---: | ---: |
| Body/list baseline distance | 1.50em | 1.80em |
| Caption baseline distance | 1.30em | 1.50em |
| Prose to section heading | 1.35em | 1.80em |
| Prose to subsection heading | 1.05em | 1.50em |
| Heading to following prose | 0.65em | 0.90em |
| Consecutive heading levels | 0.55em | 0.55em |
| Ordinary paragraph gap | 0.45em | 0.60em |

Measure baseline distance from placements, not a font's nominal line-height multiplier. Preserve larger formula clearances. Reserve heading separation before expanding body leading. Dense regions reduce added whitespace toward measured safe minima, never formula ink clearance. Regions that cannot fit bounded balancing keep the measured candidate and report `status: constrained` for detail review.

Do not expand into intentionally empty source tails. Unused height after reasonable caps is preferable to huge paragraph gaps. Fixed figures, tables, equations and page bounds remain fixed. Source mode is for explicit vertical alignment, not a repair escape hatch.

`layout.json/column_regions` records heading `before_em`, `paragraph_gaps`, actual `baseline_steps_em`, distributed height, remaining tail and constrained regions. Diagnose holes from these metrics and the obstacle map before changing wording. `composed_flows` records same-page frames joined without changing the source contract.

## Review once, then by changes

Inspect all mono 72-DPI contact sheets and the reported bilingual 144-DPI detail pages. The plan selects unsafe parsing, constrained regions and representative typography/math/table pages. Add detail when a sheet exposes a possible defect. All formulas and preserved regions still receive objective raster checks. Use `review --full` when exhaustive inspection is requested or representative pages reveal a systemic defect.

Do not inspect full images and four sets of downscaled sheets showing the same pages. After repair use `changed_pages` against passed image hashes. Unchanged pixels need no repeated aesthetic judgment, but review must still bind to current evidence. Revisit neighbors when flow changes might affect continuity.

Check coherent paragraphs, inline formula baselines, heading hierarchy and attachment to following text, legible captions, and whitespace spent on useful leading rather than mid-sentence holes. Inspect crop-mask warnings at detail scale and disclose retained prose. Record concrete observations; do not claim exhaustive high-resolution inspection from a sample.

## Repair boundary

Selection faults (`selection/*`) need content-stream inspection, not typography changes. `show_pdf_page(clip=...)` imports text from the whole source page; a clipped formula can carry thousands of invisible glyphs. Physically trim with `Page.clip_to_rect()` before saving a formula, after absorbed-fragment reconstruction, and in-memory when loading legacy formula files. Validate cleanup against the original rendered strokes. Do not rasterize formulas or cover unwanted text with white rectangles.

Each mono page must have exactly the baseline retained glyphs plus written prose and clean formula glyphs, without off-page centers. Bilingual half counts must match the respective source and translated page. Inspect `receipt.json/selection_checks`. A normal bounded text extraction can look correct while hidden Form text remains, so use `get_texttrace()` for this check and, when available, an independent PDF.js text-content extraction. Search/copy tests should check a complete paragraph with a formula and both halves separately. Superscript/subscript linear copy order remains reader-dependent; these checks do not make the PDF fully tagged or PDF/UA compliant.

Already delivered PDFs do not update when the skill changes. Rebuild from the original job using the fixed engine; do not reuse the old bilingual artifact. Existing translations and sealed asset files can remain unchanged.

`correct` takes JSON entries with `id`, `field`, `value`, `reason`. Supported fields: paragraph `role`, `continuation`, `continuation_of` (predecessor ID), and formula `placement` (asset ID). It re-seals the contract. Do not edit geometry, hash fields or thresholds by hand.

| Failure | Correct the cause |
| --- | --- |
| `parse/*`, wrong flow/role | Correct semantics or retain an unsafe region; reuse unaffected translations. |
| `translation/*` | Repair only affected strings/tokens. |
| `layout/*overflow` | Check paragraph/column boundaries before meaning-preserving compaction. |
| `layout/*overlap` | Correct structural boundaries or region composition. |
| `formula/*`, `asset/*` | Re-prepare from source or report limits; never recreate math as plain text. |
| `artifact/*`, `review/*` | Rebuild/regenerate current evidence. |
| Tight leading/headings, internal holes | Check inherited lanes, composed flows and spacing metrics. |

After two unsuccessful fixes with the same cause, retain the job and report affected pages/IDs. Do not multiply visual checks or silently accept a degraded layout to obtain a pass.
