import websocket
import json
import numpy as np
import pandas as pd
import threading
import time
from sklearn.linear_model import LogisticRegression

APP_ID = "YOUR_APP_ID"
TOKEN = "YOUR_API_TOKEN"

SYMBOL = "1HZ75V"
BASE_STAKE = 1
MARTINGALE_MULTIPLIER = 2
MAX_MARTINGALE = 3
COOLDOWN = 5

prices = []
digits = []

current_stake = BASE_STAKE
loss_count = 0
martingale_level = 0
balance = 0
model = LogisticRegression()

# ================= INDICATORS =================

def calculate_ema(data, period):
    return pd.Series(data).ewm(span=period).mean().iloc[-1]

def calculate_rsi(data, period=14):
    series = pd.Series(data)
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(period).mean().iloc[-1]
    avg_loss = loss.rolling(period).mean().iloc[-1]
    rs = avg_gain / avg_loss if avg_loss != 0 else 0
    return 100 - (100 / (1 + rs))

# ================= AI =================

def train_ai():
    if len(prices) < 50:
        return False

    X = []
    y = []

    for i in range(10, len(prices)-1):
        features = prices[i-5:i]
        X.append(features)
        y.append(1 if prices[i+1] > prices[i] else 0)

    model.fit(X, y)
    return True

def predict_direction():
    features = prices[-5:]
    prob = model.predict_proba([features])[0][1]
    return prob

def choose_barrier():
    counts = {d:0 for d in range(10)}
    for d in digits[-100:]:
        counts[d] += 1

    best_digit = 0
    best_prob = 0

    for barrier in range(9):
        prob = sum(counts[d] for d in range(barrier+1,10)) / 100
        if prob > best_prob:
            best_prob = prob
            best_digit = barrier

    return best_digit

# ================= TRADING =================

def send_proposal(ws, barrier):
    proposal = {
        "proposal": 1,
        "amount": current_stake,
        "basis": "stake",
        "contract_type": "DIGITOVER",
        "currency": "USD",
        "duration": 1,
        "duration_unit": "t",
        "symbol": SYMBOL,
        "barrier": str(barrier)
    }

    ws.send(json.dumps(proposal))

def buy_contract(ws, proposal_id):
    ws.send(json.dumps({
        "buy": proposal_id,
        "price": current_stake
    }))

# ================= WEBSOCKET =================

def on_message(ws, message):
    global prices, digits, balance, current_stake, loss_count, martingale_level

    data = json.loads(message)

    if "authorize" in data:
        balance = float(data["authorize"]["balance"])
        print("Balance:", balance)

    if "tick" in data:
        price = data["tick"]["quote"]
        prices.append(price)
        digits.append(int(str(price)[-1]))

        if len(prices) > 300:
            prices.pop(0)
            digits.pop(0)

        if len(prices) > 50:
            trade_logic(ws)

    if "proposal" in data:
        buy_contract(ws, data["proposal"]["id"])

    if "proposal_open_contract" in data:
        poc = data["proposal_open_contract"]

        if poc["is_sold"]:
            profit = float(poc["profit"])
            balance = float(poc["balance"])

            if profit < 0:
                loss_count += 1
                martingale_level += 1

                if martingale_level <= MAX_MARTINGALE:
                    current_stake *= MARTINGALE_MULTIPLIER
                else:
                    reset_martingale()

            else:
                reset_martingale()

            if loss_count >= 3:
                print("3 losses hit. Stopping.")
                ws.close()

            time.sleep(COOLDOWN)

def trade_logic(ws):
    if not train_ai():
        return

    ema5 = calculate_ema(prices, 5)
    ema10 = calculate_ema(prices, 10)
    rsi = calculate_rsi(prices)
    ai_prob = predict_direction()

    if ema5 > ema10 and rsi < 40 and ai_prob > 0.6:
        barrier = choose_barrier()
        print("Trading DIGIT OVER", barrier)
        send_proposal(ws, barrier)

def reset_martingale():
    global current_stake, martingale_level, loss_count
    current_stake = BASE_STAKE
    martingale_level = 0
    loss_count = 0

def on_open(ws):
    ws.send(json.dumps({
        "authorize": TOKEN
    }))

    time.sleep(1)

    ws.send(json.dumps({
        "ticks": SYMBOL
    }))

ws = websocket.WebSocketApp(
    f"wss://ws.derivws.com/websockets/v3?app_id={APP_ID}",
    on_message=on_message,
    on_open=on_open
)

ws.run_forever()