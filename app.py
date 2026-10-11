import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import requests
from streamlit_autorefresh import st_autorefresh
from datetime import datetime, timezone

# Noor AI Crypto Demo Bot
# Demo/paper trading ONLY. This code never places real orders.

st.set_page_config(page_title="Noor AI Crypto Demo Bot", page_icon="📊", layout="wide")
st.title("🌙 Noor AI Crypto Demo Bot")
st.caption("Crypto demo • EMA + RSI signals • Paper trading only — no real orders")

BASE_URL = "https://api.binance.com"

@st.cache_data(ttl=60)
def get_klines(symbol: str, interval: str, limit: int = 200) -> pd.DataFrame:
    url = f"{BASE_URL}/api/v3/klines"
    response = requests.get(
        url,
        params={"symbol": symbol, "interval": interval, "limit": limit},
        timeout=15,
    )
    response.raise_for_status()
    rows = response.json()
    cols = [
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_volume", "trades", "taker_buy_base",
        "taker_buy_quote", "ignore",
    ]
    df = pd.DataFrame(rows, columns=cols)
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df["close_time"] = pd.to_datetime(df["close_time"], unit="ms", utc=True)
    # Drop the currently forming candle so signals use closed candles only.
    now = pd.Timestamp.now(tz="UTC")
    df = df[df["close_time"] < now].copy()
    return df.reset_index(drop=True)

