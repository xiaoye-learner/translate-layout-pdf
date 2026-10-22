---
name: translate-layout-pdf
description: Translate text-based academic and technical PDFs with Codex while preserving page size, columns, vector formulas, images, tables and links. Use for readable layout-preserving or bilingual PDF translation; scanned PDFs require OCR first.
license: AGPL-3.0-only
---

# Translate Layout PDF

Use the active model for translation and the bundled engine for extraction, layout, verification and delivery. Resolve scripts against this skill directory; put jobs and runtime dependencies in the task workspace. Never edit the source PDF.

## Readability and efficiency

Use default `balanced` layout. Preserve pages, columns and fixed objects while allowing prose and headings to move together **within** a clear column region. Preserving layout does not require preserving every paragraph's original y coordinate. Use `--layout-mode source` only when the user explicitly prioritizes vertical correspondence; do not fall back to it to obtain a passing build.

The engine composes same-page continuations before line breaking, infers the column of short headings from neighboring body text, and allocates spare height to heading gaps and measured baseline spacing. CJK body baselines prefer 1.50–1.80em; headings have a larger break before than after. These are bounded preferences, not permission to overlap fixed objects or stretch sparse pages. See [quality-and-repair.md](references/quality-and-repair.md).

Use compact CLI summaries. Do not repeatedly print full document/layout JSON, successful formula check lists or complete translated batches into context. Full records remain on disk; use `--verbose` only for diagnosis.

## Run

1. `python scripts/layout_pdf.py doctor`

   Requires Python 3.10+, `pymupdf>=1.26.5,<1.27`, Pillow, jsonschema and fontTools. Install missing packages in a workspace runtime, not global Python.

2. `python scripts/layout_pdf.py prepare INPUT.pdf JOB --target-language zh-CN`

   Use the requested target language, otherwise the language of the request. Preparation refuses an existing job. Common multi-line titles and bullet continuations are normalized before allocating containers.

3. `python scripts/layout_pdf.py inspect JOB`

   Read the page/role/preservation map and grouped diagnostics. Inspect specific paragraphs with `inspect JOB --pages 3,4`; read `JOB/batches.json` in manageable chunks. Investigate concrete role, order or formula-boundary warnings before translating. Use `correct` for demonstrated semantic mistakes, not edits to sealed geometry/hashes.

   Source reconstruction (`build JOB --preflight`) is a diagnostic tool for uncertain extraction or an unfamiliar producer, not an obligatory second full-document visual review. Formula/vector/source-preservation checks still run on every translated build. Inspect warned masks and representative complex formulas at detail scale; do not manually recheck every successfully verified asset on every build.

4. Read [translation-contract.md](references/translation-contract.md). Translate each batch once into a UTF-8 ID-to-string JSON object, then `python scripts/layout_pdf.py merge JOB BATCH.json`. Reuse accepted translations when repairing layout; do not retranslate an entire paper for a local problem.

5. `python scripts/layout_pdf.py build JOB`

   Build validates translations, compiles layout and performs PDF/raster checks. Invalid geometry stops before expensive artifact rendering. Read the compact failure summary and inspect only affected IDs/pages. A nonzero exit or `ok: false` is a failed candidate even when older PDF files exist. Do not weaken thresholds or shorten correct prose to conceal a parsing error.

6. `python scripts/layout_pdf.py review JOB`

   Inspect all **mono 72-DPI contact sheets** for order, balance and gross defects, then reported **bilingual 144-DPI detail pages** for typography, mathematics, headings and alignment. The plan includes unsafe parsing and constrained regions, plus representative complex structures. Open additional pages if a sheet, warning or linguistic review raises concern. `review JOB --full` is available for an exhaustive audit.

   After a repair, `changed_pages` identifies pages differing from a previously passed pixel baseline. Reinspect changed pages and affected neighbors; avoid reopening unchanged pages or redundant sheets. Objective checks still run globally, and a new build always requires a new hash-bound review. Sampling cannot prove every translation correct; disclose retained source text and substantive limits.

   `python scripts/layout_pdf.py review JOB --status passed --notes "SPECIFIC OBSERVATIONS" --evidence-hash HASH`

7. `python scripts/layout_pdf.py deliver JOB OUTPUT_DIR`

   Atomic delivery requires current engine/document/layout/artifact hashes and a passed review. Confirm both PDFs open with expected pages. Retain failed jobs for recovery.

## Content boundaries

- Preserve each `[[Mdddd]]` / `[[Pdddd]]` token byte-for-byte, in order, exactly once. One semantic paragraph per string, without manual line breaks.
- Mathematics remains source vector art, including scripts, accents, fractions and baselines. Preserve detected table cells and complex illustration labels. Disclose retained prose and provide a separate translation when isolation is unsafe.
- Selection is an independent artifact requirement: formula crops must physically remove off-clip text operators, not merely hide the source page behind a clip/CropBox. Legacy assets are cleaned in memory on rebuild. Keep global glyph-budget, off-page and bilingual-half checks enabled; normal `get_text()` and PNG review alone can miss hidden text. Generated paragraphs are painted in semantic reading order. See the selection checks in [quality-and-repair.md](references/quality-and-repair.md).
- New CJK body paragraphs receive a two-em indent; continuations, headings, captions, lists and footnotes do not. Same-style headings use one size and a real bold face.
- Classify parsing, translation, geometry, integrity and visual rhythm separately. Correct the cause, then rebuild. Stop after two unsuccessful fixes with the same failure fingerprint and report the concrete limitation.

For failures read [quality-and-repair.md](references/quality-and-repair.md); for engine maintenance read [architecture.md](references/architecture.md). Scanned pages or unsupported encodings may need OCR or a different backend.
