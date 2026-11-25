import os
import sqlite3
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters

# Enable logging (required for Railway logs)
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN environment variable not set")

# ---- Database initialization (SQLite persistent storage) ----
def init_db():
    conn = sqlite3.connect('novapay.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS invoices
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  amount REAL,
                  description TEXT,
                  status TEXT DEFAULT 'pending',
                  created_at TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS transactions
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  amount REAL,
                  type TEXT,
                  category TEXT,
                  note TEXT,
                  created_at TEXT)''')
    conn.commit()
    conn.close()

init_db()

def get_db():
    return sqlite3.connect('novapay.db')

# ---- Command handlers ----
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📄 Create Invoice", callback_data='new_invoice')],
        [InlineKeyboardButton("💰 Record Transaction", callback_data='new_transaction')],
        [InlineKeyboardButton("📊 View Report", callback_data='report')],
        [InlineKeyboardButton("❓ Help", callback_data='help')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "Welcome to Nova Pay — your free digital payment assistant.\n\n"
        "Use the menu below to manage invoices, transactions, and reports.\n"
        "All data is stored locally for your account.",
        reply_markup=reply_markup
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Nova Pay Help:\n"
        "/start - Main menu\n"
        "/newinvoice - Create a new invoice\n"
        "/record - Record a transaction\n"
        "/report - View financial summary\n"
        "/cancel - Cancel current operation\n\n"
        "This bot is a personal finance assistant. "
        "It does not connect to banks or process real payments."
    )

async def new_invoice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Send the invoice details in this format:\n\n"
        "Amount | Description\n"
        "Example: 150.00 | Consulting service"
    )
    context.user_data['awaiting_invoice'] = True

async def record_transaction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Send the transaction in this format:\n\n"
        "Amount | Type(income/expense) | Category | Note\n"
        "Example: 75.50 | expense | Software | Monthly subscription"
    )
    context.user_data['awaiting_transaction'] = True

async def report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT COUNT(*), COALESCE(SUM(amount),0) FROM invoices WHERE user_id=? AND status='pending'", (user_id,))
    inv_count, inv_total = c.fetchone()
    c.execute("SELECT type, COALESCE(SUM(amount),0) FROM transactions WHERE user_id=? GROUP BY type", (user_id,))
    rows = c.fetchall()
    conn.close()

    income = expense = 0.0
    for t, amt in rows:
        if t == 'income':
            income = amt
        elif t == 'expense':
            expense = amt

    await update.message.reply_text(
        f"📊 Nova Pay Report\n"
        f"─────────────────\n"
        f"Pending invoices: {inv_count} (total {inv_total:.2f})\n"
        f"Total income recorded: {income:.2f}\n"
        f"Total expenses recorded: {expense:.2f}\n"
        f"Net balance: {income - expense:.2f}\n"
        f"─────────────────\n"
        f"Data is based on records you entered."
    )

# ---- Button callbacks ----
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == 'new_invoice':
        await query.edit_message_text("Send the invoice details in this format:\n\nAmount | Description\nExample: 150.00 | Consulting service")
        context.user_data['awaiting_invoice'] = True
    elif query.data == 'new_transaction':
        await query.edit_message_text("Send the transaction in this format:\n\nAmount | Type(income/expense) | Category | Note\nExample: 75.50 | expense | Software | Monthly subscription")
        context.user_data['awaiting_transaction'] = True
    elif query.data == 'report':
        user_id = query.from_user.id
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT COUNT(*), COALESCE(SUM(amount),0) FROM invoices WHERE user_id=? AND status='pending'", (user_id,))
        inv_count, inv_total = c.fetchone()
        c.execute("SELECT type, COALESCE(SUM(amount),0) FROM transactions WHERE user_id=? GROUP BY type", (user_id,))
        rows = c.fetchall()
        conn.close()
        income = expense = 0.0
        for t, amt in rows:
            if t == 'income': income = amt
            elif t == 'expense': expense = amt
        await query.edit_message_text(
            f"📊 Nova Pay Report\nPending invoices: {inv_count} ({inv_total:.2f})\n"
            f"Income: {income:.2f} | Expenses: {expense:.2f} | Net: {income-expense:.2f}"
        )
    elif query.data == 'help':
        await query.edit_message_text(
            "Nova Pay is a free assistant for invoices and transactions.\n"
            "Use /start to return to the menu.\n"
            "All data is stored for your account only."
        )

# ---- Text message handler (processes user input) ----
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    if context.user_data.get('awaiting_invoice'):
        context.user_data['awaiting_invoice'] = False
        parts = text.split('|')
        if len(parts) != 2:
            await update.message.reply_text("Invalid format. Use: Amount | Description")
            return
        try:
            amount = float(parts[0].strip())
        except ValueError:
            await update.message.reply_text("Amount must be a number. Try again.")
            return
        desc = parts[1].strip()
        conn = get_db()
        c = conn.cursor()
        c.execute("INSERT INTO invoices (user_id, amount, description, created_at) VALUES (?,?,?,?)",
                  (user_id, amount, desc, now))
        conn.commit()
        conn.close()
        await update.message.reply_text(f"✅ Invoice created: {amount:.2f} — {desc}")
        return

    if context.user_data.get('awaiting_transaction'):
        context.user_data['awaiting_transaction'] = False
        parts = text.split('|')
        if len(parts) != 4:
            await update.message.reply_text("Invalid format. Use: Amount | income/expense | Category | Note")
            return
        try:
            amount = float(parts[0].strip())
        except ValueError:
            await update.message.reply_text("Amount must be a number.")
            return
        t_type = parts[1].strip().lower()
        if t_type not in ('income', 'expense'):
            await update.message.reply_text("Type must be 'income' or 'expense'.")
            return
        category = parts[2].strip()
        note = parts[3].strip()
        conn = get_db()
        c = conn.cursor()
        c.execute("INSERT INTO transactions (user_id, amount, type, category, note, created_at) VALUES (?,?,?,?,?,?)",
                  (user_id, amount, t_type, category, note, now))
        conn.commit()
        conn.close()
        await update.message.reply_text(f"✅ Recorded {t_type}: {amount:.2f} ({category})")
        return

    await update.message.reply_text("Use /start to see the menu, or /help for instructions.")

# ---- Main entry point ----
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("newinvoice", new_invoice))
    app.add_handler(CommandHandler("record", record_transaction))
    app.add_handler(CommandHandler("report", report))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Nova Pay bot starting...")
    app.run_polling()

if __name__ == '__main__':
    main()
