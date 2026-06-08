import os
import time
import random
import asyncio
import discord
from discord import app_commands
from discord.ext import commands

from keep_alive import keep_alive
from db import (
init_db, get_balance, set_balance, get_leaderboard,
record_wager, get_wager_req, add_wager_req,
get_last_daily, set_last_daily,
)
from games import coinflip, slots, blackjack_deal, hand_value, cards_display

POINT_VALUE    = 0.01
DAILY_BONUS    = 2
DAILY_COOLDOWN = 86400
SLOT_SYMBOLS   = ["🍒", "🍋", "🍉", "⭐", "💎"]

IMG = {
"coin":      "https://cdn.jsdelivr.net/gh/twitter/twemoji@latest/assets/72x72/1fa99.png",
"slots":     "https://cdn.jsdelivr.net/gh/twitter/twemoji@latest/assets/72x72/1f3b0.png",
"blackjack": "https://cdn.jsdelivr.net/gh/twitter/twemoji@latest/assets/72x72/1f0cf.png",
"money":     "https://cdn.jsdelivr.net/gh/twitter/twemoji@latest/assets/72x72/1f4b0.png",
"trophy":    "https://cdn.jsdelivr.net/gh/twitter/twemoji@latest/assets/72x72/1f3c6.png",
"transfer":  "https://cdn.jsdelivr.net/gh/twitter/twemoji@latest/assets/72x72/1f4b8.png",
"gift":      "https://cdn.jsdelivr.net/gh/twitter/twemoji@latest/assets/72x72/1f381.png",
"bank":      "https://cdn.jsdelivr.net/gh/twitter/twemoji@latest/assets/72x72/1f3e6.png",
"gem":       "https://cdn.jsdelivr.net/gh/twitter/twemoji@latest/assets/72x72/1f48e.png",
"bomb":      "https://cdn.jsdelivr.net/gh/twitter/twemoji@latest/assets/72x72/1f4a3.png",
}

intents = discord.Intents.default()
intents.message_content = True   # enabled in Discord Developer Portal
bot = commands.Bot(command_prefix=".", intents=intents, help_command=None)

── helpers ───────────────────────────────────────────────────────────────────

def format_money(pts: int) -> str:
return f"${pts * POINT_VALUE:,.2f}"

def balance_display(pts: int) -> str:
return f"{pts:,} credits ({format_money(pts)})"

def validate_bet(bet: int, balance: int) -> str | None:
if bet <= 0:
return "Bet must be greater than 0."
if bet > balance:
return f"You only have {balance_display(balance)}."
return None

def seconds_to_hms(s: int) -> str:
h, rem = divmod(s, 3600)
m, sec = divmod(rem, 60)
parts = []
if h:   parts.append(f"{h}h")
if m:   parts.append(f"{m}m")
if sec or not parts: parts.append(f"{sec}s")
return " ".join(parts)

def make_embed(title: str, desc: str, color: discord.Color,
image_key: str,
user: discord.User | discord.Member | None = None,
footer: str = "") -> discord.Embed:
embed = discord.Embed(title=title, description=desc, color=color)
embed.set_thumbnail(url=IMG[image_key])
if user:
embed.set_author(name=user.display_name, icon_url=user.display_avatar.url)
if footer:
embed.set_footer(text=footer)
return embed

── mines multiplier ─────────────────────────────────────────────────────────

def mines_multiplier(total: int, mines: int, revealed: int,
house_edge: float = 0.97) -> float:
"""Probability-based cash-out multiplier after revealed safe tiles."""
if revealed == 0:
return 1.0
prob = 1.0
for i in range(revealed):
safe_left  = total - mines - i
total_left = total - i
if total_left <= 0 or safe_left <= 0:
return 0.0
prob *= safe_left / total_left
return round(house_edge / prob, 2)

── interactive blackjack view ────────────────────────────────────────────────

class BlackjackView(discord.ui.View):
"""Manages a live blackjack hand with Hit / Stand / Double Down buttons."""

