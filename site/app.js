"use strict";
let snapshot = null;
let selectedCoin = "PRL";
let fetching = false;
let networkError = false;
let toastTimer;
let livePrices = {};
let priceFetching = false;
let priceFetchError = false;
let priceAttemptAt = 0;
const PRICE_URL = "https://api.coingecko.com/api/v3/simple/price?ids=pearl-2,nockchain&vs_currencies=usd,cny&include_24hr_change=true&include_last_updated_at=true";
const $ = id => document.getElementById(id);
const validNumber = n => typeof n === "number" && Number.isFinite(n);
const fmt = (n, places = 4) => validNumber(n) ? new Intl.NumberFormat("zh-CN", {minimumFractionDigits:places, maximumFractionDigits:places}).format(n) : "—";
const money = (n, currency="USD", digits=2) => validNumber(n) ? new Intl.NumberFormat("en-US", {style:"currency",currency,minimumFractionDigits:digits,maximumFractionDigits:digits}).format(n) : "—";
const escapeHTML = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const timeText = (value, short = false) => {
  if (!value || !Number.isFinite(Date.parse(value))) return "—";
  return new Intl.DateTimeFormat("zh-CN", {timeZone:"Asia/Shanghai", month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit", ...(short ? {} : {year:"numeric"}), hour12:false}).format(new Date(value));
};
function source(key) { return snapshot?.sources?.[key] || {state:"unavailable", data:null}; }
function outdated(key) {
  const s = source(key);
  const elapsed = (Date.now() - Date.parse(s.updated_at)) / 1000;
  return networkError || !Number.isFinite(elapsed) || elapsed > (snapshot?.config.stale_after_seconds || 900) || !["ok","empty"].includes(s.state);
}
function tag(key, emptyLabel="暂无记录") {
  const s=source(key);
  if (!s.data) return '<span class="tag bad">查询暂不可用</span>';
  if (outdated(key)) return '<span class="tag warn">上次成功数据</span>';
  if (s.state === "empty") return `<span class="tag warn">${emptyLabel}</span>`;
  return '<span class="tag">链上已核实</span>';
}
function balanceHTML(value, coin) {
  if (!validNumber(value)) return `<span>—</span><span class="currency">${coin}</span>`;
  const [integer, decimal]=fmt(value).split(".");
  return `${integer}<span class="fraction">.${decimal}</span><span class="currency">${coin}</span>`;
}
function showToast(message) {
  $("toast").textContent=message; $("toast").hidden=false;
  clearTimeout(toastTimer); toastTimer=setTimeout(()=>$("toast").hidden=true,3000);
}
function quote(coin) {
  const cached=source("prices").data?.quotes?.[coin], live=livePrices[coin];
  const q=live && (!cached || Date.parse(live.updated_at)>=Date.parse(cached.updated_at)) ? live : cached;
  if (!q || !validNumber(q.usd) || q.usd<=0 || !validNumber(q.cny) || q.cny<=0 || !Number.isFinite(Date.parse(q.updated_at))) return null;
  return {...q, stale:Date.now()-Date.parse(q.updated_at)>900000, cached:q!==live};
}
function coinValue(coin) {
  const balance=source(coin.toLowerCase()+"_chain").data?.balance, price=quote(coin);
  if (!validNumber(balance) || balance<0 || !price) return null;
  return {usd:balance*price.usd,cny:balance*price.cny,stale:outdated(coin.toLowerCase()+"_chain")||price.stale};
}
function renderValuation() {
  const coins=["PRL","NOCK"], values=coins.map(coinValue), known=values.filter(Boolean);
  const missing=coins.filter((_,i)=>!values[i]);
  $("total-usd").textContent=known.length ? money(known.reduce((sum,v)=>sum+v.usd,0)) : "—";
  $("total-cny").textContent=known.length ? "约 "+money(known.reduce((sum,v)=>sum+v.cny,0),"CNY")+" CNY" : "余额或行情暂不可用";
  const stale=known.some(v=>v.stale), cached=coins.some(c=>quote(c)?.cached);
  $("value-state").textContent=!known.length?"暂无法估值":missing.length?"部分估值":stale?"数据较旧":"当前余额估值";
  $("value-state").className="tag"+(!known.length||missing.length||stale?" warn":"");
  $("value-note").textContent="仅计算钱包当前余额，矿池待付款与待成熟收益不计入。"+(missing.length?`${missing.join("、")} 余额或报价未核实，未计入合计。`:"")+(stale?" 部分余额或报价较旧，估值仅供参考。":"");
  const times=coins.map(c=>quote(c)?.updated_at).filter(Boolean).sort();
  $("price-status").textContent=times.length?`报价 ${timeText(times[0],true)} · 每 60 秒尝试更新${priceFetchError?" · 更新失败，使用已缓存报价":cached?" · 当前使用快照报价":""}${coins.some(c=>quote(c)?.stale)?" · 报价已过期":""}`:priceFetchError?"行情暂不可用，等待下次更新。":"正在获取最新行情…";
}
function priceHTML(coin) {
  const q=quote(coin), value=coinValue(coin);
  const change=validNumber(q?.change_24h)?`${q.change_24h>0?"+":""}${fmt(q.change_24h,2)}%`:"—";
  const changeClass=!validNumber(q?.change_24h)?"":q.change_24h>=0?"positive":"negative";
  return `<div class="market-line"><span>最新价格</span><strong data-price="${coin}">${money(q?.usd,"USD",coin==="NOCK"?6:4)}</strong><span class="price-change ${changeClass}">${change} <small>24h</small></span></div><div class="market-detail"><span>${q?money(q.cny,"CNY",coin==="NOCK"?4:2)+" CNY":"报价待更新"}</span><span>${q?timeText(q.updated_at,true)+(q.stale?" · 已过期":priceFetchError?" · 缓存":""):"CoinGecko"}</span></div>
    <div class="coin-valuation"><span>钱包估值${value?.stale?"（数据较旧）":""}</span><div><strong data-wallet-value="${coin}">${money(value?.usd)}</strong><small>${value?"约 "+money(value.cny,"CNY")+" CNY":"余额或报价未知"}</small></div></div>`;
}
async function refreshPrices() {
  if (priceFetching || Date.now()-priceAttemptAt<15000) return;
  priceFetching=true;priceAttemptAt=Date.now();
  const controller=new AbortController(), timer=setTimeout(()=>controller.abort(),12000);
  try {
    const response=await fetch(PRICE_URL,{signal:controller.signal});
    if(!response.ok) throw new Error("Price unavailable");
    const body=await response.json();
    const next={};
    for(const [coin,id] of [["PRL","pearl-2"],["NOCK","nockchain"]]) {
      const r=body[id];
      if(!r || !validNumber(r.usd)||r.usd<=0||!validNumber(r.cny)||r.cny<=0||!validNumber(r.last_updated_at)||r.last_updated_at<=0||r.last_updated_at*1000>Date.now()+300000) continue;
      next[coin]={usd:r.usd,cny:r.cny,change_24h:validNumber(r.usd_24h_change)?r.usd_24h_change:null,updated_at:new Date(r.last_updated_at*1000).toISOString()};
    }
    if(!Object.keys(next).length) throw new Error("Invalid price data");
    // A partial response must not erase a previously valid quote for the other coin.
    livePrices={...livePrices,...next};priceFetchError=Object.keys(next).length<2;
  } catch {priceFetchError=true;}
  finally {clearTimeout(timer);priceFetching=false;if(snapshot){renderValuation();$("balances").innerHTML=renderCoin("PRL")+renderCoin("NOCK");}else renderValuation();}
}
function renderCoin(coin) {
  const key=coin.toLowerCase(), chain=source(key+"_chain"), pool=source(key+"_pool"), data=chain.data, p=pool.data;
  const config=snapshot.config, minimum=config[key+"_min_payout"];
  const progress=validNumber(p?.balance) ? Math.max(0,Math.min(100,p.balance/minimum*100)) : 0;
  const missing=validNumber(p?.balance) ? Math.max(0,minimum-p.balance) : null;
  const explorer=key==="prl" ? `https://www.prlscan.com/address/${config.prl_address}` : `https://nockscan.com/address/${config.nock_address}`;
  const empty=data?.address_not_found;
  const message=empty ? "浏览器暂无该地址记录，尚未查到链上到账。" : !data ? "暂时无法核实钱包余额，请稍后刷新。" : outdated(key+"_chain") ? "查询暂不可用或数据较旧，下方保留上次结果。" : "当前地址余额，已扣除历史转出。";
  let payoutText=missing===null ? "矿池查询暂不可用，付款进度未知。" : missing>0 ? `距最低付款额还差 ${fmt(missing)} ${coin}。` : "已达到最低付款额，等待矿池付款处理。";
  if (coin==="NOCK") payoutText+=` 每 ${config.nock_payout_interval_hours} 小时处理一次。`;
  return `<article class="coin-panel" aria-label="${coin} 钱包与矿池"><div class="coin-top"><div class="coin-title"><span class="coin-symbol ${key}" aria-hidden="true">${coin==="PRL"?"p":"n"}</span><h2>${coin}<small>${coin==="PRL"?"Pearl":"Nockchain"}</small></h2></div>${tag(key+"_chain")}</div>
    <p class="balance-label">钱包余额</p><div class="balance-number">${balanceHTML(data?.balance,coin)}</div><p class="wallet-message">${message}</p>
    ${priceHTML(coin)}
    <div class="stat-line"><span>累计转入钱包</span><strong>${fmt(data?.received_total)} <small>${coin}</small></strong></div>
    <div class="stat-line"><span>矿池累计付款</span><strong>${fmt(p?.paid_total)} <small>${coin}</small></strong></div>
    <div class="pool-section"><div class="pool-title">仍在矿池的收益<small>${outdated(key+"_pool") ? "数据待更新" : "尚未进入钱包"}</small></div>
      <div class="stat-line"><span>待付款余额</span><strong>${fmt(p?.balance)} ${coin}</strong></div><div class="stat-line"><span>待成熟收益</span><strong>${fmt(p?.pending)} ${coin}</strong></div>
      <div class="progress-label"><span>最低付款额 ${fmt(minimum,0)} ${coin}</span><span>${p ? fmt(progress,1)+"%" : "—"}</span></div><progress max="100" value="${progress}" aria-label="${coin} 最低付款进度"></progress><p class="payout-note">${payoutText}</p></div>
    <div class="coin-foot"><a href="${explorer}" target="_blank" rel="noopener noreferrer">区块浏览器核对 ↗</a><time>钱包核验 ${timeText(chain.updated_at,true)}</time></div></article>`;
}
function renderMining() {
  const pool=source("prl_pool").data;
  let state="状态未知", style="warn";
  if (pool && !outdated("prl_pool")) {
    if (!pool.workers.length) {state="矿工离线";style="bad";}
    else if (pool.hashrate>0) {state="正在挖矿";style="ok";}
    else {state="已连接 · 等待算力";style="warn";}
  } else if (pool) state="数据较旧 · 待确认";
  $("mining-status").textContent=state;
  $("status-dot").className="status-dot "+style;
  $("hashrate").textContent=pool ? fmt(pool.hashrate/1e12,2)+" TH/s" : "—";
  $("worker-count").textContent=pool ? `${pool.workers.length} 台${outdated("prl_pool")?"（上次）":""}` : "—";
  $("binding").textContent=!pool ? "未能核实" : pool.nock_payout_address===snapshot.config.nock_address ? (outdated("prl_pool")?"上次核实已绑定":"已绑定 · 地址一致") : pool.nock_payout_address ? "地址不一致，请核对" : "尚未绑定";
  const workers=pool?.workers || [];
  $("workers-content").innerHTML=!pool ? '<p class="empty">矿池查询暂不可用，无法判断矿工是否在线。</p>' : !workers.length ? '<p class="empty"><strong>矿池当前没有在线矿工</strong>请检查矿机服务或连接；这里会在下次更新后重新显示。</p>' : workers.map(w=>{
    const rate=w.gpus.reduce((sum,g)=>sum+g.hashrate,0);
    return `<div class="worker-row"><div class="worker-name">${escapeHTML(w.name)}<small>${escapeHTML(w.version.replaceAll("_"," "))}</small></div><div class="gpu">${w.gpus.map(g=>escapeHTML(g.name)).join(" / ")||"等待显卡信息"}<small>矿池报告 · ${timeText(source("prl_pool").updated_at,true)}</small></div><span class="online">${outdated("prl_pool")?"上次连接记录":"● 已连接"}</span><div class="speed">${fmt(rate/1e12,2)}<small>TH/s</small></div></div>`;
  }).join("");
}
function renderHistory() {
  if (!snapshot) return;
  const key=selectedCoin==="PRL"?"prl_txs":"nock_chain", s=source(key);
  const rows=s.data?.transactions || [];
  $("history-note").textContent=`${selectedCoin==="PRL"?"最近 50 笔交易中的已确认转入，已排除转出与找零。":"最近链上转入记录。"} 时间为北京时间。${outdated(key)?" 当前数据待更新。":""}`;
  if (!s.data) {$("history-content").innerHTML='<p class="empty">到账记录暂时查询失败，请稍后刷新。不会把查询失败当成零到账。</p>';return;}
  if (!rows.length) {$("history-content").innerHTML=`<div class="empty"><strong>${s.data.address_not_found?"浏览器尚未查到这个 NOCK 地址":"当前查询范围内没有转入记录"}</strong>${selectedCoin==="NOCK"?`矿池收益见上方。需累计到 ${fmt(snapshot.config.nock_min_payout,0)} NOCK，并等待付款后才会出现在钱包。`:"钱包累计转入和余额见上方。"}</div>`;return;}
  $("history-content").innerHTML=`<div class="table-wrap"><table><thead><tr><th>到账时间 / 北京</th><th>到账数量</th><th>类型</th><th>链上记录</th></tr></thead><tbody>${rows.slice(0,8).map(r=>{
    const url=r.url||`https://nockscan.com/address/${snapshot.config.nock_address}`;
    // The collector generates links from fixed explorer hosts.
    const safe=/^https:\/\/(www\.prlscan\.com|nockscan\.com)\//.test(url) ? url : "#";
    return `<tr><td>${timeText(r.time,true)}</td><td class="amount">+${fmt(r.amount)}<small>${selectedCoin}</small></td><td>${escapeHTML(r.label)}</td><td><a class="tx-link" href="${escapeHTML(safe)}" target="_blank" rel="noopener noreferrer" aria-label="查看 ${escapeHTML(r.txid)} 链上记录">${escapeHTML(r.txid.slice(0,7))}… ↗</a></td></tr>`;
  }).join("")}</tbody></table></div>`;
}
function renderDetails() {
  const c=snapshot.config;
  $("addresses").innerHTML=["PRL","NOCK"].map(coin=>`<div class="address-row"><b>${coin}</b><code>${escapeHTML(c[coin.toLowerCase()+"_address"])}</code><button class="copy" type="button" data-copy="${coin}" aria-label="复制 ${coin} 收款地址">复制地址</button></div>`).join("");
  document.querySelectorAll("[data-copy]").forEach(button=>button.addEventListener("click",async()=>{
    const address=c[button.dataset.copy.toLowerCase()+"_address"];
    try {await navigator.clipboard.writeText(address);showToast(`${button.dataset.copy} 地址已复制`);} catch {showToast("复制未成功，请长按或选中上面的完整地址复制。");}
  }));
  $("rules-note").textContent=`付款规则核实于 ${c.payout_rules_verified_at}，后续以矿池规则为准。此页面不会执行转账或修改收款地址。`;
  const names={prl_pool:"PRL 矿池",nock_pool:"NOCK 矿池",prl_chain:"PRL 钱包",prl_txs:"PRL 到账",nock_chain:"NOCK 钱包"};
  $("source-health").innerHTML=Object.entries(names).map(([k,name])=>`<span class="${outdated(k)?"warn":""}">${name} · ${source(k).state==="empty"?"暂无地址记录":outdated(k)?"待更新":"正常"} · ${timeText(source(k).updated_at,true)}</span>`).join("");
}
function renderFreshness() {
  if (!snapshot) return;
  $("updated").textContent=`快照 ${timeText(snapshot.generated_at,true)} · 北京时间`;
  const problems=Object.keys(snapshot.sources).filter(k=>k!=="prices" && outdated(k));
  const p=source("prl_pool").data;
  let text=networkError?"暂时无法读取新快照，下面保留上次数据，当前矿工状态需要重新确认。":problems.length?"部分数据查询失败或已超过 15 分钟，已标注上次成功数据；当前余额与矿工状态可能有变化。":"";
  if (p && p.nock_payout_address!==snapshot.config.nock_address) text+=(text?" ":"")+"矿池的 NOCK 收款地址未绑定或与本页地址不一致，请核对。";
  $("notice").hidden=!text;$("notice").textContent=text;
}
function render() {
  renderFreshness(); renderMining(); renderValuation();
  $("balances").innerHTML=renderCoin("PRL")+renderCoin("NOCK");
  renderHistory(); renderDetails();
}
async function refresh(manual=false) {
  if (fetching) return;
  fetching=true;$("refresh").disabled=true;
  const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),15000);
  try {
    const response=await fetch(`data/status.json?t=${Date.now()}`,{cache:"no-store",signal:controller.signal});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const next=await response.json();
    if (next.schema_version!==1 || !next.sources || !next.config) throw new Error("Invalid snapshot");
    const changed=next.generated_at!==snapshot?.generated_at;
    snapshot=next;networkError=false;render();
    if (manual) showToast(changed?"已读取最新快照":"已经是最新快照，等待下一次定时采集。");
  } catch {
    networkError=true;
    if (snapshot) render();
    else {$("notice").hidden=false;$("notice").textContent="暂时无法加载数据，请稍后点刷新重试。";$("updated").textContent="读取失败";$("mining-status").textContent="状态未知";$("binding").textContent="未能核实";$("history-content").innerHTML='<p class="empty">到账记录暂时无法加载。</p>';$("workers-content").innerHTML='<p class="empty">矿工状态暂时无法加载。</p>';}
    if (manual) showToast("读取失败，请稍后重试。");
  } finally {clearTimeout(timer);fetching=false;$("refresh").disabled=false;}
}
$("refresh").addEventListener("click",()=>{refresh(true);refreshPrices();});
document.querySelectorAll("[data-coin]").forEach(button=>button.addEventListener("click",()=>{
  selectedCoin=button.dataset.coin;
  document.querySelectorAll("[data-coin]").forEach(b=>{b.classList.toggle("active",b===button);b.setAttribute("aria-pressed",String(b===button));});renderHistory();
}));
refresh();refreshPrices();setInterval(()=>{if (!document.hidden) {refresh();refreshPrices();}},60000);
setInterval(()=>{if (snapshot && !document.hidden) {renderFreshness();renderMining();renderValuation();}},15000);
document.addEventListener("visibilitychange",()=>{if(!document.hidden){refresh();refreshPrices();}});
