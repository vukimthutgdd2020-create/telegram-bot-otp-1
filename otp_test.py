import asyncio
import logging
import sqlite3
from pathlib import Path
from urllib.parse import quote

import httpx
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    URLInputFile
)

# --- CẤU HÌNH ---
BOT_TOKEN = "8304789506:AAGKVXmYxAkBfnPLwYdQVY6kYJ_iSwmEP14"
ADMIN_ID = 6676245961
OTP_API_KEY = "8fc8e078133cde11"
OTP_BASE_URL = "https://chaycodeso3.com/api"

BANK_BIN = "970422"
BANK_ACCOUNT = "346641789567"
ACCOUNT_NAME = "VU VAN CUONG"

BASE_DIR = Path(__file__).resolve().parent
DB_NAME = str(BASE_DIR / "shop_bot.db")

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# --- FSM (Quản lý trạng thái nhập tiền) ---
class DepositState(StatesGroup):
    waiting_for_amount = State()

# --- DATABASE ---
def db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = db()
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS users(user_id INTEGER PRIMARY KEY, full_name TEXT, username TEXT, balance INTEGER DEFAULT 0)")
    cur.execute("PRAGMA table_info(users)")
    columns = [column[1] for column in cur.fetchall()]
    if 'balance' not in columns:
        cur.execute("ALTER TABLE users ADD COLUMN balance INTEGER DEFAULT 0")
    conn.commit()
    conn.close()

def get_user(user_id):
    conn = db()
    user = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()
    return user

def update_balance(user_id, amount):
    conn = db()
    conn.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
    conn.commit()
    conn.close()

def save_user(user):
    conn = db()
    conn.execute("INSERT OR IGNORE INTO users (user_id, full_name, username, balance) VALUES (?, ?, ?, 0)", (user.id, user.full_name, user.username))
    conn.commit()
    conn.close()

# --- API OTP ---
class ChayCodeAPI:
    def __init__(self, api_key):
        self.api_key = api_key

    async def _get(self, params):
        params['apik'] = self.api_key
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(OTP_BASE_URL, params=params, timeout=20)
                return response.json()
            except Exception:
                return {"ResponseCode": 1, "Msg": "Lỗi kết nối Server"}

    async def get_apps(self):
        return await self._get({'act': 'app'})

    async def request_number(self, app_id):
        return await self._get({'act': 'number', 'appId': app_id})

    async def get_otp_code(self, request_id):
        return await self._get({'act': 'code', 'id': request_id})

otp_api = ChayCodeAPI(OTP_API_KEY)

# --- KEYBOARDS ---
def main_menu_keyboard(user_id):
    user = get_user(user_id)
    balance = user['balance'] if user else 0
    bal_text = "Vô hạn" if user_id == ADMIN_ID else f"{balance:,}đ"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"💰 Số dư: {bal_text}", callback_data="refresh_bal")],
        [InlineKeyboardButton(text="📱 Thuê số OTP", callback_data="otp_list")],
        [InlineKeyboardButton(text="💳 Nạp tiền", callback_data="deposit"),
         InlineKeyboardButton(text="☎️ Hỗ trợ", callback_data="contact")],
    ])

# --- HANDLERS ---
@dp.message(Command("start"))
async def show_menu(m: Message):
    save_user(m.from_user)
    await m.answer(f"👋 Chào <b>{m.from_user.full_name}</b>!", reply_markup=main_menu_keyboard(m.from_user.id))

@dp.callback_query(F.data == "refresh_bal")
async def refresh_bal(c: CallbackQuery):
    await c.message.edit_reply_markup(reply_markup=main_menu_keyboard(c.from_user.id))
    await c.answer("Đã cập nhật số dư!")

# --- XỬ LÝ NẠP TIỀN ---
@dp.callback_query(F.data == "deposit")
async def deposit_start(c: CallbackQuery, state: FSMContext):
    await c.message.answer("⌨️ Vui lòng nhập số tiền bạn muốn nạp (Ví dụ: 50000):")
    await state.set_state(DepositState.waiting_for_amount)
    await c.answer()

@dp.message(DepositState.waiting_for_amount)
async def deposit_amount_received(m: Message, state: FSMContext):
    if not m.text.isdigit():
        return await m.answer("❌ Vui lòng chỉ nhập số dương!")
    
    amount = int(m.text)
    if amount < 1000:
        return await m.answer("❌ Số tiền tối thiểu là 1,000đ")
    
    await state.clear()
    user_id = m.from_user.id
    memo = f"NAP{user_id}"
    qr_url = f"https://img.vietqr.io/image/{BANK_BIN}-{BANK_ACCOUNT}-compact2.jpg?amount={amount}&addInfo={memo}&accountName={quote(ACCOUNT_NAME)}"
    
    await m.answer_photo(
        photo=URLInputFile(qr_url),
        caption=(f"💳 <b>THÔNG TIN THANH TOÁN</b>\n\n"
                 f"💰 Số tiền: <b>{amount:,}đ</b>\n"
                 f"📝 Nội dung: <code>{memo}</code>\n\n"
                 f"ℹ️ Admin sẽ nhận được yêu cầu và duyệt tiền cho bạn ngay khi nhận được thanh toán.")
    )

    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Duyệt", callback_data=f"admin_approve|{user_id}|{amount}"),
            InlineKeyboardButton(text="❌ Hủy", callback_data=f"admin_reject|{user_id}")
        ]
    ])
    
    await bot.send_message(
        ADMIN_ID,
        f"🔔 <b>YÊU CẦU NẠP TIỀN MỚI</b>\n\n"
        f"👤 Khách: <b>{m.from_user.full_name}</b>\n"
        f"🆔 ID: <code>{user_id}</code>\n"
        f"💵 Số tiền: <b>{amount:,}đ</b>\n"
        f"📝 Nội dung: <code>{memo}</code>",
        reply_markup=admin_kb
    )

