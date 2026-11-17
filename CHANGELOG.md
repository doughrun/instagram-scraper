# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.0] - 2026-11-17

First public release.

### Added
- **Claude Code plugin** with an `instagram-scraper` skill that Claude uses automatically for
  Instagram links, posts, reels, carousels, profiles and @handles.
- **`post`**: caption, hashtags, mentions, tagged users, co-authors, location, likes, comment count,
  audio track, paid-partnership flag, alt text; comments with replies; original media download;
  a video map for every video.
- **`profile`**: bio, links, stats and the latest posts, plus a thumbnail contact sheet of the feed;
  `--deep` processes every post.
- **`comments`**: compact offline view of a fetched post's comments with sort, limit and regex filter.
- **Video map**: 10 fps scan, dHash + color-signature scene segmentation with a length-based budget,
  local OCR (RapidOCR) at 5 fps with fuzzy de-noising and persistent-overlay detection, local
  transcription (faster-whisper), contact sheets sized to Claude's image token budget.
- **`zoom`** (full-resolution crops and dense time-range sheets) and **`thorough`** (estimate-first,
  full-resolution quadrants).
- **Login & session**: one-time visible login window using the installed Edge/Chrome, manual cookie
  paste fallback, `status`, and detection of expired sessions, security checkpoints and rate limits
  (exit codes 3 and 4).
- **`setup`**: prerequisite check with per-OS install hints, opt-in NVIDIA GPU pack, opt-in Claude
  Code read permission for the data folder.
- Unit tests, a Windows-compatible trigger evaluation (17/17), and CI on Windows, macOS and Linux.

[Unreleased]: https://github.com/doughrun/instagram-scraper/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/doughrun/instagram-scraper/releases/tag/v0.1.0
