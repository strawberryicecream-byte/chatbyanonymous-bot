# bot.py
import os
import asyncio
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters, ContextTypes
)

# لازم تحط TELEGRAM_TOKEN في Environment Variables على Render
TOKEN = os.environ.get("TELEGRAM_TOKEN")
if not TOKEN:
    raise RuntimeError("Set TELEGRAM_TOKEN env variable before running.")

waiting = []
active = {}
lock = asyncio.Lock()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = user.id

    async with lock:
        if uid in active:
            await update.message.reply_text("أنت بالفعل في محادثة. اكتب /end لإنهائها.")
            return
        if waiting and waiting[0] != uid:
            partner = waiting.pop(0)
            active[uid] = partner
            active[partner] = uid
            await context.bot.send_message(partner, "📩 جالك شريك مجهول! ابدأ الدردشة.")
            await update.message.reply_text("📩 تم وصلّك بشريك مجهول! ابدأ الدردشة.")
        else:
            if uid not in waiting:
                waiting.append(uid)
            await update.message.reply_text("⏳ مستني شريك... اكتب /end لو عايز تلغي الانتظار.")

async def end(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    async with lock:
        if uid in active:
            partner = active.pop(uid)
            active.pop(partner, None)
            await update.message.reply_text("❌ انتهت المحادثة.")
            try:
                await context.bot.send_message(partner, "❌ انتهت المحادثة من الطرف الآخر.")
            except:
                pass
        else:
            if uid in waiting:
                waiting.remove(uid)
                await update.message.reply_text("🛑 تم إلغاء الانتظار.")
            else:
                await update.message.reply_text("أنت مش في محادثة حالياً.")

async def forward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in active:
        await update.message.reply_text("أنت مش مربوط بأي شريك. اكتب /start للانتظار.")
        return

    partner = active.get(uid)
    if not partner:
        await update.message.reply_text("حصل خطأ، حاول /end ثم /start.")
        return

    try:
        await update.message.copy(chat_id=partner)
    except Exception:
        await update.message.reply_text("مفيش وصول للشريك دلوقتي. اكتب /end وعاود المحاولة.")
        async with lock:
            active.pop(uid, None)
            active.pop(partner, None)

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "/start - ابحث عن شريك\n/end - أنهِ المحادثة أو ألغِ الانتظار\n/help - اوامر المساعدة\n\nملاحظة: لا نخزن رسائلك في أي مكان دائم."
    )

def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("end", end))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, forward))

    print("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
