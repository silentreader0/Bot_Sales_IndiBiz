import os
import json
import logging
from datetime import datetime
import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
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
CREDENTIALS = os.environ.get("GOOGLE_CREDENTIALS")

# ============================================================
# KOLOM DI GOOGLE SHEET (1-based index)
# Urutan: Tanggal | Yang Input | Nama Usaha | Nama PIC | NIK KTP |
#         Tempat/Tgl Lahir | No HP Aktif | No HP Alt | Email |
#         Speed Layanan | Harga Paket | Alamat Pemasangan |
#         Chat ID | Nomor Order | Status | Notif Terkirim
# ============================================================
COL_CHAT_ID        = 13  # M - Chat ID user (otomatis)
COL_NOMOR_ORDER    = 14  # N - Nomor Order (diisi admin)
COL_STATUS         = 15  # O - Status (diisi admin)
COL_NOTIF_TERKIRIM = 16  # P - Notif Terkirim (otomatis)

# ============================================================
# LOGGING
# ============================================================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================================
# PILIHAN SPEED LAYANAN
# ============================================================
SPEED_OPTIONS = ["50", "75", "100", "150", "200", "300"]

# ============================================================
# TEMPLATE FORM (tanpa Speed Layanan & Harga Paket — diisi via bot)
# ============================================================
TEMPLATE = """📋 *FORM DATA PELANGGAN*

Silakan copy teks di bawah ini, isi datanya, lalu kirim balik ke sini:

```
Nama Usaha        : 
Nama PIC          : 
NIK KTP           : 
Tempat/Tgl Lahir  : 
No HP Aktif       : 
No HP Alternatif  : (isi strip jika tidak ada)
Email             : 
Alamat Pemasangan : 
```

⚠️ Jangan ubah nama field-nya ya, hanya isi bagian setelah tanda titik dua ( : )

Setelah kirim form ini, kamu akan diminta memilih *Speed Layanan* dan mengisi *Harga Paket*."""

FIELDS = [
    "nama usaha",
    "nama pic",
    "nik ktp",
    "tempat/tgl lahir",
    "no hp aktif",
    "no hp alternatif",
    "email",
    "alamat pemasangan",
]

OPTIONAL_FIELDS = ["no hp alternatif"]

# ============================================================
# STATE CONVERSATION
# ============================================================
WAITING_INPUT  = 1
WAITING_SPEED  = 2
WAITING_HARGA  = 3

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
            "No HP Alternatif", "Email", "Speed Layanan", "Harga Paket",
            "Alamat Pemasangan", "Chat ID", "Nomor Order", "Status", "Notif Terkirim"
        ]
        sheet.append_row(headers)

    return sheet

# ============================================================
# PARSE TEMPLATE YANG DIISI USER
# ============================================================
def parse_input(text: str):
    data = {}
    lines = text.strip().splitlines()

    for line in lines:
        if ":" not in line:
            continue
        parts = line.split(":", 1)
        key   = parts[0].strip().lower()
        value = parts[1].strip() if len(parts) > 1 else ""

        for field in FIELDS:
            if field in key:
                data[field] = value if value else "-"
                break

    missing = []
    for field in FIELDS:
        if field in OPTIONAL_FIELDS:
            continue
        if field not in data or data[field] in ("", "-", "(isi strip jika tidak ada)"):
            missing.append(field.title())

    for field in OPTIONAL_FIELDS:
        if field not in data:
            data[field] = "-"

    return data, missing

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
    from_user = update.effective_user
    context.user_data["input_by"] = (
        f"@{from_user.username}" if from_user.username
        else f"{from_user.first_name or ''} {from_user.last_name or ''}".strip()
    )
    context.user_data["chat_id"] = update.effective_chat.id

    await update.message.reply_text(TEMPLATE, parse_mode="Markdown")
    return WAITING_INPUT

async def batal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("❌ Proses input dibatalkan.")
    return ConversationHandler.END

