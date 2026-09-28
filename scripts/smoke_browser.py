"""Optional local browser checks: needs Playwright + installed Chrome, not production dependencies."""
from functools import partial
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
import json
from pathlib import Path
import re
from threading import Thread
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_):
        pass


def main():
    artifacts = ROOT / "artifacts"
    artifacts.mkdir(exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(ROOT / "site")))
    Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"
    snapshot = json.loads((ROOT / "site/data/status.json").read_text(encoding="utf-8"))
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="chrome", headless=True)
            page = browser.new_page(viewport={"width":1440,"height":1120})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(base, wait_until="networkidle")
            expect(page.locator(".coin-panel")).to_have_count(2)
            expect(page.locator("#mining-status")).not_to_have_text("正在查询")
            expect(page.locator("tbody tr")).not_to_have_count(0)
            page.screenshot(path=str(artifacts / "desktop.png"), full_page=True)
            page.get_by_role("button", name="NOCK", exact=True).click()
            expect(page.locator("#history-content")).to_contain_text("尚未查到")
            page.set_viewport_size({"width":390,"height":844})
            page.screenshot(path=str(artifacts / "mobile.png"), full_page=True)
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "Mobile overflow"
            page.locator("summary").click()
            expect(page.locator("#addresses")).to_contain_text(snapshot["config"]["nock_address"])
            old = json.loads(json.dumps(snapshot))
            for source in old["sources"].values():
                source["updated_at"] = "2026-01-01T00:00:00Z"
            page.route("**/data/status.json?*", lambda route: route.fulfill(json=old))
            page.get_by_role("button", name="刷新数据").click()
            expect(page.locator("#mining-status")).to_contain_text("数据较旧")
            expect(page.locator("#notice")).to_be_visible()
            expect(page.locator(".coin-panel .tag").first).to_have_text("上次成功数据")
            page.unroute("**/data/status.json?*")
            page.route("**/data/status.json?*", lambda route: route.abort())
            page.get_by_role("button", name="刷新数据").click()
            expect(page.locator("#notice")).to_contain_text("暂时无法读取")
            fresh = browser.new_page(viewport={"width":390,"height":844})
            fresh.route("**/data/status.json?*", lambda route: route.fulfill(status=503, body="unavailable"))
            fresh.goto(base, wait_until="networkidle")
            expect(fresh.locator("#mining-status")).to_have_text("状态未知")
            expect(fresh.locator("#updated")).to_have_text("读取失败")
            assert not errors, errors
            print("PASS: desktop/mobile, real balances, transactions, tabs, addresses, no overflow, stale/error/initial-failure states")
            browser.close()
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()
