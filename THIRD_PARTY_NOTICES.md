# Third-party software and design references

This repository is licensed under `AGPL-3.0-only` because its native engine imports and runs PyMuPDF in-process. The repository does not vendor the Python packages listed below; users install them separately from their normal package indexes. A binary, wheel, container, or application bundle that redistributes those packages must also include the license material shipped by the applicable packages and comply with their complete terms.

## Runtime dependencies

| Component | Tested version | License | Use |
|---|---:|---|---|
| [PyMuPDF](https://github.com/pymupdf/PyMuPDF) and its MuPDF engine | 1.26.5 | GNU Affero General Public License v3, or a separate Artifex commercial license | PDF parsing, geometry, vector extraction, rendering, editing, font embedding, and output |
| [Pillow](https://github.com/python-pillow/Pillow) | 11.1.0 | MIT-CMU | Raster comparison during verification |
| [fontTools](https://github.com/fonttools/fonttools) | 4.55.3 | MIT | Type 1 glyph outline and font metric inspection |
| [jsonschema](https://github.com/python-jsonschema/jsonschema) | 4.23.0 | MIT | Validation of the versioned document contract |

The version ranges used by this repository are recorded in `requirements.txt`. Python standard-library modules are not listed here.

## Fonts

No font file is included in this repository. The engine uses a font pair already installed on the user's system or paths explicitly supplied with `--font` and `--bold-font`. Generated PDFs may contain a subset of the selected font; redistribution of an output document remains subject to that font's embedding permissions. The Windows DengXian files used during development report OS/2 `fsType = 8` (editable embedding). The Linux fallback paths point to Noto Sans CJK, which is normally distributed under the SIL Open Font License 1.1; the actual installed files and their license must still be checked by the distributor.

## Design references with no incorporated code

The following repositories were inspected for architectural or workflow ideas. No source file, renderer, schema, fixture, asset, or runtime dependency from them is included in this repository.

| Project | Inspected commit | License | Scope of reference |
|---|---|---|---|
| [Archify](https://github.com/tt-a1i/archify) | `06dd052602dd9a369e4d034e24faef0917b5a60c` | MIT; copyright 2026 tt-a1i (Archify), copyright 2025 Cocoon AI | Small entry skill, typed intermediate representation, deterministic validation, immutable evidence, and atomic delivery concepts |
| [BabelDOC](https://github.com/funstory-ai/BabelDOC) | `38d3896dcde9b5a940c62cf5563cadea673a64d3` | AGPL-3.0 | Separation of parsing, translation, and reconstruction responsibilities |
| [PDFMathTranslate](https://github.com/PDFMathTranslate/PDFMathTranslate) | `f273d5434c4ed3baac2d66097cec636bd8cd3e4b` | AGPL-3.0 | Formula-preserving PDF translation workflow research |
| [PDFMathTranslate-next](https://github.com/PDFMathTranslate/PDFMathTranslate-next) | `3538a8195d8379fe3fb4a0117c88d15c5b7b5e89` | AGPL-3.0 | Backend boundaries and document reconstruction workflow research |

Ideas, system behavior, and workflow patterns were reimplemented independently in the native `layoutpdf` modules. If future work copies or adapts expressive code, schemas, tests, documentation, or assets from any referenced project, this notice and the repository license review must be updated before release.

## Publication checklist

1. Keep `LICENSE`, `THIRD_PARTY_NOTICES.md`, and `requirements.txt` in source releases.
2. Publish the complete corresponding source for the distributed or network-accessible application as required by AGPL-3.0.
3. Preserve dependency license files when publishing a container, executable, wheel bundle, or vendored dependency tree.
4. Do not add BabelDOC, PDFMathTranslate, Archify, fonts, fixtures, or sample papers to a release unless their exact license and attribution requirements have been reviewed for that release.
5. Re-run dependency and license review whenever a version range, backend, bundled asset, or distribution format changes.
