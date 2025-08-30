import calendar
from email import message
import logging
import json
import os
import re
from socket import fromfd
from xml.dom.minidom import NamedNodeMap
from dotenv import load_dotenv; load_dotenv()
load_dotenv()
from datetime import datetime, timedelta, date, time 
from uuid import uuid4
from telegram import MessageId, Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, ContextTypes, filters
)
from telegram.error import BadRequest
from telegram_bot_calendar import DetailedTelegramCalendar, LSTEP
import html
import pytz 

MOSCOW_TZ = pytz.timezone('Europe/Moscow')

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- КОНФИГУРАЦИЯ БОТА ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID"))
           
# --------------------------

russian_month_names = {
    1: "Январь",
    2: "Февраль",
    3: "Март",
    4: "Апрель",
    5: "Май",
    6: "Июнь",
    7: "Июль",
    8: "Август",
    9: "Сентябрь",
    10: "Октябрь",
    11: "Ноябрь",
    12: "Декабрь"
}

# Состояния для ConversationHandler
(MENU_CATEGORY, MENU_ITEM,
 FAQ_QUESTION,
 REVIEW_TEXT,
 PROBLEM_TEXT,
 LIVE_CHAT_USER, LIVE_CHAT_ADMIN_REPLY,
 ASK_DATE, ASK_TIME, ASK_GUESTS, ASK_NAME, ASK_PHONE, ASK_WISHES, CONFIRM_RESERVATION) = range(14) 

# Пути к файлам данных
DATA_DIR = 'data'
MENU_FILE = os.path.join(DATA_DIR, 'menu.json')
FAQ_FILE = os.path.join(DATA_DIR, 'faq.json')
REVIEWS_FILE = os.path.join(DATA_DIR, 'reviews.json')
PROBLEMS_FILE = os.path.join(DATA_DIR, 'problems.json')
USER_STATES_FILE = os.path.join(DATA_DIR, 'user_states.json')

menu_data = {} # Глобальная переменная для хранения данных меню
reviews_data = []


try:
    with open(REVIEWS_FILE, 'r', encoding='utf-8') as f:
        reviews_data = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    reviews_data = []
    logger.info("Файл отзывов не найден или пуст, инициализирована новая структура.")

# Убедимся, что директория data существует
os.makedirs(DATA_DIR, exist_ok=True)

# --- Функции для работы с данными (загрузка/сохранение) ---

async def get_file_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.photo:
        file_id = update.message.photo[-1].file_id
        await update.message.reply_text(f"File ID для этой фотографии: '{file_id}' \n\n Используйте его в menu.json", parse_mode='Markdown')
    elif update.message.document:
        file_id = update.message.document.file_id
        await update.message.reply_text(f"File ID для этого документа: '{file_id}' \n\n Используйте его в menu.json", parse_mode='Markdown')
    else:
        await update.message.reply_text("Пожалуйста, отправьте фотографию или файл.")

def load_data(filepath, default_value={}):
    if not os.path.exists(filepath):
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(default_value, f, ensure_ascii=False, indent=4)
        return default_value
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except json.JSONDecodeError:
        logger.error(f"Error decoding JSON from {filepath}. Returning default value.")
        return default_value

def save_data(filepath, data):
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

# Загружаем данные при старте бота
menu_data = load_data(MENU_FILE)
faq_data = load_data(FAQ_FILE)
reviews_data = load_data(REVIEWS_FILE, default_value=[])
problems_data = load_data(PROBLEMS_FILE, default_value=[])
user_states_data = load_data(USER_STATES_FILE) # Для активных чатов поддержки

# --- Вспомогательные функции ---

# Вспомогательная функция для форматирования даты
def format_date_for_display(date_obj):
    return date_obj.strftime("%d.%m.%Y")

def get_main_keyboard():
    """Возвращает клавиатуру главного меню."""
    keyboard = [
        [InlineKeyboardButton("🍽️ Меню", callback_data="menu")],
        [InlineKeyboardButton("❓ Вопросы", callback_data="faq")],
        [InlineKeyboardButton("📝 Забронировать стол", callback_data="start_reservation")],
        [InlineKeyboardButton("✍️ Оставить отзыв", callback_data="start_review")],
        [InlineKeyboardButton("⚠️ Сообщить о проблеме", callback_data="start_problem")],
        [InlineKeyboardButton("🗣️ Связаться со службой заботы", callback_data="support")]
    ]
    return InlineKeyboardMarkup(keyboard)

async def send_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, message_text="Выберите действие:"):
    """Отправляет или редактирует сообщение с главным меню."""
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(
            text=message_text,
            reply_markup=get_main_keyboard()
        )
    else:
        await update.message.reply_text(
            text=message_text,
            reply_markup=get_main_keyboard()
        )
    return ConversationHandler.END

