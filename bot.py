import os
import json
import logging
from datetime import datetime
import pytz
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
)
import gspread
from google.oauth2.service_account import Credentials

# ============================================================
# KONFIGURASI - Isi di Railway Environment Variables
# ============================================================
BOT_TOKEN   = os.environ.get("BOT_TOKEN")
SHEET_ID    = os.environ.get("SHEET_ID")
SHEET_NAME  = os.environ.get("SHEET_NAME", "Data Pelanggan")
CREDENTIALS = os.environ.get("GOOGLE_CREDENTIALS")  # isi dengan isi file JSON (string)

# ============================================================
# LOGGING
# ============================================================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================================
# KONEKSI KE GOOGLE SHEET
# ============================================================
def get_sheet():
    creds_dict = json.loads(CREDENTIALS)
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    client = gspread.authorize(creds)
    ss = client.open_by_key(SHEET_ID)

    try:
        sheet = ss.worksheet(SHEET_NAME)
    except gspread.exceptions.WorksheetNotFound:
        sheet = ss.add_worksheet(title=SHEET_NAME, rows=1000, cols=20)
        headers = [
            "Tanggal Input", "Yang Input", "Nama Usaha", "Nama PIC",
            "NIK KTP", "Tempat/Tgl Lahir PIC", "No HP Aktif",
            "No HP Alternatif", "Email", "Paket Berlangganan", "Alamat Pemasangan"
        ]
        sheet.append_row(headers)

    return sheet

# ============================================================
# URUTAN PERTANYAAN
# Untuk tambah field baru: tambahkan dict baru di list ini
# ============================================================
QUESTIONS = [
    {"key": "nama_usaha",        "label": "Nama Usaha",                                          "optional": False},
    {"key": "nama_pic",          "label": "Nama PIC",                                            "optional": False},
    {"key": "nik_ktp",           "label": "NIK KTP",                                             "optional": False},
    {"key": "ttl_pic",           "label": "Tempat/Tanggal Lahir PIC\n(contoh: Jakarta, 01 Januari 1990)", "optional": False},
    {"key": "no_hp",             "label": "No HP Aktif",                                         "optional": False},
    {"key": "no_hp_alt",         "label": "No HP Alternatif\n(ketik 'skip' jika tidak ada)",     "optional": True},
    {"key": "email",             "label": "Email",                                               "optional": False},
    {"key": "paket",             "label": "Paket Berlangganan",                                  "optional": False},
    {"key": "alamat_pemasangan", "label": "Alamat Pemasangan",                                   "optional": False},
]

# State untuk ConversationHandler
ANSWERING = 1

# ============================================================
# COMMAND HANDLERS
# ============================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.effective_user.first_name
    await update.message.reply_text(
        f"👋 Halo, *{name}*!\n\n"
        f"Saya bot pendataan pelanggan.\n\n"
        f"Ketik /daftar untuk mulai input data pelanggan baru.\n"
        f"Ketik /batal untuk membatalkan proses yang sedang berjalan.",
        parse_mode="Markdown"
    )

async def daftar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    context.user_data["step"] = 0
    context.user_data["data"] = {}

    from_user = update.effective_user
    context.user_data["input_by"] = (
        f"@{from_user.username}" if from_user.username
        else f"{from_user.first_name or ''} {from_user.last_name or ''}".strip()
    )

    await ask_question(update, context)
    return ANSWERING

async def batal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("❌ Proses input dibatalkan.")
    return ConversationHandler.END

# ============================================================
# LOGIKA PERTANYAAN & JAWABAN
# ============================================================
async def ask_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    step = context.user_data["step"]
    q = QUESTIONS[step]
    total = len(QUESTIONS)
    optional_note = "" if q["optional"] else " _(wajib diisi)_"
    await update.message.reply_text(
        f"📝 *[{step + 1}/{total}]* {q['label']}{optional_note}",
        parse_mode="Markdown"
    )

async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    step = context.user_data["step"]
    q = QUESTIONS[step]
    text = update.message.text.strip()

    if text.lower() == "skip":
        if q["optional"]:
            context.user_data["data"][q["key"]] = "-"
        else:
            await update.message.reply_text("⚠️ Field ini wajib diisi, tidak bisa dilewati.")
            return ANSWERING
    else:
        context.user_data["data"][q["key"]] = text

    context.user_data["step"] += 1

    if context.user_data["step"] < len(QUESTIONS):
        await ask_question(update, context)
        return ANSWERING
    else:
        await save_to_sheet(update, context)
        return ConversationHandler.END

# ============================================================
# SIMPAN KE GOOGLE SHEET
# ============================================================
async def save_to_sheet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data     = context.user_data["data"]
    input_by = context.user_data["input_by"]

    try:
        tz  = pytz.timezone("Asia/Jakarta")
        now = datetime.now(tz).strftime("%d/%m/%Y %H:%M:%S")

        sheet = get_sheet()
        row = [
            now,
            input_by,
            data.get("nama_usaha", ""),
            data.get("nama_pic", ""),
            data.get("nik_ktp", ""),
            data.get("ttl_pic", ""),
            data.get("no_hp", ""),
            data.get("no_hp_alt", ""),
            data.get("email", ""),
            data.get("paket", ""),
            data.get("alamat_pemasangan", ""),
        ]
        sheet.append_row(row)

        summary = (
            f"✅ *Data berhasil disimpan!*\n\n"
            f"🏢 Nama Usaha      : {data.get('nama_usaha')}\n"
            f"👤 Nama PIC        : {data.get('nama_pic')}\n"
            f"🪪 NIK KTP         : {data.get('nik_ktp')}\n"
            f"🎂 Tempat/Tgl Lahir: {data.get('ttl_pic')}\n"
            f"📱 No HP Aktif     : {data.get('no_hp')}\n"
            f"📱 No HP Alt       : {data.get('no_hp_alt')}\n"
            f"📧 Email           : {data.get('email')}\n"
            f"📦 Paket           : {data.get('paket')}\n"
            f"📍 Alamat          : {data.get('alamat_pemasangan')}\n"
            f"🕐 Waktu Input     : {now}\n"
            f"👤 Diinput oleh    : {input_by}\n\n"
            f"Ketik /daftar untuk input data pelanggan baru."
        )
        await update.message.reply_text(summary, parse_mode="Markdown")

    except Exception as e:
        logger.error(f"Error save_to_sheet: {e}")
        await update.message.reply_text("⚠️ Terjadi kesalahan saat menyimpan data. Hubungi admin.")

    context.user_data.clear()

# ============================================================
# PESAN DI LUAR KONTEKS
# ============================================================
async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Ketik /daftar untuk mulai input data, atau /start untuk info lebih lanjut."
    )

# ============================================================
# MAIN
# ============================================================
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("daftar", daftar)],
        states={
            ANSWERING: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_answer),
                CommandHandler("batal", batal),
            ],
        },
        fallbacks=[CommandHandler("batal", batal)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_handler)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unknown))

    logger.info("Bot berjalan...")
    app.run_polling()

if __name__ == "__main__":
    main()
