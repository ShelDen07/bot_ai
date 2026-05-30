import os
import time
import sqlite3
from dotenv import load_dotenv

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from groq import Groq

# ================= ENV =================
load_dotenv()

TOKEN = os.getenv("TELEGRAM_TOKEN")
GROQ_KEY = os.getenv("GROQ_API_KEY")
ADMIN_ID = os.getenv("ADMIN_ID")

if not TOKEN or not GROQ_KEY:
    raise Exception("❌ .env не заполнен")

client = Groq(api_key=GROQ_KEY)

# ================= DB =================
conn = sqlite3.connect("final_bot.db", check_same_thread=False)
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    mode TEXT,
    messages INTEGER DEFAULT 0,
    last_request REAL DEFAULT 0
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT,
    role TEXT,
    content TEXT
)
""")

conn.commit()

# ================= AI MODES =================
MODES = {
    "assistant": "Ты умный, краткий AI ассистент.",
    "friend": "Ты дружелюбный собеседник.",
    "strict": "Ты строгий учитель, отвечай коротко."
}

DAILY_LIMIT = 50  # лимит сообщений в день (можно менять)

# ================= DB HELPERS =================
def get_user(user_id):
    cur.execute("SELECT mode, messages, last_request FROM users WHERE user_id=?", (user_id,))
    row = cur.fetchone()

    if not row:
        cur.execute("INSERT INTO users VALUES (?, ?, ?, ?)", (user_id, "assistant", 0, 0))
        conn.commit()
        return "assistant", 0, 0

    return row


def update_user(user_id, **kwargs):
    fields = ", ".join([f"{k}=?" for k in kwargs])
    values = list(kwargs.values())
    values.append(user_id)

    cur.execute(f"UPDATE users SET {fields} WHERE user_id=?", values)
    conn.commit()


def add_history(user_id, role, content):
    cur.execute(
        "INSERT INTO history (user_id, role, content) VALUES (?, ?, ?)",
        (user_id, role, content)
    )
    conn.commit()


def get_history(user_id, limit=12):
    cur.execute(
        "SELECT role, content FROM history WHERE user_id=? ORDER BY id DESC LIMIT ?",
        (user_id, limit)
    )
    rows = cur.fetchall()
    return list(reversed(rows))


def clear_user(user_id):
    cur.execute("DELETE FROM history WHERE user_id=?", (user_id,))
    cur.execute("UPDATE users SET messages=0 WHERE user_id=?", (user_id,))
    conn.commit()


def is_admin(user_id):
    return str(user_id) == str(ADMIN_ID)

# ================= AI =================
def ask_ai(user_id, text):
    try:
        mode, messages, last_req = get_user(user_id)

        # лимит
        if messages >= DAILY_LIMIT:
            return "⚠️ дневной лимит исчерпан"

        system = MODES.get(mode, MODES["assistant"])

        history = get_history(user_id)

        messages_payload = [{"role": "system", "content": system}]

        for r, c in history:
            messages_payload.append({"role": r, "content": c})

        messages_payload.append({"role": "user", "content": text})

        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=messages_payload,
            temperature=0.7
        )

        answer = response.choices[0].message.content

        add_history(user_id, "user", text)
        add_history(user_id, "assistant", answer)

        update_user(user_id, messages=messages + 1)

        return answer[:4000]

    except Exception as e:
        return f"❌ AI error: {e}"

# ================= COMMANDS =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🚀 FINAL AI BOT\n\n"
        "/mode assistant | friend | strict\n"
        "/reset\n"
        "/stats\n"
        "/admin_stats (admin only)"
    )


async def mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)

    if not context.args:
        await update.message.reply_text("используй /mode assistant|friend|strict")
        return

    m = context.args[0]

    if m not in MODES:
        await update.message.reply_text("❌ нет такого режима")
        return

    update_user(user_id, mode=m)

    await update.message.reply_text(f"✅ режим: {m}")


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    clear_user(user_id)
    await update.message.reply_text("🧹 очищено")


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    mode, messages, _ = get_user(user_id)

    await update.message.reply_text(
        f"📊 режим: {mode}\n"
        f"💬 сообщений: {messages}/{DAILY_LIMIT}"
    )


async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id

    if not is_admin(user_id):
        await update.message.reply_text("⛔ нет доступа")
        return

    cur.execute("SELECT COUNT(*) FROM users")
    users = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM history")
    msgs = cur.fetchone()[0]

    await update.message.reply_text(
        f"👥 users: {users}\n"
        f"💬 messages: {msgs}"
    )

# ================= HANDLER =================
async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.message.from_user.id)
    text = update.message.text

    mode, messages, last_req = get_user(user_id)

    # антиспам (2 сек)
    now = time.time()
    if now - last_req < 2:
        await update.message.reply_text("⏳ подожди 2 сек")
        return

    update_user(user_id, last_request=now)

    print("USER:", text)

    answer = ask_ai(user_id, text)

    print("AI:", answer)

    await update.message.reply_text(answer)

# ================= RUN =================
def main():
    print("🚀 FINAL LEVEL BOT STARTED")

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("mode", mode))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("admin_stats", admin_stats))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))

    print("✅ RUNNING 24/7 READY")
    app.run_polling()


if __name__ == "__main__":
    main()