def __init__(self, uid: int, initial_bet: int,  
             player: list[int], dealer: list[int], deck: list[int],  
             user: discord.User | discord.Member):  
    super().__init__(timeout=120)  
    self.uid         = uid  
    self.initial_bet = initial_bet  
    self.total_bet   = initial_bet   # grows on double down  
    self.player      = list(player)  
    self.dealer      = list(dealer)  
    self.deck        = list(deck)  
    self.user        = user  
    self.message: discord.Message | None = None  

# ── embed builders ────────────────────────────────────────────────────────  

def _active_embed(self) -> discord.Embed:  
    pv = hand_value(self.player)  
    embed = make_embed(  
        "🃏 Blackjack", "Your move — choose an action below.",  
        discord.Color.blurple(), "blackjack", self.user,  
        footer=f"Bet: {self.total_bet:,} credits • {format_money(self.total_bet)}"  
    )  
    embed.add_field(name="🃏 Your Hand",  
                    value=f"{cards_display(self.player)} = **{pv}**", inline=True)  
    embed.add_field(name="🤖 Dealer Shows",  
                    value=f"`{self.dealer[1]}` | `?`", inline=True)  
    return embed  

def _result_embed(self, title: str, desc: str, color: discord.Color,  
                  net: int, new_balance: int) -> discord.Embed:  
    pv = hand_value(self.player)  
    dv = hand_value(self.dealer)  
    net_str = f"+{format_money(net)}" if net > 0 else (f"-{format_money(abs(net))}" if net < 0 else "±$0.00")  
    embed = make_embed(  
        "🃏 Blackjack", f"**{title}** — {desc}",  
        color, "blackjack", self.user,  
        footer=f"Bet: {self.total_bet:,} credits • {format_money(self.total_bet)}"  
    )  
    embed.add_field(name="🃏 Your Hand",  
                    value=f"{cards_display(self.player)} (**{pv}**)", inline=True)  
    embed.add_field(name="🤖 Dealer Hand",  
                    value=f"{cards_display(self.dealer)} (**{dv}**)", inline=True)  
    embed.add_field(name="Net",         value=net_str,                 inline=True)  
    embed.add_field(name="New Balance", value=balance_display(new_balance), inline=False)  
    return embed  

# ── game logic ────────────────────────────────────────────────────────────  

def _disable_all(self):  
    for item in self.children:  
        item.disabled = True  

def _disable_double(self):  
    for item in self.children:  
        if isinstance(item, discord.ui.Button) and item.label == "Double Down":  
            item.disabled = True  

async def _resolve(self, interaction: discord.Interaction):  
    """Dealer draws to 17+ then settle the hand."""  
    self._disable_all()  

    while hand_value(self.dealer) < 17 and self.deck:  
        self.dealer.append(self.deck.pop())  

    pv = hand_value(self.player)  
    dv = hand_value(self.dealer)  

    if dv > 21:  
        title, desc, payout_mult, color = "🎉 Dealer Busts — You Win!", "Dealer went over 21.", 2, discord.Color.green()  
    elif pv > dv:  
        title, desc, payout_mult, color = "🎉 You Win!", f"**{pv}** beats **{dv}**.", 2, discord.Color.green()  
    elif pv == dv:  
        title, desc, payout_mult, color = "🤝 Push", "It's a tie — bet returned.", 1, discord.Color.yellow()  
    else:  
        title, desc, payout_mult, color = "💀 Dealer Wins", f"**{dv}** beats **{pv}**.", 0, discord.Color.red()  

    payout = self.total_bet * payout_mult  
    net    = payout - self.total_bet  

    current = await get_balance(self.uid)  
    new_bal = current + payout  
    await set_balance(self.uid, new_bal)  

    embed = self._result_embed(title, desc, color, net, new_bal)  
    await interaction.response.edit_message(content=None, embed=embed, view=self)  

