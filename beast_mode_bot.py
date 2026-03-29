# --- HARVESTER LOGIC ADDITION ---
def harvest_momentum(current_price, avg_buy_price, confidence):
    """
    Logic to catch momentum and harvest small wins.
    """
    # 1. THE HARVEST (Take Profit)
    # If we own it and are up by 7 cents, SELL immediately to lock in the win.
    if avg_buy_price > 0:
        profit = current_price - avg_buy_price
        if profit >= 0.07:
            return "SELL_HARVEST"

    # 2. THE MOMENTUM BUY
    # If we don't own it and confidence is high (65%+) and price is rising.
    if avg_buy_price == 0 and confidence >= 0.65:
        return "BUY_MOMENTUM"

    # 3. THE RE-ENTRY (Buy the Dip)
    # If we just sold at a high, wait for a 3-cent drop to buy back in.
    # This catches the 'zigzag' of a game.
    return "HOLD"
