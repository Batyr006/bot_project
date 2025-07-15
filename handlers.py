import os
import io
import re
import threading
import sqlite3
import uuid


import telebot
from telebot import types
from keyboards import done_inline_keyboard
from keyboards import manage_photo_keyboard
from database import save_rating, get_ratings_for_user
from keyboards import main_menu_keyboard


from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from telebot.types import InputFile
from telebot.apihelper import ApiTelegramException


from database import (
    init_db, user_exists, create_user, update_user_main, get_user_data,
    update_sozhitel_info, update_tarif_info,
    create_application, get_applications_by_user, get_application,
    update_application, delete_application, add_application_photo,
    get_application_photos, set_application_status, get_pending_applications,
    get_average_rating, count_applications_by_user, update_rating, get_ratings_by_user, 
    add_response, DB_NAME  # новая функция для откликов
)
from keyboards import (
    get_role_keyboard, get_category_keyboard, get_district_keyboard, get_operator_keyboard,
    main_menu_keyboard, profile_edit_keyboard, my_applications_keyboard,
    confirm_keyboard, search_category_keyboard, admin_inline_buttons,
    create_app_keyboard, edit_contact_keyboard, recipient_keyboard,
    get_search_actions_keyboard  # новая клавиатура для поиска объявлений
)

# ========== Определение состояний (State Management) ==========
STATE_NONE = 0
STATE_SHOW_MY_APPS = 1000
STATE_WAITING_FULLNAME = 1
STATE_WAITING_LASTNAME = 2
STATE_WAITING_PHONE = 3
STATE_WAITING_ROLE = 4
STATE_WAITING_CATEGORY = 5
STATE_WAITING_DISTRICT = 6
STATE_WAITING_RENTPRICE = 7
STATE_WAITING_COMMENT = 8
STATE_WAITING_OPERATOR = 9
STATE_WAITING_TARIFFPRICE = 10
STATE_WAITING_DESCRIPTION = 11
STATE_WAITING_MONTHLY = 12
STATE_WAITING_PAYDAY = 13

STATE_APP_CHOOSE = 110
STATE_APP_EDIT = 111
STATE_APP_EDIT_TITLE = 112
STATE_APP_EDIT_DETAILS = 113

# --- Состояния для отзывов (Friendly Review Flow) ---
STATE_RATING_USER_ID = 120   # ждём ID пользователя, которому оставляют отзыв
STATE_RATING_MESSAGE = 121   # ждём сообщение с оценкой и комментарием
STATE_PHOTO_MANAGE = 902
temp_photos_for_review = {}  # (user_id, app_id): [list of photo paths]


STATE_PHOTO_ADD_CONFIRM = 903
STATE_CONFIRM_PHOTOS_SEND = 904
STATE_APP_EDIT_CONFIRM = 114




STATE_ADD_PHOTO_PROCESS = 901

# --- Состояния для поиска объявлений ---
STATE_SEARCH_CHOOSE_CAT = 200
STATE_SEARCH_DISTRICT = 201
STATE_SEARCH_OPERATOR = 202

# --- Состояния для создания заявки ---
STATE_APP_CHOOSE_TYPE = 300
STATE_APP_SOZHI_DISTRICT = 301
STATE_APP_SOZHI_TITLE = 302
STATE_APP_SOZHI_DETAILS = 303
STATE_APP_SOZHI_PHOTOS = 304
STATE_APP_TARIF_OPERATOR = 305
STATE_APP_TARIF_TITLE = 306
STATE_APP_TARIF_DETAILS = 307
STATE_APP_TARIF_PHOTOS = 308
STATE_APP_CONFIRM = 309

# --- Меню «Получатель» (для поиска) ---
STATE_RECIPIENT_MENU = 400

# Новое состояние для постраничного просмотра результатов поиска
STATE_SHOW_SEARCH_RESULTS = 777


STATE_EDIT_RATING_SELECT = 130
STATE_EDIT_RATING_INPUT = 131
STATE_EDIT_CONFIRM = 114



# очередь модерации правок заявок
pending_edits: dict[str, dict] = {}

# очередь модерации комментариев/отзывов
pending_moderations: dict[str, dict] = {}


# В разделе с состояниями добавьте:
STATE_ASK_PHOTOS = "ask_photos"  # Этап вопроса "Хотите добавить фото?"


# Список ID админов техподдержки
SUPPORT_ADMINS = [6466622805, 925319869, 6625311475]  # замени на реальные id

# Состояние пользователя в поддержке
STATE_SUPPORT_CHAT = "support_chat"

# Отслеживание активных чатов поддержки (кто кому отвечает)
support_active_chats = {}

# ID администратора в Telegram (пример) – сюда будут приходить уведомления! 👮‍♂️
ADMIN_ID = 2001143425

# Словарь для хранения состояний пользователей
user_states = {}

# множество заблокированных ID
banned_users = set()

PHOTO_REVIEW_PENDING = {}

# Создание папки для сохранения фотографий, если её нет, для удобства хранения фото заявок 📸
PHOTO_DIR = "user_photos"
if not os.path.exists(PHOTO_DIR):
    os.makedirs(PHOTO_DIR)


