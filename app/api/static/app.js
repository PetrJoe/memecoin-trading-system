"use strict";

/* Meme Trader dashboard — vanilla AJAX client, no dependencies.
   All server data is rendered via textContent (no innerHTML) to avoid XSS. */

const state = {
  csrf: null,
  pollTimer: null,
  sinceTs: 0,
  emergencyArmed: false,
};

const $ = (id) => document.getElementById(id);

/* ------------------------------------------------------------------ utils */
function fmtUsd(v, digits = 2) {
  if (v === null || v === undefined) return "—";
  const sign = v < 0 ? "-" : "";
  return sign + "$" + Math.abs(v).toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}
function fmtPct(v) {
  if (v === null || v === undefined) return "—";
  return (v > 0 ? "+" : "") + v.toFixed(2) + "%";
}
function pnlClass(v) { return v > 0 ? "pos" : v < 0 ? "neg" : "muted"; }
function fmtTime(ts) { return new Date(ts * 1000).toLocaleTimeString(); }
function fmtUptime(s) {
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

async function api(path, opts = {}) {
  const headers = { "Content-Type": "application/json" };
  if (state.csrf) headers["X-CSRF-Token"] = state.csrf;
  const res = await fetch(path, { ...opts, headers, credentials: "same-origin" });
  let data = {};
  try { data = await res.json(); } catch { /* empty body */ }
  if (res.status === 401 && !path.startsWith("/api/login") && !path.startsWith("/api/logout")) {
    showLogin("Session expired. Please sign in again.");
    throw new Error("unauthenticated");
  }
  if (!res.ok) {
    const err = new Error(data.detail || data.message || res.statusText);
    err.status = res.status;
    err.data = data;
    throw err;
  }
  return data;
}

/* ------------------------------------------------------------------ login */
function showLogin(message) {
  $("dashboard").hidden = true;
  $("login-overlay").style.display = "flex";
  const errBox = $("login-error");
  if (message) { errBox.textContent = message; errBox.hidden = false; } else { errBox.hidden = true; }
  state.csrf = null;
  if (state.pollTimer) { clearInterval(state.pollTimer); state.pollTimer = null; }
}

async function tryBootstrap() {
  try {
    const res = await fetch("/api/status", { credentials: "same-origin" });
    if (res.ok) {
      $("login-overlay").style.display = "none";
      $("dashboard").hidden = false;
      await refresh();
      startPolling();
    }
  } catch { /* not logged in yet */ }
}

async function login(event) {
  event.preventDefault();
  const btn = $("login-btn");
  btn.disabled = true;
  $("login-error").hidden = true;
  try {
    const res = await fetch("/api/login", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username: $("login-username").value,
        password: $("login-password").value,
      }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || !data.ok) {
      let msg = data.message || data.detail || "Login failed";
      if (data.retry_after) msg += ` (retry in ${data.retry_after}s)`;
      $("login-error").textContent = msg;
      $("login-error").hidden = false;
      return;
    }
    state.csrf = data.csrf_token;
    $("login-overlay").style.display = "none";
    $("dashboard").hidden = false;
    $("login-password").value = "";
    state.sinceTs = 0;
    await refresh();
    startPolling();
  } catch (e) {
    $("login-error").textContent = e.message || "Network error";
    $("login-error").hidden = false;
  } finally {
    btn.disabled = false;
  }
}

async function logout() {
  try { await api("/api/logout", { method: "POST" }); } catch { /* ignore */ }
  showLogin();
  $("login-username").value = "";
  $("login-password").value = "";
}

/* ---------------------------------------------------------------- polling */
function startPolling() {
  if (state.pollTimer) clearInterval(state.pollTimer);
  state.pollTimer = setInterval(refresh, 5000);
}

async function refresh() {
  try {
    const status = await api("/api/status");
    const trades = await api("/api/events", { since: state.sinceTs, limit: 200 });
    renderStatus(status);
    renderEvents(trades);
    $("last-refresh").textContent = "updated " + new Date().toLocaleTimeString();
  } catch (e) {
    if (e.message !== "unauthenticated") console.error("refresh failed:", e);
  }
}