# ---Обработчики команд ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /start."""
    user = update.effective_user
    await update.message.reply_html(
        f"Здравствуйте, {user.mention_html()}! 👋 Добро пожаловать в службу заботы о гостях нашего Китайского бистро 'БАО'❤️.\n"
        "Чем мы можем Вам помочь?",
        reply_markup=get_main_keyboard()
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /help."""
    await update.message.reply_text(
        "Мы можем:\n"
        "- Показать Вам меню;\n"
        "- Ответить на часто задаваемые вопросы;\n"
        "- Забронировать стол;\n"
        "- Принять Ваш отзыв или сообщение о проблеме;\n"
        "- Связать Вас с менеджером службы заботы о наших гостях;\n\n"
        "Воспользуйтесь кнопками ниже:",
        reply_markup=get_main_keyboard()
    )

# --- Функции меню ---

async def show_menu_categories(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Показывает категории меню."""
    query = update.callback_query
    await query.answer()

    keyboard = []
    for category in menu_data.keys():
        keyboard.append([InlineKeyboardButton(category, callback_data=f"menu_cat_{category}")])
    keyboard.append([InlineKeyboardButton("🔙 В главное меню", callback_data="start")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text="Выберите категорию меню:", reply_markup=reply_markup)
    return MENU_CATEGORY

async def show_menu_items(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Показывает блюда в выбранной категории."""
    query = update.callback_query
    await query.answer()
    category = query.data.replace("menu_cat_", "")

    if category not in menu_data:
        await query.edit_message_text("Извините, эта категория не найдена.")
        return await show_menu_categories(update, context)

    items = menu_data[category]
    message_text = f"--- {category} ---\n\n"
    for item in items:
        message_text += f"*{item['name']}* \n"
        message_text += f"{item['description']} \n"
        message_text += f"_Цена:_ {item['price']}₽ \n\n"

    keyboard = [[InlineKeyboardButton("🔙 К категориям", callback_data="menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        text=message_text,
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )
    return MENU_ITEM


# --- Функции FAQ ---

async def show_faq_questions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Показывает список вопросов FAQ."""
    query = update.callback_query
    await query.answer()

    keyboard = []
    for i, item in enumerate(faq_data.get("Вопросы", [])):
        keyboard.append([InlineKeyboardButton(item['question'], callback_data=f"faq_q_{i}")])
    keyboard.append([InlineKeyboardButton("🔙 В главное меню", callback_data="start")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text="Выберите вопрос, чтобы узнать ответ:", reply_markup=reply_markup)
    return FAQ_QUESTION

async def show_faq_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Показывает ответ на выбранный вопрос FAQ."""
    query = update.callback_query
    await query.answer()
    index = int(query.data.replace("faq_q_", ""))

    questions = faq_data.get("Вопросы", [])
    if 0 <= index < len(questions):
        question_item = questions[index]
        message_text = f"*{question_item['question']}*\n\n{question_item['answer']}"
    else:
        message_text = "Извините, вопрос не найден."

    keyboard = [[InlineKeyboardButton("🔙 К вопросам", callback_data="faq")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        text=message_text,
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )
    return FAQ_QUESTION

    # --- Функции Отзывов ---

async def start_review(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Начинает процесс сбора отзыва."""
    query = update.callback_query
    keyboard=[]
    # Унифицируем, через что отправлять сообщение/редактировать
    target_message = query.message if query else update.message
    if query:
        await query.answer()
        await query.edit_message_text("Пожалуйста, напишите Ваш отзыв. Он очень важен для нас!",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 В главное меню", callback_data="start")]])
        )
    elif target_message: # Если команда вызвана напрямую
        await target_message.reply_text(
            "Пожалуйста, напишите Ваш отзыв. Он очень важен для нас!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 В главное меню", callback_data="start")]])
        )
    else:
        logger.error("start_review вызван без update.message или update.callback_query")
        return ConversationHandler.END # Завершаем, если не удалось определить, куда отвечать
    return REVIEW_TEXT

async def process_review(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обрабатывает полученный отзыв."""
    user = update.effective_user
    review_text = update.message.text
    review_entry = {
        "user_id": user.id,
        "username": user.username if user.username else user.full_name,
        "date": datetime.now().isoformat(),
        "text": review_text
    }
    reviews_data.append(review_entry)
    save_data(REVIEWS_FILE, reviews_data)

    await update.message.reply_text(
       "Спасибо за Ваш отзыв! Мы стараемся для Вас!",
       reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 В главное меню", callback_data="start")]])
    )
    # Уведомляем админов
    await context.bot.send_message(
        chat_id=ADMIN_CHAT_ID,
        text=f"📢 НОВЫЙ ОТЗЫВ ОТ ГОСТЯ: \n\n"
            f"От: {user.mention_html()} (ID: {user.id} )\n"
            f"Отзыв: {review_text}",
        parse_mode="HTML"
    )
    return ConversationHandler.END

async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отменяет текущую ConversationHandler."""
    await update.message.reply_text(
        "Действие отменено.",
        reply_markup=get_main_keyboard()
    )
    context.user_data.pop('review_data', None)
    return ConversationHandler.END


# --- Функции Проблем ---

async def start_problem(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Начинает процесс сбора описания проблемы."""
    keyboard=[]
    query = update.callback_query
    target_message = query.message if query else update.message

    if query:
        await query.answer()
        await query.edit_message_text(
            "Опишите, пожалуйста, Вашу проблему как можно подробнее. "
            "Это поможет нам быстрее ее решить.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 В главное меню", callback_data="start")]])
        )
    elif target_message:
        await target_message.reply_text(
            "Опишите, пожалуйста, Вашу проблему как можно подробнее. "
            "Это поможет нам быстрее ее решить.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 В главное меню", callback_data="start")]])
        )
    else:
        logger.error("start_problem вызван без update.message или update.callback_query")
    return PROBLEM_TEXT

async def process_problem(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обрабатывает полученное описание проблемы."""
    user = update.effective_user
    problem_text = update.message.text

    problem_entry = {
        "user_id": user.id,
        "username": user.username if user.username else user.full_name,
        "date": datetime.now().isoformat(),
        "text": problem_text
    }
    problems_data.append(problem_entry)
    save_data(PROBLEMS_FILE, problems_data)

    await update.message.reply_text(
        "Спасибо за сообщение. Мы уже работаем над решением!",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 В главное меню", callback_data="start")]])
    )
    # Уведомляем админов
    await context.bot.send_message(
        chat_id=ADMIN_CHAT_ID,
        text=f"🚨 НОВАЯ ПРОБЛЕМА ОТ ГОСТЯ: \n\n"
             f"От: {user.mention_html()} (ID: {user.id})\n"
             f"Проблема: {problem_text}",
        parse_mode="HTML"
    )
    return ConversationHandler.END

async def _send_chat_status_message(update: Update, context: ContextTypes.DEFAULT_TYPE, is_new_chat: bool):
    """Отправляет сообщение пользователю о статусе чата (начало/уже активен)."""
    user_id = str(update.effective_user.id)
    chat_active_message = (
        "Вы уже в активном чате со службой заботы о наших гостях. "
        "Пожалуйста, дождитесь ответа или отправьте Ваше сообщение."
    )
    new_chat_message = (
        "Вы подключены к службе заботы о наших гостях. Опишите Ваш вопрос, менеджер скоро ответит. "
        "Чтобы завершить чат, нажмите '🚫 Завершить чат'."
    )
    reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("🚫 Завершить чат", callback_data="end_chat")]])

    if is_new_chat:
        if update.callback_query:
            await update.callback_query.edit_message_text(new_chat_message, reply_markup=reply_markup)
        else:
            await update.message.reply_text(new_chat_message, reply_markup=reply_markup)
    else: # Chat is already active
        if update.callback_query:
            await update.callback_query.edit_message_text(chat_active_message, reply_markup=reply_markup)
        else:
            await update.message.reply_text(chat_active_message, reply_markup=reply_markup)

