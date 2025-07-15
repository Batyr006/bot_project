import sqlite3
from typing import List, Tuple, Optional

DB_NAME = "users_data.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()

    # Таблица пользователей (убрано: role, category)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        first_name TEXT,
        last_name TEXT,
        phone TEXT,
        username TEXT
    )
    """)

    # Квартира
    cur.execute("""
    CREATE TABLE IF NOT EXISTS sozhitel (
        user_id INTEGER,
        district TEXT,
        rent_price TEXT,
        comment TEXT
    )
    """)

    # Тариф
    cur.execute("""
    CREATE TABLE IF NOT EXISTS tarif (
        user_id INTEGER,
        operator TEXT,
        tariff_price TEXT,
        description TEXT,
        monthly TEXT,
        pay_day TEXT
    )
    """)

    # Обычные фото (если нужны)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS photos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        file_path TEXT
    )
    """)

    # Оценки
    cur.execute("""
    CREATE TABLE IF NOT EXISTS ratings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        rater_id INTEGER,
        rating REAL,
        comment TEXT
    )
    """)

    # Заявки (сохраняем category и operator в самих заявках)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS applications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        category TEXT,
        district TEXT,
        operator TEXT,
        title TEXT,
        details TEXT,
        status TEXT  -- 'pending' / 'approved' / 'rejected' / 'revise'
    )
    """)

    # Фото для заявок
    cur.execute("""
    CREATE TABLE IF NOT EXISTS application_photos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        application_id INTEGER,
        user_id INTEGER,
        file_path TEXT
    )
    """)

    # Кто на кого откликнулся
    cur.execute("""
    CREATE TABLE IF NOT EXISTS responses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        from_user_id INTEGER,
        to_user_id INTEGER,
        application_id INTEGER,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)

    conn.commit()
    conn.close()

# ---------- USERS ----------
def user_exists(user_id: int) -> bool:
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return bool(row)

def create_user(user_id: int):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO users(user_id) VALUES(?)", (user_id,))
    conn.commit()
    conn.close()

def update_user_main(user_id: int, field: str, value: str):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    sql = f"UPDATE users SET {field}=? WHERE user_id=?"
    cur.execute(sql, (value, user_id))
    conn.commit()
    conn.close()

def update_user_username(user_id: int, username: str):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("UPDATE users SET username=? WHERE user_id=?", (username, user_id))
    conn.commit()
    conn.close()

def get_user_data(user_id: int) -> dict:
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT first_name, last_name, phone, username FROM users WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return {}
    first_name, last_name, phone, username = row

    # sozhitel
    cur.execute("SELECT district, rent_price, comment FROM sozhitel WHERE user_id=?", (user_id,))
    srow = cur.fetchone()
    if srow:
        district, rent_price, comment = srow
    else:
        district = rent_price = comment = None

    # tarif
    cur.execute("SELECT operator, tariff_price, description, monthly, pay_day FROM tarif WHERE user_id=?", (user_id,))
    trow = cur.fetchone()
    if trow:
        operator, tariff_price, description, monthly, pay_day = trow
    else:
        operator = tariff_price = description = monthly = pay_day = None

    conn.close()
    return {
        "first_name": first_name,
        "last_name": last_name,
        "phone": phone,
        "username": username,
        "district": district,
        "rent_price": rent_price,
        "comment": comment,
        "operator": operator,
        "tariff_price": tariff_price,
        "description": description,
        "monthly": monthly,
        "pay_day": pay_day
    }

# Остальные функции (photo, application, responses, ratings) оставляем без изменений — они не используют role/category


def update_user_username(user_id: int, username: str):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("UPDATE users SET username=? WHERE user_id=?", (username, user_id))
    conn.commit()
    conn.close()





def update_sozhitel_info(user_id: int, field: str, value: str):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM sozhitel WHERE user_id=?", (user_id,))
    if not cur.fetchone():
        cur.execute("INSERT INTO sozhitel(user_id) VALUES(?)", (user_id,))
    sql = f"UPDATE sozhitel SET {field}=? WHERE user_id=?"
    cur.execute(sql, (value, user_id))
    conn.commit()
    conn.close()

def update_tarif_info(user_id: int, field: str, value: str):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM tarif WHERE user_id=?", (user_id,))
    if not cur.fetchone():
        cur.execute("INSERT INTO tarif(user_id) VALUES(?)", (user_id,))
    sql = f"UPDATE tarif SET {field}=? WHERE user_id=?"
    cur.execute(sql, (value, user_id))
    conn.commit()
    conn.close()

# ---------- PHOTOS ----------
def save_photo(user_id: int, file_path: str):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("INSERT INTO photos(user_id, file_path) VALUES(?,?)", (user_id, file_path))
    conn.commit()
    conn.close()

def get_user_photos(user_id: int) -> list:
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT file_path FROM photos WHERE user_id=?", (user_id,))
    rows = cur.fetchall()
    conn.close()
    return [r[0] for r in rows]

