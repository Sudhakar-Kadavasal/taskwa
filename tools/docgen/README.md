# Document generators

ReportLab scripts that produce the PDF document set in `docs/`.
They share `dg_common.py` (Mint Ledger design system — palette, styles,
page furniture, chat bubbles, drawn-illustration helpers).

```bash
pip install reportlab pypdf
python tools/docgen/dg_manual.py    # docs/TaskWA-User-Manual.pdf
python tools/docgen/dg_install.py   # docs/TaskWA-Installation-Guide.pdf
                                    #  + docs/TaskWA-Command-Card.pdf (1 page)
```

Rules learned the hard way:
- Fonts: DejaVu family (registered in dg_common). No emoji glyphs — write
  words. ASCII art needs XPreformatted, not Paragraph.
- Literal `<...>` in text must be escaped as `&lt;...&gt;` (Paragraph and
  XPreformatted both parse markup; unknown tags are silently dropped).
- Never set TA_JUSTIFY on XPreformatted content — ReportLab crashes
  (`ParaLines has no attribute lineBreak`) when an entity-bearing line wraps.
- The Command Card must stay ONE page — check with pypdf after edits.
- Mint Ledger palette lives in dg_common.py; the legacy variable names
  ORANGE/ORANGE_D now hold emerald values on purpose (avoids a mass rename).
- After regenerating, visually verify: `pdftoppm -png -r 60 <pdf> page`
  and inspect the images before committing.

The marketing flyer (docs/TaskWA-Flyer.pdf) is the user's final approved
file — do NOT regenerate or overwrite it.