# --- Функции Live Chat (Служба поддержки) ---

async def start_live_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Начинает чат пользователя с менеджером."""
    query = update.callback_query
    user = update.effective_user
    user_id = str(user.id)

    if query:
        await query.answer()
    # Проверяем, если пользователь уже в активном чате
    if user_id in user_states_data and user_states_data[user_id].get("state") == "chat_active":
        await _send_chat_status_message(update, context, is_new_chat=False)
        return LIVE_CHAT_USER

    # Если это новый чат
    await _send_chat_status_message(update, context, is_new_chat=True)

    # Сохраняем состояние пользователя
    user_states_data[user_id] = {"state": "chat_active", "admin_chat_id": ADMIN_CHAT_ID}
    save_data(USER_STATES_FILE, user_states_data)

    # Уведомляем админов о новом запросе
    await context.bot.send_message(
        chat_id=ADMIN_CHAT_ID,
        text=f"🗣️ НОВЫЙ ЗАПРОС В ПОДДЕРЖКУ: \n\n"
             f"От: {user.mention_html()} \n"
             f"Напишите /reply {user.id} для ответа пользователю.",
        parse_mode="HTML"
    )
    return LIVE_CHAT_USER

async def handle_user_message_in_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Пересылает сообщение пользователя админам."""
    user = update.effective_user
    user_id = str(user.id)
    message_text = update.message.text

    # Проверяем, что пользователь действительно в режиме чата
    if user_id in user_states_data and user_states_data[user_id].get("state") == "chat_active":
        # Пересылаем сообщение админам
         # Используем forward_message для сохранения типа сообщения (текст, фото, документ и т.д.)
        await context.bot.forward_message(
            chat_id=ADMIN_CHAT_ID,
            from_chat_id=user.id,
            message_id=update.message.message_id
        )
        # Дополнительное сообщение для админа с кнопкой завершения
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=f"⬆️ Сообщение выше от {user.mention_html()} (ID: {user.id}).",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🚫 Завершить этот чат", callback_data=f"admin_end_chat_{user_id}")]])
        )
        await update.message.reply_text("Ваше сообщение отправлено менеджеру.")
        return LIVE_CHAT_USER
    else:
        # Если почему-то не в чате, но сообщение пришло сюда
        await send_main_menu(update, context, "Не удалось определить ваше состояние. Пожалуйста, попробуйте еще раз.")
        return ConversationHandler.END


async def end_live_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Пользователь завершает чат."""
    query = update.callback_query
    user = update.effective_user
    user_id = str(user.id)

    if query:
        await query.answer("Чат завершен.")
        await query.edit_message_text("❌ Чат со службой заботы завершен. Если у Вас возникнут новые вопросы, Вы всегда можете начать новый чат.")
    else:
        await update.message.reply_text("❌ Чат со службой заботы завершен. Если у Вас возникнут новые вопросы, Вы всегда можете начать новый чат.")

    if user_id in user_states_data:
        # Уведомляем админа о завершении чата пользователем
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=f"🚪 Пользователь {user.mention_html()} завершил чат.",
            parse_mode="HTML"
        )
        del user_states_data[user_id] 
        save_data(USER_STATES_FILE, user_states_data)

    return ConversationHandler.END


async def admin_end_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Админ завершает чат по кнопке."""
    query = update.callback_query
    admin_id = update.effective_user.id
    if admin_id != ADMIN_CHAT_ID and update.effective_chat.id != ADMIN_CHAT_ID: # Только админы могут завершать
        await query.answer("У вас нет прав для этого действия.")
        return

    user_to_end_id = query.data.replace("admin_end_chat_", "")

    if user_to_end_id in user_states_data:
        del user_states_data[user_to_end_id]
        save_data(USER_STATES_FILE, user_states_data)

        # Уведомляем пользователя
        try:
            await context.bot.send_message(
                chat_id=int(user_to_end_id),
                text="Менеджер завершил чат с Вами. Если у Вас есть другие вопросы, пожалуйста, воспользуйтесь главным меню ли начните чат заново.",
                reply_markup=get_main_keyboard()
            )
        except Exception as e:
            logger.error(f"Could not send message to user {user_to_end_id}: {e}")

        await query.edit_message_text(f"Чат с {user_to_end_id.mention_html()} завершен.")
    else:
        await query.edit_message_text(f"Активный чат {user_to_end_id.mention_html()} не найден.")
    await query.answer()


