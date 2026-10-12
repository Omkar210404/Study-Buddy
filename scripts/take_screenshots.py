"""Take the README screenshots from a running app. A development tool, not part of the app.

Needs Playwright (`pip install playwright`) and a Chromium, Chrome or Edge browser.
It only looks: it flips a card but never rates one, so the database is left as it was.

    python scripts/take_screenshots.py --url http://127.0.0.1:8765
    python scripts/take_screenshots.py --url http://127.0.0.1:8766 --only report   # app in mock LLM mode
"""

import argparse
from pathlib import Path

from playwright.sync_api import Browser, Error, Playwright, sync_playwright

DESKTOP = {"width": 1180, "height": 860}
PHONE = {"width": 390, "height": 844}


def launch(playwright: Playwright) -> Browser:
    for options in ({}, {"channel": "chrome"}, {"channel": "msedge"}):
        try:
            return playwright.chromium.launch(**options)
        except Error:
            continue
    raise SystemExit("No Chromium, Chrome or Edge browser could be started.")


def main_shots(browser: Browser, url: str, out: Path) -> None:
    page = browser.new_page(viewport=DESKTOP, color_scheme="light")
    page.goto(f"{url}/")
    page.screenshot(path=out / "today.png")

    page.set_viewport_size({"width": DESKTOP["width"], "height": 1280})
    page.goto(f"{url}/decks/1")
    page.screenshot(path=out / "study-view.png")
    page.set_viewport_size(DESKTOP)

    page.goto(f"{url}/review?deck=1")
    page.screenshot(path=out / "review-front.png")
    page.keyboard.press("Space")
    page.wait_for_selector(".ratings:not([hidden])")
    page.wait_for_timeout(300)
    page.screenshot(path=out / "review-back.png", full_page=True)

    page.goto(f"{url}/decks/1/quiz?mode=mc")
    page.screenshot(path=out / "quiz.png")

    page.goto(f"{url}/progress")
    page.screenshot(path=out / "progress.png", full_page=True)
    page.close()

    phone = browser.new_page(viewport=PHONE, color_scheme="dark", device_scale_factor=2)
    phone.goto(f"{url}/review?deck=1")
    phone.keyboard.press("Space")
    phone.wait_for_selector(".ratings:not([hidden])")
    phone.wait_for_timeout(300)
    phone.screenshot(path=out / "review-phone-dark.png", full_page=True)
    phone.close()


def report_shot(browser: Browser, url: str, out: Path) -> None:
    """Needs the app started with LLM_PROVIDER=mock MOCK_LLM_MODE=mixed on an empty database."""
    page = browser.new_page(viewport={"width": 1180, "height": 1000}, color_scheme="light")
    page.goto(f"{url}/")
    page.get_by_role("button", name="Try it with the sample notes").click()
    page.wait_for_url("**/decks/*")
    page.goto(f"{url}/sources/1")
    page.get_by_role("button", name="Generate cards with the model").click()
    page.wait_for_url("**/runs/*")
    page.screenshot(path=out / "generation-report.png")
    page.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    parser.add_argument("--out", type=Path, default=Path("docs/screenshots"))
    parser.add_argument("--only", choices=["main", "report"], default="main")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        browser = launch(playwright)
        if args.only == "main":
            main_shots(browser, args.url.rstrip("/"), args.out)
        else:
            report_shot(browser, args.url.rstrip("/"), args.out)
        browser.close()
    print(f"Screenshots written to {args.out}")


if __name__ == "__main__":
    main()