/* ----------------------------------------------------------------- render */
function renderStatus(s) {
  // Badges
  const modeBadge = $("mode-badge");
  modeBadge.textContent = s.mode.toUpperCase();
  modeBadge.className = "badge " + (s.mode === "live" ? "badge-live" : "badge-paper");

  const cbState = s.circuit_breaker.state;
  const cbBadge = $("cb-badge");
  cbBadge.textContent = cbState;
  cbBadge.className = "badge " + (cbState === "NORMAL" ? "badge-normal" : cbState === "EMERGENCY" ? "badge-emergency" : "badge-paused");
  $("stat-cb").textContent = cbState;
  $("stat-cb").style.color = cbState === "NORMAL" ? "var(--green)" : cbState === "EMERGENCY" ? "var(--red)" : "var(--amber)";

  // Banner
  const banner = $("alert-banner");
  if (cbState !== "NORMAL") {
    const lastEvent = s.circuit_breaker.recent_events[s.circuit_breaker.recent_events.length - 1];
    banner.textContent = `⚠ Circuit breaker ${cbState}${lastEvent ? ": " + lastEvent.message : ""}`;
    banner.hidden = false;
  } else {
    banner.hidden = true;
  }

  // Stat cards
  if (s.balance) {
    $("stat-equity").textContent = fmtUsd(s.balance.total_usd);
    $("stat-equity-pnl").textContent = `${fmtUsd(s.balance.total_pnl)} (${fmtPct(s.balance.total_pnl_pct)})`;
    $("stat-equity-pnl").className = "card-sub " + pnlClass(s.balance.total_pnl);
    $("stat-cash").textContent = fmtUsd(s.balance.cash_usd);
    const pnlEl = $("stat-pnl");
    pnlEl.textContent = fmtUsd(s.balance.total_pnl);
    pnlEl.className = "card-value " + pnlClass(s.balance.total_pnl);
    $("stat-fees").textContent = "fees " + fmtUsd(s.balance.total_fees);
  }
  $("stat-positions").textContent = s.open_positions.length;
  if (s.risk) $("stat-exposure").textContent = fmtUsd(s.risk.current_exposure_usd) + " exposure";
  if (s.pnl) {
    $("stat-winrate").textContent = s.pnl.total_trades ? s.pnl.win_rate.toFixed(0) + "%" : "—";
    $("stat-trades").textContent = `${s.pnl.winning_trades}W / ${s.pnl.losing_trades}L`;
  }
  $("uptime").textContent = "up " + fmtUptime(s.uptime_seconds);

  renderPositions(s.open_positions);
  renderTrades(s.pnl);
}

function renderPositions(positions) {
  const body = $("positions-body");
  body.textContent = "";
  if (!positions.length) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 8; td.className = "muted"; td.textContent = "No open positions";
    tr.appendChild(td); body.appendChild(tr);
    return;
  }
  for (const p of positions) {
    const tr = document.createElement("tr");

    addTd(tr, p.symbol, "strong");
    addTd(tr, fmtUsd(p.entry_price, 6));
    addTd(tr, fmtUsd(p.current_price, 6));
    addTd(tr, p.quantity.toFixed(2));
    addTd(tr, fmtUsd(p.value_usd));

    const pnlTd = addTd(tr, `${fmtUsd(p.unrealized_pnl)} (${fmtPct(p.unrealized_pnl_pct)})`);
    pnlTd.className = pnlClass(p.unrealized_pnl);

    addTd(tr, `${p.stop_loss ? fmtUsd(p.stop_loss, 4) : "—"} / ${p.take_profit ? fmtUsd(p.take_profit, 4) : "—"}`);

    const tdBtn = document.createElement("td");
    const btn = document.createElement("button");
    btn.className = "btn btn-warn";
    btn.textContent = "Close";
    btn.addEventListener("click", () => closePosition(p.token_address, btn));
    tdBtn.appendChild(btn);
    tr.appendChild(tdBtn);

    body.appendChild(tr);
  }
}

