const ACTIONABLE_STAGES = new Set([
  "traded",
  "order_live",
  "risk_blocked",
  "cycle_limit_skip",
  "already_traded_skip",
  "active_order_skip",
  "balance_skip",
  "order_rejected",
  "tightened_skip"
]);

const STAGE_LABELS = {
  traded: "TRADED",
  order_live: "LIVE ORDER",
  risk_blocked: "RISK BLOCK",
  cycle_limit_skip: "CYCLE LIMIT",
  shadow_only: "SHADOW",
  tightened_skip: "15M TIGHT",
  already_traded_skip: "DONE",
  active_order_skip: "ORDER LIVE",
  balance_skip: "NO CASH",
  order_rejected: "REJECTED",
  analysis_skip: "SKIP",
  analysis_ready: "READY"
};

const FILTERS = {
  actionable: true,
  marketType: "all",
  direction: "all"
};

const API_URL = location.protocol.startsWith("http")
  ? "/api/monitor"
  : "http://127.0.0.1:8765/api/monitor";

const CHART_SYMBOLS = {
  btc: { symbol: "BINANCE:BTCUSDT", label: "BTCUSDT", venue: "Binance" },
  eth: { symbol: "BINANCE:ETHUSDT", label: "ETHUSDT", venue: "Binance" },
  sol: { symbol: "BINANCE:SOLUSDT", label: "SOLUSDT", venue: "Binance" },
  doge: { symbol: "BINANCE:DOGEUSDT", label: "DOGEUSDT", venue: "Binance" },
  xrp: { symbol: "BINANCE:XRPUSDT", label: "XRPUSDT", venue: "Binance" },
  bnb: { symbol: "BINANCE:BNBUSDT", label: "BNBUSDT", venue: "Binance" },
  hype: { symbol: "BYBIT:HYPEUSDT", label: "HYPEUSDT", venue: "Bybit" }
};

const nodes = {
  feedStatus: document.getElementById("feedStatus"),
  modeValue: document.getElementById("modeValue"),
  tickValue: document.getElementById("tickValue"),
  mode15mValue: document.getElementById("mode15mValue"),
  updatedValue: document.getElementById("updatedValue"),
  balanceValue: document.getElementById("balanceValue"),
  availableValue: document.getElementById("availableValue"),
  equityValue: document.getElementById("equityValue"),
  winRateValue: document.getElementById("winRateValue"),
  riskValue: document.getElementById("riskValue"),
  activityLog: document.getElementById("activityLog"),
  signalList: document.getElementById("signalList"),
  recentTrades: document.getElementById("recentTrades"),
  filterButtons: Array.from(document.querySelectorAll(".filter-btn")),
  symbolButtons: Array.from(document.querySelectorAll(".symbol-btn")),
  liveClock: document.getElementById("liveClock"),
  timeframeBtn5m: document.getElementById("timeframeBtn5m"),
  timeframeBtn15m: document.getElementById("timeframeBtn15m"),
  stageChart: document.getElementById("stageChart"),
  stageChartLabel: document.getElementById("stageChartLabel"),
  stageChartVenue: document.getElementById("stageChartVenue")
};

let fetchTimer = null;
let currentTimeframe = "5";
let currentChartSymbol = "btc";
let chartPinned = false;
let clockTimer = null;
let lastSnapshotText = null;

function fmtMoney(value) {
  if (value == null || Number.isNaN(Number(value))) return "--";
  return Number(value).toLocaleString(undefined, {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  });
}

function fmtPct(value) {
  if (value == null || Number.isNaN(Number(value))) return "--";
  return `${(Number(value) * 100).toFixed(1)}%`;
}

function fmtPrice(value) {
  if (value == null || Number.isNaN(Number(value))) return "--";
  return Number(value).toFixed(3);
}

function fmtTime(value) {
  if (!value) return "--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "--";
  return date.toLocaleTimeString([], { hour12: false });
}