async def reply_to_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатывает команду /reply от админа."""
    admin_id = update.effective_user.id
    if admin_id != ADMIN_CHAT_ID and update.effective_chat.id != ADMIN_CHAT_ID: # Только админы могут отвечать
        await update.message.reply_text("У вас нет прав для использования этой команды.")
        return

    args = context.args
    if not args or len(args) < 2:
        await update.message.reply_text(
            "Использование: /reply <user_id> <текст_ответа>\n"
            "Пример: /reply 123456789 Привет, чем могу помочь?",
            parse_mode="Markdown"
        )
        return

    user_to_reply_id = args[0]
    reply_text = " ".join(args[1:])

    if user_to_reply_id in user_states_data and user_states_data[user_to_reply_id].get("state") == "chat_active":
        try:
            await context.bot.send_message(
                chat_id=int(user_to_reply_id),
                text=f"💬 *Ответ службы заботы:*\n_{reply_text}_",
                parse_mode="Markdown"
            )
            await update.message.reply_text(f"Ответ отправлен {user_to_reply_id.mention_html()}.")
        except Exception as e:
            await update.message.reply_text(f"Не удалось отправить ответ {user_to_reply_id.mention_html()}: {e}")
            logger.error(f"Error sending reply to user {user_to_reply_id.mention_html()}: {e}")
    else:
        await update.message.reply_text(f"{user_to_reply_id.mention_html()} не находится в активном чате или не найден.")

async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ответ на неизвестные команды."""
    await update.message.reply_text("Извините, я не понял эту команду. Пожалуйста, используйте кнопки или /help.")
    await send_main_menu(update, context)


def create_month_calendar(year: int, month: int, min_date: date):
    cal = calendar.Calendar()
    month_days = cal.monthdatescalendar(year, month)
    keyboard = []

    # Заголовки дней недели
    keyboard.append([InlineKeyboardButton(day, callback_data="ignore") for day in ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]])

    for week in month_days:
        row = []
        for day_date in week:
            # Проверяем, относится ли день к текущему отображаемому месяцу
            if day_date.month == month:
                # Проверяем, является ли дата прошедшей (до min_date)
                if day_date < min_date:
                    # Прошедшие даты делаем неактивными и пустыми
                    row.append(InlineKeyboardButton(" ", callback_data="ignore"))
                else:
                    # Допустимые даты
                    row.append(InlineKeyboardButton(str(day_date.day), callback_data=f"date_{day_date.isoformat()}"))
            else:
                # Даты из предыдущего/следующего месяца, отображаемые в сетке календаря
                row.append(InlineKeyboardButton(" ", callback_data="ignore")) # Пустые клетки для других месяцев
        keyboard.append(row)

    prev_month_date = (date(year, month, 1) - timedelta(days=1))
    next_month_date = (date(year, month, 1) + timedelta(days=31)).replace(day=1)

    keyboard.append([
        InlineKeyboardButton(f"<{russian_month_names[prev_month_date.month]}", callback_data=f"month_{prev_month_date.year}_{prev_month_date.month}"),
        InlineKeyboardButton(f"{russian_month_names[month]} {year}", callback_data="ignore"), # Используем словарь для текущего месяца
        InlineKeyboardButton(f"{russian_month_names[next_month_date.month]}>", callback_data=f"month_{next_month_date.year}_{next_month_date.month}")
    ])

    return InlineKeyboardMarkup(keyboard)    


# Функция бронирование
async def start_reservation(update: Update, context) -> InlineKeyboardMarkup:
    query = update.callback_query
    if query:
        await query.answer() # Подтверждаем обратный вызов (callback_query)
        # Если это обратный вызов, мы редактируем сообщение
        message_editor = query.edit_message_text
    else:
        # Если это команда (например, /reserve), мы отвечаем на сообщение
        message_editor = update.message.reply_text

    context.user_data['reservation_data'] = {} # Инициализация данных для бронирования
    now = datetime.now()

    calendar_markup = create_month_calendar(now.year, now.month, min_date=now.date())

    current_keyboard_rows = list(calendar_markup.inline_keyboard)
    current_keyboard_rows.append([InlineKeyboardButton("🔙 В главное меню", callback_data="start")])
    final_markup = InlineKeyboardMarkup(current_keyboard_rows)

    await message_editor(
        "В какой день Вы планируете посетить наше бистро? Пожалуйста, выберите дату:",
        reply_markup=final_markup
    )

    return ASK_DATE