def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["EMA_9"] = df["close"].ewm(span=9, adjust=False).mean()
    df["EMA_21"] = df["close"].ewm(span=21, adjust=False).mean()
    delta = df["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, float("nan"))
    df["RSI"] = 100 - (100 / (1 + rs))
    return df

def get_signal(df: pd.DataFrame):
    if len(df) < 30:
        return "NO TRADE", "Not enough closed candles to calculate indicators."
    last = df.iloc[-1]
    prev = df.iloc[-2]
    if pd.isna(last["RSI"]):
        return "NO TRADE", "RSI is not ready yet."
    crossed_up = prev["EMA_9"] <= prev["EMA_21"] and last["EMA_9"] > last["EMA_21"]
    crossed_down = prev["EMA_9"] >= prev["EMA_21"] and last["EMA_9"] < last["EMA_21"]
    if crossed_up and last["RSI"] < 70:
        return "BUY", "EMA 9 crossed above EMA 21 and RSI is below 70."
    if crossed_down and last["RSI"] > 30:
        return "SELL", "EMA 9 crossed below EMA 21 and RSI is above 30."
    if last["EMA_9"] > last["EMA_21"] and 45 <= last["RSI"] <= 65:
        return "BUY", "Trend is upward (EMA 9 above EMA 21) and RSI is in a moderate range."
    if last["EMA_9"] < last["EMA_21"] and 35 <= last["RSI"] <= 55:
        return "SELL", "Trend is downward (EMA 9 below EMA 21) and RSI is in a moderate range."
    return "NO TRADE", "The indicator conditions are mixed; waiting is preferable."

def init_state():
    defaults = {
        "cash": 10000.0,
        "position_qty": 0.0,
        "entry_price": None,
        "trade_log": [],
        "last_processed_candle": None,
        "auto_demo": False,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

init_state()

with st.sidebar:
    st.header("⚙️ Settings")
    symbol = st.selectbox("Crypto pair", ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"])
    interval = st.selectbox("Candle timeframe", ["5m", "15m", "1h", "4h", "1d"], index=1)
    trade_size = st.number_input("Demo order size (USDT)", min_value=10.0, max_value=2000.0, value=100.0, step=10.0)
    stop_loss_pct = st.slider("Demo stop-loss (%)", min_value=0.5, max_value=10.0, value=2.0, step=0.5)
    take_profit_pct = st.slider("Demo take-profit (%)", min_value=0.5, max_value=20.0, value=4.0, step=0.5)
    auto_demo = st.checkbox("Auto paper-trading (demo only)", value=False, help="When enabled, the page checks for a new closed candle about every 30 seconds and processes it once. It never places real orders.")
    st.caption("Virtual starting balance: 10,000 USDT. This is not real money.")
    if st.button("Reset demo account", use_container_width=True):
        st.session_state.cash = 10000.0
        st.session_state.position_qty = 0.0
        st.session_state.entry_price = None
        st.session_state.trade_log = []
        st.session_state.last_processed_candle = None
        st.rerun()

if auto_demo:
    st_autorefresh(interval=30_000, key="noor_auto_refresh")

col_refresh, col_note = st.columns([1, 3])
with col_refresh:
    refresh = st.button("🔄 Refresh market data", type="primary", use_container_width=True)
with col_note:
    st.write("Market data is fetched from Binance public endpoints. Refresh to update the chart and evaluate one new closed candle.")

try:
    if refresh:
        get_klines.clear()
    df = add_indicators(get_klines(symbol, interval))
    if df.empty or len(df) < 30:
        st.error("Market data is not sufficient yet. Try again in a moment.")
        st.stop()
except Exception as e:
    st.error("Could not load market data. Check your internet and try again later.")
    st.caption(f"Technical detail: {e}")
    st.stop()

signal, reason = get_signal(df)
last = df.iloc[-1]
price = float(last["close"])
candle_time = last["close_time"].isoformat()

# Automatic demo mode processes each newly available closed candle at most once.
# If auto mode is off, the user can process a candle with the manual button.
manual_step = st.button("▶ Run one demo trading step", use_container_width=True)
should_process = auto_demo or manual_step
if should_process:
    if st.session_state.last_processed_candle != candle_time:
        qty = float(st.session_state.position_qty)
        entry = st.session_state.entry_price

        # Exit existing long position on signal SELL or simulated SL/TP.
        if qty > 0 and entry is not None:
            pnl_pct = (price - entry) / entry * 100
            exit_reason = None
            if pnl_pct <= -stop_loss_pct:
                exit_reason = "Stop-loss"
            elif pnl_pct >= take_profit_pct:
                exit_reason = "Take-profit"
            elif signal == "SELL":
                exit_reason = "SELL signal"
            if exit_reason:
                proceeds = qty * price
                pnl = qty * (price - entry)
                st.session_state.cash += proceeds
                st.session_state.trade_log.append({
                    "Time (UTC)": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                    "Action": "SELL / CLOSE",
                    "Price": round(price, 4),
                    "Quantity": round(qty, 8),
                    "PnL (USDT)": round(pnl, 4),
                    "Reason": exit_reason,
                })
                st.session_state.position_qty = 0.0
                st.session_state.entry_price = None

        # Open a long demo position only if no position exists and BUY is signaled.
        if st.session_state.position_qty == 0 and signal == "BUY":
            cost = min(float(trade_size), float(st.session_state.cash))
            if cost >= 10:
                qty = cost / price
                st.session_state.cash -= cost
                st.session_state.position_qty = qty
                st.session_state.entry_price = price
                st.session_state.trade_log.append({
                    "Time (UTC)": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                    "Action": "BUY / OPEN",
                    "Price": round(price, 4),
                    "Quantity": round(qty, 8),
                    "PnL (USDT)": 0.0,
                    "Reason": reason,
                })
        st.session_state.last_processed_candle = candle_time
        st.rerun()
    elif manual_step and not auto_demo:
        st.info("This closed candle has already been processed. Wait for a new candle to close.")

# Headline metrics
position_value = float(st.session_state.position_qty) * price
unrealized = 0.0
if st.session_state.position_qty > 0 and st.session_state.entry_price:
    unrealized = st.session_state.position_qty * (price - st.session_state.entry_price)
equity = float(st.session_state.cash) + position_value

m1, m2, m3, m4 = st.columns(4)
m1.metric("Latest closed price", f"${price:,.2f}")
m2.metric("Signal", signal)
m3.metric("Virtual equity", f"${equity:,.2f}", f"{equity - 10000:+,.2f} USDT")
m4.metric("Open position value", f"${position_value:,.2f}")

st.info(f"**Signal explanation:** {reason}  \n**Last closed candle (UTC):** {last['close_time'].strftime('%Y-%m-%d %H:%M:%S')}")

fig = go.Figure()
fig.add_trace(go.Candlestick(
    x=df["open_time"], open=df["open"], high=df["high"],
    low=df["low"], close=df["close"], name="Candles"
))
fig.add_trace(go.Scatter(x=df["open_time"], y=df["EMA_9"], name="EMA 9", mode="lines"))
fig.add_trace(go.Scatter(x=df["open_time"], y=df["EMA_21"], name="EMA 21", mode="lines"))
fig.update_layout(
    title=f"{symbol} — {interval} closed candles",
    xaxis_title="Time (UTC)", yaxis_title="Price (USDT)",
    xaxis_rangeslider_visible=False, height=520, margin=dict(l=10, r=10, t=50, b=10)
)
st.plotly_chart(fig, use_container_width=True)

r1, r2, r3 = st.columns(3)
r1.metric("RSI (14)", "—" if pd.isna(last["RSI"]) else f"{last['RSI']:.2f}")
r2.metric("EMA 9", f"{last['EMA_9']:,.2f}")
r3.metric("EMA 21", f"{last['EMA_21']:,.2f}")

st.subheader("📒 Paper trading account")
p1, p2, p3 = st.columns(3)
p1.metric("Virtual cash", f"${st.session_state.cash:,.2f}")
p2.metric("Position quantity", f"{st.session_state.position_qty:.8f}")
p3.metric("Unrealized PnL", f"${unrealized:+,.2f}")

if st.session_state.trade_log:
    st.dataframe(pd.DataFrame(st.session_state.trade_log).iloc[::-1], use_container_width=True, hide_index=True)
else:
    st.write("No demo trades yet. Press **Run one demo trading step** when you want the bot to process the latest closed candle.")

st.caption("Limitations: this is a beginner demo using simple technical rules. It does not learn from data, cannot guarantee accuracy, and does not submit real orders. Trading fees, slippage and exchange outages are not fully simulated. Do not add real exchange API keys.")
