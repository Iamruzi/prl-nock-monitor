# PRL / NOCK 个人监控页

免费、只读的个人挖矿账本。GitHub Pages 托管静态网页，GitHub Actions 标准公共 runner 定时查询公开接口；不需要 SSH 凭据、矿机公网端口、钱包私钥或付费 API。

在线地址：<https://iamruzi.github.io/prl-nock-monitor/>

## 内容与口径

- 钱包余额与累计转入：PRL 来自 prlscan，NOCK 来自 nockscan；PRL 使用 external_received_grains 排除找零。
- 矿池累计付款、待付款余额和待成熟收益：分别读取 Pearlhash PRL 与 NOCK 账本。矿池付款不作为链上到账证明。
- 最近到账记录：最近 50 笔地址交易内的已确认转入。PRL 排除发送方为自己的找零交易；本页最多展示 8 笔。
- 挖矿状态：依据矿池连接与显卡算力，不直接检测 systemd、GPU 温度或服务器。
- 价格：CoinGecko 的 `pearl-2` / `nockchain`，美元、人民币与 24 小时涨跌幅。页面打开时每 60 秒尝试直连刷新，云端快照也保留行情；失败会标记并使用缓存，报价时间取行情源的 last_updated_at。
- 钱包总价值：当前钱包余额乘报价，分别汇总 USD 与 CNY。累计历史到账、矿池待付款与待成熟不计入；未知币种余额或报价不能当成零，显示已知部分及「部分估值」。这不是按历史成交价统计的已实现收入。
- 公共快照只保留金额、地址、交易、矿工名、版本、GPU 型号和算力；不保留 IP、worker ID 或原始 API 数据。
- Nockscan 明确返回 Address not found 时显示「暂无地址记录」和未知余额，不伪装成已核实的零余额。

## 更新与异常

每 5 分钟尝试采集并发布；GitHub 调度可能延迟或丢弃高负载时段任务，不保证分钟级实时性。页面每 60 秒读取快照，显示北京时间。超过 15 分钟或上游查询失败会显示过期提示。失败时可保留上一份已发布数据和原更新时间。

公开仓库连续 60 天无活动可能停用 schedule。工作流每月自动提交 `.schedule-heartbeat` 保持活动（此路径不会额外触发发布）。若自动化停用或 GitHub 访问受限，页面会显示数据过期；可从 Actions → Update mining dashboard → Run workflow 手动恢复。

付款规则保存在 config.json，核实日期为 2026-09-28：PRL 最低 1，NOCK 最低 350，NOCK 每 6 小时付款。规则后续可能变化，需要按矿池公告更新。

## 本地运行与升级

运行依赖完整列于 requirements.lock：生产 Python 3.12、标准库，无 pip/npm/CDN 依赖。开发支持 Python 3.10+。

```sh
python scripts/preflight.py
python -m unittest discover -s tests -v
python scripts/collect.py
python -m http.server 19101 --bind 127.0.0.1 --directory site
```

访问 http://127.0.0.1:19101/ 。不要用 file:// 直接打开 HTML。

修改 config.json、site/ 或 scripts/ 后运行上述检查，推送 main，Actions 会自动发布。GitHub Pages 的 build_type 应为 workflow。首次部署可手动触发工作流。所有外部 Actions 均锁定到提交 SHA，升级时先核对官方仓库再更新 SHA 并复测。

本地视觉验证使用环境中已有的 Playwright 和 Chrome，不属于网页或采集程序的运行依赖。

## 来源

- Pearlhash：<https://pearlhash.xyz/>，`/api/account/{PRL}`、`/api/nock-balance/{PRL}`。
- prlscan：<https://www.prlscan.com/>，其网页使用的 `https://api.prlscan.com/v1/addresses/{PRL}` 和 `/txs`。
- nockscan API 文档：<https://nockscan.com/api>，金额单位为 nicks，65,536 nicks = 1 NOCK。
- CoinGecko 行情接口：<https://docs.coingecko.com/reference/simple-price>。匿名公开 API 可能限流；前端仅请求价格，不向行情服务发送钱包地址。
- GitHub Pages 免费公共仓库与限制：<https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits>。
