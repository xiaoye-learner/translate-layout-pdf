# Contributing

Contributions are accepted under the repository's `AGPL-3.0-only` license. Submit only material you created or have the right to contribute.

## Before opening a pull request

1. Keep changes focused on one behavior or one related repair.
2. Add a regression test for observable layout, contract, or delivery changes.
3. Run:

   ```bash
   python scripts/layout_pdf.py doctor
   python -m unittest discover -s tests -v
   ```

4. For visual changes, include a minimal synthetic source, the final diagnostics, and 72/144 DPI evidence.
5. Update `THIRD_PARTY_NOTICES.md` before adding or changing a dependency, backend, font, fixture, copied implementation, schema, or other third-party asset.

Do not commit confidential documents, unpublished papers, copyrighted PDFs without redistribution permission, credentials, personal data, or production logs. Prefer fixtures generated entirely by code under `tests/`.

Describe the concrete trigger, behavior before and after the change, validation commands, and any remaining limitations in the pull request.
