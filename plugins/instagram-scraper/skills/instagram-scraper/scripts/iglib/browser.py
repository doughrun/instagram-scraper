"""The hidden browser: one persistent Playwright profile that holds the Instagram session.

All Instagram traffic goes through `Visit` — a normal page load whose own data
responses are captured passively. We never call Instagram endpoints ourselves.
"""
from __future__ import annotations

import json
import os
import random
import re
import sys
import time
from contextlib import contextmanager
from pathlib import Path

from filelock import FileLock, Timeout

from . import paths

IG = "https://www.instagram.com"
CHANNELS = ("msedge", "chrome", "chromium")  # installed browsers first; chromium needs `playwright install`


class IGError(Exception):
    code = 1
    kind = "error"

    def to_json(self) -> dict:
        return {"error": self.kind, "message": str(self)}


class SessionExpired(IGError):
    code, kind = 3, "session_expired"


class Checkpoint(IGError):
    code, kind = 3, "checkpoint"


class RateLimited(IGError):
    code, kind = 4, "rate_limited"


class Busy(IGError):
    code, kind = 1, "busy"


class NoBrowser(IGError):
    code, kind = 1, "no_browser"


class NotFound(IGError):
    code, kind = 2, "not_found"


def log(m: str) -> None:
    print(m, file=sys.stderr, flush=True)


def profile_dir() -> Path:
    return paths.data_dir() / "browser-profile"


def config_path() -> Path:
    return paths.data_dir() / "browser.json"


