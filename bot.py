import asyncio
import calendar
import json
import os
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import (
    InlineKeyboardButton, InlineKeyboardMarkup, FSInputFile,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
)
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.storage.memory import MemoryStorage

API_TOKEN = "8722047645:AAEG7wE-82ZI3CyBL14Mh4UQy3GT9J5bxL8"
ADMIN_ID = 7308147004

bot = Bot(token=API_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ─── Постоянное хранилище броней в файле ─────────────────────────────────────
BOOKINGS_FILE = "bookings.json"

def load_bookings() -> tuple[dict, int]:
    """Загружает брони из файла. Возвращает (bookings, max_id)."""
    if not os.path.exists(BOOKINGS_FILE):
        return {}, 0
    try:
        with open(BOOKINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Ключи в JSON всегда строки — конвертируем обратно в int
        bk = {int(k): v for k, v in data.get("bookings", {}).items()}
        counter = data.get("counter", 0)
        return bk, counter
    except Exception:
        return {}, 0

def save_bookings():
    """Сохраняет текущие брони в файл."""
    try:
        with open(BOOKINGS_FILE, "w", encoding="utf-8") as f:
            json.dump({"bookings": bookings, "counter": booking_counter}, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Ошибка сохранения броней: {e}")

# Загружаем при старте
bookings, booking_counter = load_bookings()

# Длительность сеанса — 2 часа (в слотах по 1 часу)
SESSION_HOURS = 2

services = [
    {"name": "Классический маникюр",           "price": "25€", "img": "images/klas.jpg"},
    {"name": "Маникюр с гель-лаком, коррекция", "price": "25€", "img": "images/gel.jpg"},
    {"name": "Наращивание ногтей",              "price": "35€", "img": "images/nara.jpg"},
    {"name": "Гигиенический педикюр",           "price": "25€", "img": "images/pedik.jpg"},
    {"name": "Педикюр с гель-лаком, коррекция", "price": "35€", "img": "images/pedik_gel.jpg"},
    {"name": "Мужской SPA-педикюр",             "price": "30€", "img": "images/spa.jpg"},
    {"name": "Снятие покрытия",                 "price": "15€", "img": "images/del.jpg"},
]

MONTHS = {
    1: "Январь",  2: "Февраль", 3: "Март",    4: "Апрель",
    5: "Май",     6: "Июнь",    7: "Июль",    8: "Август",
    9: "Сентябрь",10: "Октябрь",11: "Ноябрь", 12: "Декабрь"
}

TIME_SLOTS = ["09:00", "10:00", "11:00", "12:00", "13:00",
              "14:00", "15:00", "16:00", "17:00", "18:00", "19:00"]


# ─── FSM ─────────────────────────────────────────────────────────────────────

class Booking(StatesGroup):
    service = State()
    month   = State()
    day     = State()
    time    = State()
    name    = State()
    phone   = State()


class EditBooking(StatesGroup):
    service = State()
    month   = State()
    day     = State()
    time    = State()
    name    = State()
    phone   = State()


# ─── Вспомогательные функции ─────────────────────────────────────────────────

def next_booking_id() -> int:
    global booking_counter
    booking_counter += 1
    return booking_counter

def add_booking(user_id: int, booking: dict):
    """Добавляет бронь и сохраняет на диск."""
    bookings.setdefault(user_id, []).append(booking)
    save_bookings()

def remove_booking(user_id: int, bid: int):
    """Удаляет бронь и сохраняет на диск."""
    if user_id in bookings:
        bookings[user_id] = [x for x in bookings[user_id] if x["id"] != bid]
        save_bookings()


def get_booking(user_id: int, bid: int) -> dict | None:
    for b in bookings.get(user_id, []):
        if b["id"] == bid:
            return b
    return None


def get_all_bookings() -> list[dict]:
    """Все брони всех пользователей, отсортированные по дате/времени"""
    all_b = []
    for uid, user_bookings in bookings.items():
        for b in user_bookings:
            all_b.append({**b, "user_id": uid})
    all_b.sort(key=lambda x: (x["month"], x["day"], x["time"]))
    return all_b


def get_blocked_slots(month: int, day: int, exclude_bid: int | None = None) -> set[str]:
    """Возвращает множество заблокированных слотов на день (сам слот + SESSION_HOURS-1 после)"""
    blocked = set()
    for uid, user_bookings in bookings.items():
        for b in user_bookings:
            if exclude_bid and b["id"] == exclude_bid:
                continue
            if b["month"] == month and b["day"] == day:
                booked_idx = TIME_SLOTS.index(b["time"])
                # Блокируем booked_idx и SESSION_HOURS-1 слотов после
                for i in range(SESSION_HOURS):
                    idx = booked_idx + i
                    if 0 <= idx < len(TIME_SLOTS):
                        blocked.add(TIME_SLOTS[idx])
                # Также блокируем слоты ДО, которые захватят этот момент
                # (если кто-то запишется на час раньше, он тоже займёт этот слот)
                for i in range(1, SESSION_HOURS):
                    idx = booked_idx - i
                    if 0 <= idx < len(TIME_SLOTS):
                        blocked.add(TIME_SLOTS[idx])
    return blocked


def format_booking(b: dict, idx: int | None = None, show_user: bool = False) -> str:
    month_name = MONTHS[b["month"]]
    prefix = f"*Бронь №{idx}*\n" if idx else ""
    user_line = f"🆔 User ID: {b.get('user_id', '—')}\n" if show_user else ""
    return (
        f"{prefix}"
        f"💅 Услуга: {b['service']}\n"
        f"📅 Дата: {b['day']} {month_name}\n"
        f"🕐 Время: {b['time']}\n"
        f"👤 Имя: {b['name']}\n"
        f"📞 Телефон: {b['phone']}\n"
        f"{user_line}"
    )


# ─── Постоянная нижняя клавиатура ────────────────────────────────────────────

def bottom_kb(is_admin: bool = False) -> ReplyKeyboardMarkup:
    buttons = [[
        KeyboardButton(text="💅 Услуги"),
        KeyboardButton(text="📋 Мои брони"),
    ]]
    if is_admin:
        buttons[0].append(KeyboardButton(text="🔐 Админка"))
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


# ─── Инлайн-клавиатуры ───────────────────────────────────────────────────────

def main_menu_kb():
    rows = [
        [InlineKeyboardButton(text=f"{s['name']} — {s['price']}", callback_data=f"svc:{s['name']}")]
        for s in services
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def months_kb():
    now = datetime.now()
    rows, row = [], []
    for num, name in MONTHS.items():
        if num < now.month:
            continue
        row.append(InlineKeyboardButton(text=name, callback_data=f"month:{num}"))
        if len(row) == 3:
            rows.append(row); row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def days_kb(month: int):
    now = datetime.now()
    _, days_in_month = calendar.monthrange(now.year, month)
    rows, row = [], []
    for day in range(1, days_in_month + 1):
        if month == now.month and day < now.day:
            continue
        row.append(InlineKeyboardButton(text=str(day), callback_data=f"day:{day}"))
        if len(row) == 7:
            rows.append(row); row = []
    if row:
        rows.append(row)
    rows.append([
        InlineKeyboardButton(text="◀️ Назад",        callback_data="back_to_months"),
        InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def time_kb(month: int, day: int, exclude_bid: int | None = None):
    blocked = get_blocked_slots(month, day, exclude_bid)
    rows, row = [], []
    for slot in TIME_SLOTS:
        if slot in blocked:
            # Показываем занятый слот серым крестиком (нельзя нажать — disabled через текст)
            row.append(InlineKeyboardButton(text=f"❌ {slot}", callback_data="slot_busy"))
        else:
            cb = "t_" + slot.replace(":", "")
            row.append(InlineKeyboardButton(text=slot, callback_data=cb))
        if len(row) == 3:
            rows.append(row); row = []
    if row:
        rows.append(row)
    rows.append([
        InlineKeyboardButton(text="◀️ Назад",        callback_data="back_to_days"),
        InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def back_to_menu_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")],
    ])


def booking_list_kb(user_id: int):
    user_bookings = bookings.get(user_id, [])
    rows = []
    for i, b in enumerate(user_bookings, 1):
        month_name = MONTHS[b["month"]]
        label = f"#{i} — {b['service'][:18]} | {b['day']} {month_name} {b['time']}"
        rows.append([InlineKeyboardButton(text=label, callback_data=f"viewb:{b['id']}")])
    rows.append([InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def booking_actions_kb(bid: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✏️ Редактировать", callback_data=f"edit_booking:{bid}"),
            InlineKeyboardButton(text="🗑 Удалить",        callback_data=f"del_booking:{bid}"),
        ],
        [
            InlineKeyboardButton(text="◀️ Все брони",     callback_data="my_booking"),
            InlineKeyboardButton(text="🏠 Главное меню",  callback_data="main_menu"),
        ],
    ])


def confirm_delete_kb(bid: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"confirm_del:{bid}"),
            InlineKeyboardButton(text="❌ Отмена",       callback_data=f"viewb:{bid}"),
        ]
    ])


def edit_options_kb(bid: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💅 Изменить услугу",  callback_data=f"efield:service:{bid}")],
        [InlineKeyboardButton(text="📅 Изменить дату",    callback_data=f"efield:date:{bid}")],
        [InlineKeyboardButton(text="🕐 Изменить время",   callback_data=f"efield:time:{bid}")],
        [InlineKeyboardButton(text="👤 Изменить имя",     callback_data=f"efield:name:{bid}")],
        [InlineKeyboardButton(text="📞 Изменить телефон", callback_data=f"efield:phone:{bid}")],
        [InlineKeyboardButton(text="◀️ Назад",            callback_data=f"viewb:{bid}")],
    ])


def services_edit_kb(bid: int):
    rows = [
        [InlineKeyboardButton(text=f"{s['name']} — {s['price']}", callback_data=f"esvc:{bid}:{s['name']}")]
        for s in services
    ]
    rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data=f"edit_booking:{bid}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ─── Панель админа ───────────────────────────────────────────────────────────

def admin_panel_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Все брони",         callback_data="admin_all")],
        [InlineKeyboardButton(text="📅 Брони на сегодня",  callback_data="admin_today")],
        [InlineKeyboardButton(text="🔜 Брони на завтра",   callback_data="admin_tomorrow")],
    ])


