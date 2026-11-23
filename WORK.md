---
this_file: WORK.md
---

# Work log

## 2026-11-24 — fly-january 0.1.1

- The docs wrapper and CI use Python 3.13. Fly supplies the Vexy menu and footer and keeps the existing light and dark modes.
- The print guide uses the print-site 2.9 renderer and its packaged stylesheets within a regular Fly page. Its nine chapters, table of contents and internal links are present at `print_page/`.
- `bash build.sh --docs --strict` rebuilt `docs/` with zero warnings. All 11 HTML pages passed local asset and link checks. Pytest passed all 232 tests, including the print-guide regression test.

## 2026-10-18: documentation plugins

- Use MaterialX search, inherited metadata and a topic index; keep ordered navigation in awesome-nav.
- The documentation wrapper installs the plugins required by this site.
- Strict documentation build and rendered output checks passed.
- Documentation CI now uses the same isolated ProperDocs/plugin wrapper as local builds.
