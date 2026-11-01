from flask import Flask, render_template, jsonify
import os, time, hmac, hashlib, math, requests

app = Flask(__name__)

LOCKED_RULES = {"trade_percent":30,"min_rr":"1:2","daily_profit_target_inr":2000,"max_open_positions":1,"time_exit":False,"real_trading":False}
DELTA_BASE_URL="https://api.india.delta.exchange"

def public_get(path,params=None):
    r=requests.get(DELTA_BASE_URL+path,params=params or {},timeout=12,headers={"User-Agent":"jarvis-delta-web/12"}); r.raise_for_status(); p=r.json()
    if not p.get("success",False): raise RuntimeError(str(p.get("error","delta_error")))
    return p.get("result",[])

def delta_get(path):
    api_key=os.getenv("DELTA_API_KEY","").strip(); api_secret=os.getenv("DELTA_API_SECRET","").strip()
    if not api_key or not api_secret: return None,"delta_credentials_missing"
    timestamp=str(int(time.time())); message="GET"+timestamp+path
    signature=hmac.new(api_secret.encode(),message.encode(),hashlib.sha256).hexdigest()
    headers={"Accept":"application/json","api-key":api_key,"signature":signature,"timestamp":timestamp,"User-Agent":"jarvis-delta-web/12-readonly"}
    try:
        response=requests.get(DELTA_BASE_URL+path,headers=headers,timeout=10)
        try: payload=response.json()
        except ValueError: return None,f"delta_http_{response.status_code}"
        if response.status_code!=200 or not payload.get("success",False):
            error=payload.get("error",{})
            if isinstance(error,dict): return None,error.get("code") or f"delta_http_{response.status_code}"
            return None,str(error) or f"delta_http_{response.status_code}"
        return payload.get("result",[]),None
    except requests.RequestException as exc: return None,f"network_error:{type(exc).__name__}"

def ema_series(values,period):
    if len(values)<period: return []
    k=2/(period+1); out=[None]*(period-1); x=sum(values[:period])/period; out.append(x)
    for v in values[period:]: x=v*k+x*(1-k); out.append(x)
    return out

def ema(values,period):
    s=ema_series(values,period); return s[-1] if s else None

def alma(values,window=9,offset=.85,sigma=6):
    if len(values)<window:return None
    vals=values[-window:]; m=offset*(window-1); s=window/sigma
    w=[math.exp(-((i-m)**2)/(2*s*s)) for i in range(window)]
    return sum(v*x for v,x in zip(vals,w))/sum(w)

def ao(highs,lows):
    if len(highs)<34:return None
    med=[(h+l)/2 for h,l in zip(highs,lows)]; return sum(med[-5:])/5-sum(med[-34:])/34

def macd(values):
    a,b=ema(values,12),ema(values,26); return None if a is None or b is None else a-b

def rsi(values,period=14):
    if len(values)<period+1:return None
    d=[values[i]-values[i-1] for i in range(1,len(values))][-period:]
    gain=sum(max(x,0) for x in d)/period; loss=sum(max(-x,0) for x in d)/period
    if loss==0:return 100.0
    rs=gain/loss; return 100-(100/(1+rs))

def atr(highs,lows,closes,period=14):
    if len(closes)<period+1:return None
    tr=[]
    for i in range(1,len(closes)): tr.append(max(highs[i]-lows[i],abs(highs[i]-closes[i-1]),abs(lows[i]-closes[i-1])))
    return sum(tr[-period:])/period

def adx(highs,lows,closes,period=14):
    if len(closes)<period+1:return None
    trs=[]; plus=[]; minus=[]
    for i in range(1,len(closes)):
        trs.append(max(highs[i]-lows[i],abs(highs[i]-closes[i-1]),abs(lows[i]-closes[i-1])))
        up=highs[i]-highs[i-1]; down=lows[i-1]-lows[i]
        plus.append(up if up>down and up>0 else 0); minus.append(down if down>up and down>0 else 0)
    tr=sum(trs[-period:]); pd=sum(plus[-period:]); md=sum(minus[-period:])
    if tr==0:return 0.0
    pdi=100*pd/tr; mdi=100*md/tr
    return 0.0 if pdi+mdi==0 else 100*abs(pdi-mdi)/(pdi+mdi)

