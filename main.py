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
    get_last_daily, set_last_daily, get_lifetime_stats, add_withdrawal
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
intents.message_content = True
bot = commands.Bot(command_prefix=".", intents=intents, help_command=None)


def format_money(pts: int) -> str:
    return f"${pts * POINT_VALUE:,.2f}"

def balance_display(pts: int) -> str:
    return f"**{pts:,}** credits ({format_money(pts)})"

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


@bot.event
async def on_ready():
    await init_db()
    await bot.tree.sync()
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    print("Bot is ready!")


@bot.command(name="balance", aliases=["bal"])
async def prefix_balance(ctx: commands.Context):
    uid = ctx.author.id
    bal, wager = await get_balance(uid), await get_wager_req(uid)
    embed = make_embed("💰 Balance", balance_display(bal), discord.Color.gold(),
                       "money", ctx.author, footer=f"1 credit = {format_money(1)}")
    if wager > 0:
        embed.add_field(name="⚠️ Wager Requirement",
                        value=f"Must wager **{wager:,}** more credits before withdrawing.", inline=False)
    await ctx.send(embed=embed)


@bot.command(name="stats")
async def prefix_stats(ctx: commands.Context, user: discord.User | None = None):
    """View casino profile and lifetime statistics."""
    target_user = user or ctx.author
    uid = target_user.id
    
    bal = await get_balance(uid)
    stats = await get_lifetime_stats(uid)
    remaining = DAILY_COOLDOWN - (int(time.time()) - await get_last_daily(uid))
    
    embed = discord.Embed(
        title=f"🎰 {target_user.display_name} Casino Profile",
        color=discord.Color.gold()
    )
    embed.set_thumbnail(url=target_user.display_avatar.url)
    
    daily_status = f"⏳ Ready in {seconds_to_hms(remaining)}" if remaining > 0 else "✅ Ready to claim"
    embed.add_field(
        name="💰 Main Balance",
        value=f"{balance_display(bal)}\n🎁 Daily Reward: {daily_status}",
        inline=False
    )
    
    embed.add_field(
        name="──────── LIFETIME STATISTICS ────────",
        value="** **",
        inline=False
    )
    embed.add_field(
        name="🎲 Games Played",
        value=str(stats["games_played"]),
        inline=True
    )
    embed.add_field(
        name="🏆 Games Won",
        value=str(stats["games_won"]),
        inline=True
    )
    embed.add_field(
        name="💀 Games Lost",
        value=str(stats["games_lost"]),
        inline=True
    )
    embed.add_field(
        name="💸 Total Wagered",
        value=f"**{stats['total_wagered']:,}** ({format_money(stats['total_wagered'])})",
        inline=True
    )
    embed.add_field(
        name="🎁 Bonus Received",
        value=f"**{stats['promo_received']:,}** ({format_money(stats['promo_received'])})",
        inline=True
    )
    embed.add_field(
        name="📤 Tips Sent",
        value=f"**{stats['tips_sent']:,}** ({format_money(stats['tips_sent'])})",
        inline=True
    )
    embed.add_field(
        name="📥 Tips Received",
        value=f"**{stats['tips_received']:,}** ({format_money(stats['tips_received'])})",
        inline=True
    )
    embed.add_field(
        name="🏦 Total Withdrawn",
        value=f"**{stats['total_withdrawn']:,}** ({format_money(stats['total_withdrawn'])})",
        inline=True
    )
    
    embed.set_footer(text=f"Requested by {ctx.author.display_name}")
    await ctx.send(embed=embed)


@bot.command(name="coinflip", aliases=["cf", "flip"])
async def prefix_coinflip(ctx: commands.Context, bet: int = 0, side: str = ""):
    side = side.lower()
    side = {"h": "heads", "t": "tails"}.get(side, side)
    if side not in ("heads", "tails") or bet <= 0:
        await ctx.send("Usage: `.cf <amount> <heads|tails>`  e.g. `.cf 100 h`")
        return
    
    balance = await get_balance(ctx.author.id)
    if err := validate_bet(bet, balance):
        await ctx.send(err)
        return
    
    msg = await ctx.send("🪙 Flipping the coin...")
    
    for frame in ["🔵 Heads?", "⚪ Tails?", "🔵 Heads?", "⚪ Tails?", "🔵 Heads?", "⚪ Tails?"]:
        await msg.edit(content=f"🪙 {frame}")
        await asyncio.sleep(0.35)

    won, message, new_balance = coinflip(side, bet, balance)
    await set_balance(ctx.author.id, new_balance)
    await record_wager(ctx.author.id, bet)

    embed = make_embed("🪙 Coin Flip", message,
                       discord.Color.green() if won else discord.Color.red(),
                       "coin", ctx.author,
                       footer=f"Bet: {bet:,} credits • {format_money(bet)}")
    embed.add_field(name="Result",      value="🏆 You won!" if won else "💀 You lost.", inline=True)
    embed.add_field(name="Net",         value=f"+{format_money(bet)}" if won else f"-{format_money(bet)}", inline=True)
    embed.add_field(name="New Balance", value=balance_display(new_balance), inline=False)
    await msg.edit(content=None, embed=embed)


