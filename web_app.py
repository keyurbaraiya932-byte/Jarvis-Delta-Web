from flask import Flask, render_template, jsonify
import os

app = Flask(__name__)

LOCKED_RULES = {
    "trade_percent": 30,
    "min_rr": "1:2",
    "daily_profit_target_inr": 2000,
    "max_open_positions": 1,
    "time_exit": False,
    "real_trading": False,
}

@app.get("/")
def home():
    return render_template("index.html", rules=LOCKED_RULES)

@app.get("/health")
def health():
    return jsonify(ok=True, service="JARVIS Delta Web", real_trading=False)

@app.get("/api/status")
def status():
    return jsonify(ok=True, mode="SAFE_DEPLOY", real_trading=False, rules=LOCKED_RULES,
                   message="Cloud shell online. Delta credentials not configured; real execution locked OFF.")

if __name__ == "__main__":
    from waitress import serve
    serve(app, host="0.0.0.0", port=int(os.getenv("PORT", "8080")), threads=4)