def admin_booking_kb(bid: int, user_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑 Отменить бронь", callback_data=f"admin_del:{bid}:{user_id}")],
        [InlineKeyboardButton(text="◀️ Назад",          callback_data="admin_all")],
    ])


# ─── Старт ───────────────────────────────────────────────────────────────────

@dp.message(Command(commands=["start"]))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    is_admin = message.from_user.id == ADMIN_ID
    photo = FSInputFile("images/darja.png")
    await message.answer_photo(
        photo=photo,
        caption="💅 *Добро пожаловать!*\n\nЯ — Дарья, мастер маникюра и педикюра.",
        parse_mode="Markdown",
    )
    await message.answer("Выберите услугу 👇", reply_markup=bottom_kb(is_admin))
    await message.answer("Список услуг:", reply_markup=main_menu_kb())


# ─── Нижняя кнопка «Услуги» ──────────────────────────────────────────────────

@dp.message(F.text == "💅 Услуги")
async def btn_services(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Выберите услугу:", reply_markup=main_menu_kb())


# ─── Нижняя кнопка «Мои брони» ───────────────────────────────────────────────

@dp.message(F.text == "📋 Мои брони")
async def btn_my_bookings(message: types.Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    user_bookings = bookings.get(user_id, [])
    if not user_bookings:
        await message.answer("У вас нет активных броней.")
        return
    await message.answer(
        f"📋 *Ваши брони* ({len(user_bookings)} шт.):",
        parse_mode="Markdown",
        reply_markup=booking_list_kb(user_id)
    )


# ─── Нижняя кнопка «Панель админа» ───────────────────────────────────────────

@dp.message(F.text == "🔐 Админка")
async def btn_admin_panel(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔️ Нет доступа.")
        return
    all_b = get_all_bookings()
    await message.answer(
        f"🔐 *Панель администратора*\nВсего броней: {len(all_b)}",
        parse_mode="Markdown",
        reply_markup=admin_panel_kb()
    )


# ─── Инлайн: главное меню ────────────────────────────────────────────────────

@dp.callback_query(F.data == "main_menu")
async def go_main_menu(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.answer("Выберите услугу:", reply_markup=main_menu_kb())
    await call.answer()


# ─── Инлайн: мои брони ───────────────────────────────────────────────────────

@dp.callback_query(F.data == "my_booking")
async def show_my_bookings(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    user_id = call.from_user.id
    user_bookings = bookings.get(user_id, [])
    if not user_bookings:
        await call.answer("У вас нет активных броней.", show_alert=True)
        return
    await call.message.answer(
        f"📋 *Ваши брони* ({len(user_bookings)} шт.):",
        parse_mode="Markdown",
        reply_markup=booking_list_kb(user_id)
    )
    await call.answer()


@dp.callback_query(F.data.startswith("viewb:"))
async def view_booking(call: types.CallbackQuery):
    user_id = call.from_user.id
    bid = int(call.data.split(":")[1])
    b = get_booking(user_id, bid)
    if not b:
        await call.answer("Бронь не найдена.", show_alert=True)
        return
    user_bookings = bookings.get(user_id, [])
    idx = next((i + 1 for i, x in enumerate(user_bookings) if x["id"] == bid), 1)
    await call.message.answer(
        f"📋 {format_booking(b, idx)}",
        parse_mode="Markdown",
        reply_markup=booking_actions_kb(bid)
    )
    await call.answer()


# ─── Занятый слот ────────────────────────────────────────────────────────────

@dp.callback_query(F.data == "slot_busy")
async def slot_busy(call: types.CallbackQuery):
    await call.answer("❌ Это время занято. Мастер будет занят 2 часа.", show_alert=True)


# ─── Удаление брони (клиент) ─────────────────────────────────────────────────

@dp.callback_query(F.data.startswith("del_booking:"))
async def delete_booking_confirm(call: types.CallbackQuery):
    bid = int(call.data.split(":")[1])
    await call.message.answer("❗️ Вы уверены, что хотите удалить эту бронь?", reply_markup=confirm_delete_kb(bid))
    await call.answer()


@dp.callback_query(F.data.startswith("confirm_del:"))
async def confirm_delete(call: types.CallbackQuery):
    user_id = call.from_user.id
    bid = int(call.data.split(":")[1])
    b = get_booking(user_id, bid)
    if b and user_id in bookings:
        remove_booking(user_id, bid)
        await bot.send_message(ADMIN_ID, f"🗑 *Клиент отменил бронь!*\n\n{format_booking(b)}", parse_mode="Markdown")
    await call.message.answer("✅ Бронь удалена.", reply_markup=back_to_menu_kb())
    await call.answer()


# ─── Редактирование брони ────────────────────────────────────────────────────

@dp.callback_query(F.data.startswith("edit_booking:"))
async def edit_booking_menu(call: types.CallbackQuery):
    bid = int(call.data.split(":")[1])
    await call.message.answer("Что хотите изменить?", reply_markup=edit_options_kb(bid))
    await call.answer()


@dp.callback_query(F.data.startswith("efield:"))
async def edit_field_start(call: types.CallbackQuery, state: FSMContext):
    parts = call.data.split(":", 2)
    field, bid = parts[1], int(parts[2])
    await state.update_data(edit_bid=bid)

    if field == "service":
        await call.message.answer("Выберите новую услугу:", reply_markup=services_edit_kb(bid))
        await state.set_state(EditBooking.service)
    elif field == "date":
        await call.message.answer("Выберите новый месяц:", reply_markup=months_kb())
        await state.set_state(EditBooking.month)
    elif field == "time":
        user_id = call.from_user.id
        b = get_booking(user_id, bid)
        if b:
            await call.message.answer(
                "Выберите новое время:\n_(❌ — занято)_",
                parse_mode="Markdown",
                reply_markup=time_kb(b["month"], b["day"], exclude_bid=bid)
            )
        await state.set_state(EditBooking.time)
    elif field == "name":
        await call.message.answer("Введите новое имя:")
        await state.set_state(EditBooking.name)
    elif field == "phone":
        await call.message.answer("Введите новый номер телефона:")
        await state.set_state(EditBooking.phone)
    await call.answer()


async def notify_edit(user_id: int, bid: int):
    b = get_booking(user_id, bid)
    if not b:
        return
    save_bookings()  # Сохраняем изменения на диск
    user_bookings = bookings.get(user_id, [])
    idx = next((i + 1 for i, x in enumerate(user_bookings) if x["id"] == bid), 1)
    await bot.send_message(
        user_id,
        f"✅ *Ваша бронь обновлена!*\n\n{format_booking(b, idx)}",
        parse_mode="Markdown",
        reply_markup=booking_actions_kb(bid)
    )
    await bot.send_message(
        ADMIN_ID,
        f"✏️ *Клиент изменил бронь!*\n\n{format_booking(b)}",
        parse_mode="Markdown"
    )


@dp.callback_query(F.data.startswith("esvc:"), EditBooking.service)
async def edit_service_save(call: types.CallbackQuery, state: FSMContext):
    user_id = call.from_user.id
    _, bid_str, service_name = call.data.split(":", 2)
    bid = int(bid_str)
    b = get_booking(user_id, bid)
    if b:
        b["service"] = service_name
    await state.clear()
    await notify_edit(user_id, bid)
    await call.answer()


@dp.callback_query(F.data.startswith("month:"), EditBooking.month)
async def edit_month_save(call: types.CallbackQuery, state: FSMContext):
    month = int(call.data.split(":")[1])
    await state.update_data(edit_month=month)
    await call.message.answer(f"Выберите день ({MONTHS[month]}):", reply_markup=days_kb(month))
    await state.set_state(EditBooking.day)
    await call.answer()


@dp.callback_query(F.data.startswith("day:"), EditBooking.day)
async def edit_day_save(call: types.CallbackQuery, state: FSMContext):
    user_id = call.from_user.id
    day = int(call.data.split(":")[1])
    data = await state.get_data()
    bid = data["edit_bid"]
    month = data.get("edit_month")
    b = get_booking(user_id, bid)
    if b and month:
        b["month"] = month
        b["day"] = day
    await state.clear()
    await notify_edit(user_id, bid)
    await call.answer()


@dp.callback_query(F.data.startswith("t_"), EditBooking.time)
async def edit_time_save(call: types.CallbackQuery, state: FSMContext):
    user_id = call.from_user.id
    raw = call.data[2:]
    time_str = raw[:2] + ":" + raw[2:]
    data = await state.get_data()
    bid = data["edit_bid"]
    b = get_booking(user_id, bid)
    if b:
        b["time"] = time_str
    await state.clear()
    await notify_edit(user_id, bid)
    await call.answer()


@dp.message(EditBooking.name)
async def edit_name_save(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    data = await state.get_data()
    bid = data["edit_bid"]
    b = get_booking(user_id, bid)
    if b:
        b["name"] = message.text
    await state.clear()
    await notify_edit(user_id, bid)


@dp.message(EditBooking.phone)
async def edit_phone_save(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    data = await state.get_data()
    bid = data["edit_bid"]
    b = get_booking(user_id, bid)
    if b:
        b["phone"] = message.text
    await state.clear()
    await notify_edit(user_id, bid)


# ─── Панель админа (инлайн) ──────────────────────────────────────────────────

@dp.callback_query(F.data.startswith("admin_"))
async def admin_actions(call: types.CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("⛔️ Нет доступа.", show_alert=True)
        return

    action = call.data

    if action == "admin_all":
        all_b = get_all_bookings()
        if not all_b:
            await call.message.answer("Броней пока нет.")
            await call.answer()
            return
        # Показываем по 10 броней
        text = f"📋 *Все брони ({len(all_b)} шт.):*\n\n"
        rows = []
        for i, b in enumerate(all_b, 1):
            month_name = MONTHS[b["month"]]
            text += (
                f"*#{i}* | {b['day']} {month_name} {b['time']}\n"
                f"💅 {b['service']}\n"
                f"👤 {b['name']} | 📞 {b['phone']}\n\n"
            )
            rows.append([InlineKeyboardButton(
                text=f"🗑 Отменить #{i} — {b['name']} {b['day']} {month_name}",
                callback_data=f"admin_del:{b['id']}:{b['user_id']}"
            )])
        rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data="admin_back")])
        await call.message.answer(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))

    elif action == "admin_today":
        now = datetime.now()
        today_b = [b for b in get_all_bookings() if b["month"] == now.month and b["day"] == now.day]
        if not today_b:
            await call.message.answer("Сегодня броней нет.")
        else:
            text = f"📅 *Брони на сегодня ({now.day} {MONTHS[now.month]}):*\n\n"
            rows = []
            for i, b in enumerate(today_b, 1):
                text += f"*{b['time']}* | 💅 {b['service']}\n👤 {b['name']} | 📞 {b['phone']}\n\n"
                rows.append([InlineKeyboardButton(
                    text=f"🗑 Отменить {b['time']} — {b['name']}",
                    callback_data=f"admin_del:{b['id']}:{b['user_id']}"
                )])
            rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data="admin_back")])
            await call.message.answer(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))

    elif action == "admin_tomorrow":
        now = datetime.now()
        _, days_in_month = calendar.monthrange(now.year, now.month)
        if now.day < days_in_month:
            tom_day, tom_month = now.day + 1, now.month
        else:
            tom_day, tom_month = 1, now.month + 1 if now.month < 12 else 1
        tom_b = [b for b in get_all_bookings() if b["month"] == tom_month and b["day"] == tom_day]
        if not tom_b:
            await call.message.answer("Завтра броней нет.")
        else:
            text = f"🔜 *Брони на завтра ({tom_day} {MONTHS[tom_month]}):*\n\n"
            rows = []
            for i, b in enumerate(tom_b, 1):
                text += f"*{b['time']}* | 💅 {b['service']}\n👤 {b['name']} | 📞 {b['phone']}\n\n"
                rows.append([InlineKeyboardButton(
                    text=f"🗑 Отменить {b['time']} — {b['name']}",
                    callback_data=f"admin_del:{b['id']}:{b['user_id']}"
                )])
            rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data="admin_back")])
            await call.message.answer(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))

    elif action == "admin_back":
        all_b = get_all_bookings()
        await call.message.answer(
            f"🔐 *Панель администратора*\nВсего броней: {len(all_b)}",
            parse_mode="Markdown",
            reply_markup=admin_panel_kb()
        )

    elif action.startswith("admin_del:"):
        parts = action.split(":")
        bid, uid = int(parts[1]), int(parts[2])
        b = get_booking(uid, bid)
        if b and uid in bookings:
            remove_booking(uid, bid)
            # Уведомляем клиента
            try:
                await bot.send_message(
                    uid,
                    f"❌ *Ваша бронь была отменена мастером.*\n\n{format_booking(b)}",
                    parse_mode="Markdown"
                )
            except Exception:
                pass
            await call.message.answer(f"✅ Бронь #{bid} отменена.")
        else:
            await call.message.answer("Бронь не найдена.")

    await call.answer()


