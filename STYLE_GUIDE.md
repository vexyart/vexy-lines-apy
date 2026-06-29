# Documentation Style Guide — vexy-lines-apy

> "The app does the drawing. This package tells it what to draw."

## Lead with what the reader can do, not what the package is

Start every doc page and docstring with a concrete action or outcome, not a feature list.

Bad: "MCPClient is a context-managed TCP client for the Vexy Lines JSON-RPC 2.0 server."
Good: "Connect to Vexy Lines, drive it programmatically — open documents, tweak fills, export."

## State the requirement up front

If a method or feature requires the desktop app, say so in the first sentence.
If it works offline (parser-only, style engine without MCP), say that too.

Good: "Requires the Vexy Lines app (auto-launched if not running)."
Good: "Offline — no app needed."

## Code examples before prose explanation

Every public API surface should have a runnable code block before any explanatory text.
Keep examples under 15 lines. Prefer `with MCPClient() as vl:` over assigning the client to a variable and calling `__enter__` manually.

## Units and defaults belong in the signature, not buried in paragraphs

Mention the unit (pixels, mm, dpi, seconds) in the `Args:` block.
Mention the default value if it affects the common case.

## App-version notes format

Use: `Requires Vexy Lines **X.Y** or later.`
Place this as the second line of the docstring, after the one-line summary, before Args.

## Optional dependencies

Name the pip extra explicitly: `pip install "vexy-lines-apy[svg]"`.
Also show the direct form (`pip install svglab`) for users who manage dependencies manually.

## Changelog entries

One bullet per user-visible change. Use lowercase `feat:`, `fix:`, `refactor:`, `test:`, `chore:` prefixes.
Reference the issue number if applicable: `(Issue #617)`.

## README length

Keep the root README under 200 lines. Link to `src_docs/` for deep reference (API tables, protocol details, style engine internals).
