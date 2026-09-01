# Daily Reference Book GUI

Use `/knowledge` and the **Daily Reference Books** button to manage reference
book sources for the Daily Knowledge feature.

Use `/knowledge_book_add` to upload a structured JSON book through Discord's
native command form. No manual `sources.json` editing is required.

Each book is stored in `knowledge/source/` and registered in the existing
knowledge manifest with:
- category: `reference_book`
- status: `verified`
- daily source enabled/disabled
- selection weight (1-100)

Higher weight makes a source more likely to be selected.

The Daily Knowledge Engine combines configured websites and enabled reference
books and performs weighted random source selection.

Reference books are intentionally separate from official BSEMC documents.
They must not be used as institutional policy sources.