def load_config() -> dict:
    try:
        return json.loads(config_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_config(cfg: dict) -> None:
    config_path().write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def pause(lo: float = 2.0, hi: float = 5.0) -> None:
    time.sleep(random.uniform(lo, hi))


@contextmanager
def locked():
    lock = FileLock(str(paths.data_dir() / "browser.lock"))
    try:
        lock.acquire(timeout=120)
    except Timeout as e:
        raise Busy("another Instagram command is using the browser; try again shortly") from e
    try:
        yield
    finally:
        lock.release()


def _launch(p, headless: bool, channel: str | None, user_agent: str | None):
    tried = [channel] if channel else list(CHANNELS)
    last = None
    for ch in tried:
        try:
            kw = dict(headless=headless, viewport={"width": 1280, "height": 900} if headless else None,
                      locale="en-US")
            if ch != "chromium":
                kw["channel"] = ch
            if user_agent:
                kw["user_agent"] = user_agent
            profile_dir().mkdir(parents=True, exist_ok=True)
            return p.chromium.launch_persistent_context(str(profile_dir()), **kw), ch
        except Exception as e:  # noqa: BLE001 - try the next channel
            last = e
    raise NoBrowser(f"no usable browser (tried {', '.join(tried)}): {last}. "
                    "Install Edge or Chrome, or run: uv run --with playwright playwright install chromium")


def real_user_agent(p, channel: str) -> str:
    kw = {} if channel == "chromium" else {"channel": channel}
    b = p.chromium.launch(headless=True, **kw)
    ua = b.new_page().evaluate("navigator.userAgent")
    b.close()
    return ua.replace("HeadlessChrome", "Chrome").replace("HeadlessEdg", "Edg")


@contextmanager
def hidden_browser():
    """Headless persistent context with the real browser's UA. Holds the profile lock."""
    from playwright.sync_api import sync_playwright

    cfg = load_config()
    with locked(), sync_playwright() as p:
        channel = cfg.get("channel")
        ua = cfg.get("user_agent")
        if not channel or not ua:
            # no login recorded yet (or a migrated profile): pick a browser, derive its UA, remember both
            for ch in CHANNELS:
                try:
                    ua = real_user_agent(p, ch)
                    channel = ch
                    save_config({**cfg, "channel": ch, "user_agent": ua})
                    break
                except Exception:  # noqa: BLE001
                    continue
        ctx, channel = _launch(p, True, channel, ua)
        try:
            yield ctx
        finally:
            ctx.close()


# ---------- a single normal page visit, with passive capture ----------

_JSON_BLOB = re.compile(r'<script type="application/json"[^>]*>(.*?)</script>', re.S)
_RATE_TEXT = ("feedback_required", "Please wait a few minutes", "rate_limit_error")


class Visit:
    """Open `path` like a person would and collect the data Instagram sends to the page."""

    def __init__(self, ctx, path: str, settle: float = 6.0):
        self.ctx = ctx
        self.page = ctx.pages[0] if ctx.pages else ctx.new_page()
        self.responses: list[tuple[str | None, dict]] = []   # (friendly_name, json)
        self._rate_hit = False
        self.page.on("response", self._on_response)
        url = path if path.startswith("http") else IG + path
        log(f"Visiting {url}")
        self.page.goto(url, wait_until="domcontentloaded", timeout=45000)
        time.sleep(settle)
        self.check()

    def _on_response(self, r) -> None:
        u = r.url
        if "instagram.com" not in u or not ("/api/" in u or "/graphql" in u):
            return
        if r.status == 429:
            self._rate_hit = True
            return
        try:
            body = r.text()
        except Exception:  # noqa: BLE001 - body unavailable (redirects, aborted)
            return
        if any(t in body[:2000] for t in _RATE_TEXT):
            self._rate_hit = True
        try:
            data = json.loads(body)
        except ValueError:
            return
        name = None
        pd = r.request.post_data or ""
        m = re.search(r"fb_api_req_friendly_name=([^&]+)", pd)
        if m:
            name = m.group(1)
        self.responses.append((name, data))
        dump = os.environ.get("IG_SKILL_DEBUG_DUMP")
        if dump:  # developer aid: save every captured response to inspect Instagram's shapes
            Path(dump).mkdir(parents=True, exist_ok=True)
            (Path(dump) / f"{len(self.responses):03d}_{name or 'unnamed'}.json").write_text(body, encoding="utf-8")

    def check(self) -> None:
        url = self.page.url
        if "/accounts/login" in url:
            raise SessionExpired("Instagram session expired or logged out; run setup/login again")
        if "/challenge/" in url or "/checkpoint/" in url:
            raise Checkpoint("Instagram wants a security check; open Instagram in a browser/app, "
                             "confirm it's you, then try again")
        if self._rate_hit:
            raise RateLimited("Instagram is rate-limiting this account; stop and try again in a few hours")
        # Logged-out signals (any one is enough): Instagram cleared the session cookie,
        # the page carries the logged-out marker, or it shows the login form.
        has_cookie = any(c["name"] == "sessionid" and c["value"] for c in self.ctx.cookies(IG))
        logged_out_page = self.page.evaluate("""() =>
            /not-logged-in/.test(document.documentElement.className) ||
            !!document.querySelector('input[name="username"][type="text"], form#loginForm, input[name="password"]')
        """)
        if not has_cookie or logged_out_page:
            raise SessionExpired("the hidden browser is not logged in (session expired or logged out); "
                                 "run setup/login again")

    def embedded(self) -> list:
        """JSON blobs server-rendered into the page HTML."""
        out = []
        for blob in _JSON_BLOB.findall(self.page.content()):
            if '"xdt_' not in blob and "comment" not in blob and "user" not in blob:
                continue
            try:
                out.append(json.loads(blob))
            except ValueError:
                continue
        return out

    def all_json(self) -> list:
        return self.embedded() + [d for _, d in self.responses]

    def by_name(self, name: str) -> list:
        return [d for n, d in self.responses if n == name]

    def is_404(self) -> bool:
        t = (self.page.title() or "").lower()
        return "page not found" in t or "isn't available" in t


def walk(o, pred):
    """Yield every dict in a JSON tree that satisfies pred."""
    stack = [o]
    while stack:
        x = stack.pop()
        if isinstance(x, dict):
            if pred(x):
                yield x
            stack.extend(x.values())
        elif isinstance(x, list):
            stack.extend(x)
