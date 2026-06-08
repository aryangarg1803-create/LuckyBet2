# ===== db.py =====
import time
import aiosqlite
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "data.db")

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS balances (
                user_id    INTEGER PRIMARY KEY,
                balance    INTEGER NOT NULL DEFAULT 1000,
                last_daily INTEGER NOT NULL DEFAULT 0,
                wager_req  INTEGER NOT NULL DEFAULT 0
            )
        """)
        for col, default in [("last_daily", 0), ("wager_req", 0)]:
            try:
                await db.execute(f"ALTER TABLE balances ADD COLUMN {col} INTEGER NOT NULL DEFAULT {default}")
            except Exception:
                pass
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS stats (
                user_id          INTEGER PRIMARY KEY,
                games_played     INTEGER NOT NULL DEFAULT 0,
                games_won        INTEGER NOT NULL DEFAULT 0,
                games_lost       INTEGER NOT NULL DEFAULT 0,
                total_wagered    INTEGER NOT NULL DEFAULT 0,
                promo_received   INTEGER NOT NULL DEFAULT 0,
                tips_sent        INTEGER NOT NULL DEFAULT 0,
                tips_received    INTEGER NOT NULL DEFAULT 0,
                total_withdrawn  INTEGER NOT NULL DEFAULT 0
            )
        """)
        await db.commit()

async def _ensure_row(db, user_id: int):
    await db.execute(
        "INSERT OR IGNORE INTO balances (user_id, balance) VALUES (?, 1000)",
        (user_id,)
    )

async def _ensure_stats_row(db, user_id: int):
    await db.execute(
        "INSERT OR IGNORE INTO stats (user_id) VALUES (?)",
        (user_id,)
    )

async def get_balance(user_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT balance FROM balances WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
            return row[0] if row else 1000

async def set_balance(user_id: int, amount: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await _ensure_row(db, user_id)
        await db.execute("UPDATE balances SET balance = ? WHERE user_id = ?", (amount, user_id))
        await db.commit()

async def record_wager(user_id: int, amount: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await _ensure_row(db, user_id)
        await db.execute("""
            UPDATE balances
            SET wager_req = MAX(0, wager_req - ?)
            WHERE user_id = ?
        """, (amount, user_id))
        await db.commit()

async def get_wager_req(user_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT wager_req FROM balances WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0

async def add_wager_req(user_id: int, amount: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await _ensure_row(db, user_id)
        await db.execute("UPDATE balances SET wager_req = wager_req + ? WHERE user_id = ?", (amount, user_id))
        await db.commit()

async def get_last_daily(user_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT last_daily FROM balances WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0

async def set_last_daily(user_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await _ensure_row(db, user_id)
        await db.execute("UPDATE balances SET last_daily = ? WHERE user_id = ?", (int(time.time()), user_id))
        await db.commit()

async def get_leaderboard(limit: int = 10) -> list[tuple[int, int]]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT user_id, balance FROM balances ORDER BY balance DESC LIMIT ?", (limit,)
        ) as cur:
            return await cur.fetchall()

async def get_lifetime_stats(user_id: int) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        await _ensure_stats_row(db, user_id)
        async with db.execute(
            """SELECT games_played, games_won, games_lost, total_wagered, 
                      promo_received, tips_sent, tips_received, total_withdrawn 
               FROM stats WHERE user_id = ?""",
            (user_id,)
        ) as cur:
            row = await cur.fetchone()
            if row:
                return {
                    "games_played": row[0],
                    "games_won": row[1],
                    "games_lost": row[2],
                    "total_wagered": row[3],
                    "promo_received": row[4],
                    "tips_sent": row[5],
                    "tips_received": row[6],
                    "total_withdrawn": row[7],
                }
            return {
                "games_played": 0,
                "games_won": 0,
                "games_lost": 0,
                "total_wagered": 0,
                "promo_received": 0,
                "tips_sent": 0,
                "tips_received": 0,
                "total_withdrawn": 0,
            }

async def record_game(user_id: int, won: bool, wagered: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await _ensure_stats_row(db, user_id)
        await db.execute(
            """UPDATE stats
               SET games_played = games_played + 1,
                   games_won = games_won + ?,
                   games_lost = games_lost + ?,
                   total_wagered = total_wagered + ?
               WHERE user_id = ?""",
            (1 if won else 0, 0 if won else 1, wagered, user_id)
        )
        await db.commit()

async def add_promo_received(user_id: int, amount: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await _ensure_stats_row(db, user_id)
        await db.execute(
            "UPDATE stats SET promo_received = promo_received + ? WHERE user_id = ?",
            (amount, user_id)
        )
        await db.commit()

async def add_tip_sent(user_id: int, amount: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await _ensure_stats_row(db, user_id)
        await db.execute(
            "UPDATE stats SET tips_sent = tips_sent + ? WHERE user_id = ?",
            (amount, user_id)
        )
        await db.commit()

async def add_tip_received(user_id: int, amount: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await _ensure_stats_row(db, user_id)
        await db.execute(
            "UPDATE stats SET tips_received = tips_received + ? WHERE user_id = ?",
            (amount, user_id)
        )
        await db.commit()

async def add_withdrawal(user_id: int, amount: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await _ensure_stats_row(db, user_id)
        await db.execute(
            "UPDATE stats SET total_withdrawn = total_withdrawn + ? WHERE user_id = ?",
            (amount, user_id)
        )
        await db.commit()