async def _bust(self, interaction: discord.Interaction):  
    self._disable_all()  
    pv      = hand_value(self.player)  
    current = await get_balance(self.uid)  
    embed   = make_embed(  
        "🃏 Blackjack", "**💀 Bust! You went over 21.**",  
        discord.Color.red(), "blackjack", self.user,  
        footer=f"Bet: {self.total_bet:,} credits"  
    )  
    embed.add_field(name="🃏 Your Hand",  
                    value=f"{cards_display(self.player)} (**{pv}**)", inline=True)  
    embed.add_field(name="🤖 Dealer",  
                    value=f"`{self.dealer[1]}` | `?`", inline=True)  
    embed.add_field(name="Net",     value=f"-{format_money(self.total_bet)}", inline=True)  
    embed.add_field(name="Balance", value=balance_display(current),           inline=False)  
    await interaction.response.edit_message(content=None, embed=embed, view=self)  

# ── buttons ───────────────────────────────────────────────────────────────  

@discord.ui.button(label="Hit", style=discord.ButtonStyle.primary, emoji="🃏")  
async def hit_btn(self, interaction: discord.Interaction, button: discord.ui.Button):  
    if interaction.user.id != self.uid:  
        await interaction.response.send_message("This isn't your game!", ephemeral=True)  
        return  

    self.player.append(self.deck.pop())  
    pv = hand_value(self.player)  

    if pv > 21:  
        await self._bust(interaction)  
    elif pv == 21:  
        await self._resolve(interaction)  
    else:  
        self._disable_double()  
        await interaction.response.edit_message(embed=self._active_embed(), view=self)  

@discord.ui.button(label="Stand", style=discord.ButtonStyle.secondary, emoji="✋")  
async def stand_btn(self, interaction: discord.Interaction, button: discord.ui.Button):  
    if interaction.user.id != self.uid:  
        await interaction.response.send_message("This isn't your game!", ephemeral=True)  
        return  
    await self._resolve(interaction)  

@discord.ui.button(label="Double Down", style=discord.ButtonStyle.success, emoji="💰")  
async def double_btn(self, interaction: discord.Interaction, button: discord.ui.Button):  
    if interaction.user.id != self.uid:  
        await interaction.response.send_message("This isn't your game!", ephemeral=True)  
        return  

    current = await get_balance(self.uid)  
    if current < self.initial_bet:  
        await interaction.response.send_message(  
            f"You need **{self.initial_bet:,}** credits to double down but only have {balance_display(current)}.",  
            ephemeral=True  
        )  
        return  

    # deduct the extra bet immediately  
    await set_balance(self.uid, current - self.initial_bet)  
    await record_wager(self.uid, self.initial_bet)  
    self.total_bet += self.initial_bet  

    self.player.append(self.deck.pop())  
    pv = hand_value(self.player)  

    if pv > 21:  
        await self._bust(interaction)  
    else:  
        await self._resolve(interaction)  

async def on_timeout(self):  
    self._disable_all()  
    if self.message:  
        try:  
            await self.message.edit(  
                content="⏰ Game timed out — buttons expired.",  
                view=self  
            )  
        except Exception:  
            pass

── interactive mines view ────────────────────────────────────────────────────

class MinesView(discord.ui.View):
"""4×5 grid of tiles (20 total) + Cash Out row. Mines hidden underneath."""

GRID_ROWS = 4  
GRID_COLS = 5  
TOTAL     = GRID_ROWS * GRID_COLS  # 20 tiles  