function renderTrades(pnl) {
  const body = $("trades-body");
  body.textContent = "";
  if (!pnl || !pnl.total_trades) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 5; td.className = "muted"; td.textContent = "No trades yet";
    tr.appendChild(td); body.appendChild(tr);
    return;
  }
  const rows = [
    ["Best trade", fmtUsd(pnl.best_trade_pnl), pnlClass(pnl.best_trade_pnl)],
    ["Worst trade", fmtUsd(pnl.worst_trade_pnl), pnlClass(pnl.worst_trade_pnl)],
    ["Avg win", fmtUsd(pnl.average_win), "pos"],
    ["Avg loss", "-" + fmtUsd(pnl.average_loss).replace("$", "$"), "neg"],
    ["Profit factor", pnl.profit_factor ? pnl.profit_factor.toFixed(2) : "—", "muted"],
    ["Max drawdown", pnl.max_drawdown_pct.toFixed(1) + "%", "neg"],
  ];
  for (const [label, value, cls] of rows) {
    const tr = document.createElement("tr");
    addTd(tr, label, "muted");
    const td = addTd(tr, value);
    td.className = cls;
    const pad = document.createElement("td"); pad.colSpan = 3; tr.appendChild(pad);
    body.appendChild(tr);
  }
}

function renderEvents(resp) {
  const list = $("events-list");
  for (const ev of resp.events) {
    const li = document.createElement("li");
    li.className = "ev-" + ev.level;

    const time = document.createElement("span");
    time.className = "ev-time"; time.textContent = fmtTime(ev.timestamp);
    const type = document.createElement("span");
    type.className = "ev-type"; type.textContent = ev.event_type;
    const msg = document.createElement("span");
    msg.className = "ev-msg";
    msg.textContent = ev.message + (ev.data.token ? ` — ${ev.data.token}` : "");
    if (ev.data.realized_pnl !== undefined && ev.data.realized_pnl !== null) {
      msg.textContent += ` (${fmtUsd(ev.data.realized_pnl)})`;
    }
    li.append(time, type, msg);
    list.prepend(li);
  }
  if (state.sinceTs === 0) {
    // First load: trim list
    while (list.children.length > 50) list.removeChild(list.lastChild);
  }
  if (resp.events.length) {
    state.sinceTs = Math.max(...resp.events.map((e) => e.timestamp));
  }
  $("events-note").textContent = list.children.length ? `${list.children.length} shown` : "";
}

/* ---------------------------------------------------------------- helpers */
function addTd(tr, text, cls) {
  const td = document.createElement("td");
  if (cls) td.className = cls;
  td.textContent = text;
  tr.appendChild(td);
  return td;
}

function armButton(btn, label, action) {
  if (btn.dataset.armed) {
    btn.dataset.armed = "";
    btn.classList.remove("confirming");
    btn.textContent = label;
    return action();
  }
  btn.dataset.armed = "1";
  btn.classList.add("confirming");
  btn.textContent = "Confirm?";
  setTimeout(() => {
    if (btn.dataset.armed) {
      btn.dataset.armed = "";
      btn.classList.remove("confirming");
      btn.textContent = label;
    }
  }, 3000);
}

/* --------------------------------------------------------------- actions */
async function doAction(path, okMsg) {
  try {
    const res = await api(path, { method: "POST" });
    console.log(okMsg, res);
    await refresh();
  } catch (e) {
    console.error(e.message);
    await refresh();
  }
}

function closePosition(token, btn) {
  armButton(btn, "Close", () => doAction(`/api/actions/positions/${token}/close`, "closed"));
}

/* ------------------------------------------------------------------ init */
document.addEventListener("DOMContentLoaded", () => {
  $("login-form").addEventListener("submit", login);
  $("logout-btn").addEventListener("click", logout);

  $("pause-btn").addEventListener("click", () => doAction("/api/actions/pause", "paused"));
  $("resume-btn").addEventListener("click", () => doAction("/api/actions/resume", "resumed"));
  $("emergency-btn").addEventListener("click", (e) => {
    armButton(e.currentTarget, "🛑 Emergency close all", () => doAction("/api/actions/emergency-close-all", "emergency"));
  });

  tryBootstrap();
});
