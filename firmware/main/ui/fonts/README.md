# Production font asset

`font_maple_mono_16.c` is generated from Maple Mono NF CN Regular, official
v7.9 release, using `lv_font_conv@1.5.3`: 16 px, 4 bpp, uncompressed, no kerning,
and the available encoded characters in U+0020–U+10FFFF. It is licensed under
the adjacent [SIL Open Font License](OFL.txt), including the upstream copyright
notice. This license applies to the font asset, independently of project code.

Keep the generated C asset, this README, and the license in version control.
Firmware and desktop UI builds compile the committed asset directly, without
Node.js/npm or font conversion. The downloaded ZIP, source TTF, converter cache,
and comparison outputs belong under the ignored `build/` directory.

Only font maintainers need to regenerate from the repository root with:

```bash
python scripts/firmware/generate_font.py
```

Generation needs Python 3.12+, Node.js/npm, and first-run access to GitHub Releases
and npm; no installed font is required.
See [font conversion and validation](../../../../docs/font-conversion.md)
for hashes, coverage, memory use, layout constraints, previews, and build checks.
