# Contributing to Instagram Scraper

Thanks for helping. This project lives or dies by people noticing when Instagram changes something,
so bug reports are as valuable as code.

## Ways to help

- **Report a breakage.** Instagram changes its pages often. If a post, profile or comment fetch
  suddenly returns `not_found`, empty comments, or wrong data, open a
  [bug report](https://github.com/doughrun/instagram-scraper/issues/new?template=bug_report.yml).
- **Test on your platform.** macOS and Linux reports are especially welcome.
- **Improve the video map.** Better OCR clean-up, segmentation, or token efficiency.
- **Docs.** Clearer install steps, troubleshooting entries, translations.

## Ground rules

1. **Read-only, always.** Pull requests that add liking, commenting, following, posting, DMs, or
   anything else that acts on Instagram won't be merged.
2. **Be gentle with Instagram.** No bulk crawling, no parallel browsers, no retry loops on rate
   limits. All Instagram traffic goes through `browser.Visit` (a normal page load with passive
   capture). Don't add direct calls to Instagram endpoints.
3. **Never commit real user data.** No real usernames, comments, captions, cookies, or scraped media
   in tests, fixtures, issues or screenshots. Tests use synthetic, Instagram-*shaped* data
   (see `tests/test_instagram.py`). Redact before you paste debug output.
4. **Cross-platform.** Code must work on Windows, macOS and Linux: no hard-coded paths and no
   OS-specific shell commands. Use `pathlib` and `platformdirs`.

## Development setup

You need [uv](https://docs.astral.sh/uv/) and [ffmpeg](https://ffmpeg.org).

```bash
git clone https://github.com/doughrun/instagram-scraper.git
cd instagram-scraper

# Run the unit tests (no Instagram access needed)
uv run --with pytest --with platformdirs --with pillow --with filelock --with httpx pytest -q tests

# Try the plugin in Claude Code straight from your checkout
claude --plugin-dir plugins/instagram-scraper
```

The CLI is a single script with inline dependencies ([PEP 723](https://peps.python.org/pep-0723/)),
so `uv run` builds its environment automatically:

```bash
uv run plugins/instagram-scraper/skills/instagram-scraper/scripts/ig.py --help
uv run plugins/instagram-scraper/skills/instagram-scraper/scripts/ig.py video path/to/any.mp4   # no Instagram needed
```

### Project layout

```text
.claude-plugin/marketplace.json            # makes this repo installable as a plugin marketplace
plugins/instagram-scraper/
├── .claude-plugin/plugin.json             # plugin manifest
└── skills/instagram-scraper/
    ├── SKILL.md                           # what Claude reads: when to use the skill and how
    └── scripts/
        ├── ig.py                          # CLI entry point (JSON on stdout)
        └── iglib/
            ├── browser.py                 # hidden browser, Visit (passive capture), error detection
            ├── session.py                 # login / paste / status
            ├── instagram.py               # parse page data by shape: posts, comments, profiles
            ├── pipeline.py                # post/profile orchestration, media download
            ├── frames.py, segments.py     # 10 fps scan, scene segmentation, token math
            ├── ocr.py                     # RapidOCR + clean-up (clustering, overlays)
            ├── transcribe.py              # faster-whisper, optional GPU pack
            ├── videomap.py, sheets.py     # video map, contact sheets, zoom, thorough
            └── paths.py, permissions.py   # data folder, Claude Code read rule
tests/                                     # offline unit tests (synthetic data)
evals/                                     # skill-trigger evaluation
```

### Debugging Instagram's data shapes

Instagram data is parsed **by shape, not by query name**, because names and paths change. To see
what a page actually receives, set `IG_SKILL_DEBUG_DUMP=<folder>` and run a command: every captured
response is saved there. These dumps contain real people's content, so keep them out of the repo
(`dumps/` is git-ignored) and out of issues.

### Changing `SKILL.md`

`SKILL.md`'s `description` decides when Claude uses the skill. If you change it, run the trigger
evaluation (it calls `claude -p`, one query at a time, and never executes the skill):

```bash
python evals/trigger_eval.py plugins/instagram-scraper/skills/instagram-scraper/SKILL.md evals/trigger_queries.json
```

All queries should pass. Add a query to `evals/trigger_queries.json` for any case you fix.

## Pull requests

1. Fork, then create a branch from `main`.
2. Keep changes focused; one topic per PR.
3. Add or update tests for logic changes. `pytest` must pass.
4. Update `README.md` / `SKILL.md` if behavior or commands change, and add an entry under
   **Unreleased** in `CHANGELOG.md`.
5. Fill in the PR template, including how you tested. "Fetched a public reel on Windows" is a fine
   answer, but don't paste other people's content.

## Releasing (maintainers)

1. Bump `version` in `plugins/instagram-scraper/.claude-plugin/plugin.json` and
   `.claude-plugin/marketplace.json`.
2. Move **Unreleased** in `CHANGELOG.md` to the new version.
3. Tag `vX.Y.Z` and create a GitHub release.