# ---------- APPLICATIONS ----------
def create_application(user_id: int, category: str, district: str, operator: str,
                       title: str, details: str) -> int:
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO applications(user_id, category, district, operator, title, details, status)
        VALUES (?,?,?,?,?,?,?)
    """, (user_id, category, district, operator, title, details, "pending"))
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return new_id

def get_applications_by_user(user_id: int) -> list:
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT id, category, district, operator, title, details, status
        FROM applications
        WHERE user_id=?
        ORDER BY id ASC
    """, (user_id,))
    rows = cur.fetchall()
    conn.close()
    return rows

def get_application(user_id: int, app_id: int):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT id, category, district, operator, title, details, status
        FROM applications
        WHERE user_id=? AND id=?
    """, (user_id, app_id))
    row = cur.fetchone()
    conn.close()
    return row

def update_application(user_id: int, app_id: int, new_title: str, new_details: str):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        UPDATE applications
        SET title=?, details=?
        WHERE user_id=? AND id=?
    """, (new_title, new_details, user_id, app_id))
    conn.commit()
    conn.close()

def delete_application(user_id: int, app_id: int):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("DELETE FROM applications WHERE user_id=? AND id=?", (user_id, app_id))
    conn.commit()
    conn.close()

def add_application_photo(app_id: int, user_id: int, file_path: str):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO application_photos(application_id, user_id, file_path)
        VALUES (?,?,?)
    """, (app_id, user_id, file_path))
    conn.commit()
    conn.close()

def get_application_photos(app_id: int) -> list:
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT file_path FROM application_photos WHERE application_id=?", (app_id,))
    rows = cur.fetchall()
    conn.close()
    return [r[0] for r in rows]

def set_application_status(app_id: int, new_status: str):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("UPDATE applications SET status=? WHERE id=?", (new_status, app_id))
    conn.commit()
    conn.close()

def get_pending_applications() -> list:
    """Возвращаем заявки, у которых status='pending' или 'revise'."""
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT id, user_id, category, district, operator, title, details, status
        FROM applications
        WHERE status IN ('pending','revise')
        ORDER BY id ASC
    """)
    rows = cur.fetchall()
    conn.close()
    return rows

def count_applications_by_user(user_id: int) -> int:
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM applications WHERE user_id=?", (user_id,))
    c = cur.fetchone()[0]
    conn.close()
    return c if c else 0

# ---------- RATINGS ----------
def save_rating(rater_id: int, user_id: int, rating: int, comment: str) -> None:
    """
    Сохраняет отзыв:
      rater_id — кто оставил,
      user_id  — кого оценили,
      rating   — 1–5,
      comment  — текст.
    """
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO ratings (user_id, rater_id, rating, comment) VALUES (?, ?, ?, ?)",
        (user_id, rater_id, rating, comment)
    )
    conn.commit()
    conn.close()

def get_average_rating(user_id: int) -> Optional[float]:
    """
    Возвращает среднюю оценку (округлённую до 0.1)
    или None, если оценок ещё нет.
    """
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT AVG(rating) FROM ratings WHERE user_id=?", (user_id,))
    val = cur.fetchone()[0]
    conn.close()
    if val is None:
        return None
    return round(val, 1)

# ФУНКЦИЯ ДЛЯ ПОЛУЧЕНИЯ ОТЗЫВОВ, КОТОРЫЕ ПОЛЬЗОВАТЕЛЬ НАПИСАЛ (для истории отзывов)
def get_ratings_by_user(user_id: int) -> list:
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT id, user_id, rating, comment
        FROM ratings
        WHERE rater_id = ?
        ORDER BY id DESC
    """, (user_id,))
    rows = cur.fetchall()
    conn.close()
    return rows

# ФУНКЦИЯ ДЛЯ ПОЛУЧЕНИЯ ОТЗЫВОВ О ПОЛЬЗОВАТЕЛЕ (для просмотра чужих отзывов)
def get_ratings_for_user(user_id: int) -> list:
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT id, rater_id, rating, comment
        FROM ratings
        WHERE user_id = ?
        ORDER BY id DESC
    """, (user_id,))
    rows = cur.fetchall()
    conn.close()
    return rows


# ОБНОВЛЕНИЕ ОТЗЫВА
def update_rating(rating_id: int, rating: float, comment: str) -> None:
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        UPDATE ratings
        SET rating = ?, comment = ?
        WHERE id = ?
    """, (rating, comment, rating_id))
    conn.commit()
    conn.close()


# ---------- RESPONSES (новая логика) ----------
def add_response(from_user_id: int, to_user_id: int, application_id: int):
    """
    Записывает факт, что пользователь 'from_user_id' откликнулся
    на заявку 'application_id' (принадлежащую 'to_user_id').
    """
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO responses(from_user_id, to_user_id, application_id)
        VALUES (?,?,?)
    """, (from_user_id, to_user_id, application_id))
    conn.commit()
    conn.close()


def get_application_owner(app_id: int) -> int | None:
    """
    Возвращает user_id владельца заявки или None, если заявки нет.
    """
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM applications WHERE id=?", (app_id,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None
