from flask import Flask, render_template, jsonify
import os
import time
import hmac
import hashlib
import requests

app = Flask(__name__)

LOCKED_RULES = {
    "trade_percent": 30,
    "min_rr": "1:2",
    "daily_profit_target_inr": 2000,
    "max_open_positions": 1,
    "time_exit": False,
    "real_trading": False,
}

DELTA_BASE_URL = "https://api.india.delta.exchange"


def public_get(path, params=None):
    r = requests.get(DELTA_BASE_URL + path, params=params or {}, timeout=12,
                     headers={"User-Agent": "jarvis-delta-web/12"})
    r.raise_for_status()
    p = r.json()
    if not p.get("success", False):
        raise RuntimeError(str(p.get("error", "delta_error")))
    return p.get("result", [])


def delta_get(path):
    """Read-only authenticated GET. It cannot place orders."""
    api_key = os.getenv("DELTA_API_KEY", "").strip()
    api_secret = os.getenv("DELTA_API_SECRET", "").strip()
    if not api_key or not api_secret:
        return None, "delta_credentials_missing"
    timestamp = str(int(time.time()))
    message = "GET" + timestamp + path
    signature = hmac.new(api_secret.encode(), message.encode(), hashlib.sha256).hexdigest()
    headers = {"Accept":"application/json","api-key":api_key,"signature":signature,
               "timestamp":timestamp,"User-Agent":"jarvis-delta-web/12-readonly"}
    try:
        response = requests.get(DELTA_BASE_URL + path, headers=headers, timeout=10)
        try: payload = response.json()
        except ValueError: return None, f"delta_http_{response.status_code}"
        if response.status_code != 200 or not payload.get("success", False):
            error = payload.get("error", {})
            if isinstance(error, dict): return None, error.get("code") or f"delta_http_{response.status_code}"
            return None, str(error) or f"delta_http_{response.status_code}"
        return payload.get("result", []), None
    except requests.RequestException as exc:
        return None, f"network_error:{type(exc).__name__}"


def ema(values, period):
    if len(values) < period: return None
    k = 2.0 / (period + 1)
    x = sum(values[:period]) / period
    for v in values[period:]: x = v * k + x * (1-k)
    return x


def alma(values, window=9, offset=.85, sigma=6):
    if len(values) < window: return None
    vals = values[-window:]
    m = offset * (window-1); s = window / sigma
    weights = [pow(2.718281828, -((i-m)**2)/(2*s*s)) for i in range(window)]
    return sum(v*w for v,w in zip(vals,weights)) / sum(weights)


def ao(highs, lows):
    if len(highs) < 34: return None
    med = [(h+l)/2 for h,l in zip(highs,lows)]
    return sum(med[-5:])/5 - sum(med[-34:])/34


def macd(values):
    e12, e26 = ema(values,12), ema(values,26)
    if e12 is None or e26 is None: return None
    return e12-e26


def signal_from_candles(candles):
    rows = sorted(candles, key=lambda x: x.get("time",0))
    # Drop newest candle so decisions use closed candles only.
    if len(rows) > 40: rows = rows[:-1]
    closes=[float(x["close"]) for x in rows]; highs=[float(x["high"]) for x in rows]; lows=[float(x["low"]) for x in rows]
    if len(closes) < 40: return {"signal":"WAIT","reason":"not_enough_closed_candles"}
    a=alma(closes); av=ao(highs,lows); mv=macd(closes); last=closes[-1]
    if last>a and av>0 and mv>0: sig="BUY"
    elif last<a and av<0 and mv<0: sig="SELL"
    else: sig="WAIT"
    return {"signal":sig,"close":last,"alma":round(a,8),"ao":round(av,8),"macd":round(mv,8),"closed_candle_only":True}


@app.get("/")
def home(): return render_template("index.html", rules=LOCKED_RULES)

@app.get("/health")
def health(): return jsonify(ok=True, service="JARVIS Delta Web", real_trading=False)

@app.get("/api/status")
def status():
    configured=bool(os.getenv("DELTA_API_KEY") and os.getenv("DELTA_API_SECRET"))
    return jsonify(ok=True,mode="SAFE_DEPLOY",real_trading=False,delta_credentials_configured=configured,rules=LOCKED_RULES,
                   public_market_scanner=True,message="Public scanner enabled. Real execution locked OFF.")

@app.get("/api/market/products")
def products():
    try:
        result=public_get("/v2/products")
        return jsonify(ok=True,real_trading=False,count=len(result),products=result)
    except Exception as e: return jsonify(ok=False,error=type(e).__name__,real_trading=False),502

@app.get("/api/scan/<symbol>")
def scan(symbol):
    try:
        end=int(time.time()); start=end-(60*60*100)
        candles=public_get("/v2/history/candles", {"symbol":symbol.upper(),"resolution":"1h","start":start,"end":end})
        out=signal_from_candles(candles)
        return jsonify(ok=True,symbol=symbol.upper(),resolution="1h",real_trading=False,rules=LOCKED_RULES,**out)
    except Exception as e: return jsonify(ok=False,symbol=symbol.upper(),error=type(e).__name__,real_trading=False),502

@app.get("/api/delta/wallet-test")
def wallet_test():
    balances,error=delta_get("/v2/wallet/balances")
    if error: return jsonify(ok=False,real_trading=False,error=error),502
    return jsonify(ok=True,real_trading=False,mode="READ_ONLY",balance_count=len(balances) if isinstance(balances,list) else None,balances=balances)

if __name__ == "__main__":
    from waitress import serve
    serve(app,host="0.0.0.0",port=int(os.getenv("PORT","8080")),threads=4)