def __init__(self, uid: int, bet: int, mine_count: int,  
             user: discord.User | discord.Member):  
    super().__init__(timeout=300)  
    self.uid        = uid  
    self.bet        = bet  
    self.mine_count = mine_count  
    self.user       = user  
    self.revealed   = [False] * self.TOTAL  
    self.mines_pos  = set(random.sample(range(self.TOTAL), mine_count))  
    self.safe_found = 0  
    self.game_over  = False  
    self.message: discord.Message | None = None  

    for i in range(self.TOTAL):  
        btn = discord.ui.Button(  
            emoji="💠",  
            style=discord.ButtonStyle.secondary,  
            custom_id=f"mine_tile_{i}",  
            row=i // self.GRID_COLS,  
        )  
        btn.callback = self._make_tile_cb(i)  
        self.add_item(btn)  

    cashout = discord.ui.Button(  
        label="Cash Out",  
        emoji="💰",  
        style=discord.ButtonStyle.success,  
        custom_id="mine_cashout",  
        row=4,  
    )  
    cashout.callback = self._cashout_cb  
    self.add_item(cashout)  

# ── multiplier ────────────────────────────────────────────────────────────  

def mult(self, after: int | None = None) -> float:  
    return mines_multiplier(self.TOTAL, self.mine_count,  
                            self.safe_found if after is None else after)  

# ── embed builders ────────────────────────────────────────────────────────  

def initial_embed(self) -> discord.Embed:  
    embed = make_embed(  
        "💎 Mines",  
        f"**{self.mine_count}** mines hidden across **{self.TOTAL}** tiles.\n"  
        f"Click tiles to reveal gems. Cash out before hitting a mine!",  
        discord.Color.blurple(), "gem", self.user,  
        footer=f"Bet: {self.bet:,} credits • {format_money(self.bet)}",  
    )  
    embed.add_field(name="💣 Mines",       value=str(self.mine_count),              inline=True)  
    embed.add_field(name="💎 Safe Tiles",  value=str(self.TOTAL - self.mine_count), inline=True)  
    embed.add_field(name="First Pick ×",   value=f"**{self.mult(1)}×**",            inline=True)  
    return embed  

def active_embed(self) -> discord.Embed:  
    m      = self.mult()  
    payout = int(self.bet * m)  
    left   = self.TOTAL - self.mine_count - self.safe_found  
    embed  = make_embed(  
        "💎 Mines",  
        f"**{self.safe_found}** gem{'s' if self.safe_found != 1 else ''} found — keep going or cash out!",  
        discord.Color.blurple(), "gem", self.user,  
        footer=f"Bet: {self.bet:,} credits • {self.mine_count} mines • {format_money(self.bet)}",  
    )  
    embed.add_field(name="💎 Found",         value=str(self.safe_found),        inline=True)  
    embed.add_field(name="Multiplier",        value=f"**{m}×**",                 inline=True)  
    embed.add_field(name="💰 Cashout Value",  value=f"**{payout:,}** credits",   inline=True)  
    embed.add_field(name="🔷 Safe Tiles Left",value=str(left),                   inline=True)  
    return embed  

# ── button helpers ────────────────────────────────────────────────────────  

def _tile_btn(self, idx: int) -> discord.ui.Button | None:  
    for item in self.children:  
        if isinstance(item, discord.ui.Button) and item.custom_id == f"mine_tile_{idx}":  
            return item  
    return None  

def _disable_all(self):  
    for item in self.children:  
        item.disabled = True  

def _show_mines(self, triggered: int | None = None):  
    for pos in self.mines_pos:  
        btn = self._tile_btn(pos)  
        if btn and not self.revealed[pos]:  
            btn.emoji    = discord.PartialEmoji.from_str("💥" if pos == triggered else "💣")  
            btn.style    = discord.ButtonStyle.danger  
            btn.disabled = True  

# ── tile callback factory ─────────────────────────────────────────────────  

