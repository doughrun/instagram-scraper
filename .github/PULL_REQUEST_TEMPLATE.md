## What does this change?

<!-- One or two sentences. Link the issue if there is one: "Fixes #123" -->

## How did you test it?

<!-- e.g. "pytest passes; fetched a public reel and a carousel on macOS 15". Don't paste other people's content. -->

## Checklist

- [ ] Stays read-only (no liking, commenting, following, posting or messaging)
- [ ] All Instagram traffic goes through `browser.Visit`, with no direct endpoint calls, retry loops or parallel browsers
- [ ] No real user data, cookies or scraped media in code, tests or this PR
- [ ] Works cross-platform (no hard-coded paths or OS-specific shell commands)
- [ ] Tests added or updated, and `pytest` passes
- [ ] `README.md` / `SKILL.md` / `CHANGELOG.md` (Unreleased) updated if behavior changed
- [ ] If `SKILL.md`'s description changed: trigger eval run and passing
