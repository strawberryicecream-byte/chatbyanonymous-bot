# bot.py (Final Stable Version - Rebuilt from User's Working Code)
import os
import asyncio
import random
import threading
import time
import requests
import sqlite3
from datetime import datetime, timedelta
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    filters, ContextTypes
)

# --- CONFIGURATION ---
TOKEN = os.environ.get("TELEGRAM_TOKEN")
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID")
TMDB_API_KEY = os.environ.get("TMDB_API_KEY")

if not TOKEN: raise RuntimeError("FATAL: TELEGRAM_TOKEN not set.")
if ADMIN_CHAT_ID: ADMIN_CHAT_ID = int(ADMIN_CHAT_ID)
if not TMDB_API_KEY: print("WARNING: TMDB_API_KEY not set. Movie/Anime suggestions will use a basic list.")

# --- PROMO CODES DICTIONARY (WITH NEW CODE) ---
PROMO_CODES = {
    "WELCOME10": 10, "SPECIALGIFT": 25, "WEEKEND5": 5, "ULTIMATEVIP2024": 200
}

# --- DATABASE SETUP ---
def db_connect(): return sqlite3.connect('users.db', check_same_thread=False)
def setup_database():
    conn = db_connect()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY, first_name TEXT, age TEXT, region TEXT, gender TEXT,
            points INTEGER DEFAULT 5, reputation_score REAL DEFAULT 7.0, total_chats INTEGER DEFAULT 0,
            positive_ratings INTEGER DEFAULT 0
        )''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS redeemed_codes (
            user_id INTEGER, code TEXT, PRIMARY KEY (user_id, code)
        )''')
    conn.commit(); conn.close(); print("Database setup complete.")

def get_user(user_id):
    conn = db_connect(); conn.row_factory = sqlite3.Row; cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)); user_data = cursor.fetchone(); conn.close()
    return dict(user_data) if user_data else None
def add_user(user_id, first_name):
    if get_user(user_id): return False
    conn = db_connect(); cursor = conn.cursor()
    cursor.execute("INSERT INTO users (user_id, first_name, points) VALUES (?, ?, 5)", (user_id, first_name)); conn.commit(); conn.close()
    return True
def update_user(user_id, field, value):
    conn = db_connect(); cursor = conn.cursor()
    cursor.execute(f"UPDATE users SET {field} = ? WHERE user_id = ?", (value, user_id)); conn.commit(); conn.close()
def grant_points(user_id, amount):
    conn = db_connect(); cursor = conn.cursor()
    cursor.execute("UPDATE users SET points = points + ? WHERE user_id = ?", (amount, user_id)); conn.commit(); conn.close()
def has_redeemed_code(user_id, code):
    conn = db_connect(); cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM redeemed_codes WHERE user_id = ? AND code = ?", (user_id, code)); result = cursor.fetchone(); conn.close()
    return result is not None
def mark_code_as_redeemed(user_id, code):
    conn = db_connect(); cursor = conn.cursor()
    cursor.execute("INSERT INTO redeemed_codes (user_id, code) VALUES (?, ?)", (user_id, code)); conn.commit(); conn.close()

# --- WEB SERVER FOR KEEP-ALIVE ---
app = Flask(__name__)
@app.route('/')
def index(): return "Bot is alive and running!"
def run_flask(): app.run(host='0.0.0.0', port=8080)
def keep_alive():
    flask_thread = threading.Thread(target=run_flask); flask_thread.daemon = True; flask_thread.start()
    while True:
        time.sleep(300)
        try: requests.get(f"https://{os.environ['REPLIT_DEV_DOMAIN']}", timeout=10 )
        except Exception: pass

# --- BOT STATE & KEYBOARDS ---
waiting_pool = {"male": [], "female": [], "any": []}; active_chats = {}; active_games = {}; pending_invites = {}; lock = asyncio.Lock()
def main_menu_keyboard():
    return ReplyKeyboardMarkup([
        ["🎮 Random Chat", "🔎 Search by Gender"],
        ["🛑 End Chat", "Next ⏭️"],
        ["👤 My Profile", "ℹ️ Help"]
    ], resize_keyboard=True)
def gender_keyboard(): return InlineKeyboardMarkup([[InlineKeyboardButton("I'm a Male 👨", callback_data="gender_male"), InlineKeyboardButton("I'm a Female 👩", callback_data="gender_female")]])
def age_keyboard(): return InlineKeyboardMarkup([[InlineKeyboardButton("18-30", callback_data="age_18-30")], [InlineKeyboardButton("30-40", callback_data="age_30-40")], [InlineKeyboardButton("40-50", callback_data="age_40-50")]])
def region_keyboard(): return InlineKeyboardMarkup([[InlineKeyboardButton("Asia", callback_data="region_Asia")], [InlineKeyboardButton("Europe", callback_data="region_Europe")], [InlineKeyboardButton("Africa", callback_data="region_Africa")], [InlineKeyboardButton("America", callback_data="region_America")]])
def post_chat_keyboard(partner_id): return InlineKeyboardMarkup([[InlineKeyboardButton("Polite 👍", callback_data=f"rate_polite_{partner_id}"), InlineKeyboardButton("Respectful 👍", callback_data=f"rate_respect_{partner_id}")], [InlineKeyboardButton("Report 🚩", callback_data=f"report_{partner_id}")]])
def in_chat_actions_keyboard(): return InlineKeyboardMarkup([[InlineKeyboardButton("🎲 Suggest a Game of X-O", callback_data="suggest_xo")], [InlineKeyboardButton("🎬 Suggest a Movie", callback_data="suggest_movie")], [InlineKeyboardButton("🎌 Suggest an Anime", callback_data="suggest_anime")]])
def game_invite_keyboard(inviter_id): return InlineKeyboardMarkup([[InlineKeyboardButton("✅ Accept", callback_data=f"xo_accept_{inviter_id}"), InlineKeyboardButton("❌ Decline", callback_data=f"xo_decline_{inviter_id}")]])

# --- GAME LOGIC (X-O) ---
class XO_Game:
    def __init__(self, p1, p2): self.p1, self.p2, self.board, self.turn, self.winner, self.sym, self.msgs = p1, p2, [" "] * 9, p1, None, {p1: "🍓", p2: "🥝"}, {}
    def get_keyboard(self): return InlineKeyboardMarkup([[InlineKeyboardButton(self.board[i] if self.board[i] != " " else "⬜️", callback_data=f"xo_move_{i}") for i in range(j, j + 3)] for j in range(0, 9, 3)])
    def make_move(self, pos, p_id):
        if self.winner or self.board[pos] != " " or p_id != self.turn: return False
        self.board[pos] = self.sym[p_id]
        if any(all(self.board[i] == self.sym[p_id] for i in wc) for wc in [[0,1,2],[3,4,5],[6,7,8],[0,3,6],[1,4,7],[2,5,8],[0,4,8],[2,4,6]]): self.winner = p_id
        elif " " not in self.board: self.winner = "tie"
        self.turn = self.p2 if self.turn == self.p1 else self.p1; return True
    def get_status(self):
        if self.winner: return f"Game over! Winner: {self.sym[self.winner]} 🎉" if self.winner != "tie" else "It's a tie! 🤝"
        return f"It's {self.sym[self.turn]}'s turn."

# --- TMDb API Function ---
def get_tmdb_suggestion(suggestion_type: str):
    if not TMDB_API_KEY: return None, "Suggestion feature is currently disabled."
    base_url = "https://api.themoviedb.org/3"
    if suggestion_type == "movie":
        endpoint = "/movie/popular"
        params = {'api_key': TMDB_API_KEY, 'language': 'en-US', 'page': random.randint(1, 50 )}
    else:
        endpoint = "/discover/tv"
        params = {'api_key': TMDB_API_KEY, 'language': 'en-US', 'with_keywords': '210024|287501', 'with_origin_country': 'JP', 'page': random.randint(1, 20)}
    try:
        response = requests.get(base_url + endpoint, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        if not data.get('results'): return None, "Could not find a suggestion right now."
        item = random.choice(data['results'])
        title = item.get('title') or item.get('name')
        overview = item.get('overview', 'No description available.')
        rating = item.get('vote_average', 0)
        poster_path = item.get('poster_path')
        poster_url = f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else None
        message = (f"**{title}**\n\n"
                   f"⭐ **Rating:** {rating:.1f}/10\n\n"
                   f"**Synopsis:**\n_{overview[:250] + '...' if len(overview ) > 250 else overview}_")
        return poster_url, message
    except Exception as e:
        print(f"TMDb Error: {e}")
        return None, "An error occurred while getting a suggestion."

# --- CORE BOT HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; is_new_user = add_user(user.id, user.first_name)
    if context.args and context.args[0].startswith('ref_') and is_new_user:
        try:
            referrer_id = int(context.args[0].split('_')[1])
            if get_user(referrer_id) and user.id != referrer_id:
                grant_points(user.id, 5); grant_points(referrer_id, 5)
                await update.message.reply_text("Welcome! You and your friend have both received 5 bonus points!")
                await context.bot.send_message(referrer_id, f"🎉 Your friend {user.first_name} joined! You both earned 5 points.")
        except Exception: pass
    await update.message.reply_text("Welcome!", reply_markup=main_menu_keyboard()); await check_registration(update, context)

async def check_registration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id; user_data = get_user(user_id); message = update.message or update.callback_query.message
    if not user_data.get("gender"): await message.reply_text("To get started, please tell us your gender:", reply_markup=gender_keyboard())
    elif not user_data.get("age"): await message.reply_text("Great! Now, please select your age range:", reply_markup=age_keyboard())
    elif not user_data.get("region"): await message.reply_text("Almost there! Which region are you from?", reply_markup=region_keyboard())
    elif update.callback_query: await message.reply_text("You are all set! You can now start a chat.")

async def find_partner_flow(update: Update, context: ContextTypes.DEFAULT_TYPE, search_preference: str = "any"):
    user_id = update.effective_user.id; message = update.message
    async with lock:
        if user_id in active_chats: await message.reply_text("You are already in a chat."); return
        user_data = get_user(user_id)
        if not all(user_data.get(key) for key in ["gender", "age", "region"]): await message.reply_text("Please complete your profile first via /start."); return

        my_gender = user_data["gender"]
        for pool in waiting_pool.values():
            if user_id in pool: pool.remove(user_id)

        target_pool_key = "female" if my_gender == "male" and search_preference == "gender" else "male" if my_gender == "female" and search_preference == "gender" else "any"
        partner_id = None

        if waiting_pool.get(target_pool_key): partner_id = waiting_pool[target_pool_key].pop(0)
        elif target_pool_key != "any" and waiting_pool.get("any"): partner_id = waiting_pool["any"].pop(0)
        elif target_pool_key == "any":
            combined_pools = waiting_pool["male"] + waiting_pool["female"]
            if combined_pools:
                partner_id = random.choice(combined_pools)
                if get_user(partner_id)["gender"] == "male": waiting_pool["male"].remove(partner_id)
                else: waiting_pool["female"].remove(partner_id)

        if partner_id and partner_id != user_id:
            active_chats[user_id], active_chats[partner_id] = partner_id, user_id
            update_user(user_id, "total_chats", get_user(user_id)["total_chats"] + 1)
            update_user(partner_id, "total_chats", get_user(partner_id)["total_chats"] + 1)
            user_rep, partner_rep = get_user(user_id)["reputation_score"], get_user(partner_id)["reputation_score"]
            await context.bot.send_message(partner_id, f"📩 Partner found! Their reputation is {user_rep:.1f}/10.", reply_markup=in_chat_actions_keyboard())
            await message.reply_text(f"📩 Partner found! Their reputation is {partner_rep:.1f}/10.", reply_markup=in_chat_actions_keyboard())
        else:
            if user_id not in waiting_pool[my_gender]: waiting_pool[my_gender].append(user_id)
            search_msg = "opposite gender" if search_preference == "gender" else "random"
            await message.reply_text(f"⏳ Searching for a {search_msg} partner...")

async def random_chat_start(update: Update, context: ContextTypes.DEFAULT_TYPE): await find_partner_flow(update, context, search_preference="any")
async def gender_search_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id; user_data = get_user(user_id)
    if not user_data or not all(user_data.get(key) for key in ["gender", "age", "region"]): await update.message.reply_text("Please complete your profile first via /start."); return
    if user_data["points"] >= 5:
        update_user(user_id, "points", user_data["points"] - 5)
        await update.message.reply_text(f"5 points used. You have {user_data['points'] - 5} left.")
        await find_partner_flow(update, context, search_preference="gender")
    else: await update.message.reply_text(f"You need 5 points, but you only have {user_data['points']}.")

async def end_chat_logic(user_id, context):
    async with lock:
        was_waiting = any(user_id in pool for pool in waiting_pool.values())
        if was_waiting:
            for pool in waiting_pool.values():
                if user_id in pool: pool.remove(user_id)
            return "search_cancelled", None
        if user_id in active_chats:
            partner_id = active_chats.pop(user_id)
            active_chats.pop(partner_id, None)
            if user_id in active_games: del active_games[user_id]
            if partner_id in active_games: del active_games[partner_id]
            if user_id in pending_invites.values():
                inv_key = [k for k, v in pending_invites.items() if v == user_id][0]
                del pending_invites[inv_key]
            try: await context.bot.send_message(partner_id, "❌ The other user has left the chat.")
            except Exception: pass
            return "chat_ended", partner_id
    return "not_in_chat", None

async def end(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result, partner_id = await end_chat_logic(update.effective_user.id, context)
    if result == "search_cancelled": await update.message.reply_text("🛑 Search cancelled.")
    elif result == "chat_ended": await update.message.reply_text("❌ Chat ended. Please rate your partner:", reply_markup=post_chat_keyboard(partner_id))
    else: await update.message.reply_text("You are not in a chat or search.")

async def next_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Switching to a new partner...")
    result, _ = await end_chat_logic(update.effective_user.id, context)
    if result == "not_in_chat":
        await update.message.reply_text("You weren't in a chat, starting a new search.")
    await find_partner_flow(update, context, search_preference="any")

async def forward_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id; message_text = update.message.text

    command_map = {
        "🎮 Random Chat": random_chat_start, "🔎 Search by Gender": gender_search_start,
        "🛑 End Chat": end, "Next ⏭️": next_chat,
        "👤 My Profile": show_profile, "ℹ️ Help": help_cmd
    }

    if message_text in command_map:
        await command_map[message_text](update, context)
        return

    if user_id in active_chats:
        partner_id = active_chats[user_id]
        try: await update.message.copy(chat_id=partner_id)
        except Exception: await update.message.reply_text("Could not reach your partner.")
        return

    if update.message.reply_to_message and user_id == ADMIN_CHAT_ID:
        await reply_to_user(update, context)
        return

    await update.message.reply_text("You are not in a chat. Please use the buttons to start an activity.")

async def reply_to_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    original_message = update.message.reply_to_message.text
    try: target_user_id = int(original_message.split('`')[1])
    except (IndexError, ValueError): return
    try:
        await context.bot.send_message(chat_id=target_user_id, text=f"✉️ **Support Reply:**\n\n{update.message.text}", parse_mode='Markdown')
        await update.message.reply_text(f"✅ Reply sent to user {target_user_id}.")
    except Exception as e: await update.message.reply_text(f"❌ Failed to send reply. Error: {e}")

async def show_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id; user_data = get_user(user_id); bot_username = (await context.bot.get_me()).username
    if not user_data: await update.message.reply_text("Could not find your profile. Please type /start."); return
    points, reputation = user_data.get("points", 0), user_data.get("reputation_score", 7.0)
    referral_link = f"https://t.me/{bot_username}?start=ref_{user_id}"
    profile_text = (f"👤 **My Profile**\n\n⭐ **Reputation:** {reputation:.1f}/10.0\n💰 **Points:** {points}\n\n"
                    f"🔗 **Your Referral Link:**\n`{referral_link}`\n\n"
                    f"To redeem a code, type:\n`/redeem YOUR_CODE_HERE`" )
    await update.message.reply_text(profile_text, parse_mode='Markdown')
async def redeem_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not context.args: await update.message.reply_text("Usage: /redeem YOUR_CODE"); return
    code = context.args[0].upper()
    if code not in PROMO_CODES: await update.message.reply_text("Invalid promo code."); return
    if has_redeemed_code(user_id, code): await update.message.reply_text("You have already used this code."); return
    points_to_add = PROMO_CODES[code]
    grant_points(user_id, points_to_add); mark_code_as_redeemed(user_id, code)
    new_total_points = get_user(user_id)["points"]
    await update.message.reply_text(f"✅ Success! You redeemed {points_to_add} points. New balance: {new_total_points}.")
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "**Commands & Features**\n\n"
        "🎮 **Random Chat**: Finds a random partner.\n"
        "🔎 **Search by Gender**: Uses 5 points to find a partner of the opposite gender.\n"
        "🛑 **End Chat**: Stops the current chat or search.\n"
        "⏭️ **Next**: Ends the current chat and finds a new partner immediately.\n"
        "👤 **My Profile**: Shows your points, reputation, and referral link.\n\n"
        "To redeem a code: `/redeem YOUR_CODE`\n"
        "To contact support: `/contact Your message here`",
        parse_mode='Markdown'
    )
async def contact_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not ADMIN_CHAT_ID: await update.message.reply_text("Contact feature is disabled."); return
    message_text = " ".join(context.args)
    if not message_text: await update.message.reply_text("Usage: /contact Your message here"); return
    user_id = update.effective_user.id
    forward_text = f"Support Message from User ID: `{user_id}`\n\n---\n\n{message_text}"
    try:
        await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=forward_text, parse_mode='Markdown')
        await update.message.reply_text("Your message has been sent.")
    except Exception as e: await update.message.reply_text("Error sending message.")

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer(); user_id = query.from_user.id; data = query.data
    if data == "suggest_movie" or data == "suggest_anime":
        if user_id not in active_chats: await query.edit_message_text("This chat has ended."); return
        partner_id = active_chats[user_id]
        suggestion_type = "movie" if data == "suggest_movie" else "anime"
        poster_url, message = get_tmdb_suggestion(suggestion_type)
        for p_id in [user_id, partner_id]:
            try:
                if poster_url: await context.bot.send_photo(p_id, photo=poster_url, caption=message, parse_mode='Markdown')
                else: await context.bot.send_message(p_id, message, parse_mode='Markdown')
            except Exception as e: print(f"Failed to send suggestion to {p_id}: {e}")
        for p_id in [user_id, partner_id]:
            try: await context.bot.send_message(p_id, "What would you like to do next?", reply_markup=in_chat_actions_keyboard())
            except Exception: pass
        try: await query.message.delete()
        except: pass
        return
    if data == "suggest_xo":
        if user_id not in active_chats: await query.edit_message_text("This chat has ended."); return
        partner_id = active_chats[user_id]; pending_invites[partner_id] = user_id
        await context.bot.send_message(partner_id, "Your partner wants to play X-O!", reply_markup=game_invite_keyboard(user_id))
        await query.edit_message_text("Invitation sent. Waiting for partner to accept...")
        return
    if data.startswith("xo_accept_"):
        inviter_id = int(data.split("_")[-1])
        if pending_invites.get(user_id) != inviter_id: await query.edit_message_text("This invitation is invalid or has expired."); return
        del pending_invites[user_id]
        game = XO_Game(inviter_id, user_id); active_games[user_id] = game; active_games[inviter_id] = game
        for p_id in [user_id, inviter_id]:
            msg = await context.bot.send_message(p_id, f"Game started! You are {game.sym[p_id]}.\n{game.get_status()}", reply_markup=game.get_keyboard())
            game.msgs[p_id] = msg.message_id
        await query.message.delete(); return
    if data.startswith("xo_decline_"):
        inviter_id = int(data.split("_")[-1])
        if pending_invites.get(user_id) != inviter_id: await query.edit_message_text("This invitation is invalid or has expired."); return
        del pending_invites[user_id]
        await context.bot.send_message(inviter_id, "Your partner declined the game invitation.")
        await query.edit_message_text("You declined the invitation."); return
    if data.startswith("xo_move_"):
        if user_id not in active_games: return
        game = active_games[user_id]
        if user_id != game.turn: await context.bot.answer_callback_query(query.id, text="It's not your turn!"); return
        if game.make_move(int(data.split("_")[-1]), user_id):
            for p_id, msg_id in game.msgs.items():
                try: await context.bot.edit_message_text(chat_id=p_id, message_id=msg_id, text=f"You are {game.sym[p_id]}.\n{game.get_status()}", reply_markup=game.get_keyboard())
                except Exception: pass
            if game.winner:
                for p_id in [game.p1, game.p2]:
                    if p_id in active_games: del active_games[p_id]
                    await context.bot.send_message(p_id, game.get_status())
                    await context.bot.send_message(p_id, "You can now continue chatting or suggest another activity.", reply_markup=in_chat_actions_keyboard())
        return
    if data.startswith("gender_"): update_user(user_id, "gender", data.split("_")[1]); await query.edit_message_text(f"Gender set: {data.split('_')[1].capitalize()}"); await check_registration(update, context)
    elif data.startswith("age_"): update_user(user_id, "age", data.split("_")[1]); await query.edit_message_text(f"Age set: {data.split('_')[1]}"); await check_registration(update, context)
    elif data.startswith("region_"): update_user(user_id, "region", data.split("_")[1]); await query.edit_message_text(f"Region set: {data.split('_')[1]}"); await check_registration(update, context)
    elif data.startswith("rate_"):
        _, rate_type, partner_id_str = data.split("_"); partner_id = int(partner_id_str)
        partner_data = get_user(partner_id)
        if partner_data:
            if rate_type == "report":
                if ADMIN_CHAT_ID:
                    report_text = f"🚩 **User Report**\n\nUser `{user_id}` reported user `{partner_id}`."
                    await context.bot.send_message(ADMIN_CHAT_ID, report_text, parse_mode='Markdown')
                    await query.edit_message_text("Report sent to admin. Thank you.")
                else:
                    await query.edit_message_text("Report feature is currently disabled.")
            else:
                new_pos_ratings = partner_data["positive_ratings"] + 1; new_total_chats = partner_data["total_chats"]
                new_rep = min(10.0, ((new_pos_ratings / new_total_chats) * 3 + 7) if new_total_chats > 0 else 7.0)
                update_user(partner_id, "positive_ratings", new_pos_ratings); update_user(partner_id, "reputation_score", new_rep)
                await query.edit_message_text("Thank you for your feedback!")
        await query.message.delete()
        return

def main():
    setup_database()
    keep_alive_thread = threading.Thread(target=keep_alive); keep_alive_thread.daemon = True; keep_alive_thread.start()
    application = Application.builder().token(TOKEN).build()

    # Command Handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("redeem", redeem_code))
    application.add_handler(CommandHandler("help", help_cmd))
    application.add_handler(CommandHandler("contact", contact_admin))

    # Message Handler for text commands and forwarding
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, forward_message))

    # Callback Query Handler for all inline buttons
    application.add_handler(CallbackQueryHandler(callback_handler))

    print("Bot application (Final Stable Version - Rebuilt) is configured and starting...")
    application.run_polling()

if __name__ == "__main__":
    main()