def _make_tile_cb(self, idx: int):  
    async def _cb(interaction: discord.Interaction):  
        if interaction.user.id != self.uid:  
            await interaction.response.send_message("This isn't your game!", ephemeral=True)  
            return  
        if self.game_over or self.revealed[idx]:  
            await interaction.response.send_message("Already revealed!", ephemeral=True)  
            return  

        await interaction.response.defer()  
        self.revealed[idx] = True  

        if idx in self.mines_pos:  
            await self._hit_mine(interaction, idx)  
        else:  
            self.safe_found += 1  
            btn = self._tile_btn(idx)  
            if btn:  
                btn.emoji    = discord.PartialEmoji.from_str("💎")  
                btn.style    = discord.ButtonStyle.success  
                btn.disabled = True  

            if self.safe_found == self.TOTAL - self.mine_count:  
                await self._auto_win(interaction)  
            else:  
                await interaction.edit_original_response(embed=self.active_embed(), view=self)  
    return _cb  

# ── game event handlers ───────────────────────────────────────────────────  

async def _hit_mine(self, interaction: discord.Interaction, triggered: int):  
    self.game_over = True  
    self._disable_all()  

    # Step 1 — show explosion tile  
    btn = self._tile_btn(triggered)  
    if btn:  
        btn.emoji = discord.PartialEmoji.from_str("💥")  
        btn.style = discord.ButtonStyle.danger  

    boom_embed = make_embed(  
        "💣 Mines", "**BOOM!** 💥  You hit a mine!",  
        discord.Color.red(), "bomb", self.user,  
        footer=f"Bet: {self.bet:,} credits",  
    )  
    await interaction.edit_original_response(embed=boom_embed, view=self)  
    await asyncio.sleep(0.4)  

    # Step 2 — reveal other mines one by one  
    others = [p for p in self.mines_pos if p != triggered]  
    random.shuffle(others)  
    for pos in others:  
        m_btn = self._tile_btn(pos)  
        if m_btn:  
            m_btn.emoji    = discord.PartialEmoji.from_str("💣")  
            m_btn.style    = discord.ButtonStyle.danger  
            m_btn.disabled = True  
        await interaction.edit_original_response(view=self)  
        await asyncio.sleep(0.15)  

    # Step 3 — final result embed  
    await asyncio.sleep(0.25)  
    current_bal = await get_balance(self.uid)  
    result = make_embed(  
        "💣 Mines",  
        f"**BOOM!** You triggered a mine after finding **{self.safe_found}** gem(s).",  
        discord.Color.red(), "bomb", self.user,  
        footer=f"Bet: {self.bet:,} credits • {self.mine_count} mines",  
    )  
    result.add_field(name="💎 Gems Found", value=str(self.safe_found),         inline=True)  
    result.add_field(name="Result",         value="Mine hit — lost your bet",   inline=True)  
    result.add_field(name="Net",            value=f"-{format_money(self.bet)}", inline=True)  
    result.add_field(name="Balance",        value=balance_display(current_bal), inline=False)  
    await interaction.edit_original_response(embed=result, view=self)  

async def _cashout_cb(self, interaction: discord.Interaction):  
    if interaction.user.id != self.uid:  
        await interaction.response.send_message("This isn't your game!", ephemeral=True); return  
    if self.game_over:  
        await interaction.response.send_message("Game is already over!", ephemeral=True); return  
    if self.safe_found == 0:  
        await interaction.response.send_message(  
            "Reveal at least one tile before cashing out!", ephemeral=True); return  

    await interaction.response.defer()  
    self.game_over = True  
    self._disable_all()  
    self._show_mines()  

    m       = self.mult()  
    payout  = int(self.bet * m)  
    net     = payout - self.bet  
    current = await get_balance(self.uid)  
    new_bal = current + payout  
    await set_balance(self.uid, new_bal)  

    result = make_embed(  
        "💎 Mines", f"💰 **Cashed out at {m}×!**",  
        discord.Color.green(), "gem", self.user,  
        footer=f"Bet: {self.bet:,} credits • {self.mine_count} mines",  
    )  
    result.add_field(name="💎 Gems Found", value=str(self.safe_found),                                inline=True)  
    result.add_field(name="Multiplier",     value=f"**{m}×**",                                        inline=True)  
    result.add_field(name="Net",            value=f"+{format_money(net)}",                            inline=True)  
    result.