@dp.callback_query(F.data.startswith("admin_"))
async def admin_action_handler(c: CallbackQuery):
    if c.from_user.id != ADMIN_ID:
        return await c.answer("Bạn không có quyền!", show_alert=True)
    
    parts = c.data.split("|")
    action = parts[0]
    target_id = int(parts[1])
    
    if action == "admin_approve":
        amount = int(parts[2])
        update_balance(target_id, amount)
        try:
            await bot.send_message(target_id, f"✅ <b>NẠP TIỀN THÀNH CÔNG!</b>\n\nTài khoản của bạn đã được cộng <b>{amount:,}đ</b>.")
        except: pass
        await c.message.edit_text(c.message.text + f"\n\n✅ <b>Đã duyệt {amount:,}đ</b>")
        await c.answer("Đã cộng tiền thành công!")
    elif action == "admin_reject":
        try:
            await bot.send_message(target_id, "❌ Yêu cầu nạp tiền đã bị từ chối.")
        except: pass
        await c.message.edit_text(c.message.text + "\n\n❌ <b>Đã từ chối</b>")
        await c.answer("Đã hủy yêu cầu!")

# --- XỬ LÝ OTP (ĐÃ CẬP NHẬT GIÁ) ---
@dp.callback_query(F.data == "otp_list")
async def otp_list_callback(c: CallbackQuery):
    res = await otp_api.get_apps()
    if res.get("ResponseCode") == 0:
        all_apps = res["Result"]
        fb_apps = [a for a in all_apps if "facebook" in a['Name'].lower()]
        other_apps = [a for a in all_apps if "facebook" not in a['Name'].lower()][:25]
        btns = []
        for app in (fb_apps + other_apps):
            # Nhân giá gốc (ví dụ 1.5) với 5000 (1000 để ra VNĐ và *5 giá bán)
            sell_price = int(float(app['Cost']) * 5000)
            btns.append([InlineKeyboardButton(
                text=f"{app['Name']} - {sell_price:,}đ", 
                callback_data=f"buy|{app['Id']}|{sell_price}"
            )])
        btns.append([InlineKeyboardButton(text="⬅️ Quay lại", callback_data="menu")])
        await c.message.edit_text("<b>Chọn dịch vụ:</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=btns))

@dp.callback_query(F.data.startswith("buy|"))
async def otp_buy_callback(c: CallbackQuery):
    _, app_id, sell_price = c.data.split("|")
    sell_price = int(sell_price)
    user_id = c.from_user.id
    is_admin = (user_id == ADMIN_ID)
    
    if not is_admin:
        user = get_user(user_id)
        if not user or user['balance'] < sell_price:
            return await c.answer(f"❌ Cần {sell_price:,}đ để thuê!", show_alert=True)
            
    await c.message.edit_text("⏳ Đang lấy số...")
    res = await otp_api.request_number(app_id)
    if res.get("ResponseCode") == 0:
        if not is_admin: update_balance(user_id, -sell_price)
        phone = res["Result"]["Number"]
        req_id = res["Result"]["Id"]
        display_phone = f"0{phone}" if not str(phone).startswith('0') else phone
        fee_display = "0đ (Admin)" if is_admin else f"{sell_price:,}đ"
        await c.message.edit_text(f"✅ <b>ĐÃ LẤY SỐ</b>\n📞 Số: <code>{display_phone}</code>\n💰 Phí: {fee_display}\n🕒 Đợi mã OTP...")
        asyncio.create_task(wait_for_otp(user_id, req_id, display_phone, sell_price, is_admin))
    else:
        await c.answer(f"Lỗi: {res.get('Msg')}", show_alert=True)

async def wait_for_otp(user_id, req_id, phone, sell_price, is_admin):
    for _ in range(60):
        await asyncio.sleep(7)
        res = await otp_api.get_otp_code(req_id)
        if res.get("ResponseCode") == 0:
            await bot.send_message(user_id, f"🎯 <b>MÃ OTP:</b> <code>{res['Result']['Code']}</code>\n📞 Số: <code>{phone}</code>")
            return
        elif res.get("ResponseCode") == 2: break
    if not is_admin: 
        update_balance(user_id, sell_price)
        await bot.send_message(user_id, f"❌ Hết hạn số <code>{phone}</code>. Đã hoàn lại {sell_price:,}đ.")
    else:
        await bot.send_message(user_id, f"❌ Hết hạn số <code>{phone}</code> (Admin).")

@dp.callback_query(F.data == "menu")
async def menu_back(c: CallbackQuery):
    await c.message.edit_text("🏠 <b>Menu</b>", reply_markup=main_menu_keyboard(c.from_user.id))

async def main():
    init_db()
    print("Bot is running...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())