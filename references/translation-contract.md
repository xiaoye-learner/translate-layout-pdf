# Translation contract

Translate semantic paragraphs in `batches.json`; never translate extracted PDF lines independently. Entries with the same `flow_id` form one reading flow across columns or pages and should be translated together with shared context.

## Immutable tokens

- `[[Mdddd]]` names a source-derived mathematical asset. Keep its spelling, count, and order exactly.
- `[[Pdddd]]` protects a URL, email address, DOI, citation, or similar literal. Keep it exactly; the renderer restores the source text.
- Do not introduce another token-shaped string. Do not put a token on a separate line unless its surrounding paragraph is itself a display formula flow.

Inspect assets adjacent to prose punctuation. A vector token can already contain a source parenthesis or separator; preserve it once and do not add a duplicate in the translated prose. Maintain the semantic boundary on either side of a fixed display equation even when the surrounding text shares a continuation flow.

The merge command rejects missing, duplicated, reordered, unknown, empty, multiline, and fenced translations as one atomic batch. A rejected batch makes no partial edits.

## Role decisions

| Role | Translation behavior |
|---|---|
| `title` | Concise title wording; no terminal punctuation added without cause. |
| `heading`, `subheading` | Preserve the section number and hierarchy; use concise terminology. |
| `body` | Translate the full paragraph meaning. Preserve citations, variables, units, and proper nouns. |
| `caption` | Localize Figure/Table labels consistently. |
| `footnote` | Translate compactly; retain its markers and protected links. |
| `list` | Preserve one item per source item and its leading marker. |

Author and affiliation blocks, page furniture, pure equations, detected tables, images, and numeric-only regions are normally preserved. Record consistent terminology before translating the first batch, and apply it across all batches.

Do not add translator commentary, Markdown, segment labels, or invented explanations to a translated string. If the source extraction joins or splits the wrong content, correct the structure before translation.