@bot.command(name="slots", aliases=["slot", "spin"])
async def prefix_slots(ctx: commands.Context, bet: int = 0):
    balance = await get_balance(ctx.author.id)
    if err := validate_bet(bet, balance):
        await ctx.send(err)
        return
    
    msg = await ctx.send("🎰 Spinning the reels...")
    
    won, roll, payout, new_balance = slots(bet, balance)
    await set_balance(ctx.author.id, new_balance)
    await record_wager(ctx.author.id, bet)

    spin = lambda: random.choice(SLOT_SYMBOLS)
    for _ in range(4):
        await msg.edit(content=f"🎰  {spin()} | {spin()} | {spin()}")
        await asyncio.sleep(0.35)
    for _ in range(2):
        await msg.edit(content=f"🎰  **{roll[0]}** | {spin()} | {spin()}")
        await asyncio.sleep(0.35)
    for _ in range(2):
        await msg.edit(content=f"🎰  **{roll[0]}** | **{roll[1]}** | {spin()}")
        await asyncio.sleep(0.35)
    await msg.edit(content=f"🎰  **{roll[0]}** | **{roll[1]}** | **{roll[2]}**")
    await asyncio.sleep(0.5)

    net = payout - bet
    if payout == 0:
        result_text, color = f"No match — lost **{bet:,}** credits.", discord.Color.red()
    elif len(set(roll)) == 1:
        result_text, color = f"🎉 JACKPOT! ×{payout // bet} multiplier!", discord.Color.gold()
    else:
        result_text, color = "Two of a kind! ×2 multiplier.", discord.Color.green()

    embed = make_embed("🎰 Slot Machine", f"# {roll[0]}  {roll[1]}  {roll[2]}",
                       color, "slots", ctx.author,
                       footer=f"Bet: {bet:,} credits • {format_money(bet)}")
    embed.add_field(name="Result",      value=result_text,                   inline=False)
    embed.add_field(name="Payout",      value=f"**{payout:,}** credits",     inline=True)
    embed.add_field(name="Net",         value=(f"+{format_money(net)}" if net >= 0 else f"-{format_money(abs(net))}"), inline=True)
    embed.add_field(name="New Balance", value=balance_display(new_balance),  inline=False)
    await msg.edit(content=None, embed=embed)


@bot.command(name="blackjack", aliases=["bj"])
async def prefix_blackjack(ctx: commands.Context, bet: int = 0):
    balance = await get_balance(ctx.author.id)
    if err := validate_bet(bet, balance):
        await ctx.send(err)
        return
    
    await set_balance(ctx.author.id, balance - bet)
    await record_wager(ctx.author.id, bet)

    player, dealer, deck = blackjack_deal()
    player_val = hand_value(player)
    dealer_val = hand_value(dealer)

    msg = await ctx.send("🃏 Dealing cards...")
    await asyncio.sleep(0.4)
    await msg.edit(content=f"🃏  Your hand: `{player[0]}`\n🤖  Dealer shows: `?`")
    await asyncio.sleep(0.5)
    await msg.edit(content=f"🃏  Your hand: `{player[0]}` `{player[1]}`\n🤖  Dealer shows: `?`")
    await asyncio.sleep(0.5)
    await msg.edit(content=f"🃏  Your hand: `{player[0]}` `{player[1]}` = **{player_val}**\n🤖  Dealer shows: `{dealer[1]}`")
    await asyncio.sleep(0.6)

    if player_val == 21:
        payout = int(bet * 1.5)
        new_bal = balance - bet + bet + payout
        await set_balance(ctx.author.id, new_bal)
        embed = make_embed("🃏 Blackjack", "🎉 **BLACKJACK! Natural 21!**",
                           discord.Color.gold(), "blackjack", ctx.author,
                           footer=f"Bet: {bet:,} credits • 1.5× payout")
        embed.add_field(name="🃏 Your Hand",   value=f"{cards_display(player)} (**21**)",       inline=True)
        embed.add_field(name="🤖 Dealer Hand", value=f"{cards_display(dealer)} ({dealer_val})", inline=True)
        embed.add_field(name="Payout",         value=f"+**{payout:,}** credits ({format_money(payout)})", inline=False)
        embed.add_field(name="New Balance",    value=balance_display(new_bal),                  inline=False)
        await msg.edit(content=None, embed=embed)
        return

    await msg.edit(content="🃏 Blackjack - Natural 21! You win!")