async def calendar_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    data = query.data

    # Определяем сегодняшнюю дату для валидации min_date и max_date
    now_date = date.today() # Используем date.today() для консистентности
    MAX_RESERVATION_DAYS = 30 # Можно вынести в константу
    max_reserv_date = now_date + timedelta(days=MAX_RESERVATION_DAYS)

    if data.startswith("date_"):
        selected_date_str = data.split("_")[1]
        try:
            selected_date = date.fromisoformat(selected_date_str)
        except ValueError:
            await query.edit_message_text("Ошибка: Неверный формат даты.")
            # Возвращаемся в то же состояние или завершаем
            return ASK_DATE # или ConversationHandler.END

        # Дополнительная валидация выбранной даты
        if selected_date < now_date:
            await query.edit_message_text("Эх, если бы мы могли бронировать столы на '"'вчера'"', мы бы сами там сидели!😉 Увы, машина времени пока в ремонте. Выберите, пожалуйста, дату, которая еще не наступила.",
                                          reply_markup=create_month_calendar(now_date.year, now_date.month, now_date))
            return ASK_DATE # Остаемся в состоянии выбора даты
        elif selected_date > max_reserv_date:
            await query.edit_message_text(f"Вы не можете бронировать даты далее чем на {MAX_RESERVATION_DAYS} дней вперед.",
                                          reply_markup=create_month_calendar(now_date.year, now_date.month, now_date))
            return ASK_DATE # Остаемся в состоянии выбора даты

        # Если дата валидна, сохраняем ее и переходим к следующему шагу (например, выбор времени)
        context.user_data['reservation_data']['selected_date'] = selected_date
        await query.edit_message_text(
            f"Отлично! Дата: {format_date_for_display(selected_date)}.\n"
            "Теперь укажите желаемое время:",
            reply_markup=generate_time_keyboard(selected_date) # Генерируем клавиатуру времени
        )
        return ASK_TIME

    elif data.startswith("month_"):
        _, year_str, month_str = data.split("_")
        try:
            year, month = int(year_str), int(month_str)
        except ValueError:
            await query.edit_message_text("Ошибка: Неверный формат месяца.")
            return ASK_DATE

        # Заново генерируем календарь для нового месяца
        calendar_markup = create_month_calendar(year, month, min_date=now_date)
        
        # Добавляем кнопку "В главное меню"
        current_keyboard_rows = list(calendar_markup.inline_keyboard)
        current_keyboard_rows.append([InlineKeyboardButton("🔙 В главное меню", callback_data="start")])
        final_markup = InlineKeyboardMarkup(current_keyboard_rows)

        await query.edit_message_reply_markup(reply_markup=final_markup)
        return ASK_DATE # Остаемся в состоянии выбора даты

    elif data == "ignore":
        # Если нажата неактивная кнопка, просто ничего не делаем.
        # query.answer() уже был вызван в начале функции.
        return ASK_DATE # Остаемся в текущем состоянии

    # Если callback_data не соответствует ни одному из ожидаемых шаблонов
    await query.edit_message_text("Неизвестное действие.")
    return ASK_DATE

def generate_time_keyboard(selected_date: date):
    now_dt = datetime.now(MOSCOW_TZ) # Текущая дата и время
    
    #диапазон работы заведения
    start_hour = 11
    end_hour = 21 # До 21:00 включительно

    time_slots = []

    for hour in range(start_hour, end_hour + 1):
        for minute_step in [0, 30]: # Шаги по 30 минут
            proposed_naive_dt = datetime.combine(selected_date, datetime.min.replace(hour=hour, minute=minute_step).time())
            proposed_aware_dt_moscow = MOSCOW_TZ.localize(proposed_naive_dt)
            if proposed_aware_dt_moscow >= now_dt:
                time_slots.append(proposed_naive_dt) # Добавляем "naive" время для отображения

    # Размещаем кнопки времени по 4 в ряд
    row = []
    keyboard = []
    for i, slot in enumerate(time_slots):
        row.append(InlineKeyboardButton(slot.strftime("%H:%M"), callback_data=f"time_{slot.strftime('%H:%M')}"))
        if len(row) == 4 or i == len(time_slots) - 1: # Закрываем ряд каждые 4 кнопки или если это последняя
            keyboard.append(row)
            row = []
    
    keyboard.append([InlineKeyboardButton("Отмена бронирования", callback_data="cancel_reserve")])
    return InlineKeyboardMarkup(keyboard)

# Хендлер для обработки выбора времени из инлайн-клавиатуры
async def process_time_selection(update: Update, context):
    query = update.callback_query
    await query.answer()
    print(f"DEBUG: context.user_data at process_time_selection start: {context.user_data}")

    if query.data == "cancel_reserve":
        await query.edit_message_text("❌ Бронирование отменено.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 В главное меню", callback_data="start")]]))
        context.user_data.pop('reservation_data', None)
        return ConversationHandler.END

    reservation_data = context.user_data.get('reservation_data', {})

    try:
        # Извлекаем время из callback_data, например "time_19:30"
        time_str = query.data.split('_')[1]
        selected_time_naive = datetime.strptime(time_str, "%H:%M").time()
    except (IndexError, ValueError):
        logger.error(f"Неверный формат callback_data для времени: {query.data}")
        date_for_keyboard = reservation_data.get('selected_date', datetime.now().date())
        await query.edit_message_text(
            "Произошла ошибка при выборе времени. Пожалуйста, попробуйте еще раз.",
            reply_markup=generate_time_keyboard(date_for_keyboard)
        )
        return ASK_TIME

    now_dt_moscow = datetime.now(MOSCOW_TZ)

    # Повторная проверка на прошедшее время, если дата "Сегодня"
    # (Хотя generate_time_keyboard уже отфильтровывает, это дополнительная защита)
    selected_full_dt_naive = datetime.combine(reservation_data['selected_date'], selected_time_naive)
    selected_full_dt_moscow = MOSCOW_TZ.localize(selected_full_dt_naive)

    reservation_data['time'] = selected_time_naive
    reservation_data['full_datetime'] = selected_full_dt_moscow

    logger.debug(f"DEBUG: Выбранное время: {selected_time_naive}")
    logger.debug(f"DEBUG: Полное выбранное время (datetime, MSK): {selected_full_dt_moscow}")
    logger.debug(f"DEBUG: Текущее время now_dt (MSK): {now_dt_moscow}")
    logger.debug(f"DEBUG: Порог для сравнения (MSK): {now_dt_moscow - timedelta(minutes=5)}")

    if selected_full_dt_moscow <= now_dt_moscow:
        await query.edit_message_text(
            "Мы пока не умеем перемещаться в прошлое, поэтому выбрать это время не получится😁. Пожалуйста, укажите время, которое только предстоит.",
            reply_markup=generate_time_keyboard(reservation_data['selected_date'])
        )
        return ASK_TIME

    reservation_data['time'] = selected_time_naive
    reservation_data['full_datetime'] = selected_full_dt_moscow # Сохраняем aware datetime для дальнейших операций
    logger.info(f"Время бронирования выбрано: {selected_time_naive}")

    await query.edit_message_text(
        text=f"Выбрано время: {selected_time_naive.strftime('%H:%M')}.",
        reply_markup=InlineKeyboardMarkup([]) # <--- Вот здесь мы передаем пустую InlineKeyboardMarkup
    )

    await context.bot.send_message(
        chat_id=query.message.chat_id,
        text="На сколько человек бронируем стол? (например, 4)",
        reply_markup=ReplyKeyboardMarkup([["Отмена бронирования"]], one_time_keyboard=True, resize_keyboard=True)
    )

    return ASK_GUESTS