# ============================================================
# STEP 1 — TERIMA FORM TEKS DARI USER
# ============================================================
async def handle_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    data, missing = parse_input(text)

    if missing:
        await update.message.reply_text(
            f"⚠️ Data tidak lengkap atau format salah!\n\n"
            f"Field yang belum terisi:\n" +
            "\n".join([f"• {m}" for m in missing]) +
            f"\n\nSilakan kirim ulang dengan format template yang benar.",
            parse_mode="Markdown"
        )
        return WAITING_INPUT

    # Simpan data sementara
    context.user_data["form_data"] = data

    # Tampilkan inline button pilihan speed
    keyboard = [
        [
            InlineKeyboardButton("🚀 50 Mbps",  callback_data="speed_50"),
            InlineKeyboardButton("🚀 75 Mbps",  callback_data="speed_75"),
            InlineKeyboardButton("🚀 100 Mbps", callback_data="speed_100"),
        ],
        [
            InlineKeyboardButton("⚡ 150 Mbps", callback_data="speed_150"),
            InlineKeyboardButton("⚡ 200 Mbps", callback_data="speed_200"),
            InlineKeyboardButton("⚡ 300 Mbps", callback_data="speed_300"),
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "✅ Form diterima!\n\n"
        "📶 Pilih *Speed Layanan* yang sesuai:",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )
    return WAITING_SPEED

# ============================================================
# STEP 2 — TERIMA PILIHAN SPEED LEWAT BUTTON
# ============================================================
async def handle_speed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    speed = query.data.replace("speed_", "")
    context.user_data["form_data"]["speed layanan"] = f"{speed} Mbps"

    # Edit pesan button supaya tidak bisa dipilih ulang
    await query.edit_message_text(
        f"✅ Form diterima!\n\n"
        f"📶 Speed Layanan: *{speed} Mbps* dipilih.\n\n"
        f"💰 Sekarang masukkan *Harga Paket* (angka saja, contoh: 150000):",
        parse_mode="Markdown"
    )
    return WAITING_HARGA

# ============================================================
# STEP 3 — TERIMA HARGA PAKET (WAJIB ANGKA)
# ============================================================
async def handle_harga(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().replace(".", "").replace(",", "")

    if not text.isdigit():
        await update.message.reply_text(
            "⚠️ Harga paket harus berupa *angka* saja!\n\n"
            "Contoh yang benar: `150000`\n"
            "Silakan coba lagi.",
            parse_mode="Markdown"
        )
        return WAITING_HARGA

    harga = int(text)
    context.user_data["form_data"]["harga paket"] = harga

    input_by = context.user_data.get("input_by", "Unknown")
    chat_id  = context.user_data.get("chat_id", "")
    data     = context.user_data["form_data"]

    await save_to_sheet(update, context, data, input_by, chat_id)
    return ConversationHandler.END

# ============================================================
# SIMPAN KE GOOGLE SHEET
# ============================================================
async def save_to_sheet(update, context, data, input_by, chat_id):
    try:
        tz  = pytz.timezone("Asia/Jakarta")
        now = datetime.now(tz).strftime("%d/%m/%Y %H:%M:%S")

        sheet = get_sheet()

        # Format harga ke Rupiah untuk ditampilkan di summary
        harga_raw = data.get("harga paket", 0)
        harga_fmt = f"Rp {int(harga_raw):,}".replace(",", ".")

        row = [
            now,
            input_by,
            data.get("nama usaha", ""),
            data.get("nama pic", ""),
            data.get("nik ktp", ""),
            data.get("tempat/tgl lahir", ""),
            data.get("no hp aktif", ""),
            data.get("no hp alternatif", ""),
            data.get("email", ""),
            data.get("speed layanan", ""),   # Kolom J - Speed Layanan
            int(harga_raw),                  # Kolom K - Harga Paket (angka)
            data.get("alamat pemasangan", ""),
            str(chat_id),                    # Kolom M - Chat ID
            "",                              # Kolom N - Nomor Order (diisi admin)
            "",                              # Kolom O - Status (diisi admin)
            "",                              # Kolom P - Notif Terkirim (otomatis)
        ]
        sheet.append_row(row)

        summary = (
            f"🎉 *Data berhasil disimpan!*\n\n"
            f"🏢 Nama Usaha      : {data.get('nama usaha')}\n"
            f"👤 Nama PIC        : {data.get('nama pic')}\n"
            f"🪪 NIK KTP         : {data.get('nik ktp')}\n"
            f"🎂 Tempat/Tgl Lahir: {data.get('tempat/tgl lahir')}\n"
            f"📱 No HP Aktif     : {data.get('no hp aktif')}\n"
            f"📱 No HP Alt       : {data.get('no hp alternatif')}\n"
            f"📧 Email           : {data.get('email')}\n"
            f"📶 Speed Layanan   : {data.get('speed layanan')}\n"
            f"💰 Harga Paket     : {harga_fmt}\n"
            f"📍 Alamat          : {data.get('alamat pemasangan')}\n"
            f"🕐 Waktu Input     : {now}\n"
            f"👤 Diinput oleh    : {input_by}\n\n"
            f"⏳ Nomor order akan dikirim ke sini setelah diproses admin."
        )
        await update.message.reply_text(summary, parse_mode="Markdown")

    except Exception as e:
        logger.error(f"Error save_to_sheet: {e}")
        await update.message.reply_text("⚠️ Terjadi kesalahan saat menyimpan data. Hubungi admin.")

    context.user_data.clear()

# ============================================================
# CEK NOMOR ORDER & KIRIM NOTIFIKASI (dijalankan setiap 15 menit)
# ============================================================
async def cek_nomor_order(context: ContextTypes.DEFAULT_TYPE):
    try:
        sheet = get_sheet()
        rows  = sheet.get_all_values()

        if len(rows) <= 1:
            return  # Hanya header, tidak ada data

        for i, row in enumerate(rows[1:], start=2):
            while len(row) < COL_NOTIF_TERKIRIM:
                row.append("")

            chat_id        = row[COL_CHAT_ID - 1].strip()
            nomor_order    = row[COL_NOMOR_ORDER - 1].strip()
            status         = row[COL_STATUS - 1].strip()
            notif_terkirim = row[COL_NOTIF_TERKIRIM - 1].strip()

            if chat_id and nomor_order and not notif_terkirim:
                nama_usaha = row[2] if len(row) > 2 else "-"
                nama_pic   = row[3] if len(row) > 3 else "-"

                pesan = (
                    f"🎉 *Nomor Order Tersedia!*\n\n"
                    f"🏢 Nama Usaha  : {nama_usaha}\n"
                    f"👤 Nama PIC    : {nama_pic}\n"
                    f"📋 Nomor Order : *{nomor_order}*\n"
                    f"📌 Status      : {status if status else '-'}\n\n"
                    f"Silakan simpan nomor order ini untuk keperluan tracking."
                )

                try:
                    await context.bot.send_message(
                        chat_id=int(chat_id),
                        text=pesan,
                        parse_mode="Markdown"
                    )
                    sheet.update_cell(i, COL_NOTIF_TERKIRIM, "✅ Terkirim")
                    logger.info(f"Notif terkirim ke chat_id {chat_id} untuk order {nomor_order}")

                except Exception as e:
                    logger.error(f"Gagal kirim notif ke {chat_id}: {e}")

    except Exception as e:
        logger.error(f"Error cek_nomor_order: {e}")

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
            WAITING_INPUT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_input),
                CommandHandler("batal", batal),
            ],
            WAITING_SPEED: [
                CallbackQueryHandler(handle_speed, pattern="^speed_"),
                CommandHandler("batal", batal),
            ],
            WAITING_HARGA: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_harga),
                CommandHandler("batal", batal),
            ],
        },
        fallbacks=[CommandHandler("batal", batal)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_handler)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unknown))

    # Job setiap 15 menit untuk cek nomor order baru
    app.job_queue.run_repeating(
        cek_nomor_order,
        interval=900,   # 900 detik = 15 menit
        first=60,       # Mulai cek pertama setelah 60 detik bot nyala
    )

    logger.info("Bot berjalan...")
    app.run_polling()

if __name__ == "__main__":
    main()