@bot.command(name="daily")
async def prefix_daily(ctx: commands.Context):
    uid       = ctx.author.id
    remaining = DAILY_COOLDOWN - (int(time.time()) - await get_last_daily(uid))
    if remaining > 0:
        embed = make_embed("⏳ Already Claimed", f"Come back in **{seconds_to_hms(remaining)}**.",
                           discord.Color.orange(), "gift", ctx.author)
        await ctx.send(embed=embed)
        return
    
    bal     = await get_balance(uid)
    new_bal = bal + DAILY_BONUS
    await set_balance(uid, new_bal)
    await set_last_daily(uid)
    embed = make_embed("🎁 Daily Bonus",
                       f"You claimed **{DAILY_BONUS}** credits ({format_money(DAILY_BONUS)})!",
                       discord.Color.blurple(), "gift", ctx.author,
                       footer="Next claim available in 24 hours.")
    embed.add_field(name="New Balance", value=balance_display(new_bal), inline=False)
    await ctx.send(embed=embed)


@bot.command(name="transfer", aliases=["send", "give"])
async def prefix_transfer(ctx: commands.Context, user: discord.User = None, amount: int = 0):
    if not user:
        await ctx.send("Usage: `.transfer @user 100`")
        return
    if user.id == ctx.author.id:
        await ctx.send("You can't transfer to yourself.")
        return
    if user.bot:
        await ctx.send("You can't transfer to a bot.")
        return
    if amount <= 0:
        await ctx.send("Amount must be greater than 0.")
        return
    
    sb = await get_balance(ctx.author.id)
    if amount > sb:
        await ctx.send(f"You only have {balance_display(sb)}.")
        return
    
    rb = await get_balance(user.id)
    await set_balance(ctx.author.id, sb - amount)
    await set_balance(user.id, rb + amount)
    embed = make_embed("💸 Transfer Successful",
                       f"Sent **{amount:,}** credits ({format_money(amount)}) to {user.mention}.",
                       discord.Color.green(), "transfer", ctx.author)
    embed.add_field(name="Your Balance",          value=balance_display(sb - amount), inline=True)
    embed.add_field(name=f"{user.name}'s Balance", value=balance_display(rb + amount), inline=True)
    await ctx.send(embed=embed)


@bot.command(name="leaderboard", aliases=["lb", "top"])
async def prefix_leaderboard(ctx: commands.Context):
    rows = await get_leaderboard(10)
    if not rows:
        await ctx.send("No players yet!")
        return
    
    medals = ["🥇", "🥈", "🥉"]
    lines  = [f"{medals[i] if i < 3 else f'`{i+1}.`'}  <@{uid}> — {balance_display(bal)}"
              for i, (uid, bal) in enumerate(rows)]
    embed = make_embed("🏆 Leaderboard", "\n".join(lines), discord.Color.gold(), "trophy",
                       footer=f"1 credit = {format_money(1)}")
    await ctx.send(embed=embed)


