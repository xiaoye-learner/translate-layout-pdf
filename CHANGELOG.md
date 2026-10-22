# Changelog

All notable changes to this project will be documented here.

## Unreleased

- Canonicalized generated-font ToUnicode mappings with NFC and valid UTF-16BE destinations, restoring literal CJK search across Noto font aliases without changing glyphs or weakening search assertions.
- Added portable synthetic-font regression tests for compatibility aliases, supplementary characters and unchanged rendering; the suite now contains 54 tests.
- Physically removed off-clip text from formula assets and cleaned legacy assets in memory, preventing invisible source-page text from polluting selection and copying.
- Added glyph-budget, off-page and bilingual-half checks, with before/after raster checks for clip cleanup and semantic-order text insertion.
- Inherited body column widths for short headings, composed same-page continuations before wrapping, and allocated bounded CJK baseline and heading spacing.
- Normalized common multi-line titles and bullet continuations, added cached CFF subset-font ink metrics, and improved formula-line and table boundary detection.
- Added compact CLI diagnostics, page-specific inspection, fail-fast layout checks, focused visual evidence and pixel-based changed-page reporting.
- Expanded the regression suite to 52 tests and excluded local credentials, task data, coverage and packaged archives from Git.

- Added level-specific space before headings with priority over body-leading expansion, compact consecutive heading groups, dense-region fallback, and measured heading-gap records.

- Kept Latin symbol labels and consecutive inline formula assets together when wrapping, preventing isolated NBT/AUC script fragments.
- Kept explicitly unchanged paragraph flows in the source PDF with original typography and links, verified against source ink.
- Split continuation layout at fixed display equations to keep citations and sentence endings on the correct side.
- Added obstacle-aware column-region balancing with bounded line and paragraph spacing, plus an explicit `source` layout mode.
- Recorded distributed height and residual whitespace per column region in the layout plan.
- Isolated formulas with vector ink masks when a neighboring line enters only an empty crop corner; actual ink collisions still preserve the source region.
- Selected the target-language face inside TTC/OTC collections, preventing Ubuntu Noto CJK from silently using Japanese glyph variants for Simplified Chinese output.
- Made CJK leading verification account for a font's minimum safe glyph height across platforms.
- Updated GitHub Actions to the current Node 24-based checkout and Python setup actions.
- Split mixed formula/prose lines so natural-language text remains translatable while source mathematics stays vector-preserved and inline.
- Added containment-based absorption of overlapping numeric and script fragments into their formula assets.
- Merged overlapping same-flow semantic fragments across formula boundaries, with safeguards that keep standalone display equations separate.
- Replaced fixed-area formula collision checks with relative overlap fractions to ignore insignificant glyph-edge contact.
- Separated glyph height from baseline advance so a one-line source box does not force global text shrinkage.
- Added in-paragraph CJK orphan rebalancing instead of repeatedly shrinking an entire style.
- Added bounded body expansion with audited local fallback for constrained short and formula-only frames.
- Added a 6% CJK body leading increase and recorded it in the layout plan.
- Improved conservative handling of ambiguous formulas, borderless tables, figure regions, run-in headings, and source preflight.
- Expanded the automated regression suite to 40 tests.

## 5.0.0 - 2026-09-05

- Replaced the monolithic workflow with versioned document contracts and modular extraction, font, layout, and pipeline components.
- Added source-derived vector assets for inline formulas with signed baseline metrics.
- Added two-em CJK body indentation, continuation flows, consistent real-bold heading styles, bounded CJK expansion, and orphan-line rejection.
- Added schema, hash, geometry, coverage, formula, link, preserved-region, visual-review, and delivery gates.
- Added deterministic translated and bilingual PDF construction.
- Added 24 automated regression tests and independent forward evaluation.
- Declared `AGPL-3.0-only` licensing and documented runtime dependencies and design references.