function stageLabel(stage) {
  return STAGE_LABELS[stage] || stage.replaceAll("_", " ").toUpperCase();
}

function stageClass(stage) {
  return `stage-${String(stage || "").replace(/[^a-z0-9_-]/gi, "")}`;
}

function setFeedStatus(kind, text) {
  nodes.feedStatus.className = `chip ${kind}`;
  nodes.feedStatus.textContent = text;
}

function buildChartUrl(symbol, timeframe) {
  return `https://s.tradingview.com/widgetembed/?symbol=${symbol}&interval=${timeframe}&theme=dark&hide_top_toolbar=1&hide_legend=1&hide_side_toolbar=1&save_image=0&withdateranges=0`;
}

function resolveChartKey(...values) {
  const combined = values
    .filter(Boolean)
    .map((value) => String(value).toUpperCase())
    .join(" ");

  if (!combined) return null;
  if (combined.includes("DOGE")) return "doge";
  if (combined.includes("HYPE")) return "hype";
  if (combined.includes("BTC")) return "btc";
  if (combined.includes("ETH")) return "eth";
  if (combined.includes("SOL")) return "sol";
  if (combined.includes("XRP")) return "xrp";
  if (combined.includes("BNB")) return "bnb";
  return null;
}

function updateStageChart() {
  const chart = CHART_SYMBOLS[currentChartSymbol] || CHART_SYMBOLS.btc;
  const nextUrl = buildChartUrl(chart.symbol, currentTimeframe);
  if (nodes.stageChart.src !== nextUrl) {
    nodes.stageChart.src = nextUrl;
  }
  nodes.stageChart.title = `${chart.label} chart`;
  nodes.stageChartLabel.textContent = `${chart.label} ${currentTimeframe}m`;
  nodes.stageChartVenue.textContent = `${chart.venue} reference context`;

  nodes.timeframeBtn5m.classList.toggle("active", currentTimeframe === "5");
  nodes.timeframeBtn15m.classList.toggle("active", currentTimeframe === "15");
  nodes.timeframeBtn5m.setAttribute("aria-pressed", String(currentTimeframe === "5"));
  nodes.timeframeBtn15m.setAttribute("aria-pressed", String(currentTimeframe === "15"));

  nodes.symbolButtons.forEach((button) => {
    const isActive = button.dataset.symbol === currentChartSymbol;
    button.classList.toggle("active", isActive);
    button.setAttribute("aria-pressed", String(isActive));
  });
}

function setChartSymbol(symbolKey, pinned = true) {
  if (!CHART_SYMBOLS[symbolKey]) return;
  currentChartSymbol = symbolKey;
  if (pinned) {
    chartPinned = true;
  }
  updateStageChart();
}

function filteredSignals(signalBoard = []) {
  return signalBoard.filter((row) => {
    if (FILTERS.actionable && !ACTIONABLE_STAGES.has(row.decision_stage)) {
      return false;
    }
    if (FILTERS.marketType !== "all" && row.market_type !== FILTERS.marketType) {
      return false;
    }
    if (FILTERS.direction !== "all" && row.direction !== FILTERS.direction) {
      return false;
    }
    return true;
  });
}

function suggestChartSymbol(snapshot) {
  const signal = filteredSignals(snapshot.signal_board || []).find((row) =>
    resolveChartKey(row.coin, row.market_slug, row.question)
  );
  if (signal) {
    return resolveChartKey(signal.coin, signal.market_slug, signal.question);
  }

  const trade = (snapshot.recent_trades || []).find((row) =>
    resolveChartKey(row.coin, row.market_slug, row.question)
  );
  if (trade) {
    return resolveChartKey(trade.coin, trade.market_slug, trade.question);
  }

  return null;
}