@bot.command(name="withdraw", aliases=["wd"])
async def prefix_withdraw(ctx: commands.Context):
    uid   = ctx.author.id
    bal   = await get_balance(uid)
    wager = await get_wager_req(uid)
    if wager > 0:
        pct = max(0, 100 - int(wager / max(bal + wager, 1) * 100))
        bar = "█" * (pct // 10) + "░" * (10 - pct // 10)
        embed = make_embed("🏦 Withdraw Status",
                           f"Wager **{wager:,}** more credits to unlock withdrawal.",
                           discord.Color.orange(), "bank", ctx.author)
        embed.add_field(name="Progress", value=f"`[{bar}]` {pct}%", inline=False)
        embed.add_field(name="Balance",  value=balance_display(bal), inline=False)
    else:
        embed = make_embed("🏦 Withdraw Status",
                           f"✅ Clear to withdraw **{bal:,}** credits ({format_money(bal)})!",
                           discord.Color.green(), "bank", ctx.author,
                           footer="Contact an admin to process your withdrawal.")
    await ctx.send(embed=embed)


@bot.command(name="adminwithdraw", aliases=["aw", "withdrawupdate"])
@commands.has_permissions(administrator=True)
async def prefix_adminwithdraw(ctx: commands.Context, user: discord.User | None = None, amount: int = 0):
    """[Admin] Manually record a withdrawal for a user."""
    if not user:
        await ctx.send("Usage: `.adminwithdraw @user <amount>`")
        return
    if amount <= 0:
        await ctx.send("Amount must be greater than 0.")
        return
    
    await add_withdrawal(user.id, amount)
    stats = await get_lifetime_stats(user.id)
    
    embed = make_embed(
        "🏦 Withdrawal Recorded",
        f"Recorded **{amount:,}** credits ({format_money(amount)}) withdrawal for {user.mention}.",
        discord.Color.green(), "bank",
        footer=f"Updated by {ctx.author.display_name}"
    )
    embed.add_field(
        name="Amount",
        value=f"**{amount:,}** ({format_money(amount)})",
        inline=True
    )
    embed.add_field(
        name="Total Withdrawn",
        value=f"**{stats['total_withdrawn']:,}** ({format_money(stats['total_withdrawn'])})",
        inline=True
    )
    await ctx.send(embed=embed)


@prefix_adminwithdraw.error
async def adminwithdraw_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Administrator permission required.")


@bot.command(name="addbal", aliases=["ab"])
@commands.has_permissions(administrator=True)
async def prefix_addbal(ctx: commands.Context, user: discord.User = None, amount: int = 0):
    if not user:
        await ctx.send("Usage: `.addbal @user <amount>`")
        return
    if amount <= 0:
        await ctx.send("Amount must be greater than 0.")
        return
    
    bal     = await get_balance(user.id)
    new_bal = bal + amount
    await set_balance(user.id, new_bal)
    embed = make_embed(
        "✅ Balance Added",
        f"Added **{amount:,}** credits ({format_money(amount)}) to {user.mention}.",
        discord.Color.green(), "money",
        footer=f"Done by {ctx.author.display_name}",
    )
    embed.add_field(name="Before", value=balance_display(bal),     inline=True)
    embed.add_field(name="After",  value=balance_display(new_bal), inline=True)
    await ctx.send(embed=embed)


@prefix_addbal.error
async def addbal_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Administrator permission required.")


@bot.command(name="removebal", aliases=["rmbal", "rb"])
@commands.has_permissions(administrator=True)
async def prefix_removebal(ctx: commands.Context, user: discord.User = None, amount: int = 0):
    if not user:
        await ctx.send("Usage: `.removebal @user <amount>`")
        return
    if amount <= 0:
        await ctx.send("Amount must be greater than 0.")
        return
    
    bal     = await get_balance(user.id)
    new_bal = max(0, bal - amount)
    removed = bal - new_bal
    await set_balance(user.id, new_bal)
    embed = make_embed(
        "❌ Balance Removed",
        f"Removed **{removed:,}** credits ({format_money(removed)}) from {user.mention}.",
        discord.Color.red(), "money",
        footer=f"Done by {ctx.author.display_name}",
    )
    embed.add_field(name="Before", value=balance_display(bal),     inline=True)
    embed.add_field(name="After",  value=balance_display(new_bal), inline=True)
    await ctx.send(embed=embed)


@prefix_removebal.error
async def removebal_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Administrator permission required.")


@bot.command(name="help", aliases=["h", "commands", "cmds"])
async def prefix_help(ctx: commands.Context):
    embed = discord.Embed(
        title="🎰 LuckyBet — Command List",
        description=(
            "Use `.` prefix for all commands below.\n"
            f"**1 credit = {format_money(1)}**"
        ),
        color=discord.Color.gold(),
    )
    embed.set_thumbnail(url=IMG["trophy"])
    embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)

    embed.add_field(
        name="🎮 Games",
        value=(
            "`.cf <amt> <h|t>` — Coin flip\n"
            "`.slots <amt>` — Slot machine\n"
            "`.bj <amt>` — Blackjack\n"
        ),
        inline=False,
    )
    embed.add_field(
        name="💰 Economy",
        value=(
            "`.bal` — Check your balance\n"
            "`.stats` — View your casino profile\n"
            "`.daily` — Claim 2 free credits (24h cooldown)\n"
            "`.transfer @user <amt>` — Send credits\n"
            "`.withdraw` — Check withdrawal eligibility\n"
            "`.lb` — Top 10 richest players\n"
        ),
        inline=False,
    )
    embed.add_field(
        name="🛠️ Admin Only",
        value=(
            "`.addbal @user <amt>` — Add credits (`.ab`)\n"
            "`.removebal @user <amt>` — Remove credits (`.rmbal` `.rb`)\n"
            "`.adminwithdraw @user <amt>` — Record withdrawal (`.aw`)"
        ),
        inline=False,
    )
    embed.set_footer(text="LuckyBet Casino • 1 credit = $0.01")
    await ctx.send(embed=embed)


if __name__ == "__main__":
    keep_alive()
    bot.run(os.getenv("TOKEN"))
