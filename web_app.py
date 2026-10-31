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


def delta_get(path):
    """Read-only authenticated GET request. This function cannot place orders."""
    api_key = os.getenv("DELTA_API_KEY", "").strip()
    api_secret = os.getenv("DELTA_API_SECRET", "").strip()
    if not api_key or not api_secret:
        return None, "delta_credentials_missing"

    method = "GET"
    timestamp = str(int(time.time()))
    query_string = ""
    body = ""
    message = method + timestamp + path + query_string + body
    signature = hmac.new(
        api_secret.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    headers = {
        "Accept": "application/json",
        "api-key": api_key,
        "signature": signature,
        "timestamp": timestamp,
        "User-Agent": "jarvis-delta-web/12-readonly",
    }

    try:
        response = requests.get(DELTA_BASE_URL + path, headers=headers, timeout=10)
        try:
            payload = response.json()
        except ValueError:
            return None, f"delta_http_{response.status_code}"
        if response.status_code != 200 or not payload.get("success", False):
            error = payload.get("error", {})
            if isinstance(error, dict):
                return None, error.get("code") or f"delta_http_{response.status_code}"
            return None, str(error) or f"delta_http_{response.status_code}"
        return payload.get("result", []), None
    except requests.RequestException as exc:
        return None, f"network_error:{type(exc).__name__}"


@app.get("/")
def home():
    return render_template("index.html", rules=LOCKED_RULES)


@app.get("/health")
def health():
    return jsonify(ok=True, service="JARVIS Delta Web", real_trading=False)


@app.get("/api/status")
def status():
    configured = bool(os.getenv("DELTA_API_KEY") and os.getenv("DELTA_API_SECRET"))
    return jsonify(
        ok=True,
        mode="SAFE_DEPLOY_READ_ONLY",
        real_trading=False,
        delta_credentials_configured=configured,
        rules=LOCKED_RULES,
        message="Read-only Delta test enabled. Real order execution remains locked OFF.",
    )


@app.get("/api/delta/wallet-test")
def wallet_test():
    balances, error = delta_get("/v2/wallet/balances")
    if error:
        return jsonify(ok=False, real_trading=False, error=error), 502

    # Return balances only; never expose API credentials/signatures.
    return jsonify(
        ok=True,
        real_trading=False,
        mode="READ_ONLY",
        balance_count=len(balances) if isinstance(balances, list) else None,
        balances=balances,
    )


if __name__ == "__main__":
    from waitress import serve
    serve(app, host="0.0.0.0", port=int(os.getenv("PORT", "8080")), threads=4)
