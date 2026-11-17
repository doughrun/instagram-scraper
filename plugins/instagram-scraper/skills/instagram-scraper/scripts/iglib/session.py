"""login (visible window, once), login --paste (manual cookie), status (one hidden visit)."""
from __future__ import annotations

import getpass
import time

from . import browser
from .browser import CHANNELS, IG, log

LOGIN_TIMEOUT = 300

PASTE_HELP = """\
Manual login (use this only if the login window doesn't work):
  1. In your normal browser, log in to https://www.instagram.com with the account the skill should use
     (a secondary account is recommended).
  2. Open Developer Tools (F12, or Cmd+Option+I on Mac) -> Application (Chrome/Edge) or Storage (Firefox)
     -> Cookies -> https://www.instagram.com
  3. Copy the Value of the cookie named `sessionid`.
  4. Paste it below (input is hidden) and press Enter.
"""


def login_window() -> dict:
    """Open a visible window on the login page; return once a session cookie exists."""
    from playwright.sync_api import sync_playwright

    with browser.locked(), sync_playwright() as p:
        ctx, channel = browser._launch(p, headless=False, channel=None, user_agent=None)
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            ua = page.evaluate("navigator.userAgent")
            page.goto(IG + "/accounts/login/")
            log("A browser window is open: log in to Instagram there (waiting up to 5 minutes)...")
            deadline = time.time() + LOGIN_TIMEOUT
            while time.time() < deadline:
                if _has_session(ctx):
                    time.sleep(3)  # let the post-login redirects and remaining cookies settle
                    browser.save_config({"channel": channel, "user_agent": ua, "logged_in_at": int(time.time())})
                    return {"ok": True, "browser": channel}
                if page.is_closed():
                    return {"ok": False, "error": "window_closed"}
                time.sleep(1)
            return {"ok": False, "error": "login_timeout"}
        finally:
            ctx.close()


def login_paste() -> dict:
    """Inject a pasted sessionid into the hidden profile (cookie never echoed or printed)."""
    from playwright.sync_api import sync_playwright

    print(PASTE_HELP, flush=True)
    sid = getpass.getpass("sessionid: ").strip().strip('"')
    if len(sid) < 20:
        return {"ok": False, "error": "bad_input", "message": "that doesn't look like a sessionid"}
    uid = sid.split("%3A", 1)[0].split(":", 1)[0]
    with browser.locked(), sync_playwright() as p:
        channel, ua = None, None
        for ch in CHANNELS:
            try:
                ua = browser.real_user_agent(p, ch)
                channel = ch
                break
            except Exception:  # noqa: BLE001
                continue
        ctx, channel = browser._launch(p, True, channel, ua)
        try:
            cookies = [{"name": "sessionid", "value": sid, "domain": ".instagram.com", "path": "/",
                        "httpOnly": True, "secure": True, "sameSite": "Lax",
                        "expires": time.time() + 180 * 86400}]
            if uid.isdigit():
                cookies.append({"name": "ds_user_id", "value": uid, "domain": ".instagram.com", "path": "/",
                                "secure": True, "sameSite": "Lax", "expires": time.time() + 90 * 86400})
            ctx.add_cookies(cookies)
        finally:
            ctx.close()
    browser.save_config({"channel": channel, "user_agent": ua, "logged_in_at": int(time.time()), "via": "paste"})
    return {"ok": True, "browser": channel, **status()}


def _has_session(ctx) -> bool:
    return any(c["name"] == "sessionid" and c["value"] for c in ctx.cookies(IG))


def status() -> dict:
    """One normal hidden visit to the home page; raises SessionExpired etc. if not usable."""
    with browser.hidden_browser() as ctx:
        if not _has_session(ctx):
            raise browser.SessionExpired("not logged in yet; run setup")
        v = browser.Visit(ctx, "/", settle=5)
        username = v.page.evaluate("""() => {
            const img = [...document.querySelectorAll('img[alt]')]
              .find(i => /'s profile picture$/.test(i.alt));
            return img ? img.alt.replace(/'s profile picture$/, '') : null;
        }""")
    cfg = browser.load_config()
    return {"logged_in": True, "username": username, "browser": cfg.get("channel"),
            "logged_in_at": cfg.get("logged_in_at")}
