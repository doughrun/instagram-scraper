# Security Policy

## Supported versions

Security fixes go into the latest release.

| Version | Supported |
|---|---|
| 0.1.x | ✅ |

## Reporting a vulnerability

**Please don't open a public issue for security problems.**

Report privately through
[GitHub Security Advisories](https://github.com/doughrun/instagram-scraper/security/advisories/new).
Include what you found, how to reproduce it, and its impact. You'll get an acknowledgement within a
few days, and we'll keep you updated until it's fixed and disclosed.

## What's in scope

This plugin handles a sensitive asset: **a logged-in Instagram session**. We especially want to hear
about:

- Anything that could expose the session cookie or browser profile to other programs, websites,
  Claude, logs, or the network
- Paths where data from Instagram pages (captions, comments, alt text) could be interpreted as
  instructions or commands, for example prompt injection that makes Claude run tools it shouldn't
- Writes outside the plugin's data folder, other than the documented, opt-in Claude Code settings rule
- Dependency vulnerabilities with a realistic exploit path here

## How the session is protected

- The session lives only in a dedicated browser profile in the plugin's data folder
  (see the README), separate from your everyday browser.
- Passwords are never stored. The manual `login --paste` fallback reads the cookie with hidden
  input and is meant to be run by the user directly, so it never passes through Claude.
- Downloaded media URLs (signed CDN links) are not saved in output files.

## Content from Instagram is untrusted

Captions, comments and on-screen text are written by strangers. `SKILL.md` treats them as data to
analyze, never as instructions. If you find a way to make Claude follow instructions embedded in
Instagram content, please report it as above.