function renderHeader(snapshot) {
  nodes.modeValue.textContent = String(snapshot.trading_mode || "--").toUpperCase();
  nodes.tickValue.textContent = String(snapshot.tick_count || 0);
  nodes.mode15mValue.textContent = snapshot.mode_15m?.tightened
    ? "tightened"
    : (snapshot.mode_15m?.enabled ? "enabled" : "disabled");
  nodes.updatedValue.textContent = fmtTime(snapshot.monitor_updated_at || snapshot.generated_at);
  nodes.balanceValue.textContent = fmtMoney(snapshot.balance);
  nodes.availableValue.textContent = fmtMoney(snapshot.available_balance);
  nodes.equityValue.textContent = fmtMoney(snapshot.account_equity);
  nodes.winRateValue.textContent = fmtPct(snapshot.win_rate);
  nodes.riskValue.textContent = `${fmtMoney(snapshot.reserved_open_exposure)} / ${snapshot.open_orders_count || 0}`;
}

function renderSignalBoard(signalBoard = []) {
  const rows = filteredSignals(signalBoard);
  nodes.signalList.innerHTML = "";

  if (!rows.length) {
    nodes.signalList.innerHTML = `<div class="empty">No signals match the current filters yet.</div>`;
    return;
  }

  rows.forEach((row) => {
    const card = document.createElement("article");
    const directionClass = row.direction === "BUY" ? "buy" : "sell";
    const stage = row.decision_stage || "analysis_skip";
    const chartKey = resolveChartKey(row.coin, row.market_slug, row.question);
    card.className = `signal-card${chartKey ? " interactive" : ""}`;
    card.innerHTML = `
      <div class="signal-top">
        <div class="coin-line">
          <div class="coin">${row.coin || "--"}</div>
          <div class="badge">${row.market_type || "--"}</div>
          ${row.direction ? `<div class="badge ${directionClass}">${row.direction}</div>` : ""}
          ${row.signal_side ? `<div class="badge">${row.signal_side}</div>` : ""}
        </div>
        <div class="badge ${stageClass(stage)}">${stageLabel(stage)}</div>
      </div>
      <div class="signal-question">${row.question || row.market_slug || "Unknown market"}</div>
      <div class="metric-row">
        <div class="metric">
          <div class="k">Time Left</div>
          <div class="v">${Math.max(0, Math.round(Number(row.seconds_to_close || 0)))}s</div>
        </div>
        <div class="metric">
          <div class="k">Confidence</div>
          <div class="v">${fmtPct(row.confidence)}</div>
        </div>
        <div class="metric">
          <div class="k">Entry</div>
          <div class="v">${fmtPrice(row.entry_price)}</div>
        </div>
        <div class="metric">
          <div class="k">Momentum</div>
          <div class="v">${row.momentum == null ? "--" : fmtPct(row.momentum)}</div>
        </div>
      </div>
      <div class="signal-prices">
        <div class="signal-reason">UP ${fmtPrice(row.up_price)} / DOWN ${fmtPrice(row.down_price)} | Edge ${fmtPct(row.raw_edge)} | Fee ${fmtPct(row.estimated_fee)} | Effective ${fmtPct(row.effective_edge)}</div>
        <div class="signal-reason">Price state: ${String(row.price_state || "--").toUpperCase()}</div>
      </div>
      <div class="signal-reason">${row.reason || "--"}</div>
    `;

    if (chartKey) {
      card.addEventListener("click", () => setChartSymbol(chartKey));
    }
    nodes.signalList.appendChild(card);
  });
}

