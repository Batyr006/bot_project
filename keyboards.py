from telebot import types

def get_role_keyboard():
    """
    Клавиатура для выбора роли: «Продавец» или «Получатель».
    Добавлена кнопка «Назад» для возврата назад. 🤖
    """
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    kb.row("Продавец", "Получатель")
    kb.add("Назад")
    return kb

def get_category_keyboard():
    """
    Клавиатура для продавца: выбор категории «Квартира» или «Тариф»,
    а также кнопка «Назад». 📋
    """
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    kb.row("Квартира", "Тариф")
    kb.add("Назад")
    return kb

def get_district_keyboard():
    """
    Клавиатура выбора района (для заявки «Квартира»).
    """
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    districts = [
        "Алатауский", "Алмалинский", "Ауэзовский",
        "Бостандыкский", "Жетысуский", "Медеуский",
        "Наурызбайский", "Турксибский"
    ]
    for d in districts:
        kb.add(d)
    kb.add("Назад")
    return kb

def get_operator_keyboard():
    """
    Клавиатура выбора оператора (для заявки «Тариф»).
    """
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    operators = ["Altel", "Tele2", "Activ", "Beeline"]
    for op in operators:
        kb.add(op)
    kb.add("Назад")
    return kb

def main_menu_keyboard(role=None):
    """
    Главное меню для любой роли (продавец/получатель):
    включает:
    - «Мой профиль»
    - «Мои заявки»
    - «Оставить отзыв»
    - «Поиск»
    - «Главный меню» (смена роли) 🤩
    """
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("Мой профиль", "Мои заявки")
    kb.row("История отзывов", "Поиск")
    kb.add("Техподдержка")
    return kb

def profile_edit_keyboard():
    """
    Клавиатура для редактирования профиля:
    - «Редактировать контакт»
    - «Назад» 🎨
    """
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("Редактировать контакт")
    kb.add("Назад")
    return kb

def my_applications_keyboard():
    """
    Клавиатура для раздела «Мои заявки»:
    - «Создать заявку»
    - «Посмотреть заявки»
    - «Добавить фото к заявке»
    - «Назад» 📑
    """
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("Создать заявку", "Посмотреть заявки")
    kb.add("Назад")
    return kb

def confirm_keyboard():
    """
    Универсальная клавиатура подтверждения с вариантами «Да» и «Нет» 👍👎
    """
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    kb.row("Да", "Нет")
    return kb

def search_category_keyboard():
    """
    Клавиатура для выбора типа поиска:
    - «Поиск Квартиры»
    - «Поиск Тариф»
    - «Назад»
    """
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    kb.row("Поиск Квартиры", "Поиск Тариф")
    kb.add("Назад")
    return kb

def admin_inline_buttons(app_id: int):
    """
    Инлайн-кнопки для администратора для модерации заявки:
    - «Одобрить»
    - «Отклонить»
    - «Доработать»
    """
    kb = types.InlineKeyboardMarkup()
    b1 = types.InlineKeyboardButton("Одобрить", callback_data=f"approve_{app_id}")
    b2 = types.InlineKeyboardButton("Отклонить", callback_data=f"reject_{app_id}")
    b3 = types.InlineKeyboardButton("Доработать", callback_data=f"revise_{app_id}")
    kb.row(b1, b2, b3)
    return kb

def create_app_keyboard():
    """
    Клавиатура при создании заявки:
    - «Квартира»
    - «Тариф»
    - «Назад»
    """
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    kb.row("Квартира", "Тариф")
    kb.add("Назад")
    return kb


def done_inline_keyboard():
    kb = types.InlineKeyboardMarkup()
    btn = types.InlineKeyboardButton("✅ Готово", callback_data="photos_done")
    kb.add(btn)
    return kb


def edit_contact_keyboard():
    """
    Клавиатура для редактирования контакта:
    - «Изменить имя»
    - «Изменить фамилию»
    - «Изменить телефон»
    - «Назад»
    """
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    kb.row("Изменить имя", "Изменить фамилию")
    kb.add("Изменить телефон")
    kb.add("Назад")
    return kb

def recipient_keyboard():
    """
    Клавиатура для роли «Получатель»:
    - «Поиск»
    - «Назад»
    """
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    kb.add("Поиск")
    kb.add("Назад")
    return kb

def get_search_actions_keyboard():
    """
    Клавиатура для просмотра найденных заявок построчно:
    - «Дальшее»
    - «Откликнулся»
    - «Отзыв»
    - «Назад» 🔎
    """
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("Откликнулся", "Поставить отзыв")
    kb.add("Дальше", "Посмотреть отзывы")
    kb.add("Назад")
    return kb


def manage_photo_keyboard():
    """
    Клавиатура для управления фото:
    - ➕ Добавить фото
    - ♻️ Заменить фото
    - ⬅️ Назад
    """
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    kb.row("➕ Добавить фото", "♻️ Заменить фото")
    kb.add("Назад")
    return kb
