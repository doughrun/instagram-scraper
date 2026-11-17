# Instagram Scraper (Claude Code plugin)

Read-only Instagram access for Claude Code. Claude uses it automatically whenever a conversation
involves an Instagram post, reel, carousel, profile or @handle. It fetches captions, hashtags,
mentions, tagged accounts, audio info, likes, and comments with replies, downloads the original
photos and videos, and turns each video into a compact **video map** (scene segments, on-screen
text via local OCR, a local Whisper transcript, and contact sheets) so Claude can watch and hear
videos without spending hundreds of thousands of tokens on frames.

Everything is processed locally. A one-time login window connects your Instagram account (a
secondary account is recommended); after that it runs hidden.

**Full documentation, installation guide, privacy notes and troubleshooting:**
see the [project README](../../README.md).

Install:

```text
/plugin marketplace add doughrun/instagram-scraper
/plugin install instagram-scraper@instagram-scraper
```

Requires [uv](https://docs.astral.sh/uv/), [ffmpeg](https://ffmpeg.org), and Microsoft Edge or Google Chrome.