# 4. Получение количества гостей
async def get_guests(update: Update, context):
    text = update.message.text
    reservation_data = context.user_data['reservation_data']

    if text.lower() == "отмена бронирования":
        await update.message.reply_text("❌ Бронирование отменено.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 В главное меню", callback_data="start")]]))
        context.user_data.pop('reservation_data', None)
        return ConversationHandler.END

    try:
        num_guests = int(text)
        if num_guests <= 0:
            await update.message.reply_text("Количество человек должно быть положительным числом.")
            return ASK_GUESTS
        if num_guests > 8:
            await update.message.reply_text("Для бронирования более 8 человек, пожалуйста, свяжитесь с нами по телефону +7 (918) 582-31-51.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 В главное меню", callback_data="start")]]))
            return ConversationHandler.END
    except ValueError:
        await update.message.reply_text("Пожалуйста, введите количество человек числом (например, 4).")
        return ASK_GUESTS

    reservation_data['num_guests'] = num_guests
    await update.message.reply_text(
        f"Отлично, {num_guests} человек.\n"
        "На какое имя резервируем стол?",
        reply_markup=ReplyKeyboardMarkup([["Отмена бронирования"]], one_time_keyboard=True, resize_keyboard=True)
    )
    return ASK_NAME

NAME_PATTERN = re.compile(r"^[а-яА-Яa-zA-Z\s\-']+$")

# 5. Получение имени
async def get_name(update: Update, context):
    text = update.message.text
    reservation_data = context.user_data['reservation_data']

    if text.lower() == "отмена бронирования":
        await update.message.reply_text("❌ Бронирование отменено.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 В главное меню", callback_data="start")]]))
        context.user_data.pop('reservation_data', None)
        return ConversationHandler.END

    name_input = text.strip()

    if not name_input:
        await update.message.reply_text("Имя не может быть пустым. Пожалуйста, введите Ваше имя.")
        return ASK_NAME # Возвращаемся в то же состояние, чтобы запросить имя снова

    # Проверка длины имени
    if len(name_input) < 2 or len(name_input) > 50: # Пример: от 2 до 50 символов
        await update.message.reply_text(
            "Имя должно быть длиной от 2 до 50 символов. "
            "Пожалуйста, введите Ваше полное имя."
        )
        return ASK_NAME

    # Проверка на корректные символы с использованием регулярного выражения
    if not NAME_PATTERN.fullmatch(name_input):
        await update.message.reply_text(
            "Кажется, это не похоже на имя. "
            "Пожалуйста, используйте только буквы, пробелы, дефисы или апострофы."
        )
        return ASK_NAME # Возвращаемся в то же состояние, чтобы запросить имя снова
    # --- Конец проверки имени ---

    reservation_data['name'] = name_input
    context.user_data['reservation_data'] = reservation_data # Обновляем user_data

    await update.message.reply_text(
        f"Приятно познакомиться, {name_input}!\n"
        "Напишите, пожалуйста, Ваш номер телефона для связи (например, +79XXYYYYZZZZ или 89XXXXXXXXX)",
        reply_markup=ReplyKeyboardMarkup([["Отмена бронирования"]], one_time_keyboard=True, resize_keyboard=True)
    )
    return ASK_PHONE

RUSSIAN_MOBILE_PHONE_PATTERN = re.compile(r"^\+79\d{9}$")

# 6. Получение телефона
async def get_phone(update: Update, context):
    text = update.message.text
    reservation_data = context.user_data['reservation_data']

    if text.lower() == "отмена бронирования":
        await update.message.reply_text("❌ Бронирование отменено.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 В главное меню", callback_data="start")]]))
        context.user_data.pop('reservation_data', None)
        return ConversationHandler.END

    cleaned_phone = text.strip().replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    standardized_phone = ""

    # 2. Стандартизация префикса и начальная проверка длины
    if cleaned_phone.startswith("8"):
        # Если номер начинается с 8 и имеет общую длину 11 цифр (8 + 10 цифр)
        if len(cleaned_phone) == 11:
            standardized_phone = "+7" + cleaned_phone[1:] # Меняем 8 на +7
        else:
            # Если начинается с 8, но не 11 цифр, это некорректно для мобильного
            pass # standardized_phone останется пустым
    elif cleaned_phone.startswith("+7"):
        # Если номер уже начинается с +7 и имеет общую длину 12 символов (+7 + 10 цифр)
        if len(cleaned_phone) == 12:
            standardized_phone = cleaned_phone
        else:
            # Если начинается с +7, но не 12 символов, это некорректно
            pass
    elif cleaned_phone.startswith("9"):
        # Если номер начинается с 9 и имеет 10 цифр (9XXXXXXXXX),
        # предполагаем, что пропущен +7
        if len(cleaned_phone) == 10:
            standardized_phone = "+7" + cleaned_phone
        else:
            pass # Пропускаем, если не 10 цифр
    else:
        # Все остальные варианты (например, номера без префикса, слишком короткие/длинные)
        pass # standardized_phone останется пустым

    # 3. Финальная проверка стандартизированного номера с помощью регулярного выражения
    if not RUSSIAN_MOBILE_PHONE_PATTERN.fullmatch(standardized_phone):
        await update.message.reply_text(
            "Пожалуйста, введите корректный мобильный номер. "
            "Номер должен содержать 11 цифр и начинаться с +7 или 8 "
            "(например, +79XXXXXXXXX или 89XXXXXXXXX)."
        )
        return ASK_PHONE # Возвращаемся в это же состояние, чтобы запросить номер снова

    
    reservation_data['phone'] = standardized_phone
    context.user_data['reservation_data'] = reservation_data # Обновляем user_data

    await update.message.reply_text(
        "Есть ли у Вас какие-то особые пожелания или комментарии к бронированию? "
        "(например, стол у окна, празднование дня рождения)",
        reply_markup=ReplyKeyboardMarkup([
            ["Нет пожеланий", "День рождения"],    # Первая строка: 2 кнопки
            ["Стол у окна", "Отмена бронирования"] # Вторая строка: 2 кнопки
        ], one_time_keyboard=True, resize_keyboard=True)
    )
    return ASK_WISHES