# ─── Новая бронь ─────────────────────────────────────────────────────────────

@dp.callback_query(F.data.startswith("svc:"))
async def service_choice(call: types.CallbackQuery, state: FSMContext):
    service_name = call.data[4:]
    service = next(s for s in services if s["name"] == service_name)
    await state.update_data(service=service_name)
    photo = FSInputFile(service["img"])
    await call.message.answer_photo(
        photo=photo,
        caption=f"✅ Вы выбрали: *{service_name}*\n\nВыберите месяц:",
        parse_mode="Markdown",
        reply_markup=months_kb()
    )
    await state.set_state(Booking.month)
    await call.answer()


@dp.callback_query(F.data == "back_to_months")
async def back_to_months(call: types.CallbackQuery, state: FSMContext):
    await call.message.answer("Выберите месяц:", reply_markup=months_kb())
    await state.set_state(Booking.month)
    await call.answer()


@dp.callback_query(F.data == "back_to_days")
async def back_to_days(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    month = data.get("month")
    if month:
        await call.message.answer(f"Выберите день ({MONTHS[month]}):", reply_markup=days_kb(month))
        await state.set_state(Booking.day)
    else:
        await call.message.answer("Выберите месяц:", reply_markup=months_kb())
        await state.set_state(Booking.month)
    await call.answer()


@dp.callback_query(F.data.startswith("month:"), Booking.month)
async def month_choice(call: types.CallbackQuery, state: FSMContext):
    month = int(call.data.split(":")[1])
    await state.update_data(month=month)
    await call.message.answer(f"Выберите день ({MONTHS[month]}):", reply_markup=days_kb(month))
    await state.set_state(Booking.day)
    await call.answer()


@dp.callback_query(F.data.startswith("day:"), Booking.day)
async def day_choice(call: types.CallbackQuery, state: FSMContext):
    day = int(call.data.split(":")[1])
    data = await state.get_data()
    month = data.get("month")
    await state.update_data(day=day)
    await call.message.answer(
        "Выберите удобное время:\n_(❌ — занято)_",
        parse_mode="Markdown",
        reply_markup=time_kb(month, day)
    )
    await state.set_state(Booking.time)
    await call.answer()


@dp.callback_query(F.data.startswith("t_"), Booking.time)
async def time_choice(call: types.CallbackQuery, state: FSMContext):
    raw = call.data[2:]
    time_str = raw[:2] + ":" + raw[2:]
    await state.update_data(time=time_str)
    await call.message.answer("Введите ваше имя:")
    await state.set_state(Booking.name)
    await call.answer()


@dp.message(Booking.name)
async def enter_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text)
    await message.answer("Введите ваш номер телефона:")
    await state.set_state(Booking.phone)


@dp.message(Booking.phone)
async def enter_phone(message: types.Message, state: FSMContext):
    data = await state.get_data()
    user_id = message.from_user.id

    bid = next_booking_id()
    new_booking = {
        "id":      bid,
        "service": data["service"],
        "month":   data["month"],
        "day":     data["day"],
        "time":    data["time"],
        "name":    data["name"],
        "phone":   message.text,
    }
    add_booking(user_id, new_booking)

    month_name = MONTHS[data["month"]]
    await message.answer(
        f"✅ *Бронь подтверждена!*\n\n{format_booking(new_booking)}",
        parse_mode="Markdown",
        reply_markup=back_to_menu_kb()
    )
    await bot.send_message(
        ADMIN_ID,
        f"🔔 *Новая бронь!*\n\n"
        f"💅 Услуга: {data['service']}\n"
        f"📅 Дата: {data['day']} {month_name}\n"
        f"🕐 Время: {data['time']}\n"
        f"👤 Имя: {data['name']}\n"
        f"📞 Телефон: {message.text}",
        parse_mode="Markdown"
    )
    await state.clear()


async def main():
    print("Бот запущен!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())