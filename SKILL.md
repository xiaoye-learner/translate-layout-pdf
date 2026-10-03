---
name: translate-layout-pdf
description: Translate text-based academic and technical PDFs with Codex while preserving page size, columns, images, source formulas, tables, links, headers, and annotations as closely as possible. Use for layout-preserving or bilingual PDF translation and its visual review; scanned PDFs require OCR first.
license: AGPL-3.0-only
---

# Translate Layout PDF

Use the active Codex model for translation. Use `scripts/layout_pdf.py` only for deterministic extraction, contracts, typesetting, verification, and delivery. Resolve all paths relative to this skill directory, and keep each run in a new task-local job directory.

The v5 engine treats semantic text and page geometry separately. It stores inline mathematics as source-derived vector assets with baseline metrics, flows a paragraph through its source containers, and applies a two-em first-line indent plus a small, explicit leading increase to new Chinese/Japanese body paragraphs. Mixed formula/prose lines are decomposed so prose stays translatable, contained script or numeric fragments are absorbed into the formula asset, and same-flow prose split across an inline formula is rejoined into one semantic paragraph. Relative overlap checks ignore insignificant glyph-edge contact but keep genuinely ambiguous regions in the source language for review. The engine selects a bounded scale and real font face per style: body expansion is capped at 1.20×, title and heading expansion at 1.50×, and a small audited set of constrained body frames may fall back locally rather than shrinking the entire document. It rebalances a single CJK character on the final line within its paragraph. It preserves detected tables rather than translating their cells.

## Run

Use the default `balanced` layout for readable translations: paragraphs flow within source column regions bounded by fixed objects, and spare height is shared through bounded line/paragraph spacing. If the user prioritizes source vertical placement, pass `build --layout-mode source`. Do not stretch content to fill intentionally empty source areas or move content across fixed objects/pages just to hide whitespace.

Reserve space before section headings by level before expanding body leading. Keep consecutive heading groups compact and adapt added spacing to the region's available height; see [references/quality-and-repair.md](references/quality-and-repair.md) for the bounded typography policy.

Explicitly unchanged flows retain the original PDF text, typography, formulas, and links; they still receive source-ink checks. Text on opposite sides of a fixed display equation is laid out separately so proportional continuation splitting cannot move a citation or sentence ending across the equation. Source reconstruction preflight always re-typesets text rather than using unchanged-flow retention.

1. Run `python scripts/layout_pdf.py doctor`. The runtime needs Python 3.10+, `pymupdf>=1.26.5,<1.27`, Pillow, jsonschema, and fontTools. If `doctor` fails because a package is missing, install only these dependencies in the active workspace runtime.
2. Prepare the job:

   `python scripts/layout_pdf.py prepare INPUT.pdf JOB --target-language zh-CN`

   Use the language requested by the user; otherwise use the language of their request. Preparation refuses an existing job and never edits the source.
3. Inspect `JOB/document.json` and `JOB/batches.json`. Confirm the reading order, paragraph roles, `flow_id` links, formula placement, preserved regions, and warnings before translating. Run a source-language reconstruction when inline formulas or multi-column flows exist:

   `python scripts/layout_pdf.py build JOB --preflight`

   Inspect its rendered result using the same review process as a translation. Inspect every `parse/formula-vector-mask` region against the source strokes at 144 DPI: the mask may exclude a neighboring glyph only when its ink is disjoint from the formula. Correct a demonstrated role, continuation, or formula-placement error with `correct`; do not hand-edit geometry or hashes.
4. Read [references/translation-contract.md](references/translation-contract.md). Translate every batch entry with Codex and write a UTF-8 JSON object from paragraph ID to translated string. Merge complete or partial batches atomically:

   `python scripts/layout_pdf.py merge JOB BATCH.json`
5. Validate and build:

   `python scripts/layout_pdf.py validate JOB --translated`

   `python scripts/layout_pdf.py build JOB`

   A nonzero exit or `ok: false` is a failed candidate even when PDF files exist. Fix only the reported cause, then rebuild.
6. Generate current evidence:

   `python scripts/layout_pdf.py review JOB`

   Inspect every target-language page at 72 DPI, every contact sheet, and the 144-DPI pages containing formulas, dense text, tables, or unusual layouts. Inspect both target-language and bilingual PDFs. Then bind the decision to the evidence hash:

   `python scripts/layout_pdf.py review JOB --status passed --notes "SPECIFIC OBSERVATIONS" --evidence-hash HASH`

   Read [references/quality-and-repair.md](references/quality-and-repair.md) when any check or visual review fails.
7. Deliver to a new user-facing directory:

   `python scripts/layout_pdf.py deliver JOB OUTPUT_DIR`

   Delivery requires the current engine, document, layout, artifacts, and passed visual review to match their hashes. It creates `translated.pdf`, `bilingual.pdf`, receipts, and `complete.json` atomically. Confirm both PDFs open and have the expected pages before deleting the verified task-local job directory.

## Invariants

- Preserve each `[[Mdddd]]` and `[[Pdddd]]` token byte-for-byte, in the original order, exactly once. Keep every translation to one semantic paragraph without manual line breaks.
- Leave source formulas as vectors. Never replace subscripts, superscripts, fraction bars, or symbols with flattened text. Latin symbol labels and consecutive inline assets stay together at wrap boundaries. An inline formula stays in its prose baseline; a display formula stays a display object.
- New Chinese or Japanese body paragraphs receive a two-em indent. Headings, continuations, captions, footnotes, and lists do not. Keep headings concise; the engine keeps a shared size and real bold face for each heading style.
- Treat diagnostics as evidence. Do not weaken validation thresholds, edit sealed geometry, or repeatedly shorten prose to conceal a parsing error.
- Retain failed jobs for recovery. Stop after two correction/rebuild attempts with the same failure fingerprint and report the concrete limitation.

For engine maintenance or backend work, read [references/architecture.md](references/architecture.md). The native v5 path targets ordinary text-based academic PDFs; scanned pages, irregular text encodings, complex vector illustrations, and undetected borderless tables may need OCR or a future backend adapter.
