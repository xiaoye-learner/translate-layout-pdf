# v5 architecture

The design follows the useful parts of Archify's workflow architecture: a small user path, a typed intermediate representation, deterministic compilation, structured diagnostics with supported fixes, immutable build evidence, and a separate atomic delivery step.

```text
source.pdf
   │ prepare
   ▼
document.json (sealed Source IR + semantic paragraphs + assets)
   │ merge translations
   ▼
validated document snapshot
   │ Typesetter.compile
   ▼
layout.json (measured placements and shared style scales)
   │ build + artifact checks
   ▼
candidate PDFs + receipt.json
   │ render + human visual decision
   ▼
evidence.json + review.json
   │ deliver only when all hashes match
   ▼
atomic output directory
```

## Modules

- `contracts.py`: JSON Schema validation, structure sealing, asset/source/font hashes, token order, coverage and flow checks, atomic JSON writes, typed diagnostics.
- `extract.py`: two-dimensional glyph analysis, paragraph and column flow inference, mixed formula/prose decomposition, containment-based formula-fragment absorption, same-flow semantic-fragment merging, conservative preservation, math-token creation, style inference.
- `fonts.py`: actual glyph ink bounds, including embedded Type 1 outline handling. This prevents nominal PDF font boxes from treating empty descender space as formula overlap.
- `layout.py`: measured token layout, baseline-aware vector math placement, two-em paragraph indentation, shared style scaling, source-container flow, punctuation constraints, and relative-overlap collision checks that distinguish meaningful intersections from tiny glyph-edge contact.
- `pipeline.py`: atomic batch merge, bounded corrections, reconstruction, formula/preserved-region image comparison, bilingual composition, rendered evidence, hash-bound review, atomic delivery.

## Data boundaries

`document.json` is the source of truth. Translation strings are mutable through `merge`; source text, geometry, tokens, styles, and asset bindings are covered by `structure_sha256`. Supported structural corrections deliberately re-seal the document and are logged.

Each build snapshots the document, records the engine hash and artifact hashes, and writes `latest.json` only for that candidate. Any later engine, document, layout, or PDF change invalidates review and delivery. Failed candidates remain available for diagnosis but are never accepted merely because a PDF file exists.

The current engine is `native-vector-v1`. Its document contract is backend-neutral enough for a future BabelDOC adapter, but this version does not claim or load BabelDOC. A future adapter must emit the same validated paragraph, asset, style, preservation, and evidence semantics before it can become a selectable backend.