# 8. Получение особых пожеланий (опционально)
async def get_wishes(update: Update, context):
    text = update.message.text
    reservation_data = context.user_data['reservation_data']

    if text.lower() == "отмена бронирования":
        await update.message.reply_text("❌ Бронирование отменено.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 В главное меню", callback_data="start")]]))
        context.user_data.pop('reservation_data', None)
        return ConversationHandler.END
    elif text.lower() == "нет пожеланий":
        reservation_data['wishes'] = None
    elif text.lower() == "день рождения":
        reservation_data['wishes'] = "День рождения"
    elif text.lower() == "стол у окна":
        reservation_data['wishes'] = "Стол у окна"
    else:
        reservation_data['wishes'] = text

    # Суммируем информацию для подтверждения
    summary = (
        "Пожалуйста, проверьте данные бронирования:\n"
        f"📅 Дата: *{format_date_for_display(reservation_data['selected_date'])}*\n"
        f"⏰ Время: *{reservation_data['time'].strftime('%H:%M')}*\n"
        f"👥 Гостей: *{reservation_data['num_guests']}*\n"
        f"👤 Имя: *{reservation_data['name']}*\n"
        f"📞 Телефон: *{reservation_data['phone']}*\n"
    )
    if reservation_data['wishes']:
        summary += f"📝 Пожелания: *{reservation_data['wishes']}*\n"

    keyboard = [
        [InlineKeyboardButton("✅ Подтвердить", callback_data="confirm_reserve")],
        [InlineKeyboardButton("❌ Отменить бронирование", callback_data="cancel_reserve")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(summary, reply_markup=reply_markup, parse_mode='Markdown')
    return CONFIRM_RESERVATION

# 9. Подтверждение или отмена бронирования (callback)
async def confirm_or_cancel_reservation(update: Update, context):
    query = update.callback_query
    await query.answer() # Обязательно ответить на CallbackQuery

    reservation_data = context.user_data['reservation_data']

    if query.data == "confirm_reserve":
        # Формируем сообщение для администратора
        admin_message = (
            "🔔 *НОВЫЙ ЗАПРОС НА БРОНИРОВАНИЕ СТОЛИКА!* 🔔\n\n"
            f"От пользователя: @{update.effective_user.username or update.effective_user.id}\n"
            f"ID пользователя: {update.effective_user.id}\n\n"
            f"📅 Дата: *{format_date_for_display(reservation_data['selected_date'])}*\n"
            f"⏰ Время: *{reservation_data['time'].strftime('%H:%M')}*\n"
            f"👥 Гостей: *{reservation_data['num_guests']}*\n"
            f"👤 Имя: *{reservation_data['name']}*\n"
            f"📞 Телефон: *{reservation_data['phone']}*\n"
        )
        if reservation_data['wishes']:
            admin_message += f"📝 Пожелания: *{reservation_data['wishes']}*\n"
        else:
            admin_message += "📝 Пожелания: _Отсутствуют_\n"

        admin_message += "\n*Не забудьте связаться с гостем для подтверждения!*"

        try:
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=admin_message,
                parse_mode='Markdown'
            )
            logger.info(f"Запрос на бронирование от {update.effective_user.id} отправлен менеджеру.")
            await query.edit_message_text(
                "✅ Ваш запрос на бронирование отправлен менеджеру.\n"
                "Мы свяжемся с Вами в ближайшее время для подтверждения!\n"
                "Спасибо за выбор нашего заведения!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 В главное меню", callback_data="start")]])  # Убираем кнопки после подтверждения
            )
        except Exception as e:
            logger.error(f"Не удалось отправить сообщение менеджеру: {e}")
            await query.edit_message_text(
                "Произошла ошибка при отправке запроса менеджеру. Пожалуйста, попробуйте позже.",
                 reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 В главное меню", callback_data="start")]])
            )

    elif query.data == "cancel_reserve":
        await query.edit_message_text("❌ Бронирование отменено.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 В главное меню", callback_data="start")]]))
        context.user_data.pop('reservation_data', None)

    # Очищаем данные пользователя после завершения диалога
    context.user_data.pop('reservation_data', None)
    return ConversationHandler.END

# Отмена бронирования (для кнопки "Отмена" или команды /cancel)
async def cancel_reservation(update: Update, context):
    logger.info(f"Пользователь {update.effective_user.id} отменил бронирование.")
    context.user_data.pop('reservation_data', None)
    await update.message.reply_text("Бронирование отменено.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

# Обработчик для случаев, когда пользователь ввел что-то неожиданное в диалоге
async def fallback_handler(update: Update, context):
    await update.message.reply_text("Пожалуйста, следуйте инструкциям.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 В главное меню", callback_data="start")]]))
    return ConversationHandler.END
        
