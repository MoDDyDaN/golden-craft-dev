"""
Telegram bot для управления лидербордом донатеров Golden Craft.
Поместите в папку с bot.py, установите зависимости, настройте .env и запустите.
"""

import os
import json
import base64
import asyncio
import logging
from datetime import datetime

import requests
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes, CommandHandler

# ── Загрузка конфига ──────────────────────────────────────────────
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")                    # Токен от @BotFather
GH_TOKEN = os.getenv("GH_TOKEN")                      # GitHub Personal Access Token (scope: repo)
REPO_OWNER = os.getenv("REPO_OWNER", "MoDDyDaN")      # Владелец репозитория
REPO_NAME = os.getenv("REPO_NAME", "golden-craft-dev")# Имя репозитория
FILE_PATH = os.getenv("FILE_PATH", "leaderboard.json")# Путь к файлу в репозитории
BRANCH = os.getenv("BRANCH", "main")                  # Ветка
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()}

# Проверки
missing = []
for var, val in [("BOT_TOKEN", BOT_TOKEN), ("GH_TOKEN", GH_TOKEN), ("ADMIN_IDS", ADMIN_IDS)]:
    if not val:
        missing.append(var)
if missing:
    raise SystemExit(f"❌ В .env не заданы: {', '.join(missing)}")

# ── Логирование ───────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger(__name__)

# ── GitHub API helpers ────────────────────────────────────────────
API_BASE = "https://api.github.com"
HEADERS = {
    "Authorization": f"Bearer {GH_TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

def gh_get(path: str):
    r = requests.get(f"{API_BASE}{path}", headers=HEADERS, timeout=15)
    r.raise_for_status()
    return r.json()

def gh_put(path: str, payload: dict):
    r = requests.put(f"{API_BASE}{path}", headers=HEADERS, json=payload, timeout=20)
    r.raise_for_status()
    return r.json()

# ── Работа с лидербордом ──────────────────────────────────────────
def fetch_leaderboard() -> list:
    """Скачивает актуальный leaderboard.json из репозитория."""
    data = gh_get(f"/repos/{REPO_OWNER}/{REPO_NAME}/contents/{FILE_PATH}?ref={BRANCH}")
    content = base64.b64decode(data["content"]).decode("utf-8")
    return json.loads(content)

def commit_leaderboard(new_data: list, message: str) -> bool:
    """Обновляет leaderboard.json в репозитории (создаёт коммит через GitHub API)."""
    # Получаем текущий sha файла
    file_info = gh_get(f"/repos/{REPO_OWNER}/{REPO_NAME}/contents/{FILE_PATH}?ref={BRANCH}")
    sha = file_info["sha"]

    content = json.dumps(new_data, ensure_ascii=False, indent=2)
    encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")

    payload = {
        "message": message,
        "content": encoded,
        "sha": sha,
        "branch": BRANCH,
    }
    gh_put(f"/repos/{REPO_OWNER}/{REPO_NAME}/contents/{FILE_PATH}", payload)
    return True

# ── Форматирование ────────────────────────────────────────────────
def format_leaderboard(data: list) -> str:
    if not data:
        return "📭 Лидерборд пуст."
    lines = ["🏆 <b>Лидерборд донатеров:</b>"]
    medals = ["🥇", "🥈", "🥉"]
    for i, entry in enumerate(data):
        medal = medals[i] if i < 3 else f"{i+1}."
        lines.append(f"{medal} <b>{entry['nick']}</b> — {entry['amount']}₽")
    return "\n".join(lines)

# ── Обработчики бота ──────────────────────────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid in ADMIN_IDS:
        await update.message.reply_html(
            "👋 Привет, админ!\n"
            "Формат ввода: <code>Ник Сумма</code> (например: <code>Steve 150</code>)\n"
            "Команды:\n"
            "  /lb — показать лидерборд\n"
            "  /reset — очистить лидерборд"
        )
    else:
        await update.message.reply_text("👋 Привет! Лидерборд обновляется админами.")

async def cmd_lb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = fetch_leaderboard()
    await update.message.reply_html(format_leaderboard(data))

async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("⛔ Только для админов.")
        return
    commit_leaderboard([], "Reset leaderboard")
    await update.message.reply_text("🗑 Лидерборд очищен.")

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка сообщений: ожидаем 'Ник Сумма' от админа."""
    uid = update.effective_user.id
    if uid not in ADMIN_IDS:
        return  # Игнорируем не-админов

    text = update.message.text.strip()
    parts = text.split()
    if len(parts) != 2:
        await update.message.reply_text(
            "❌ Формат: <code>Ник Сумма</code>\nПример: <code>Steve 150</code>",
            parse_mode="HTML"
        )
        return

    nick, amount_str = parts[0], parts[1]
    if not amount_str.isdigit():
        await update.message.reply_text("❌ Сумма должна быть числом.")
        return

    amount = int(amount_str)
    if amount <= 0:
        await update.message.reply_text("❌ Сумма должна быть положительной.")
        return

    # Загружаем текущий лидерборд, обновляем/добавляем
    data = fetch_leaderboard()
    # Ищем существующий ник
    found = False
    for entry in data:
        if entry["nick"].lower() == nick.lower():
            entry["amount"] += amount
            found = True
            break
    if not found:
        data.append({"nick": nick, "amount": amount})

    # Сортируем по убыванию суммы
    data.sort(key=lambda x: x["amount"], reverse=True)

    # Коммитим
    commit_leaderboard(data, f"Update leaderboard: {nick} +{amount}₽ ({datetime.now():%Y-%m-%d %H:%M})")

    await update.message.reply_html(
        f"✅ Обновлено: <b>{nick}</b> +{amount}₽\n\n{format_leaderboard(data)}"
    )

# ── Запуск ────────────────────────────────────────────────────────
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("lb", cmd_lb))
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    log.info("🤖 Бот запущен. Ожидаю сообщения...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()