def register_handlers(bot: telebot.TeleBot):

        #1 Блокировать любые текстовые сообщения от забаненных
    @bot.message_handler(func=lambda m: m.from_user.id in banned_users)
    def blocked_user(msg: types.Message):
        bot.send_message(
            msg.chat.id,
            "🚫 Ваш аккаунт заблокирован администратором — вы не можете пользоваться ботом."
        )

    #2 Блокировать любые коллбэки от забаненных
    @bot.callback_query_handler(func=lambda c: c.from_user.id in banned_users)
    def blocked_callback(c: types.CallbackQuery):
        bot.answer_callback_query(
            c.id,
            "🚫 Ваш аккаунт заблокирован.",
            show_alert=True
        )


    @bot.message_handler(func=lambda m: m.text == "История отзывов")
    def send_rating_history_inline(msg: types.Message):
        user_id = msg.from_user.id
        # теперь — отзывы, которые пользователь оставил
        reviews = get_ratings_by_user(user_id)
        if not reviews:
            return bot.send_message(user_id, "Вы еще не оставляли отзывов.", reply_markup=main_menu_keyboard())

        text = "<b>История ваших отзывов:</b>\n\n"
        for rid, target_id, score, comment in reviews:
            stars = "★"*int(score) + ("½" if score - int(score) >= 0.5 else "")
            # подгружаем данные контакта, о котором оставили отзыв
            u = get_user_data(target_id)
            name = f"{u.get('first_name','')} {u.get('last_name','')}".strip() or "пользователь"
            text += f"#{rid} — отзыв о <b>{name}</b>: {stars} ({score}/5)\n{comment}\n\n"

        kb = InlineKeyboardMarkup(row_width=1)
        for rid, _, _, _ in reviews:
            kb.add(InlineKeyboardButton(f"Редактировать #{rid}", callback_data=f"edit_rating_{rid}"))
        kb.add(InlineKeyboardButton("Назад", callback_data="back_profile"))

        bot.send_message(user_id, text, parse_mode="HTML", reply_markup=kb)


    
    @bot.callback_query_handler(func=lambda c: c.data.startswith("edit_rating_") or c.data=="back_profile")
    def rating_history_nav(c: types.CallbackQuery):
        user_id = c.from_user.id
        bot.answer_callback_query(c.id)

        if c.data == "back_profile":
            bot.delete_message(user_id, c.message.message_id)
            return bot.send_message(user_id, "Возвращаемся в профиль.", reply_markup=profile_edit_keyboard())

        rid = int(c.data.split("_",2)[2])
        bot.send_message(user_id,
            f"✏️ Введите новый рейтинг (1–5) и комментарий для отзыва #{rid}:",
            parse_mode="HTML")
        user_states[user_id] = {"stage": STATE_EDIT_RATING_INPUT, "rating_id": rid}



    @bot.callback_query_handler(func=lambda c: c.data.startswith("edit_rating_") or c.data=="back_profile")
    def rating_history_nav(c: types.CallbackQuery):
        user_id = c.from_user.id
        bot.answer_callback_query(c.id)
        if c.data=="back_profile":
            bot.delete_message(user_id, c.message.message_id)
            bot.send_message(user_id, "Возвращаемся в профиль.", reply_markup=profile_edit_keyboard())
            return
        rid = int(c.data.split("_",2)[2])
        bot.send_message(user_id,
            f"✏️ Введите новый рейтинг (1–5) и комментарий для отзыва #{rid}:",
            parse_mode="HTML")
        user_states[user_id] = {"stage": STATE_EDIT_RATING_INPUT, "rating_id": rid}


  

    def notify_admin_new_application(user_id, app_id, title, details, cat):
        from database import get_user_data, get_application_photos
        from keyboards import admin_inline_buttons
        import os
        from telebot import types

        user_info = get_user_data(user_id)
        username = user_info.get('username', '')
        username_text = f"@{username}" if username else "(нет username)"
        admin_text = (
            f"Поступила новая заявка #{app_id} (pending)\n"
            f"Пользователь: <b>{user_info.get('first_name', '')} {user_info.get('last_name', '')}</b>\n"
            f"Телефон: <code>{user_info.get('phone', '')}</code>\n"
            f"ID: <code>{user_id}</code>\n"
            f"TG: {username_text}\n"
            f"Категория: {cat}\n"
            f"Заголовок: <b>{title}</b>\n"
            f"Описание: {details}"
        )
        bot.send_message(
            ADMIN_ID,
            admin_text,
            reply_markup=admin_inline_buttons(app_id),
            parse_mode="HTML"
        )
        photos = get_application_photos(app_id)
        media = []
        for p in photos:
            if os.path.exists(p):
                with open(p, 'rb') as f:
                    media.append(types.InputMediaPhoto(f.read(), caption=f"Заявка #{app_id}"))
        if media:
            bot.send_media_group(ADMIN_ID, media)

    def notify_admin_edited_application(user_id, app_id):
        from database import get_user_data, get_application, get_application_photos
        import os
        from telebot import types

        user_info = get_user_data(user_id)
        username = user_info.get('username', '')
        username_text = f"@{username}" if username else "(нет username)"
        app = get_application(user_id, app_id)
        if not app:
            return
        (db_id, cat, dist, op, title, details, status) = app
        admin_text = (
            f"‼️ <b>Заявка #{app_id} была ИЗМЕНЕНА пользователем!</b>\n"
            f"Пользователь: <b>{user_info.get('first_name', '')} {user_info.get('last_name', '')}</b>\n"
            f"Телефон: <code>{user_info.get('phone', '')}</code>\n"
            f"ID: <code>{user_id}</code>\n"
            f"TG: {username_text}\n"
            f"Категория: {cat}\n"
            f"Заголовок: <b>{title}</b>\n"
            f"Описание: {details}"
        )
        bot.send_message(
            ADMIN_ID,
            admin_text,
            parse_mode="HTML"
        )
        photos = get_application_photos(app_id)
        media = []
        for p in photos:
            if os.path.exists(p):
                with open(p, 'rb') as f:
                    media.append(types.InputMediaPhoto(f.read(), caption=f"Заявка #{app_id} (обновлено)"))
        if media:
            bot.send_media_group(ADMIN_ID, media)


    # ---------- Старт и приглашение к регистрации ----------
    @bot.message_handler(commands=['start'])
    def cmd_start(message: types.Message):
        init_db()
        user_id = message.from_user.id
        username = message.from_user.username
        if username:
            from database import update_user_username
            update_user_username(user_id, username)

        if user_exists(user_id):
            data = get_user_data(user_id)
            role = data.get("role", "")
            fname = data.get("first_name", "")
            bot.send_message(
                user_id,
                f"С возвращением, {fname}! 👋\n\nВыберите действие в меню:",
                reply_markup=main_menu_keyboard(role=role)
            )
            user_states[user_id] = STATE_NONE
        else:
            create_user(user_id)
            bot.send_message(
                user_id,
                "Здравствуйте! Я помогу вам разместить или найти предложения. 😊\n\n"
                "Для начала, представьтесь, пожалуйста — укажите сразу имя и фамилию через пробел.\n"
                "Пример: <b>Адил Батырхан</b>",
                parse_mode="HTML",
                reply_markup=types.ReplyKeyboardRemove()
            )
            user_states[user_id] = STATE_WAITING_FULLNAME

    # ---------- Регистрация: Имя и фамилия в одном сообщении ----------
    @bot.message_handler(func=lambda m: user_states.get(m.from_user.id) == STATE_WAITING_FULLNAME)
    def reg_fullname(msg: types.Message):
        user_id = msg.from_user.id
        parts = msg.text.strip().split(None, 1)
        if len(parts) < 2:
            return bot.send_message(
                user_id,
                "Пожалуйста, введите имя и фамилию через пробел. Например: Адил Батырхан"
            )
        first, last = parts
        update_user_main(user_id, "first_name", first)
        update_user_main(user_id, "last_name",  last)

        # — вот тут было простое текстовое приглашение, заменяем его на кнопку —
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        markup.add(types.KeyboardButton("📱 Отправить номер", request_contact=True))
        bot.send_message(
            user_id,
            "Отлично! Теперь укажите контактный телефон.\n\n"
            "• Нажмите кнопку «📱 Отправить номер», чтобы передать его из Telegram\n"
            "• Или просто введите номер вручную:",
            reply_markup=markup
        )
        user_states[user_id] = STATE_WAITING_PHONE


    @bot.message_handler(content_types=['contact'],
                     func=lambda m: user_states.get(m.from_user.id) == STATE_WAITING_PHONE)
    def reg_phone_contact(msg: types.Message):
        user_id = msg.from_user.id
        phone = msg.contact.phone_number  # Telegram даёт только цифры и плюс
        update_user_main(user_id, "phone", phone)
        user_states.pop(user_id, None)
        bot.send_message(
            user_id,
            "✅ Регистрация завершена!",
            reply_markup=main_menu_keyboard()
        )




    # ---------- Регистрация: Телефон -
    def is_valid_phone(phone: str) -> bool:
        """
        Проверка номера:
        - начинается с 87 (11 цифр) или +77 (12 символов);
        - содержит только цифры (после +).
        """
        phone = phone.strip().replace(" ", "")

        if phone.startswith("87") and len(phone) == 11 and phone.isdigit():
            return True
        elif phone.startswith("+77") and len(phone) == 12 and phone[1:].isdigit():
            return True
        return False


    @bot.message_handler(func=lambda m: user_states.get(m.from_user.id) == STATE_WAITING_PHONE)
    def reg_phone(msg: types.Message):
        user_id = msg.from_user.id
        phone = msg.text.strip()

        if not is_valid_phone(phone):
            bot.send_message(
                user_id,
                "❌ Неверный формат номера.\n"
                "Введите вручную, например:\n"
                "87771234567 или +77712345678",
                parse_mode="HTML"
            )
            return

        update_user_main(user_id, "phone", phone)
        user_states.pop(user_id, None)
        bot.send_message(
            user_id,
            "✅ Регистрация завершена!",
            reply_markup=main_menu_keyboard()
        )

   

    @bot.message_handler(func=lambda m: user_states.get(m.from_user.id) == STATE_WAITING_COMMENT)
    def reg_comment(msg: types.Message):
        user_id = msg.from_user.id
        update_sozhitel_info(user_id, "comment", msg.text.strip())
        role = get_user_data(user_id).get("role", "")
        bot.send_message(
            user_id,
            "Регистрация завершена! Ваш профиль продавца (Квартира) обновлён. 🎉",
            reply_markup=main_menu_keyboard(role=role)
        )
        user_states[user_id] = STATE_NONE

    # ======== Обработка пути для продавца (Тариф) ========
    @bot.message_handler(func=lambda m: user_states.get(m.from_user.id) == STATE_WAITING_OPERATOR)
    def reg_operator(msg: types.Message):
        user_id = msg.from_user.id
        if msg.text.lower() == "назад":
            bot.send_message(
                user_id,
                "Вернулись к выбору категории. ↩️",
                reply_markup=get_category_keyboard()
            )
            user_states[user_id] = STATE_WAITING_CATEGORY
            return

        update_tarif_info(user_id, "operator", msg.text.strip())
        bot.send_message(user_id, "Введите цену тарифа: 💵")
        user_states[user_id] = STATE_WAITING_TARIFFPRICE

    @bot.message_handler(func=lambda m: user_states.get(m.from_user.id) == STATE_WAITING_TARIFFPRICE)
    def reg_tariff_price(msg: types.Message):
        user_id = msg.from_user.id
        if msg.text.lower() == "назад":
            bot.send_message(
                user_id,
                "Вернулись к выбору оператора. ↩️",
                reply_markup=get_operator_keyboard()
            )
            user_states[user_id] = STATE_WAITING_OPERATOR
            return

        update_tarif_info(user_id, "tariff_price", msg.text.strip())
        bot.send_message(user_id, "Добавьте описание тарифа: 📝")
        user_states[user_id] = STATE_WAITING_DESCRIPTION

    @bot.message_handler(func=lambda m: user_states.get(m.from_user.id) == STATE_WAITING_DESCRIPTION)
    def reg_description(msg: types.Message):
        user_id = msg.from_user.id
        if msg.text.lower() == "назад":
            bot.send_message(user_id, "Вернулись к вводу цены тарифа. ↩️")
            user_states[user_id] = STATE_WAITING_TARIFFPRICE
            return

        update_tarif_info(user_id, "description", msg.text.strip())
        bot.send_message(user_id, "Сколько вы платите ежемесячно за этот тариф? 💸")
        user_states[user_id] = STATE_WAITING_MONTHLY

    @bot.message_handler(func=lambda m: user_states.get(m.from_user.id) == STATE_WAITING_MONTHLY)
    def reg_monthly(msg: types.Message):
        user_id = msg.from_user.id
        update_tarif_info(user_id, "monthly", msg.text.strip())
        bot.send_message(user_id, "Укажите день оплаты (например, «5 число»): 📆")
        user_states[user_id] = STATE_WAITING_PAYDAY

    @bot.message_handler(func=lambda m: user_states.get(m.from_user.id) == STATE_WAITING_PAYDAY)
    def reg_payday(msg: types.Message):
        user_id = msg.from_user.id
        update_tarif_info(user_id, "pay_day", msg.text.strip())
        role = get_user_data(user_id).get("role", "")
        bot.send_message(
            user_id,
            "Регистрация завершена! Профиль продавца (Тариф) обновлён. 🎉",
            reply_markup=main_menu_keyboard(role=role)
        )
        user_states[user_id] = STATE_NONE

    # ---------- "Главный меню" (смена роли) ----------
    # @bot.message_handler(func=lambda m: m.text == "Главный меню")
   # def main_menu_role(msg: types.Message):
        user_id = msg.from_user.id
        update_user_main(user_id, "role", None)
        bot.send_message(
            user_id,
            "Выберите роль заново: 👤",
            reply_markup=get_role_keyboard()
        )
        user_states[user_id] = STATE_WAITING_ROLE

    # ---------- "Назад" (общий обработчик) ----------
    @bot.message_handler(func=lambda m: m.text == "Назад")
    def go_back(msg: types.Message):
        user_id = msg.from_user.id
        role = get_user_data(user_id).get("role", "")
        bot.send_message(
            user_id,
            "Вы вернулись в главное меню. 🏠",
            reply_markup=main_menu_keyboard(role=role)
        )
        user_states[user_id] = STATE_NONE
        
    
   





    # ---------- Мой профиль ----------
    @bot.message_handler(func=lambda m: m.text == "Мой профиль")
    def my_profile(msg: types.Message):
        user_id = msg.from_user.id
        data = get_user_data(user_id)

        if not data:
            bot.send_message(user_id, "Нет сохранённых данных. Введите /start для регистрации. 🚀")
            return

        avg = get_average_rating(user_id)

        if avg is None or avg == 0:
            rating_str = "Нет оценок"
        else:
            try:
                val = round(avg, 1)
                full = int(val)
                half = (val - full) >= 0.5
                stars = "★" * full + ("½" if half else "")
                rating_str = f"{stars} / 5.0 (среднее {val})"
            except Exception as e:
                rating_str = "⚠️ Ошибка при расчёте рейтинга"
                print("Ошибка округления рейтинга:", e)

        c_app = count_applications_by_user(user_id)
        text = (
            f"<b>Ваш профиль</b>\n"
            f"Имя: {data.get('first_name','')}\n"
            f"Фамилия: {data.get('last_name','')}\n"
            f"Телефон: {data.get('phone','')}\n"
            f"Заявок: {c_app}\n"
            f"Рейтинг: {rating_str}"
        )
        bot.send_message(user_id, text, parse_mode="HTML", reply_markup=profile_edit_keyboard())

    # ---------- Редактировать контакт (Имя, Фамилия, Телефон) ----------
    @bot.message_handler(func=lambda m: m.text == "Редактировать контакт")
    def edit_contact(msg: types.Message):
        user_id = msg.from_user.id
        bot.send_message(
            user_id,
            "Что вы хотите изменить? Выберите опцию ниже: 🔧",
            reply_markup=edit_contact_keyboard()
        )
        user_states[user_id] = 210  # STATE_EDIT_CONTACT_CHOICE

    @bot.message_handler(func=lambda m: user_states.get(m.from_user.id) == 210)
    def choose_what_to_edit(msg: types.Message):
        user_id = msg.from_user.id
        text = msg.text.lower()
        if text == "изменить имя":
            bot.send_message(user_id, "Введите новое имя: ✏️")
            user_states[user_id] = 211
        elif text == "изменить фамилию":
            bot.send_message(user_id, "Введите новую фамилию: ✏️")
            user_states[user_id] = 212
        elif text == "изменить телефон":
            bot.send_message(user_id, "Введите новый телефон: 📞")
            user_states[user_id] = 213
        else:
            data = get_user_data(user_id)
            role = data.get("role", "")
            bot.send_message(
                user_id,
                "Отмена. Вы вернулись в главное меню. 🏠",
                reply_markup=main_menu_keyboard(role=role)
            )
            user_states[user_id] = STATE_NONE

    @bot.message_handler(func=lambda m: user_states.get(m.from_user.id) == 211)
    def process_new_firstname(msg: types.Message):
        user_id = msg.from_user.id
        update_user_main(user_id, "first_name", msg.text.strip())
        bot.send_message(
            user_id,
            "Имя успешно обновлено! ✅",
            reply_markup=profile_edit_keyboard()
        )
        user_states[user_id] = STATE_NONE

    @bot.message_handler(func=lambda m: user_states.get(m.from_user.id) == 212)
    def process_new_lastname(msg: types.Message):
        user_id = msg.from_user.id
        update_user_main(user_id, "last_name", msg.text.strip())
        bot.send_message(
            user_id,
            "Фамилия успешно обновлена! ✅",
            reply_markup=profile_edit_keyboard()
        )
        user_states[user_id] = STATE_NONE

    @bot.message_handler(func=lambda m: user_states.get(m.from_user.id) == 213)
    def process_new_phone(msg: types.Message):
         user_id = msg.from_user.id
         phone = msg.text.strip().replace(" ", "")
         if not is_valid_phone(phone):
             bot.send_message(
                  user_id,
                  "❌ Неверный формат номера...\n<code>+77712345678</code>",
                  parse_mode="HTML"
        )
             return
         update_user_main(user_id, "phone", phone)
         bot.send_message(user_id, "Телефон обновлён! ✅", reply_markup=profile_edit_keyboard())
         user_states[user_id] = STATE_NONE

      
     

    # ---------- Мои заявки ----------
    @bot.message_handler(func=lambda m: m.text == "Мои заявки")
    def my_apps(msg: types.Message):
        user_id = msg.from_user.id
        bot.send_message(
            user_id,
            "Управление вашими заявками: 📑",
            reply_markup=my_applications_keyboard()
        )

    
     # ---------- "Посмотреть заявки" (пользователь) ----------
    @bot.message_handler(func=lambda m: m.text == "Посмотреть заявки")
    def list_apps_inline(msg: types.Message):
        user_id = msg.from_user.id
        apps = [a for a in get_applications_by_user(user_id) if a[6] in ("approved","revise")]
        if not apps:
            return bot.send_message(user_id, "У вас пока нет проверенных заявок.", reply_markup=my_applications_keyboard())

        kb = InlineKeyboardMarkup(row_width=1)
        for aid,cat,dist,op,title,details,status in apps:
            kb.add(InlineKeyboardButton(f"#{aid} «{title}»", callback_data=f"open_app_{aid}"))
        kb.add(InlineKeyboardButton("Назад", callback_data="back_apps"))
        bot.send_message(user_id, "Выберите заявку:", reply_markup=kb)

        user_states[user_id] = {"stage": STATE_SHOW_MY_APPS, "apps": {a[0]: a for a in apps}}


    
    # 1) Кнопка «Посмотреть заявку» → показываем фото + детали и переключаем в STATE_APP_EDIT
    @bot.callback_query_handler(func=lambda c: c.data.startswith("open_app_") or c.data == "back_apps")
    def open_app_by_button(c: types.CallbackQuery):
        user_id = c.from_user.id
        bot.answer_callback_query(c.id)

        # Вернуться назад в список
        if c.data == "back_apps":
            bot.delete_message(user_id, c.message.message_id)
            bot.send_message(
                user_id,
                "Возвращаемся в меню заявок.",
                reply_markup=my_applications_keyboard()
            )
            return

        # Извлекаем ID заявки
        aid = int(c.data.split("_", 2)[2])
        app = user_states.get(user_id, {}).get("apps", {}).get(aid)
        if not app:
            return bot.send_message(user_id, "❌ Заявка не найдена.")

        # 1. Фото (альбомом, если есть)
        photos = get_application_photos(aid)
        if photos:
            media = []
            for p in photos:
                if os.path.exists(p):
                    with open(p, 'rb') as f:
                        media.append(types.InputMediaPhoto(f.read()))
            bot.send_media_group(user_id, media)

        # 2. Формируем текст с деталями
        _, category, district, operator, title, details, status = app
        if category == "квартира":
            info = (
                f"<b>Заявка #{aid}</b>\n"
                f"📁 Квартира\n"
                f"📌 Район: {district}\n"
                f"💰 Стоимость квартиры: {title}\n"
                f"📝 Описание: {details}\n"
                f"⚙️ Статус: {status}"
            )
        else:
            info = (
                f"<b>Заявка #{aid}</b>\n"
                f"📁 Тариф\n"
                f"📱 Оператор: {operator}\n"
                f"💰 Стоимость тарифа: {title}\n"
                f"📅 День оплаты: {details}\n"
                f"⚙️ Статус: {status}"
            )

        # 3. Выводим клавиатуру управления
        kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
        kb.add("✏️ Редактировать", "🖼️ Редактировать фото")
        kb.add("🗑 Удалить", "Назад")
        bot.send_message(user_id, info, parse_mode="HTML", reply_markup=kb)

        # 4. Переводим в режим управления заявкой
        user_states[user_id] = {"stage": STATE_APP_EDIT, "app_id": aid}

    


    # Админ: Одобрить / Доработать / Отклонить (бан)
    @bot.callback_query_handler(func=lambda c: re.match(r'^(approve|reject|revise)_\d+$', c.data))
    def handle_admin_review(c: types.CallbackQuery):
        action, app_id_str = c.data.split("_", 1)
        app_id = int(app_id_str)

        # выбираем статус и текст для админа
        if action == "approve":
            new_status = "approved"
            user_msg = f"✅ Заявка #{app_id} одобрена."
        elif action == "revise":
            new_status = "revise"
            user_msg = f"⚠️ Заявка #{app_id} отправлена на доработку."
        else:  # reject
            new_status = "rejected"
            user_msg = f"❌ Заявка #{app_id} отклонена — аккаунт заблокирован."

        # обновляем статус в базе
        set_application_status(app_id, new_status)

        # отвечаем администратору на callback
        bot.answer_callback_query(c.id, text=user_msg, show_alert=False)

        # редактируем сообщение администратора, убираем кнопки
        bot.edit_message_text(
            chat_id=c.message.chat.id,
            message_id=c.message.message_id,
            text=f"Заявка #{app_id}: {user_msg}",
            reply_markup=None
        )

        # находим автора заявки
        conn = sqlite3.connect(DB_NAME)
        cur = conn.cursor()
        cur.execute("SELECT user_id FROM applications WHERE id=?", (app_id,))
        row = cur.fetchone()
        conn.close()
        if not row:
            return
        user_id = row[0]

        # если отклонено — баним
        if new_status == "rejected":
            banned_users.add(user_id)

        # уведомляем автора
        if new_status in ("approved", "revise"):
            bot.send_message(
                user_id,
                f"{user_msg}\nЗайдите в «Посмотреть заявки», чтобы увидеть её статус."
            )
        else:
            bot.send_message(
                user_id,
                "Ваша заявка отклонена и ваш аккаунт заблокирован. 😔"
            )

        # сбрасываем любое состояние пользователя
        user_states.pop(user_id, None)


    @bot.message_handler(func=lambda m: isinstance(user_states.get(m.from_user.id), dict)
                                and user_states[m.from_user.id].get("stage") == STATE_APP_EDIT)
    def manage_single_app(msg: types.Message):
        user_id = msg.from_user.id
        st = user_states[user_id]
        app_id = st["app_id"]
        text = msg.text.strip().lower()

        if text == "✏️ редактировать":
            # получим категорию прямо из базы
            row = get_application(user_id, app_id)  # (id, category, district, operator, title, details, status)
            _, category, _, _, _, _, _ = row
            # сформируем понятный пользователю запрос
            if category == "квартира":
                prompt = "Введите новую стоимость квартиры:"
            else:
                prompt = "Введите новую стоимость тарифа:"
            bot.send_message(user_id, prompt, reply_markup=types.ReplyKeyboardRemove())
            # сохраняем в состояние и ждём заголовок
            user_states[user_id] = {
                "stage": STATE_APP_EDIT_TITLE,
                "app_id": app_id,
                "category": category
            }
            return

        elif text == "🖼️ редактировать фото":
            user_states[user_id] = STATE_PHOTO_MANAGE
            user_states[(user_id, "app_id")] = app_id
            bot.send_message(user_id, "Выберите действие с фото:", reply_markup=manage_photo_keyboard())
            return

        elif text == "🗑 удалить":
            delete_application(user_id, app_id)
            bot.send_message(user_id, f"Заявка #{app_id} удалена. 🗑", reply_markup=my_applications_keyboard())
            user_states[user_id] = STATE_NONE
            return

        elif text == "назад":
            bot.send_message(user_id, "Возвращаемся в меню заявок.", reply_markup=my_applications_keyboard())
            user_states[user_id] = STATE_NONE
            return

        else:
            bot.send_message(user_id, "Пожалуйста, воспользуйтесь кнопками ниже.")


    
    

    @bot.message_handler(func=lambda m: user_states.get(m.from_user.id) == STATE_APP_CHOOSE)
    def choose_app(msg: types.Message):
        user_id = msg.from_user.id
        if not msg.text.isdigit():
            bot.send_message(user_id, "Пожалуйста, введите число (ID заявки). 🔢")
            return

        app_id = int(msg.text)
        row = get_application(user_id, app_id)
        if not row:
            bot.send_message(
                user_id,
                f"Заявка #{app_id} не найдена. ❌",
                reply_markup=my_applications_keyboard()
            )
            user_states[user_id] = STATE_NONE
            return

        (db_id, cat, dist, op, title, details, status) = row
        bot.send_message(
            user_id,
            f"Заявка #{db_id} [{status}] ({cat})\n"
            f"{title}\n{details}\n\n"
            "Доступны команды:\n/edit — редактировать\n/delete — удалить\n/cancel — отменить",
            reply_markup=my_applications_keyboard()
        )
        user_states[user_id] = {
            "stage": STATE_APP_EDIT,
            "app_id": db_id
        }

    # === Обработка команд внутри карточки заявки ===
    @bot.message_handler(func=lambda m: isinstance(user_states.get(m.from_user.id), dict)
                                        and user_states[m.from_user.id].get("stage") == "MANAGE_APP")
    def manage_single_app(msg: types.Message):
        user_id = msg.from_user.id
        st = user_states[user_id]
        app_id = st.get("app_id")
        text = msg.text.lower()

        if text == "🗑 удалить":
            delete_application(user_id, app_id)
            bot.send_message(user_id, f"Заявка #{app_id} удалена. 🗑", reply_markup=my_applications_keyboard())
            user_states[user_id] = STATE_NONE

        elif text == "назад":
            # Возвращаем в список заявок
            apps = get_applications_by_user(user_id)
            if not apps:
                bot.send_message(user_id, "У вас пока нет заявок. 😕", reply_markup=my_applications_keyboard())
                user_states[user_id] = STATE_NONE
                return

            user_states[user_id] = {
                "stage": "VIEW_APPS_LIST",
                "apps": apps
            }

            text = f"<b>Всего заявок: {len(apps)}</b>\n\n"
            for (app_id, cat, dist, op, title, details, status) in apps:
                text += f"🔹 <b>#{app_id}</b>: {title} — <i>{cat}</i> ({status})\n"

            text += "\nВведите <b>ID заявки</b>, чтобы открыть. Или отправьте «Назад»."
            bot.send_message(user_id, text, parse_mode="HTML")

        elif text == "✏️ редактировать":
            # Пока добавим только редактирование заголовка и описания (по аналогии)
            bot.send_message(user_id, "Введите новый заголовок заявки: ✏️")
            st["stage"] = "EDIT_TITLE"



        elif text == "🖼️ редактировать фото":
            user_states[user_id] = STATE_PHOTO_MANAGE
            user_states[(user_id, 'app_id')] = app_id
            bot.send_message(user_id, "Выберите действие с фото:", reply_markup=manage_photo_keyboard())

    @bot.message_handler(func=lambda m: user_states.get(m.from_user.id) == STATE_PHOTO_MANAGE)
    def manage_photo_action(msg: types.Message):

        user_id = msg.from_user.id
        text = msg.text.strip()
        app_id = user_states.get((user_id, 'app_id'))

        if text == "➕ Добавить фото":
            # уходим в режим накопления новых фото
            user_states[user_id] = {
                "stage": STATE_ADD_PHOTO_PROCESS,
                "app_id": app_id,
                "new_photos": []
            }
            bot.send_message(
                user_id,
                f"Отправьте до 8 фото для заявки #{app_id}. "
                "Когда закончите — нажмите «✅ Готово» или просто напишите «готов» (любым регистром), "
                "или нажмите «❌ Отмена» или напишите «отмена».",
                reply_markup=done_inline_keyboard()
            )
            return

        elif text == "♻️ Заменить фото":
            send_photo_delete_options(bot, user_id, app_id)
            bot.send_message(
                user_id,
                "Выберите, какие фото удалить или нажмите «Удалить все фотографии».",
                reply_markup=None
            )

        elif text == "Назад":
            from database import get_applications_by_user
            apps = get_applications_by_user(user_id)
            for app in apps:
                if app[0] == app_id:
                    (db_id, cat, dist, op, title, details, status) = app
                    info = (
                        f"<b>Заявка #{db_id}</b>\n"
                        f"📁 Категория: {cat}\n"
                        f"📌 Район: {dist or '-'}\n"
                        f"📱 Оператор: {op or '-'}\n"
                        f"📝 Заголовок: {title}\n"
                        f"🔍 Описание: {details}\n"
                        f"⚙️ Статус: {status}"
                    )

                    # Добавим обновлённые фотографии
                    photos = get_application_photos(app_id)
                    media = []
                    for p in photos:
                        if os.path.exists(p):
                            with open(p, 'rb') as f:
                                media.append(types.InputMediaPhoto(f.read()))
                    if media:
                        bot.send_media_group(user_id, media)

                    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
                    kb.add("✏️ Редактировать", "🖼️ Редактировать фото")
                    kb.add("🗑 Удалить", "Назад")
                    bot.send_message(user_id, info, parse_mode="HTML", reply_markup=kb)
                    user_states[user_id] = {
                        "stage": "MANAGE_APP",
                        "app_id": app_id
                    }
                    return
            bot.send_message(user_id, "Заявка не найдена.")
            user_states[user_id] = STATE_NONE

    @bot.callback_query_handler(func=lambda call: call.data == "del_all_request")
    def confirm_delete_all(call):
        markup = InlineKeyboardMarkup()
        markup.add(
            InlineKeyboardButton("✅ Да, удалить", callback_data="del_all_confirm"),
            InlineKeyboardButton("❌ Нет", callback_data="del_all_cancel")
        )
        bot.edit_message_text(
            "❗ Вы уверены, что хотите удалить все фотографии?",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=markup
        )

    @bot.callback_query_handler(func=lambda call: call.data == "del_all_confirm")
    def do_delete_all(call):
        user_id = call.from_user.id
        app_id = user_states.get((user_id, 'app_id'))
        photos = get_application_photos(app_id)
        for p in photos:
            if os.path.exists(p):
                os.remove(p)
        with sqlite3.connect(DB_NAME) as conn:
            conn.execute("DELETE FROM application_photos WHERE application_id=?", (app_id,))
        bot.edit_message_text("✅ Все фотографии удалены.", call.message.chat.id, call.message.message_id)

    @bot.callback_query_handler(func=lambda call: call.data == "del_all_cancel")
    def cancel_delete_all(call):
        bot.edit_message_text("❌ Отменено.", call.message.chat.id, call.message.message_id)

    @bot.message_handler(func=lambda m: isinstance(user_states.get(m.from_user.id), dict)
                                        and user_states[m.from_user.id].get("stage") == "EDIT_TITLE")
    def edit_title(msg: types.Message):
        user_id = msg.from_user.id
        st = user_states[user_id]
        st["new_title"] = msg.text.strip()
        st["stage"] = "EDIT_DETAILS"
        bot.send_message(user_id, "Теперь введите новое описание заявки: 📝")

    @bot.message_handler(func=lambda m: isinstance(user_states.get(m.from_user.id), dict)
                                        and user_states[m.from_user.id].get("stage") == "EDIT_DETAILS")
    def edit_details(msg: types.Message):
        user_id = msg.from_user.id
        st = user_states[user_id]
        new_title = st.get("new_title", "")
        new_details = msg.text.strip()
        app_id = st.get("app_id")

        update_application(user_id, app_id, new_title, new_details)

        bot.send_message(user_id, f"Заявка #{app_id} обновлена ✅", reply_markup=my_applications_keyboard())
        user_states[user_id] = STATE_NONE

    @bot.message_handler(commands=['edit'])
    def cmd_edit_app(msg: types.Message):
        user_id = msg.from_user.id
        st = user_states.get(user_id)
        if not isinstance(st, dict) or st.get("stage") != STATE_APP_EDIT:
            return
        bot.send_message(user_id, "Введите новый заголовок: ✏️")
        user_states[user_id] = {
            "stage": STATE_APP_EDIT_TITLE,
            "app_id": st["app_id"]
        }

    @bot.message_handler(commands=['delete'])
    def cmd_delete_app(msg: types.Message):
        user_id = msg.from_user.id
        st = user_states.get(user_id)
        if not isinstance(st, dict) or st.get("stage") != STATE_APP_EDIT:
            return
        app_id = st["app_id"]
        delete_application(user_id, app_id)
        bot.send_message(
            user_id,
            f"Заявка #{app_id} успешно удалена! 🗑️",
            reply_markup=my_applications_keyboard()
        )
        user_states[user_id] = STATE_NONE

    @bot.message_handler(commands=['cancel'])
    def cmd_cancel_app(msg: types.Message):
        user_id = msg.from_user.id
        bot.send_message(user_id, "Действие отменено. 🔙", reply_markup=my_applications_keyboard())
        user_states[user_id] = STATE_NONE

    
    
    #Пользователь нажал «✏️ Редактировать», ввёл новый заголовок:
    @bot.message_handler(
        func=lambda m: isinstance(user_states.get(m.from_user.id), dict)
                    and user_states[m.from_user.id].get("stage") == STATE_APP_EDIT_TITLE
    )
    def edit_app_title(msg: types.Message):
        user_id = msg.from_user.id
        new_title = msg.text.strip()
        st = user_states[user_id]
        st["new_title"] = new_title
        st["stage"]     = STATE_APP_EDIT_DETAILS
        bot.send_message(
            user_id,
            "Теперь введите новое описание заявки: 📝",
            reply_markup=types.ReplyKeyboardRemove()
        )


    @bot.message_handler(func=lambda m: isinstance(user_states.get(m.from_user.id), dict) and user_states[m.from_user.id].get("stage") == STATE_APP_EDIT_DETAILS)
    def edit_app_details(msg: types.Message):
        user_id     = msg.from_user.id
        st          = user_states[user_id]
        app_id      = st["app_id"]
        new_title   = st["new_title"]
        new_details = msg.text.strip()

        # генерируем уникальный ID модерации
        mod_id = str(uuid.uuid4())
        pending_edits[mod_id] = {
            "user_id":     user_id,
            "app_id":      app_id,
            "new_title":   new_title,
            "new_details": new_details
        }

        # текст для админов
        text = (
            f"✏️ <b>Пользователь предложил правки</b> к заявке #{app_id}:\n\n"
            f"<b>Новый заголовок:</b> {new_title}\n"
            f"<b>Новое описание:</b> {new_details}"
        )
        kb = InlineKeyboardMarkup(row_width=2)
        kb.add(
            InlineKeyboardButton("✅ Принять", callback_data=f"approve_edit_{mod_id}"),
            InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_edit_{mod_id}")
        )

        # рассылаем всем техподдержке
        for adm in SUPPORT_ADMINS:
            bot.send_message(adm, text, parse_mode="HTML", reply_markup=kb)

        # оповещаем автора
        bot.send_message(
            user_id,
            "✅ Ваши правки отправлены на модерацию техподдержке.",
            reply_markup=my_applications_keyboard()
        )
        user_states[user_id] = STATE_NONE



    # Обработка решения админа по правкам
    @bot.callback_query_handler(func=lambda c: re.match(r'^(approve|reject)_edit_[\w-]+$', c.data))
    def handle_edit_moderation(c: types.CallbackQuery):
        action, _, mod_id = c.data.partition("_edit_")
        data = pending_edits.pop(mod_id, None)
        bot.answer_callback_query(c.id)

        if not data:
            return bot.send_message(c.from_user.id, "⚠️ Эти правки уже были обработаны.")

        app_id    = data["app_id"]
        orig_user = data["user_id"]
        title     = data["new_title"]
        details   = data["new_details"]

        # оповещаем остальных админов, что решение уже принято
        for adm in SUPPORT_ADMINS:
            if adm != c.from_user.id:
                bot.send_message(
                    adm,
                    f"⚠️ Админ @{c.from_user.username} обработал правки к заявке #{app_id}. Дальнейшие действия не требуются."
                )

        if action == "approve":
            # ─────── ВАЖНО ───────
            # меняем статус заявки на approved, чтобы она появилась в Поиске
            set_application_status(app_id, "approved")
            # ─────────────────────

            # применяем новые заголовок и описание
            update_application(orig_user, app_id, title, details)
            bot.send_message(orig_user, f"✅ Ваши правки к заявке #{app_id} одобрены администратором, Можете найти свою заявку в поиске.")
        else:
            bot.send_message(orig_user, f"❌ Ваши правки к заявке #{app_id} отклонены администратором.")

        # убираем кнопки у админа
        bot.edit_message_reply_markup(c.message.chat.id, c.message.message_id, reply_markup=None)




    @bot.message_handler(func=lambda msg: isinstance(user_states.get(msg.from_user.id), dict) and user_states[msg.from_user.id].get("stage") == "EDIT_TITLE")
    def edit_title(msg: types.Message):
        user_id = msg.from_user.id
        new_title = msg.text.strip()

        st = user_states[user_id]
        app_id = st.get("app_id")
        update_application_title(app_id, new_title)
        bot.send_message(user_id, "✅ Заголовок обновлен. Теперь введите новое описание заявки:")
        st["stage"] = "EDIT_DESCRIPTION"

    # ---------- Создание заявки ----------
    @bot.message_handler(func=lambda m: m.text == "Создать заявку")
    def create_app_menu(msg: types.Message):
        user_states[msg.from_user.id] = STATE_APP_CHOOSE_TYPE
        bot.send_message(
            msg.chat.id,
            "Выберите тип заявки, которую хотите создать: 📝",
            reply_markup=create_app_keyboard()
        )

    @bot.message_handler(func=lambda m: user_states.get(m.from_user.id) == STATE_APP_CHOOSE_TYPE)
    def process_app_type(msg: types.Message):
        user_id = msg.from_user.id
        text = msg.text.lower()

        if text == "квартира":
            bot.send_message(
                user_id,
                "Выберите район для заявки «Квартира»: 🌍",
                reply_markup=get_district_keyboard()
            )
            user_states[user_id] = {
                "stage": "APP_SOZHI_DISTRICT",
                "category": "квартира",
                "photos": []
            }

        elif text == "тариф":
            bot.send_message(
                user_id,
                "Выберите оператора для заявки «Тариф»: 📱",
                reply_markup=get_operator_keyboard()
            )
            user_states[user_id] = {
                "stage": "APP_TARIF_OPERATOR",
                "category": "тариф",
                "photos": []
            }

        elif text == "назад":
            role = get_user_data(user_id).get("role", "")
            bot.send_message(
                user_id,
                "Вы вернулись в главное меню. 🏠",
                reply_markup=main_menu_keyboard(role=role)
            )
            user_states[user_id] = STATE_NONE

        else:
            bot.send_message(
                user_id,
                "Пожалуйста, выберите «Квартира», «Тариф» или «Назад». ❓"
            )

    # ---------- Создание заявки "Квартира" ----------
    @bot.message_handler(func=lambda m: isinstance(user_states.get(m.from_user.id), dict)
                                     and user_states[m.from_user.id].get("stage") == "APP_SOZHI_DISTRICT")
    def create_app_sozhi_district(msg: types.Message):
        user_id = msg.from_user.id
        st = user_states[user_id]

        if msg.text.lower() == "назад":
            bot.send_message(
                user_id,
                "Вы вернулись назад к выбору типа заявки. ↩️",
                reply_markup=create_app_keyboard()
            )
            user_states[user_id] = STATE_APP_CHOOSE_TYPE
            return

        st["district"] = msg.text.strip()
        st["stage"] = "APP_SOZHI_TITLE"
        bot.send_message(user_id, "Укажите цену аренды (число или строку): 💰")

    @bot.message_handler(func=lambda m: isinstance(user_states.get(m.from_user.id), dict)
                                     and user_states[m.from_user.id].get("stage") == "APP_SOZHI_TITLE")
    def create_app_sozhi_title(msg: types.Message):
        user_id = msg.from_user.id
        st = user_states[user_id]

        if msg.text.lower() == "назад":
            bot.send_message(
                user_id,
                "Вы вернулись к выбору района. ↩️",
                reply_markup=get_district_keyboard()
            )
            st["stage"] = "APP_SOZHI_DISTRICT"
            return

        st["title"] = msg.text
        st["stage"] = "APP_SOZHI_DETAILS"
        bot.send_message(user_id, "Добавьте дополнительный комментарий к жилью (например, «рядом метро», «2 комнаты» и т.п.): 📝")

    @bot.message_handler(func=lambda m: isinstance(user_states.get(m.from_user.id), dict)
                                     and user_states[m.from_user.id].get("stage") == "APP_SOZHI_DETAILS")
    def create_app_sozhi_details(msg: types.Message):
        user_id = msg.from_user.id
        st = user_states[user_id]

        if msg.text.lower() == "назад":
            bot.send_message(user_id, "Вы вернулись к заголовку заявки. ↩️")
            st["stage"] = "APP_SOZHI_TITLE"
            return

        st["details"] = msg.text
        st["stage"] = "APP_SOZHI_PHOTOS"
        st["photos"] = []
        bot.send_message(
            user_id,
            "Теперь отправьте от 1 до 8 фото. Когда закончите, нажмите кнопку <b>Готово</b>. 📸",
            parse_mode="HTML",
            reply_markup=done_inline_keyboard()
        )

    # ---------- Создание заявки "Тариф" ----------
    @bot.message_handler(func=lambda m: isinstance(user_states.get(m.from_user.id), dict)
                                    and user_states[m.from_user.id].get("stage") == "APP_TARIF_OPERATOR")
    def create_app_tarif_operator(msg: types.Message):
        user_id = msg.from_user.id
        st = user_states[user_id]

        if msg.text.lower() == "назад":
            bot.send_message(
                user_id,
                "Вы вернулись назад к выбору типа заявки. ↩️",
                reply_markup=create_app_keyboard()
            )
            user_states[user_id] = STATE_APP_CHOOSE_TYPE
            return

        st["operator"] = msg.text.strip()
        st["stage"] = "APP_TARIF_TITLE"
        bot.send_message(user_id, "Сколько вы платите ежемесячно за этот тариф? 💸")

    @bot.message_handler(func=lambda m: isinstance(user_states.get(m.from_user.id), dict)
                                    and user_states[m.from_user.id].get("stage") == "APP_TARIF_TITLE")
    def create_app_tarif_title(msg: types.Message):
        user_id = msg.from_user.id
        st = user_states[user_id]

        if msg.text.lower() == "назад":
            bot.send_message(
                user_id,
                "Вы вернулись к выбору оператора. ↩️",
                reply_markup=get_operator_keyboard()
            )
            st["stage"] = "APP_TARIF_OPERATOR"
            return

        st["title"] = msg.text
        st["stage"] = "APP_TARIF_DETAILS"
        bot.send_message(user_id, "Укажите день оплаты и добавьте дополнительный комментарий (например, «5 число»): 📆")


    @bot.message_handler(func=lambda m: isinstance(user_states.get(m.from_user.id), dict)
                                    and user_states[m.from_user.id].get("stage") == "APP_TARIF_DETAILS")
    def create_app_tarif_details(msg: types.Message):
        user_id = msg.from_user.id
        st = user_states[user_id]

        if msg.text.lower() == "назад":
            bot.send_message(user_id, "Вы вернулись к заголовку заявки. ↩️")
            st["stage"] = "APP_TARIF_TITLE"
            return

        st["details"] = msg.text
        
        # Вместо сразу запроса фото, спрашиваем нужны ли они
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        markup.add("Да", "Нет")
        
        bot.send_message(
            user_id,
            "Хотите добавить фото к тарифу? 📸\n"
            "(Если да - нажмите «Да» и загрузите до 8 фото. Если нет - «Нет» для продолжения)",
            reply_markup=markup
        )
        st["stage"] = STATE_ASK_PHOTOS
        st["photos"] = []  # Инициализируем пустой список фото


    @bot.message_handler(func=lambda m: isinstance(user_states.get(m.from_user.id), dict)
                                 and user_states[m.from_user.id].get("stage") == STATE_ASK_PHOTOS)
    def handle_photo_choice(msg: types.Message):
        user_id = msg.from_user.id
        st = user_states[user_id]
        text = msg.text.lower()

        if text == "да":
            bot.send_message(
                user_id,
                "Отправьте от 1 до 8 фото. Когда закончите, нажмите «✅ Готово»",
                reply_markup=done_inline_keyboard()
            )
            st["stage"] = "APP_TARIF_PHOTOS"
        elif text == "нет":
            st["photos"] = []  # Пустой список фото
            st["stage"] = STATE_APP_CONFIRM
            show_tarif_confirmation(user_id)  # Показываем подтверждение без фото
        else:
            bot.send_message(user_id, "Пожалуйста, выберите «Да» или «Нет»")

    def show_tarif_confirmation(user_id):
        st = user_states[user_id]
        count = len(st.get("photos", []))
        operator = st.get("operator", "—")
        
        txt = (
            f"📱 <b>Новая заявка — Тариф</b>\n"
            f"🔌 Оператор: {operator}\n"
            f"💰 Стоимость тарифа: {st['title']}\n"
            f"📅 Условия оплаты: {st['details']}\n"
            f"📷 Фото загружено: {count}\n\n"
            "Подтвердить создание заявки? (Да/Нет) ✅❌"
        )
        
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        markup.add("Да", "Нет")
        
        bot.send_message(user_id, txt, parse_mode="HTML", reply_markup=markup)


    # === ОБНОВЛЁННЫЙ ХЭНДЛЕР PHOTO ===
    @bot.message_handler(content_types=['photo'])
    def handle_app_photos(msg: types.Message):
        user_id = msg.from_user.id
        st = user_states.get(user_id)

        if isinstance(st, dict):
            stage = st.get("stage")
        else:
            stage = st

        if stage == STATE_ADD_PHOTO_PROCESS:
            app_id = user_states.get((user_id, 'app_id'))
            new_photos = st.get("new_photos", [])

            # ✅ Новая проверка — суммируем все фото
            existing_photos = get_application_photos(app_id)
            total_photos = len(existing_photos) + len(new_photos)

            if total_photos >= 8:
                bot.reply_to(msg, f"🚫 Вы не можете добавить больше 8 фото. Сейчас уже: {len(existing_photos)} сохранено, +{len(new_photos)} новых.")
                return

            # Сохраняем фото
            file_info = bot.get_file(msg.photo[-1].file_id)
            dl = bot.download_file(file_info.file_path)
            path = os.path.join(PHOTO_DIR, f"app_{app_id}_{file_info.file_unique_id}.jpg")

            with open(path, 'wb') as f:
                f.write(dl)

            new_photos.append(path)
            st["new_photos"] = new_photos

            reply = bot.reply_to(msg, f"✅ Фото принято ({len(new_photos)} / {8 - len(existing_photos)} добавлено).")
            threading.Timer(1.5, lambda: bot.delete_message(reply.chat.id, reply.message_id)).start()

        elif stage in ["APP_SOZHI_PHOTOS", "APP_TARIF_PHOTOS"]:
            if len(st.get("photos", [])) >= 8:
                bot.reply_to(msg, "Уже добавлено 8 фото, больше нельзя. ❌")
                return

            file_info = bot.get_file(msg.photo[-1].file_id)
            dl = bot.download_file(file_info.file_path)
            path = os.path.join(PHOTO_DIR, f"temp_{user_id}_{file_info.file_unique_id}.jpg")
            with open(path, 'wb') as f:
                f.write(dl)
            st["photos"].append(path)
            resp = bot.reply_to(msg, f"Фото принято ({len(st['photos'])}). 📸")
            threading.Timer(1.5, lambda: bot.delete_message(resp.chat.id, resp.message_id)).start()

    # === ОБНОВЛЁННЫЙ DONE HANDLER ===
    @bot.message_handler(commands=['done'])
    def done_creation_photos(msg: types.Message):
        user_id = msg.from_user.id
        st = user_states.get(user_id, {})

        if isinstance(st, dict):
            if st.get("stage") == STATE_ADD_PHOTO_PROCESS:
                photos = st.get("new_photos", [])
                if len(photos) == 0:
                    bot.send_message(user_id, "Вы не добавили ни одной фотографии. 📷")
                    return

                app_id = user_states.get((user_id, 'app_id'))
                user_states[user_id] = STATE_CONFIRM_PHOTOS_SEND
                user_states[(user_id, 'photos_to_send')] = photos
                bot.send_message(user_id, f"Вы точно хотите отправить {len(photos)} фото админу для заявки #{app_id}?",
                                 reply_markup=confirm_keyboard())

            elif st.get("stage") in ["APP_SOZHI_PHOTOS", "APP_TARIF_PHOTOS"]:
                if len(st["photos"]) < 1:
                    bot.send_message(user_id, "Нужно минимум 1 фото! 📷")
                    return

                st["stage"] = STATE_APP_CONFIRM
                cat = st["category"]
                txt = (
                    f"Заголовок: {st['title']}\n"
                    f"Описание: {st['details']}\n"
                    f"Фото загружено: {len(st['photos'])}\n"
                    f"Тип заявки: {cat}\n\n"
                    "Подтвердить создание заявки? (Да/Нет) ✅❌"
                )
                bot.send_message(user_id, txt, reply_markup=confirm_keyboard())

    # === ЗАВЕРШЕНИЕ ДОБАВЛЕНИЯ ФОТО (ГОТОВО) ===
    
    @bot.message_handler(func=lambda msg: msg.text and msg.text.strip().lower().replace("✅", "").replace(".", "").replace("!", "").strip() in ["готов", "готово"])
    def handle_ready_send_photos(msg):
        user_id = msg.from_user.id
        st = user_states.get(user_id)

        if not isinstance(st, dict):
            bot.send_message(user_id, "⚠️ Сейчас нельзя завершить загрузку фото. Начните с добавления фото.")
            return

        stage = st.get("stage")

        # ✅ Добавление фото (редактирование)
        if stage == STATE_ADD_PHOTO_PROCESS:
            photos = st.get("new_photos", [])
            if not photos:
                bot.send_message(user_id, "⚠️ Вы не добавили ни одной фотографии.")
                return

            app_id = user_states.get((user_id, 'app_id'))
            user_states[user_id] = STATE_CONFIRM_PHOTOS_SEND
            user_states[(user_id, 'photos_to_send')] = photos

            kb = types.InlineKeyboardMarkup()
            kb.add(
                types.InlineKeyboardButton("✅ Готово", callback_data="photos_send_confirm"),
                types.InlineKeyboardButton("❌ Отмена", callback_data="photos_send_cancel")
            )

            bot.send_message(user_id, f"Вы точно хотите отправить {len(photos)} фото админу для заявки #{app_id}?",
                            reply_markup=kb)

        # ✅ Создание заявки
        elif stage in ["APP_SOZHI_PHOTOS", "APP_TARIF_PHOTOS"]:
            photos = st.get("photos", [])
            if len(photos) < 1:
                bot.send_message(user_id, "⚠️ Нужно минимум 1 фото! 📷")
                return

            st["stage"] = STATE_APP_CONFIRM
            cat = st["category"]
            txt = (
                f"Заголовок: {st['title']}\n"
                f"Описание: {st['details']}\n"
                f"Фото загружено: {len(photos)}\n"
                f"Тип заявки: {cat}\n\n"
                "Подтвердить создание заявки? (Да/Нет) ✅❌"
            )
            bot.send_message(user_id, txt, reply_markup=confirm_keyboard())

        else:
            bot.send_message(user_id, "⚠️ Сейчас нельзя завершить загрузку фото. Начните с добавления фото.")



    def save_temp_photo_for_review(app_id, user_id, path):
        key = (user_id, app_id)
        if key not in temp_photos_for_review:
            temp_photos_for_review[key] = []
        temp_photos_for_review[key].append(path)

    def approve_photos_for_application(app_id, user_id):
        key = (user_id, app_id)
        photos = temp_photos_for_review.get(key, [])
        for path in photos:
            add_application_photo(app_id, user_id, path)
        temp_photos_for_review.pop(key, None)

    def reject_photos_for_application(app_id, user_id):
        key = (user_id, app_id)
        temp_photos_for_review.pop(key, None)  # просто удаляем временные фото



    @bot.callback_query_handler(func=lambda call: call.data == "photos_send_confirm")
    def confirm_photos_send(call):
        user_id = call.from_user.id
        app_id = user_states.get((user_id, 'app_id'))
        photos = user_states.get((user_id, 'photos_to_send'), [])

        if not app_id or not photos:
            bot.send_message(user_id, "⚠️ Ошибка: не удалось получить фото или заявку.")
            return

        # Получаем данные пользователя
        data = get_user_data(user_id)
        caption = (
            f"📸 Пользователь: <b>{data.get('first_name', '')} {data.get('last_name', '')}</b>\n"
            f"Телефон: <code>{data.get('phone', '')}</code>\n"
            f"ID: <code>{user_id}</code>\n"
            f"TG: @{data.get('username') or '(нет)'}\n"
            f"К заявке: #{app_id}\n"
            f"Тип: {data.get('category', 'квартира')}\n\n"
            f"Пользователь добавил фото к заявке\n"
            f"Выберите: ✅ Принять или ❌ Отклонить"
        )

        # Кнопки “Принять” / “Отклонить”
        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(
            types.InlineKeyboardButton("✅ Принять", callback_data=f"approve_photos_{user_id}_{app_id}"),
            types.InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_photos_{user_id}_{app_id}")
        )

        # Отправляем текст с кнопками
        bot.send_message(ADMIN_ID, caption, parse_mode="HTML", reply_markup=keyboard)

        # Отправляем фото залпом (альбомом)
        media = []
        for path in photos:
            with open(path, 'rb') as f:
                media.append(types.InputMediaPhoto(f.read()))
            save_temp_photo_for_review(app_id, user_id, path)

        bot.send_media_group(ADMIN_ID, media)

        bot.send_message(user_id, "✅ Фото отправлены админу на модерацию!", reply_markup=my_applications_keyboard())

        # Сброс состояний
        user_states[user_id] = STATE_NONE
        user_states.pop((user_id, 'app_id'), None)
        user_states.pop((user_id, 'photos_to_send'), None)

    

    @bot.callback_query_handler(func=lambda call: call.data.startswith("approve_photos_"))
    def approve_photos(call):
        try:
            parts = call.data.split("_")
            user_id = int(parts[2])
            app_id = int(parts[3])

            approve_photos_for_application(app_id, user_id)
            bot.answer_callback_query(call.id, "Фото одобрены ✅")
            bot.send_message(call.message.chat.id, "✅ Фото одобрено.")

            # Уведомление пользователю
            bot.send_message(user_id, f"✅ Ваши фото к заявке #{app_id} одобрены администратором.")
        except Exception as e:
            bot.answer_callback_query(call.id, "❌ Ошибка при одобрении фото.")
            print("Ошибка в approve_photos:", e)


    @bot.callback_query_handler(func=lambda call: call.data.startswith("reject_photos_"))
    def reject_photos(call):
        try:
            parts = call.data.split("_")
            user_id = int(parts[2])
            app_id = int(parts[3])

            reject_photos_for_application(app_id, user_id)
            bot.answer_callback_query(call.id, "Фото отклонены ❌")
            bot.send_message(call.message.chat.id, "❌ Фото отклонено.")

            # Уведомление пользователю
            bot.send_message(user_id, f"❌ Ваши фото к заявке #{app_id} были отклонены администратором.")
        except Exception as e:
            bot.answer_callback_query(call.id, "❌ Ошибка при отклонении фото.")
            print("Ошибка в reject_photos:", e)


    @bot.callback_query_handler(func=lambda call: call.data == "photos_send_cancel")
    def cancel_photos_send(call):
        user_id = call.from_user.id
        bot.send_message(user_id, "❌ Отправка фото отменена.", reply_markup=my_applications_keyboard())
        user_states[user_id] = STATE_NONE
        user_states.pop((user_id, 'app_id'), None)
        user_states.pop((user_id, 'photos_to_send'), None)

    def send_photo_to_admin_review(user_id, app_id, path):
        from_main_user = get_user_data(user_id)
        fname = from_main_user.get("first_name", "")
        text = (
            f"📸 Фото от <b>{fname}</b> к заявке #{app_id}\n"
            f"Выберите, одобрить или отклонить."
        )
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton("✅ Принять", callback_data=f"photo_ok:{path}"),
            types.InlineKeyboardButton("❌ Отклонить", callback_data=f"photo_no:{path}")
        )

        with open(path, 'rb') as photo:
            bot.send_photo(ADMIN_ID, photo, caption=text, parse_mode="HTML", reply_markup=markup)

        PHOTO_REVIEW_PENDING[path] = (user_id, app_id)

    @bot.callback_query_handler(func=lambda call: call.data.startswith("photo_ok:"))
    def approve_photo(call):
        path = call.data.split(":", 1)[1]
        if path not in PHOTO_REVIEW_PENDING:
            bot.answer_callback_query(call.id, "Фото не найдено.")
            return

        user_id, app_id = PHOTO_REVIEW_PENDING.pop(path)
        add_application_photo(app_id, user_id, path)

        bot.answer_callback_query(call.id, "Фото одобрено.")
        bot.edit_message_caption(
            caption="✅ Фото одобрено.",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id
        )
        bot.send_message(user_id, f"✅ Ваше фото к заявке #{app_id} одобрено администратором.")

    @bot.callback_query_handler(func=lambda call: call.data.startswith("photo_no:"))
    def reject_photo(call):
        path = call.data.split(":", 1)[1]
        if path not in PHOTO_REVIEW_PENDING:
            bot.answer_callback_query(call.id, "Фото не найдено.")
            return

        user_id, app_id = PHOTO_REVIEW_PENDING.pop(path)
        if os.path.exists(path):
            os.remove(path)

        bot.answer_callback_query(call.id, "Фото отклонено.")
        bot.edit_message_caption(
            caption="❌ Фото отклонено.",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id
        )
        bot.send_message(user_id, f"❌ Ваше фото к заявке #{app_id} было отклонено администратором.")

    @bot.callback_query_handler(func=lambda call: call.data == "cancel_send_photos")
    def cancel_send_photos(call):
        user_id = call.from_user.id
        bot.send_message(user_id, "❌ Отправка фото отменена.", reply_markup=my_applications_keyboard())
        user_states[user_id] = STATE_NONE
        user_states.pop((user_id, 'app_id'), None)
        user_states.pop((user_id, 'photos_to_send'), None)

    @bot.message_handler(func=lambda msg: msg.text and msg.text.strip().lower() in ["✅ готово"] and user_states.get(
        msg.from_user.id) == STATE_CONFIRM_PHOTOS_SEND)
    def confirm_photo_send(msg):
        user_id = msg.from_user.id
        app_id = user_states.get((user_id, 'app_id'))
        photos = user_states.get((user_id, 'photos_to_send'), [])

        data = get_user_data(user_id)
        caption = (
            f"📸 Пользователь: <b>{data.get('first_name', '')} {data.get('last_name', '')}</b>\n"
            f"Телефон: <code>{data.get('phone', '')}</code>\n"
            f"ID: <code>{user_id}</code>\n"
            f"TG: @{data.get('username') or '(нет)'}\n"
            f"К заявке: #{app_id}\n"
            f"Тип: {data.get('category', 'квартира')}\n\n"
            f"Пользователь добавил фото к заявке\n"
            f"Выберите: ✅ Принять или ❌ Отклонить"
        )

        bot.send_message(ADMIN_ID, caption, parse_mode="HTML")

        media = []
        for p in photos:
            with open(p, 'rb') as f:
                media.append(types.InputMediaPhoto(f.read()))
            add_application_photo(app_id, user_id, p)

        bot.send_media_group(ADMIN_ID, media)
        bot.send_message(user_id, "✅ Фото отправлены админу на модерацию!", reply_markup=my_applications_keyboard())

        user_states[user_id] = STATE_NONE
        user_states.pop((user_id, 'app_id'), None)
        user_states.pop((user_id, 'photos_to_send'), None)

    @bot.message_handler(
        func=lambda msg: msg.text and msg.text.strip().lower() in ["отмена", "❌ отмена", "❌отмена"] and user_states.get(
            msg.from_user.id) == STATE_CONFIRM_PHOTOS_SEND)
    def cancel_photo_confirmation(msg):
        user_id = msg.from_user.id
        bot.send_message(user_id, "🚫 Отправка фото отменена.", reply_markup=my_applications_keyboard())
        user_states[user_id] = STATE_NONE
        user_states.pop((user_id, 'photos_to_send'), None)
        user_states.pop((user_id, 'app_id'), None)

    # === ОТМЕНА ДОБАВЛЕНИЯ ФОТО ===
    @bot.message_handler(func=lambda msg: msg.text and msg.text.strip().lower() in ["отмена", "❌ отмена", "❌отмена"])
    def cancel_photo_upload(msg):
        user_id = msg.from_user.id
        st = user_states.get(user_id)

        if isinstance(st, dict) and st.get("stage") == STATE_ADD_PHOTO_PROCESS:
            bot.send_message(user_id, "🚫 Загрузка фото отменена. Вы вернулись в меню.",
                             reply_markup=my_applications_keyboard())
            user_states[user_id] = STATE_NONE
            user_states.pop((user_id, 'app_id'), None)
            user_states.pop((user_id, 'photos_to_send'), None)
        else:
            bot.send_message(user_id, "ℹ️ Сейчас нечего отменять.")

    @bot.callback_query_handler(func=lambda call: call.data == "photos_done")
    def handle_done_button(call):
        user_id = call.from_user.id
        msg = call.message

        bot.delete_message(msg.chat.id, msg.message_id)

        # Просто эмулируем минимальный объект
        class FakeMessage:
            def __init__(self, user_id, chat_id):
                self.from_user = types.User(user_id, is_bot=False, first_name="User")
                self.chat = types.Chat(chat_id, "private")
                self.text = "/done"
                self.photo = None  # добавить, чтобы не падало

        fake_msg = FakeMessage(user_id, msg.chat.id)
        done_creation_photos(fake_msg)

    @bot.message_handler(func=lambda m: isinstance(user_states.get(m.from_user.id), dict)
                                    and user_states[m.from_user.id].get("stage") == STATE_APP_CONFIRM)
    def confirm_app_creation(msg: types.Message):
        user_id = msg.from_user.id
        st = user_states[user_id]
        text = msg.text.lower()

        if text == "да":
            cat = st["category"]
            
            # Валидация обязательных полей
            if cat == "квартира":
                dist = st.get("district")
                if not dist:
                    bot.send_message(user_id, "❌ Выберите район! Без района заявку сохранить нельзя.")
                    return
                    
                new_id = create_application(user_id, cat, dist, None, st["title"], st["details"])
                
                # Формируем красивое сообщение для квартиры
                count = len(st.get("photos", []))
                txt = (
                    f"🏠 <b>Новая заявка — Квартира</b>\n"
                    f"📌 Район: {dist}\n"
                    f"💰 Стоимость квартиры: {st['title']}\n"
                    f"📝 Описание: {st['details']}\n"
                    f"📷 Фото загружено: {count}\n\n"
                    "✅ Заявка создана и отправлена на модерацию!"
                )
                
            elif cat == "тариф":
                op = st.get("operator")
                if not op:
                    bot.send_message(user_id, "❌ Выберите оператора! Без оператора заявку сохранить нельзя.")
                    return
                    
                new_id = create_application(user_id, cat, None, op, st["title"], st["details"])
                
                # Формируем красивое сообщение для тарифа
                count = len(st.get("photos", []))
                txt = (
                    f"📱 <b>Новая заявка — Тариф</b>\n"
                    f"🔌 Оператор: {op}\n"
                    f"💰 Стоимость тарифа: {st['title']}\n"
                    f"📅 Условия оплаты: {st['details']}\n"
                    f"📷 Фото загружено: {count}\n\n"
                    "✅ Заявка создана и отправлена на модерацию!"
                )
            
            # Добавляем фото если они есть
            for p in st.get("photos", []):
                add_application_photo(new_id, user_id, p)

            # Уведомляем админа
            notify_admin_new_application(user_id, new_id, st['title'], st['details'], cat)
            
            # Отправляем пользователю подтверждение
            bot.send_message(
                user_id,
                txt,
                parse_mode="HTML",
                reply_markup=my_applications_keyboard()
            )
            
        else:
            # Если пользователь отказался
            bot.send_message(
                user_id,
                "❌ Создание заявки отменено",
                reply_markup=my_applications_keyboard()
            )
        
        # В любом случае сбрасываем состояние
        user_states[user_id] = STATE_NONE



    @bot.message_handler(func=lambda m: user_states.get(m.from_user.id) == STATE_RATING_USER_ID)
    def handle_rating_id(msg: types.Message):
        user_id = msg.from_user.id
        if msg.text.lower() == "назад":
            role = get_user_data(user_id).get("role", "")
            bot.send_message(
                user_id,
                "Отмена. Возвращаемся в главное меню. 🔙",
                reply_markup=main_menu_keyboard(role=role)
            )
            user_states[user_id] = STATE_NONE
            return

        match = re.search(r'(\d+)', msg.text)
        if not match:
            bot.send_message(
                user_id,
                "Не вижу числа в вашем сообщении. Пожалуйста, введите именно ID (число) или «Назад» для отмены. ❓"
            )
            return

        target_id = int(match.group(1))
        user_states[(user_id, 'target_id')] = target_id
        user_states[user_id] = STATE_RATING_MESSAGE

        bot.send_message(
            user_id,
            "Отлично! Теперь введите <b>оценку</b> (число 1–5) и ваш комментарий в одном сообщении.\n\n"
            "Пример: «5 Всё понравилось, буду рекомендовать!»\n"
            "или «3 Медленно отвечали, но помогли».\n\n"
            "Если хотите отменить – отправьте «Назад».",
            parse_mode="HTML"
        )


    
    # Перехват ввода отзыва и отправка на модерацию
    @bot.message_handler(func=lambda m: user_states.get(m.from_user.id) == STATE_RATING_MESSAGE)
    def handle_rating_message(msg: types.Message):
        user_id = msg.from_user.id
        text    = msg.text.strip()

        # «Назад» — отмена
        if text.lower() == "назад":
            role = get_user_data(user_id).get("role", "")
            bot.send_message(user_id, "Отмена. Возвращаемся в меню.", reply_markup=main_menu_keyboard(role=role))
            user_states[user_id] = STATE_NONE
            return

        # Разбор: первое слово — рейтинг, остальное — комментарий
        parts = text.split(maxsplit=1)
        try:
            rating = float(parts[0].replace(",", "."))
        except (ValueError, IndexError):
            return bot.send_message(
                user_id,
                "Сначала число 1–5, затем комментарий.\nПример: <b>4.5 Отлично!</b>",
                parse_mode="HTML"
            )

        if rating < 1 or rating > 5:
            return bot.send_message(user_id, "Рейтинг должен быть от 1 до 5.")

        comment   = parts[1].strip() if len(parts) > 1 else "Без комментария"
        target_id = user_states.get((user_id, "target_id"))

        # кладём в очередь модерации
        mod_id = str(uuid.uuid4())
        pending_moderations[mod_id] = {
            "rater":  user_id,
            "target": target_id,
            "rating": rating,
            "comment": comment
        }

        # формируем сообщение и кнопки для админов
        text_to_admin = (
            f"📝 Новый отзыв от <code>{user_id}</code> о пользователе <code>{target_id}</code>:\n\n"
            f"⭐️ <b>{rating}/5</b>\n"
            f"{comment}"
        )
        kb = InlineKeyboardMarkup(row_width=2)
        kb.add(
            InlineKeyboardButton("✅ Пропустить", callback_data=f"mod_skip_{mod_id}"),
            InlineKeyboardButton("⚠️ Перепредупредить", callback_data=f"mod_warn_{mod_id}")
        )

        # отправляем всем SUPPORT_ADMINS
        for adm in SUPPORT_ADMINS:
            bot.send_message(adm, text_to_admin, parse_mode="HTML", reply_markup=kb)

        # благодарим автора
        bot.send_message(
            user_id,
            "✅ Ваш отзыв отправлен на модерацию. Спасибо!",
            reply_markup=main_menu_keyboard(role=get_user_data(user_id).get("role",""))
        )
        user_states[user_id] = STATE_NONE


    # Обработка решения админа по отзыву
    @bot.callback_query_handler(func=lambda c: re.match(r'^mod_(skip|warn)_[\w-]+$', c.data))
    def handle_comment_moderation(c: types.CallbackQuery):
        _, decision, mod_id = c.data.split("_", 2)
        data = pending_moderations.pop(mod_id, None)
        bot.answer_callback_query(c.id)

        if not data:
            return bot.send_message(c.from_user.id, "⚠️ Этот отзыв уже был обработан.")

        rater  = data["rater"]
        target = data["target"]
        rating = data["rating"]
        comment= data["comment"]

        # уведомляем остальных админов, что уже обработано
        for adm in SUPPORT_ADMINS:
            if adm != c.from_user.id:
                bot.send_message(
                    adm,
                    f"ℹ️ Админ @{c.from_user.username} уже {'пропустил' if decision=='skip' else 'удалил'} отзыв {mod_id}."
                )

        if decision == "skip":
            # сохраняем отзыв в БД
            save_rating(rater_id=rater, user_id=target, rating=rating, comment=comment)
            bot.send_message(rater, "✅ Ваш отзыв одобрен и опубликован.")
        else:
            bot.send_message(rater, "⚠️ Ваш отзыв удалён. Ваш аккаунт под риском блокировки.")

        # убираем кнопки у админа
        bot.edit_message_reply_markup(c.message.chat.id, c.message.message_id, reply_markup=None)
        # сбрасываем состояние пользователя-автора (если нужно)
        user_states.pop(rater, None)


    # ─── Поиск объявлений (Команда "Поиск") ────────────────────────────────────────
    @bot.message_handler(func=lambda m: m.text == "Поиск")
    def cmd_search(msg: types.Message):
        user_id = msg.from_user.id
        user_states[user_id] = STATE_SEARCH_CHOOSE_CAT
        bot.send_message(
            user_id,
            "Что именно хотите искать? «Поиск Квартиры» или «Поиск Тариф»? 🔍",
            reply_markup=search_category_keyboard()
        )

    @bot.message_handler(func=lambda m: user_states.get(m.from_user.id) == STATE_SEARCH_CHOOSE_CAT)
    def search_cat(msg: types.Message):
        user_id = msg.from_user.id
        txt = msg.text.lower()
        if txt == "поиск квартиры":
            bot.send_message(
                user_id,
                "Укажите район, в котором ищете предложение: 🌍",
                reply_markup=get_district_keyboard()
            )
            user_states[user_id] = STATE_SEARCH_DISTRICT
        elif txt == "поиск тариф":
            bot.send_message(
                user_id,
                "Укажите оператора: 📱",
                reply_markup=get_operator_keyboard()
            )
            user_states[user_id] = STATE_SEARCH_OPERATOR
        elif txt == "назад":
            role = get_user_data(user_id).get("role", "")
            bot.send_message(user_id, "Поиск отменён. Возвращаемся в главное меню. 🔙",
                            reply_markup=main_menu_keyboard(role=role))
            user_states[user_id] = STATE_NONE
        else:
            bot.send_message(user_id, "Выберите «Поиск Квартиры», «Поиск Тариф» или «Назад». ❓")


    # --- Поиск для категории "Квартира" ---
    @bot.message_handler(func=lambda m: user_states.get(m.from_user.id) == STATE_SEARCH_DISTRICT)
    def search_sozh_dist(msg: types.Message):
        user_id = msg.from_user.id
        if msg.text.lower() == "назад":
            bot.send_message(user_id, "Вернулись к выбору типа поиска. ↩️",
                            reply_markup=search_category_keyboard())
            user_states[user_id] = STATE_SEARCH_CHOOSE_CAT
            return

        dist = msg.text.strip()
        with sqlite3.connect(DB_NAME) as conn:
            c = conn.cursor()
            c.execute("""
                SELECT a.id, a.title, a.details, a.user_id
                FROM applications a
                WHERE a.category='квартира'
                AND a.district=?
                AND a.status='approved'
            """, (dist,))
            rows = c.fetchall()

        if not rows:
            bot.send_message(user_id, "Нет доступных заявок в этом районе. 😕")
            role = get_user_data(user_id).get("role", "")
            bot.send_message(user_id, "Поиск завершён. Возвращаемся в главное меню. 🏠",
                            reply_markup=main_menu_keyboard(role=role))
            user_states[user_id] = STATE_NONE
        else:
            user_states[user_id] = {
                "stage":    STATE_SHOW_SEARCH_RESULTS,
                "results":  rows,
                "index":    0,
                "category": "квартира"
            }
            show_current_result(user_id)


    @bot.callback_query_handler(func=lambda call: call.data.startswith(("approve_", "reject_")))
    def handle_admin_approve_reject(call):
        app_id = int(call.data.split("_")[1])

        if call.data.startswith("approve_"):
            new_status = "approved"
            status_text = "✅ Заявка одобрена!"
        elif call.data.startswith("reject_"):
            new_status = "rejected"
            status_text = "❌ Заявка отклонена!"

        set_application_status(app_id, new_status)

        bot.answer_callback_query(call.id, status_text)
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=f"Заявка #{app_id}: {status_text}",
            reply_markup=None
        )

        # Уведомление пользователю
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("SELECT user_id FROM applications WHERE id=?", (app_id,))
        row = c.fetchone()
        conn.close()

        if row:
            user_id = row[0]
            bot.send_message(user_id, f"{status_text} Ваша заявка #{app_id} была рассмотрена администратором.")

    @bot.callback_query_handler(func=lambda call: call.data.startswith("revise_"))
    def handle_revise_with_comment(call):
        app_id = int(call.data.split("_")[1])
        user_states[(call.from_user.id, 'revise_app')] = app_id
        bot.send_message(call.from_user.id, f"✏️ Введите замечание для заявки #{app_id}:")

    @bot.message_handler(func=lambda m: (m.from_user.id, 'revise_app') in user_states)
    def handle_revise_comment(msg: types.Message):
        admin_id = msg.from_user.id
        app_id = user_states.pop((admin_id, 'revise_app'))
        comment = msg.text.strip()

        set_application_status(app_id, "revise")

        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("SELECT user_id FROM applications WHERE id=?", (app_id,))
        row = c.fetchone()
        conn.close()

        if row:
            user_id = row[0]
            bot.send_message(
                user_id,
                f"⚠️ Ваша заявка #{app_id} отправлена на доработку.\n"
                f"Комментарий администратора:\n\n<b>{comment}</b>",
                parse_mode="HTML"
            )
            bot.send_message(admin_id, "Комментарий отправлен пользователю ✅")



    # --- Поиск Тариф ---
    @bot.message_handler(func=lambda m: user_states.get(m.from_user.id) == STATE_SEARCH_OPERATOR)
    def search_tarif(msg: types.Message):
        user_id = msg.from_user.id

        # кнопка «Назад»
        if msg.text.lower() == "назад":
            bot.send_message(
                user_id,
                "Вернулись к выбору типа поиска. ↩️",
                reply_markup=search_category_keyboard()
            )
            user_states[user_id] = STATE_SEARCH_CHOOSE_CAT
            return

        op = msg.text.strip()
        # вытягиваем из БД все одобренные заявки «тариф» по оператору
        with sqlite3.connect(DB_NAME) as conn:
            c = conn.cursor()
            c.execute("""
                SELECT a.id, a.operator, a.title, a.details, a.user_id
                FROM applications a
                WHERE a.category='тариф'
                AND a.operator=?
                AND a.status='approved'
            """, (op,))
            rows = c.fetchall()

        if not rows:
            bot.send_message(user_id, "Нет заявок по данному оператору. 😕")
            bot.send_message(
                user_id,
                "Поиск завершён. Возвращаемся в главное меню. 🏠",
                reply_markup=main_menu_keyboard(role=get_user_data(user_id).get("role",""))
            )
            user_states[user_id] = STATE_NONE
        else:
            # сохраняем результаты в состоянии
            user_states[user_id] = {
                "stage":    STATE_SHOW_SEARCH_RESULTS,
                "results":  rows,
                "index":    0,
                "category": "тариф"
            }
            show_current_result(user_id)


    # ---------- Функция показа найденного объявления ----------
    def show_current_result(user_id: int):
        """
        Показывает текущую найденную заявку.
        Поддерживает и 'квартира', и 'тариф'.
        """
        st = user_states.get(user_id)
        if not isinstance(st, dict):
            return

        results = st["results"]
        idx     = st["index"]
        cat     = st.get("category", "квартира")  # по умолчанию квартира

        # Конец списка
        if idx < 0 or idx >= len(results):
            bot.send_message(user_id, "Заявки закончились! ⚠️")
            bot.send_message(
                user_id,
                "Возвращаемся в главное меню. 🏠",
                reply_markup=main_menu_keyboard(role=get_user_data(user_id).get("role",""))
            )
            user_states[user_id] = STATE_NONE
            return

        # Распаковываем поля по категории
        if cat == "тариф":
            app_id, op, title, details, owner_id = results[idx]
            header = (
                f"📱 <b>Тариф</b>\n"
                f"Оператор: {op}\n"
                f"💰 Стоимость: {title}\n"
                f"📅 Оплата: {details}"
            )
        else:  # квартира
            app_id, title, details, owner_id = results[idx]
            header = (
                f"🏠 <b>Квартира</b>\n"
                f"💰 Стоимость: {title}\n"
                f"📝 Детали о квартире: {details}"
            )

        # 1) Фото, если есть
        photos = get_application_photos(app_id)
        if photos:
            media = []
            for p in photos:
                if os.path.exists(p):
                    media.append(types.InputMediaPhoto(open(p, 'rb')))
            if media:
                bot.send_media_group(user_id, media)

        # 2) Сборка текста
        text = f"Объявление #{app_id}\n\n{header}"

        # 3) Автор и рейтинг
        if owner_id == user_id:
            text += "\n\nАвтор: вы"
        else:
            uo = get_user_data(owner_id)
            name = f"{uo.get('first_name','')} {uo.get('last_name','')}".strip() or "пользователь"
            text += f"\n\nАвтор: {name}"

        avg = get_average_rating(owner_id)
        if avg:
            full, half = int(avg), (avg - int(avg) >= 0.5)
            stars = "★"*full + ("½" if half else "")
            text += f"\n\n<b>Рейтинг автора:</b> {stars} ({avg:.1f}/5)"
        else:
            text += "\n\n<b>Рейтинг автора:</b> нет оценок"

        # 4) Клавиатура с всегда доступной кнопкой "Посмотреть отзывы"
        if owner_id == user_id:
            kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
            kb.add("Дальше", "Посмотреть отзывы")
            kb.add("Назад")
        else:
            kb = get_search_actions_keyboard()

        bot.send_message(
            user_id,
            text,
            parse_mode="HTML",
            reply_markup=kb
        )



    # Вход в техподдержку    
    @bot.message_handler(func=lambda m: m.text == "Техподдержка")
    def support_entry(msg: types.Message):
        user_id = msg.from_user.id
        user_states[user_id] = STATE_SUPPORT_CHAT

        kb = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        kb.add("Назад")

        bot.send_message(
            user_id,
            "✉️ Вы подключены к техподдержке. Напишите сообщение или фото.\n\nЧтобы выйти, нажмите «Назад».",
            reply_markup=kb
        )

    # Пользователь пишет в поддержку
    @bot.message_handler(func=lambda msg: user_states.get(msg.from_user.id) == STATE_SUPPORT_CHAT, content_types=['text', 'photo'])
    def forward_to_support(msg: types.Message):
        user_id = msg.from_user.id

        # Выход из поддержки
        if msg.text and msg.text.lower() == "назад":
            user_states[user_id] = None
            bot.send_message(user_id, "🔙 Вы вышли из техподдержки.", reply_markup=types.ReplyKeyboardRemove())
            return

        # Получение данных (замени на свою функцию)
        data = get_user_data(user_id)
        username = data.get("username", "неизвестно")

        header = (
            f"📩 <b>Сообщение от пользователя</b>:\n"
            f"👤 {data.get('first_name', '')} {data.get('last_name', '')}\n"
            f"🆔 <code>{user_id}</code>\n"
            f"🔗 @{username}\n\n"
        )
        text = msg.caption if msg.caption else msg.text or ""

        for admin_id in SUPPORT_ADMINS:
            support_active_chats[admin_id] = user_id
            try:
                if msg.content_type == 'text':
                    bot.send_message(admin_id, header + text, parse_mode="HTML")

                elif msg.content_type == 'photo':
                    file_info = bot.get_file(msg.photo[-1].file_id)
                    downloaded_file = bot.download_file(file_info.file_path)

                    temp_path = f"temp_{user_id}.jpg"
                    with open(temp_path, 'wb') as f:
                        f.write(downloaded_file)

                    with open(temp_path, 'rb') as photo:
                        bot.send_photo(admin_id, photo, caption=header + text, parse_mode="HTML")

                    os.remove(temp_path)

            except Exception as e:
                bot.send_message(user_id, f"❌ Ошибка при отправке: {e}")

        bot.send_message(user_id, "📨 Ваше сообщение отправлено в техподдержку.")

    # Админ отвечает пользователю
    
    @bot.message_handler(func=lambda m: m.from_user.id in SUPPORT_ADMINS, content_types=['text', 'photo'])
    def handle_admin_reply(msg: types.Message):
        admin_id = msg.from_user.id
        user_id = support_active_chats.get(admin_id)

        if not user_id:
            bot.send_message(admin_id, "⚠️ Нет активного пользователя для ответа.")
            return

        try:
            if msg.content_type == 'text':
                bot.send_message(user_id, f"📬 Ответ от поддержки: {msg.text}")

            elif msg.content_type == 'photo':
                file_info = bot.get_file(msg.photo[-1].file_id)
                downloaded_file = bot.download_file(file_info.file_path)

                temp_path = f"admin_reply_{admin_id}.jpg"
                with open(temp_path, 'wb') as f:
                    f.write(downloaded_file)

                with open(temp_path, 'rb') as photo:
                    bot.send_photo(user_id, photo, caption="📬 Ответ от поддержки:")

                os.remove(temp_path)

            # Уведомим других админов
            for other_admin in SUPPORT_ADMINS:
                if other_admin != admin_id:
                    bot.send_message(other_admin, f"⚠️ Админ {admin_id} ответил пользователю {user_id}.")

            support_active_chats.pop(admin_id, None)

        except telebot.apihelper.ApiTelegramException as e:
            if e.error_code == 403:
                bot.send_message(admin_id, "❌ Пользователь заблокировал бота. Невозможно отправить сообщение.")
            else:
                bot.send_message(admin_id, f"❌ Другая ошибка: {e}")


    # ─── Обработчик кнопок при просмотре результатов ──────────────────────────────
    @bot.message_handler(func=lambda m:
        isinstance(user_states.get(m.from_user.id), dict)
        and user_states[m.from_user.id].get("stage") == STATE_SHOW_SEARCH_RESULTS
    )
    def handle_search_results_buttons(msg: types.Message):
        user_id = msg.from_user.id
        text    = msg.text.strip().lower()
        st      = user_states[user_id]
        idx     = st["index"]
        cat     = st.get("category", "квартира")

        # распаковываем текущую запись
        if cat == "тариф":
            app_id, op, title, details, owner_id = st["results"][idx]
        else:
            app_id, title, details, owner_id = st["results"][idx]

        # если своё объявление — запрещаем отклик/отзыв
        if owner_id == user_id and text in ("откликнулся", "поставить отзыв"):
            return bot.send_message(user_id, "❌ Это ваше объявление — нельзя.")

        # «Дальше»
        if text == "дальше":
            st["index"] += 1
            return show_current_result(user_id)

        # «Откликнулся»
        if text == "откликнулся":
            add_response(user_id, owner_id, app_id)
            od = get_user_data(owner_id)
            return bot.send_message(
                user_id,
                f"Вы откликнулись на заявку #{app_id}.\n"
                f"Имя: {od.get('first_name','')} {od.get('last_name','')}\n"
                f"Телефон: {od.get('phone','')}\n\n"
                "Свяжитесь напрямую! 📞"
            )

        # «Поставить отзыв»
        if text == "поставить отзыв":
            user_states[(user_id, 'return_after_rating')] = STATE_SHOW_SEARCH_RESULTS
            user_states[(user_id, 'search_backup')]       = {"results": st["results"], "index": idx, "category": cat}
            user_states[user_id]                          = STATE_RATING_MESSAGE
            user_states[(user_id, 'target_id')]           = owner_id
            return bot.send_message(
                user_id,
                "Оставьте оценку (1–5) и комментарий для автора.\n"
                "Пример: «4.5 Отлично помог!»\nДля отмены — «Назад». ✍️",
                parse_mode="HTML"
            )

        # «Посмотреть отзывы»
        if text == "посмотреть отзывы":
            reviews = get_ratings_for_user(owner_id)
            if not reviews:
                return bot.send_message(user_id, "Пока отзывов нет. 😕")
            out = "<b>Отзывы о пользователе:</b>\n\n"
            for _rid, rater_id, score, comment in reviews:
                u = get_user_data(rater_id)
                name = f"{u.get('first_name','')} {u.get('last_name','')}".strip()
                full = int(score); half = (score - full) >= 0.5
                stars = "★"*full + ("½" if half else "")
                out += f"<b>{name}</b>\n{stars} ({score}/5)\n{comment}\n\n"
            return bot.send_message(user_id, out, parse_mode="HTML")

        # «Назад» в главное меню
        if text == "назад":
            bot.send_message(user_id, "Поиск завершён. Возвращаемся в главное меню. 🏠",
                            reply_markup=main_menu_keyboard(role=get_user_data(user_id).get("role","")))
            user_states[user_id] = STATE_NONE
            return

        # всё остальное
        bot.send_message(user_id, "Пожалуйста, выберите одну из кнопок.")


    # Fallback – обработка неизвестных команд 
    @bot.message_handler(func=lambda m: user_states.get(m.from_user.id) == STATE_NONE)
    def fallback(msg: types.Message):
        user_id = msg.from_user.id
        data = get_user_data(user_id) or {}
        role = data.get("role", "")
        bot.send_message(
            user_id,
            "Извините, я не понял вашу команду. Выберите действие из меню или введите /start. ❓",
            reply_markup=main_menu_keyboard(role=role)
        )
        
    # Callback кнопки удаления фото

    @bot.callback_query_handler(func=lambda call: call.data.startswith("del_photo_"))
    def delete_single_photo(call):
        user_id = call.from_user.id
        app_id = user_states.get((user_id, 'app_id'))
        idx = int(call.data.split("_")[-1])
        photos = get_application_photos(app_id)

        if 0 <= idx < len(photos):
            path = photos[idx]
            if os.path.exists(path):
                os.remove(path)
            with sqlite3.connect(DB_NAME) as conn:
                conn.execute("DELETE FROM application_photos WHERE application_id=? AND file_path=?", (app_id, path))
            bot.answer_callback_query(call.id, "Фото удалено.")
            bot.delete_message(call.message.chat.id, call.message.message_id)
        else:
            bot.answer_callback_query(call.id, "Фото не найдено.")

    @bot.callback_query_handler(func=lambda call: call.data == "del_all_request")
    def confirm_delete_all(call):
        markup = InlineKeyboardMarkup()
        markup.add(
            InlineKeyboardButton("✅ Да, удалить", callback_data="del_all_confirm"),
            InlineKeyboardButton("❌ Нет", callback_data="del_all_cancel")
        )
        bot.edit_message_text(
            "❗ Вы уверены, что хотите удалить все фотографии?",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=markup
        )

    @bot.callback_query_handler(func=lambda call: call.data == "del_all_confirm")
    def do_delete_all(call):
        user_id = call.from_user.id
        app_id = user_states.get((user_id, 'app_id'))
        photos = get_application_photos(app_id)
        for p in photos:
            if os.path.exists(p):
                os.remove(p)
        with sqlite3.connect(DB_NAME) as conn:
            conn.execute("DELETE FROM application_photos WHERE application_id=?", (app_id,))
        bot.edit_message_text("✅ Все фотографии удалены.", call.message.chat.id, call.message.message_id)

    @bot.callback_query_handler(func=lambda call: call.data == "del_all_cancel")
    def cancel_delete_all(call):
        bot.edit_message_text("❌ Отменено.", call.message.chat.id, call.message.message_id)

    # Вывод фото с inline-кнопками
    def send_photo_delete_options(bot, user_id, app_id):
        photos = get_application_photos(app_id)
        for idx, path in enumerate(photos):
            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton("🗑 Удалить это фото", callback_data=f"del_photo_{idx}"))
            with open(path, "rb") as photo:
                bot.send_photo(user_id, photo, caption=f"📸 Фото №{idx + 1}", reply_markup=markup)

        confirm_all = InlineKeyboardMarkup()
        confirm_all.add(InlineKeyboardButton("🗑 Удалить все фотографии", callback_data="del_all_request"))
        bot.send_message(user_id, "Хотите удалить все фотографии?", reply_markup=confirm_all)

    
    @bot.message_handler(func=lambda m: m.text == "Посмотреть отзывы")
    def handle_view_ratings(msg: types.Message):
        user_id = msg.from_user.id
        reviews = get_ratings_for_user(user_id)

        if not reviews:
            bot.send_message(user_id, "У вас пока нет отзывов.")
            return

        out = "<b>Отзывы о вас:</b>\n\n"
        for _rid, rater_id, score, comment in reviews:
            u = get_user_data(rater_id)
            name = f"{u.get('first_name','')} {u.get('last_name','')}".strip()
            full = int(score)
            half = (score - full) >= 0.5
            stars = "★"*full + ("½" if half else "")
            out += f"<b>{name}</b>\n{stars} ({score}/5)\n{comment}\n\n"

        bot.send_message(user_id, out, parse_mode="HTML")


    @bot.message_handler(func=lambda m: m.text.lower() == "редактировать отзыв")
    def ask_which_rating_to_edit(msg: types.Message):
        user_id = msg.from_user.id
        ratings = get_ratings_by_user(user_id)

        if not ratings:
            bot.send_message(user_id, "У вас нет отзывов для редактирования.")
            return

        text = "<b>Выберите ID отзыва для редактирования:</b>\n"
        for rid, rater, score, comment in ratings:
            stars = "★" * int(score)
            text += f"#{rid} — {stars} ({score}/5)\n{comment}\n\n"

        bot.send_message(user_id, text, parse_mode="HTML")
        user_states[user_id] = STATE_EDIT_RATING_SELECT


    @bot.message_handler(func=lambda m: user_states.get(m.from_user.id) == STATE_EDIT_RATING_SELECT)
    def get_rating_id_to_edit(msg: types.Message):
        user_id = msg.from_user.id
        text = msg.text.strip().lstrip('#')
        if not text.isdigit():
            bot.send_message(user_id, "Введите корректный ID отзыва.")
            return

        rating_id = int(text)
        user_states[user_id] = {
            "stage": STATE_EDIT_RATING_INPUT,
            "rating_id": rating_id
        }

        bot.send_message(user_id, "Введите новый рейтинг (1–5) и комментарий. Например:\n<b>4.5 Хороший продавец</b>", parse_mode="HTML")



    @bot.message_handler(func=lambda m: isinstance(user_states.get(m.from_user.id), dict) and user_states[m.from_user.id].get("stage") == STATE_EDIT_RATING_INPUT)
    def process_rating_edit(msg: types.Message):
        user_id = msg.from_user.id
        parts = msg.text.strip().split(maxsplit=1)
        if len(parts) < 2:
            bot.send_message(
                user_id,
                "Введите сначала оценку, потом комментарий. Например:\n<b>4 Всё ок</b>",
                parse_mode="HTML"
            )
            return

        # парсим число
        try:
            rating = float(parts[0].replace(",", "."))
        except ValueError:
            bot.send_message(user_id, "Рейтинг должен быть числом от 1 до 5. Например: 4.5")
            return

        comment = parts[1].strip()
        if rating < 1 or rating > 5:
            bot.send_message(user_id, "Рейтинг должен быть от 1 до 5.")
            return

        # обновляем отзыв в БД
        rating_id = user_states[user_id]["rating_id"]
        update_rating(rating_id, rating, comment)

        # --- НОВЫЙ БЛОК: выводим именно ваши отзывы ---
        reviews = get_ratings_by_user(user_id)
        text = "<b>История ваших отзывов:</b>\n\n"
        for rid, target_id, score, comm in reviews:
            # звёздочки
            full = int(score)
            half = (score - full) >= 0.5
            stars = "★" * full + ("½" if half else "")

            # имя того, кому вы оставили отзыв
            u = get_user_data(target_id)
            name = f"{u.get('first_name','')} {u.get('last_name','')}".strip() or "пользователь"

            text += f"#{rid} — отзыв о <b>{name}</b>: {stars} ({score}/5)\n{comm}\n\n"

        kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
        kb.add("Редактировать отзыв", "Назад")

        bot.send_message(user_id, text, parse_mode="HTML", reply_markup=kb)
        user_states[user_id] = STATE_NONE
