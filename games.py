import random

DECK = [2, 3, 4, 5, 6, 7, 8, 9, 10, 10, 10, 10, 11] * 4

def hand_value(hand):
    value = sum(hand)
    aces = hand.count(11)
    while value > 21 and aces:
        value -= 10
        aces -= 1
    return value

def cards_display(hand):
    return " ".join(f"`{c}`" for c in hand)

def blackjack_deal():
    deck = DECK.copy()
    random.shuffle(deck)
    player = [deck.pop(), deck.pop()]
    dealer = [deck.pop(), deck.pop()]
    return player, dealer, deck

def coinflip(side, bet, balance):
    result = random.choice(["heads", "tails"])
    won = result == side
    payout = bet * 2 if won else 0
    new_balance = balance - bet + payout
    message = f"🪙 **{result.upper()}**! You {'won' if won else 'lost'} **{bet:,}** credits."
    return won, message, new_balance

def slots(bet, balance):
    SYMBOLS = ["🍒", "🍋", "🍉", "⭐", "💎"]
    roll = [random.choice(SYMBOLS) for _ in range(3)]
    
    if roll[0] == roll[1] == roll[2]:
        payout = bet * 10
    elif roll[0] == roll[1] or roll[1] == roll[2]:
        payout = bet * 2
    else:
        payout = 0
    
    new_balance = balance - bet + payout
    return payout > 0, roll, payout, new_balance