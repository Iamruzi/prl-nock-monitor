"""Browser regression tests for valuation math and quote failures; synthetic amounts."""
from copy import deepcopy
from datetime import datetime, timezone
from functools import partial
from http.server import ThreadingHTTPServer
import json
from threading import Thread
import time
from playwright.sync_api import sync_playwright, expect
from smoke_browser import QuietHandler, ROOT


def main():
    data=json.loads((ROOT / "site/data/status.json").read_text(encoding="utf-8"))
    now=datetime.now(timezone.utc).isoformat()
    for source in data["sources"].values():
        source["updated_at"]=now
        source["state"]="ok"
    data["sources"]["prl_chain"]["data"]["balance"]=200
    data["sources"]["nock_chain"]["data"]={"balance":100,"received_total":100,"transactions":[],"address_not_found":False}
    data["sources"]["prl_pool"]["data"]["balance"]=999999
    data["sources"]["prl_chain"]["data"]["received_total"]=888888
    quotes={"PRL":{"usd":2,"cny":14,"change_24h":2,"updated_at":now},
            "NOCK":{"usd":.05,"cny":.35,"change_24h":-3,"updated_at":now}}
    data["sources"]["prices"]={"data":{"provider":"CoinGecko","quotes":quotes},"state":"ok","updated_at":now}
    raw={"pearl-2":{"usd":2,"cny":14,"usd_24h_change":2,"last_updated_at":int(time.time())},
         "nockchain":{"usd":.05,"cny":.35,"usd_24h_change":-3,"last_updated_at":int(time.time())}}
    server=ThreadingHTTPServer(("127.0.0.1",0),partial(QuietHandler,directory=str(ROOT/"site")))
    Thread(target=server.serve_forever,daemon=True).start()
    base=f"http://127.0.0.1:{server.server_port}"
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(channel="chrome",headless=True)
            errors=[]

            def page_for(snapshot, prices=raw, failure=False):
                page=browser.new_page(viewport={"width":390,"height":844})
                page.on("pageerror",lambda e:errors.append(str(e)))
                page.route("**/data/status.json?*",lambda route:route.fulfill(json=snapshot))
                page.route("https://api.coingecko.com/**",lambda route:route.fulfill(status=429,body="rate limit") if failure else route.fulfill(json=prices))
                page.goto(base,wait_until="networkidle")
                return page

            page=page_for(data)
            expect(page.locator("#total-usd")).to_have_text("$405.00")
            expect(page.locator("#total-cny")).to_contain_text("2,835.00")
            expect(page.locator('[data-wallet-value="PRL"]')).to_have_text("$400.00")
            expect(page.locator('[data-wallet-value="NOCK"]')).to_have_text("$5.00")
            expect(page.locator("#value-state")).to_have_text("当前余额估值")
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            missing=deepcopy(data);missing["sources"]["nock_chain"]["data"]["balance"]=None
            page=page_for(missing)
            expect(page.locator("#total-usd")).to_have_text("$400.00")
            expect(page.locator("#value-state")).to_have_text("部分估值")
            expect(page.locator("#value-note")).to_contain_text("NOCK")
            unknown=deepcopy(data);unknown["sources"].pop("prices")
            page=page_for(unknown,failure=True)
            expect(page.locator("#total-usd")).to_have_text("—")
            expect(page.locator("#value-state")).to_have_text("暂无法估值")
            stale=deepcopy(data)
            for quote in stale["sources"]["prices"]["data"]["quotes"].values():quote["updated_at"]="2026-01-01T00:00:00Z"
            page=page_for(stale,failure=True)
            expect(page.locator("#total-usd")).to_have_text("$405.00")
            expect(page.locator("#value-state")).to_have_text("数据较旧")
            expect(page.locator("#price-status")).to_contain_text("更新失败")
            expect(page.locator("#price-status")).to_contain_text("报价已过期")
            page=page_for(unknown,prices={"pearl-2":raw["pearl-2"]})
            expect(page.locator("#total-usd")).to_have_text("$400.00")
            expect(page.locator("#value-state")).to_have_text("部分估值")
            updated=deepcopy(raw);updated["pearl-2"]["usd"]=3;updated["pearl-2"]["cny"]=21
            page=page_for(stale,prices=updated)
            expect(page.locator("#total-usd")).to_have_text("$605.00")
            expect(page.locator("#total-cny")).to_contain_text("4,235.00")
            assert not errors,errors
            browser.close()
            print("PASS: USD/CNY totals, exclude pool/history, unknown balances, missing prices, cached failure, stale quotes, live override, mobile")
    finally:
        server.shutdown()


if __name__=="__main__":main()