function renderRecentTrades(trades = []) {
  nodes.recentTrades.innerHTML = "";
  if (!trades.length) {
    nodes.recentTrades.innerHTML = `<div class="empty">No trades yet. A fresh sim reset will look empty until the next fills land.</div>`;
    return;
  }

  trades.forEach((trade) => {
    const pnlClass = trade.pnl == null ? "pending" : (trade.pnl >= 0 ? "pos" : "neg");
    const pnlText = trade.pnl == null ? "Pending settlement" : `PnL ${fmtMoney(trade.pnl)}`;
    const chartKey = resolveChartKey(trade.coin, trade.market_slug, trade.question, trade.reason);
    const card = document.createElement("article");
    card.className = `trade-card${chartKey ? " interactive" : ""}`;
    card.innerHTML = `
      <div class="trade-top">
        <div class="trade-title">${trade.question || trade.market_slug || "Unknown market"}</div>
        <div class="badge">${trade.market_type || "--"}</div>
      </div>
      <div class="trade-meta">${fmtTime(trade.timestamp)} | ${trade.side || "--"} | ${(trade.status || "pending").toUpperCase()}</div>
      <div class="trade-size">Size ${fmtMoney(trade.size)}</div>
      <div class="pnl-pill ${pnlClass}">${pnlText}</div>
      <div class="trade-meta">${trade.reason || ""}</div>
    `;

    if (chartKey) {
      card.addEventListener("click", () => setChartSymbol(chartKey));
    }
    nodes.recentTrades.appendChild(card);
  });
}

function renderActivity(lines = []) {
  nodes.activityLog.innerHTML = "";
  if (!lines.length) {
    nodes.activityLog.innerHTML = `<div class="empty">Waiting for activity.</div>`;
    return;
  }

  lines.slice().reverse().forEach((line) => {
    const div = document.createElement("div");
    div.className = "activity-line";
    div.textContent = line;
    nodes.activityLog.appendChild(div);
  });
}

function renderSnapshot(snapshot) {
  renderHeader(snapshot);
  renderSignalBoard(snapshot.signal_board || []);
  renderRecentTrades(snapshot.recent_trades || []);
  renderActivity(snapshot.recent_activity || []);

  if (!chartPinned) {
    const suggestedChart = suggestChartSymbol(snapshot);
    if (suggestedChart && suggestedChart !== currentChartSymbol) {
      setChartSymbol(suggestedChart, false);
    }
  }
}

async function poll() {
  try {
    const response = await fetch(API_URL, { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const snapshotText = await response.text();
    if (snapshotText === lastSnapshotText) {
      setFeedStatus("live", "LIVE");
      return;
    }
    lastSnapshotText = snapshotText;
    const snapshot = JSON.parse(snapshotText);
    renderSnapshot(snapshot);
    setFeedStatus("live", `${String(snapshot.status || "online").toUpperCase()}`);
  } catch (error) {
    setFeedStatus("error", `Offline: ${error.message}`);
  } finally {
    fetchTimer = window.setTimeout(poll, 2000);
  }
}

function updateLiveClock() {
  const now = new Date();
  const hours = String(now.getHours()).padStart(2, "0");
  const minutes = String(now.getMinutes()).padStart(2, "0");
  const seconds = String(now.getSeconds()).padStart(2, "0");
  const current = `${hours}:${minutes}:${seconds}`;
  nodes.liveClock.textContent = current;
}

function startClock() {
  updateLiveClock();
  if (clockTimer) clearInterval(clockTimer);
  clockTimer = setInterval(updateLiveClock, 1000);
}

function updateChartTimeframe(timeframe) {
  currentTimeframe = timeframe;
  updateStageChart();
}

function pollImmediately() {
  if (fetchTimer) {
    window.clearTimeout(fetchTimer);
    fetchTimer = null;
  }
  poll();
}

nodes.timeframeBtn5m.addEventListener("click", () => updateChartTimeframe("5"));
nodes.timeframeBtn15m.addEventListener("click", () => updateChartTimeframe("15"));

nodes.symbolButtons.forEach((button) => {
  button.addEventListener("click", () => {
    setChartSymbol(button.dataset.symbol);
  });
});

nodes.filterButtons.forEach((button) => {
  button.addEventListener("click", () => {
    const group = button.dataset.filter;
    const value = button.dataset.value;
    FILTERS[group] = value === "true" ? true : (value === "false" ? false : value);
    nodes.filterButtons.forEach((candidate) => {
      if (candidate.dataset.filter === group) {
        candidate.classList.toggle("active", candidate.dataset.value === value);
      }
    });
    pollImmediately();
  });
});

updateStageChart();
startClock();
poll();