def signal_from_candles(candles):
    rows=sorted(candles,key=lambda x:x.get("time",0))
    if len(rows)>60: rows=rows[:-1]
    closes=[float(x["close"]) for x in rows]; highs=[float(x["high"]) for x in rows]; lows=[float(x["low"]) for x in rows]
    vols=[float(x.get("volume",0) or 0) for x in rows]
    if len(closes)<55:return {"signal":"WAIT","reason":"not_enough_closed_candles"}
    last=closes[-1]; a=alma(closes); av=ao(highs,lows); mv=macd(closes); rv=rsi(closes); xv=adx(highs,lows,closes); at=atr(highs,lows,closes); e50=ema(closes,50)
    vol_avg=sum(vols[-20:])/20 if len(vols)>=20 else 0; vol_ok=(vols[-1]>=vol_avg) if vol_avg>0 else True
    core_buy=last>a and av>0 and mv>0; core_sell=last<a and av<0 and mv<0
    trend_buy=last>e50; trend_sell=last<e50; strength=xv>=20; rsi_buy=50<=rv<70; rsi_sell=30<rv<=50
    buy_confirm=sum([trend_buy,strength,rsi_buy,vol_ok]); sell_confirm=sum([trend_sell,strength,rsi_sell,vol_ok])
    if core_buy and buy_confirm>=3:sig="BUY"
    elif core_sell and sell_confirm>=3:sig="SELL"
    else:sig="WAIT"
    return {"signal":sig,"close":last,"alma":round(a,8),"ao":round(av,8),"macd":round(mv,8),"rsi":round(rv,2),"adx":round(xv,2),"atr":round(at,8),"ema50":round(e50,8),"volume_confirm":vol_ok,"confirmation_score":max(buy_confirm,sell_confirm),"confirmation_total":4,"closed_candle_only":True,"real_trading":False}

@app.get("/")
def home():return render_template("index.html",rules=LOCKED_RULES)
@app.get("/health")
def health():return jsonify(ok=True,service="JARVIS Delta Web",real_trading=False)
@app.get("/api/status")
def status():return jsonify(ok=True,mode="SAFE_DEPLOY",real_trading=False,delta_credentials_configured=bool(os.getenv("DELTA_API_KEY") and os.getenv("DELTA_API_SECRET")),rules=LOCKED_RULES,indicators=["ALMA","AO","MACD","RSI","ADX","ATR","EMA50","Volume"],message="Enhanced public scanner enabled. Real execution locked OFF.")
@app.get("/api/market/products")
def products():
    try:
        result=public_get("/v2/products");return jsonify(ok=True,real_trading=False,count=len(result),products=result)
    except Exception as e:return jsonify(ok=False,error=type(e).__name__,real_trading=False),502
@app.get("/api/scan/<symbol>")
def scan(symbol):
    try:
        end=int(time.time());start=end-(60*60*140);candles=public_get("/v2/history/candles",{"symbol":symbol.upper(),"resolution":"1h","start":start,"end":end});out=signal_from_candles(candles)
        return jsonify(ok=True,symbol=symbol.upper(),resolution="1h",rules=LOCKED_RULES,**out)
    except Exception as e:return jsonify(ok=False,symbol=symbol.upper(),error=type(e).__name__,real_trading=False),502
@app.get("/api/delta/wallet-test")
def wallet_test():
    balances,error=delta_get("/v2/wallet/balances")
    if error:return jsonify(ok=False,real_trading=False,error=error),502
    return jsonify(ok=True,real_trading=False,mode="READ_ONLY",balance_count=len(balances) if isinstance(balances,list) else None,balances=balances)

if __name__=="__main__":
    from waitress import serve
    serve(app,host="0.0.0.0",port=int(os.getenv("PORT","8080")),threads=4)