async def make_order_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /order."""
    await update.message.reply_text("Функция онлайн-заказа пока не доступна.Вы можете просмотреть наше меню, а для заказа свяжитесь с нами напрямую по телефону +7 (918) 582-31-51.",
        reply_markup=get_main_keyboard()
    )
    

# --- Главная функция бота ---

def main() -> None:
    """Запускает бота."""
    application = Application.builder().token(BOT_TOKEN).build()

    # ConversationHandler для меню
    menu_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(show_menu_categories, pattern="^menu$")],
        states={
            MENU_CATEGORY: [CallbackQueryHandler(show_menu_items, pattern="^menu_cat_")],
            MENU_ITEM: [CallbackQueryHandler(show_menu_categories, pattern="^menu$")]
        },
        fallbacks=[CallbackQueryHandler(send_main_menu, pattern="^start$"),
                   CommandHandler("start", start)]
    )
    application.add_handler(menu_conv_handler)

    # ConversationHandler для FAQ
    faq_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(show_faq_questions, pattern="^faq$")],
        states={
            FAQ_QUESTION: [CallbackQueryHandler(show_faq_answer, pattern="^faq_q_")]
        },
        fallbacks=[CallbackQueryHandler(send_main_menu, pattern="^start$"),
                   CommandHandler("start", start)]
    )
    application.add_handler(faq_conv_handler)

    # ConversationHandler для отзывов
    review_conversation = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_review, pattern="^start_review$"),
                      CommandHandler("review", start_review)],
        states={
            REVIEW_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_review)],
        },
        fallbacks=[CommandHandler("cancel", cancel_conversation),
                   MessageHandler(filters.TEXT & ~filters.COMMAND, cancel_conversation),
                   CallbackQueryHandler(send_main_menu, pattern="^start$"),
                   CommandHandler("start", start)],
        allow_reentry=True
    )
    application.add_handler(review_conversation)

    # ConversationHandler для проблем
    problem_conversation = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_problem, pattern="^start_problem$"),
                      CommandHandler("problem", start_problem)],
        states={
            PROBLEM_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_problem)],
        },
        fallbacks=[CommandHandler("cancel", cancel_conversation),
                   MessageHandler(filters.TEXT & ~filters.COMMAND, cancel_conversation),
                   CallbackQueryHandler(send_main_menu, pattern="^start$"),
                   CommandHandler("start", start)]
    )
    application.add_handler(problem_conversation)

    # ConversationHandler для живого чата
    live_chat_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_live_chat, pattern="^support$")],
        states={
            LIVE_CHAT_USER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_user_message_in_chat),
                CallbackQueryHandler(end_live_chat, pattern="^end_chat$")
            ]
        },
        fallbacks=[CommandHandler("cancel", end_live_chat), # Пользователь может завершить чат командой /cancel
                   CallbackQueryHandler(send_main_menu, pattern="^start$"),
                   CommandHandler("start", start)]
    )
    application.add_handler(live_chat_conv_handler)

    # ConversationHandler для бронирования столов
    reservation_conversation = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_reservation, pattern="^start_reservation$"), # Если бронирование начинается с кнопки
                      CommandHandler("reserve", start_reservation)
        ],
        states={
            ASK_DATE: [CallbackQueryHandler(calendar_callback_handler, pattern="^(date_|month_|start|ignore)")], # Календарь
            ASK_TIME:  [CallbackQueryHandler(process_time_selection, pattern="^time_.*|cancel_reserve$")], # Выбор времени и отмена
            ASK_GUESTS: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_guests)],
            ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            ASK_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_phone)],
            ASK_WISHES: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_wishes)],
            CONFIRM_RESERVATION: [CallbackQueryHandler(confirm_or_cancel_reservation)],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_reservation), # Команда /cancel для выхода из любого состояния
            CallbackQueryHandler(cancel_reservation, pattern="^cancel_reserve$"), # Кнопка отмены
            CommandHandler("start", start),               # Команда /start для перезапуска бота
            MessageHandler(filters.TEXT & ~filters.COMMAND & filters.Regex(r"(?i)^отмена$"), cancel_reservation), # Кнопка "Отмена"
        ],
        per_user=True,
        allow_reentry=True, # Позволяет пользователю начать новый разговор, даже если предыдущий не был завершен
    )
    application.add_handler(reservation_conversation)

    # Основные команды
    application.add_handler(CommandHandler("start", start))

    # Команды из BotFather:
    application.add_handler(CommandHandler("menu", send_main_menu)) # Теперь /menu сразу ведет к категориям
    application.add_handler(CommandHandler("review", review_conversation))
    application.add_handler(CommandHandler("order", make_order_command))     # Добавляем новый обработчик
    application.add_handler(CommandHandler("reserve", start_reservation))
    application.add_handler(CommandHandler("help", help_command))

    # Обработчик кнопки "Назад в главное меню"
    application.add_handler(CallbackQueryHandler(send_main_menu, pattern="^start$"))
    # Команда для админов, чтобы отвечать пользователям
    application.add_handler(CommandHandler("reply", reply_to_user))
    # Обработчик для кнопки "Завершить этот чат" для админа
    application.add_handler(CallbackQueryHandler(admin_end_chat, pattern="^admin_end_chat_"))
    # Обработчик для неизвестных команд и сообщений, если пользователь не в ConversationHandler
    application.add_handler(MessageHandler(filters.COMMAND, unknown))
    # Этот обработчик должен быть ПОСЛЕДНИМ, чтобы не перехватывать сообщения для ConversationHandler
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, send_main_menu))


    logger.info("Бот запускается...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    try:
        logger.info("Попытка запуска бота...")
        main()
        logger.info("Бот успешно запущен и ожидает сообщений...")
    except Exception as e:
        logger.error(f"Критическая ошибка при запуске бота: {e}", exc_info=True)

