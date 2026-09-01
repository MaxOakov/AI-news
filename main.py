import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ApplicationBuilder, CallbackQueryHandler, CommandHandler, ContextTypes

import app.config as config

load_dotenv()

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

MODEL_OPTIONS = [
    "gemini-2.5-flash",
    "gemini-3.1-flash-lite-preview",
]
ENV_PATH = Path(__file__).resolve().parent / ".env"


def update_gemini_model_in_env(model: str) -> bool:
    try:
        if ENV_PATH.exists():
            lines = ENV_PATH.read_text(encoding='utf-8', errors='ignore').splitlines()
        else:
            lines = []

        updated_lines = []
        found = False
        for line in lines:
            if line.strip().startswith("GEMINI_MODEL="):
                updated_lines.append(f"GEMINI_MODEL={model}")
                found = True
            else:
                updated_lines.append(line)

        if not found:
            updated_lines.append(f"GEMINI_MODEL={model}")

        ENV_PATH.write_text("\n".join(updated_lines) + "\n", encoding='utf-8')
        os.environ["GEMINI_MODEL"] = model
        config.GEMINI_MODEL = model
        return True
    except Exception:
        return False


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(chat_id=update.effective_chat.id, text="I'm a bot, please talk to me!")


async def gemini_version(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(option, callback_data=f"set_model:{option}")]
        for option in MODEL_OPTIONS
    ])

    await update.message.reply_text(
        text=(f"Поточна модель Gemini {config.GEMINI_MODEL}\n"
              "Оберіть модель, щоб оновити .env."),
        reply_markup=keyboard,
    )


async def set_model_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    callback_query = update.callback_query
    await callback_query.answer()

    data = callback_query.data or ""
    if not data.startswith("set_model:"):
        await callback_query.edit_message_text(text="Невірна команда вибору моделі.")
        return

    model = data.split(":", 1)[1]
    if model not in MODEL_OPTIONS:
        await callback_query.edit_message_text(text="Оберіть, будь ласка, одну з доступних моделей.")
        return

    if update_gemini_model_in_env(model):
        await callback_query.edit_message_text(
            text=f"Модель оновлено на {model}. Файл .env перезаписано."
        )
    else:
        await callback_query.edit_message_text(
            text="Не вдалося оновити файл .env. Спробуйте пізніше."
        )


if __name__ == '__main__':
    application = ApplicationBuilder().token(config.TELEGRAM_TOKEN).build()

    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('gemini_version', gemini_version))
    application.add_handler(CallbackQueryHandler(set_model_callback, pattern=r'^set_model:'))

    application.run_polling()