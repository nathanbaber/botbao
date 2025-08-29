import logging
import json
import os
import re
from dotenv import load_dotenv; load_dotenv()
load_dotenv()
from datetime import datetime, timedelta, date, time 
from uuid import uuid4
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, ContextTypes, filters
)
from telegram.error import BadRequest
from telegram_bot_calendar import DetailedTelegramCalendar, LSTEP
import html

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- КОНФИГУРАЦИЯ БОТА ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID"))
           
# --------------------------

# Состояния для ConversationHandler (все должны быть уникальными)
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
       reply_markup=get_main_keyboard()
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
        reply_markup=get_main_keyboard()
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

# --- Функции Live Chat (Служба поддержки) ---

async def start_live_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Начинает чат пользователя с менеджером."""
    query = update.callback_query
    user = update.effective_user
    user_id = str(user.id)

    if query:
        await query.answer()
        if user_id in user_states_data and user_states_data[user_id].get("state") == "chat_active":
            await query.edit_message_text(
                "Вы уже в активном чате со службой заботы о наших гостях. Пожалуйста, дождитесь ответа или отправьте Ваше сообщение.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🚫 Завершить чат", callback_data="end_chat")]])
            )
            return LIVE_CHAT_USER

        await query.edit_message_text(
            "Вы подключены к службе заботы о наших гостях. Опишите Ваш вопрос, менеджер скоро ответит. "
            "Чтобы завершить чат, нажмите '🚫 Завершить чат'.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🚫 Завершить чат", callback_data="end_chat")]])
        )
    else: # Если команда вызвана напрямую
         if user_id in user_states_data and user_states_data[user_id].get("state") == "chat_active":
            await update.message.reply_text(
                "Вы уже в активном чате со службой заботы о наших гостях. Пожалуйста, дождитесь ответа или отправьте Ваше сообщение.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🚫 Завершить чат", callback_data="end_chat")]])
            )
            return LIVE_CHAT_USER

         await update.message.reply_text(
            "Вы подключены к службе заботы о наших гостях. Опишите Ваш вопрос, менеджер скоро ответит. "
            "Чтобы завершить чат, нажмите '🚫 Завершить чат'.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🚫 Завершить чат", callback_data="end_chat")]])
        )

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
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=f"💬 Сообщение от {user.mention_html()}: \n\n"
                 f"{message_text}",
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

    await query.answer()

    if user_id in user_states_data:
        del user_states_data[user_id]
        save_data(USER_STATES_FILE, user_states_data)

        await query.edit_message_text(
            "Чат с поддержкой завершен. Спасибо за обращение!",
            reply_markup=get_main_keyboard()
        )
        # Уведомляем админов о завершении чата
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=f"ℹ️ Пользователь {user.mention_html()} завершил чат.",
            parse_mode="HTML"
        )
    else:
        await query.edit_message_text(
            "Чат не активен.",
            reply_markup=get_main_keyboard()
        )
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


# Функция бронирование
async def start_reservation(update: Update, context) -> int:
    query = update.callback_query
    context.user_data['reservation_data'] = {} # Инициализация данных для бронирования
    now = datetime.now()

    # Создаем календарь
    calendar, step = DetailedTelegramCalendar(
        locale='ru',
        min_date=now.date(), # Нельзя выбрать прошедшую дату
        max_date=now.date() + timedelta(days=30) # Максимум на 1 месяц вперед
    ).build()

    await query.edit_message_text("В какой день Вы планируете посетить наше бистро? Пожалуйста, выберите дату:",
        reply_markup=calendar,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 В главное меню", callback_data="start")]])
    )
    return ASK_DATE

# Хендлер для обработки выбора даты из календаря
async def process_date_selection(update: Update, context) -> int:
    query = update.callback_query
    await query.answer() 
    now = datetime.now()

    # Обрабатываем клики по календарю
    result, key, step = DetailedTelegramCalendar(
        locale='ru',
        min_date=now.date(),
        max_date=now.date() + timedelta(days=30)
    ).process(query.data)

    if not result and key: # Пользователь еще выбирает месяц/год/день
        await query.edit_message_text(
            f"В какой день Вы планируете посетить наше бистро? Пожалуйста, выберите дату:",
            reply_markup=key
        )
        return ASK_DATE
    elif result: # Дата выбрана
        selected_date = result
        today = now.date()

        # Повторная проверка на прошедшую дату (хотя min_date должен предотвратить)
        if selected_date < today:
            await query.edit_message_text(
                "Эх, если бы мы могли бронировать столы на '"'вчера'"', мы бы сами там сидели!😉 Увы, машина времени пока в ремонте. Выберите, пожалуйста, дату, которая еще не наступила.",
                reply_markup=None # Убираем календарь
            )
            # Отправляем новый календарь для выбора
            calendar, step = DetailedTelegramCalendar(
                locale='ru',
                min_date=today,
                max_date=today + timedelta(days=30)
            ).build()
            await query.message.reply_text("Пожалуйста, выберите корректную дату:", reply_markup=calendar)
            return ASK_DATE

        context.user_data['reservation_data']['date'] = selected_date
        logger.info(f"Дата бронирования выбрана: {selected_date}")

        await query.edit_message_text(
            f"Отлично! Дата: {format_date_for_display(selected_date)}.\n"
            "Теперь укажите желаемое время:",
            reply_markup=generate_time_keyboard(selected_date) # Генерируем клавиатуру времени
        )
        return ASK_TIME


def generate_time_keyboard(selected_date: date):
    keyboard = []
    now_dt = datetime.now() # Текущая дата и время
    current_time = now_dt.time()
    
    #диапазон работы заведения
    start_hour = 11
    end_hour = 21 # До 21:00 включительно

    time_slots = []
    for hour in range(start_hour, end_hour + 1):
        for minute_step in [0, 30]: # Шаги по 30 минут
            slot_time = time(hour, minute_step)
            slot_full_dt = datetime.combine(selected_date, slot_time)
            # Если дата "сегодня" и время слота уже прошло, пропускаем его
            if slot_full_dt < now_dt - timedelta(minutes=5): # Даем себе 5 минут "форы"
                continue
            
            time_slots.append(slot_time)

    # Размещаем кнопки времени по 2 в ряд
    row = []
    for i, slot in enumerate(time_slots):
        row.append(InlineKeyboardButton(slot.strftime("%H:%M"), callback_data=f"time_{slot.strftime('%H:%M')}"))
        if len(row) == 2 or i == len(time_slots) - 1: # Закрываем ряд каждые 4 кнопки или если это последняя
            keyboard.append(row)
            row = []
    
    keyboard.append([InlineKeyboardButton("Отмена бронирования", callback_data="cancel_reserve")])

    return InlineKeyboardMarkup(keyboard)

# Хендлер для обработки выбора времени из инлайн-клавиатуры
async def process_time_selection(update: Update, context):
    query = update.callback_query
    await query.answer()

    if query.data == "cancel_reserve":
        await query.edit_message_text("❌ Бронирование отменено.", reply_markup=None)
        context.user_data.pop('reservation_data', None)
        return ConversationHandler.END

    reservation_data = context.user_data['reservation_data']
    
    try:
        # Извлекаем время из callback_data, например "time_19:30"
        time_str = query.data.split('_')[1]
        selected_time = datetime.strptime(time_str, "%H:%M").time()
    except (IndexError, ValueError):
        logger.error(f"Неверный формат callback_data для времени: {query.data}")
        await query.edit_message_text(
            "Произошла ошибка при выборе времени. Пожалуйста, попробуйте еще раз.",
            reply_markup=generate_time_keyboard(reservation_data['date'])
        )
        return ASK_TIME

    # Повторная проверка на прошедшее время, если дата "Сегодня"
    # (Хотя generate_time_keyboard уже отфильтровывает, это дополнительная защита)
    selected_full_dt = datetime.combine(reservation_data['date'], selected_time)
    now_dt = datetime.now()

    if selected_full_dt < now_dt - timedelta(minutes=5): # С тем же запасом
        await query.edit_message_text(
            "Мы пока не умеем перемещаться в прошлое, поэтому выбрать это время не получится😁. Пожалуйста, укажите время, которое только предстоит.",
            reply_markup=generate_time_keyboard(reservation_data['date'])
        )
        return ASK_TIME

    reservation_data['time'] = selected_time
    logger.info(f"Время бронирования выбрано: {selected_time}")

    await query.edit_message_text(
        text=f"Выбрано время: {selected_time.strftime('%H:%M')}.",
        reply_markup=InlineKeyboardMarkup([]) # <--- Вот здесь мы передаем пустую InlineKeyboardMarkup
    )

    await context.bot.send_message(
        chat_id=query.message.chat_id,
        text="На сколько человек бронируем стол? (например, 4)",
        reply_markup=ReplyKeyboardMarkup([["Отмена"]], one_time_keyboard=True, resize_keyboard=True)
    )

    return ASK_GUESTS

# 4. Получение количества гостей
async def get_guests(update: Update, context):
    text = update.message.text
    reservation_data = context.user_data['reservation_data']

    if text.lower() == "отмена":
        await update.message.reply_text("Бронирование отменено.", reply_markup=ReplyKeyboardRemove())
        context.user_data.pop('reservation_data', None)
        return ConversationHandler.END

    try:
        num_guests = int(text)
        if num_guests <= 0:
            await update.message.reply_text("Количество человек должно быть положительным числом.")
            return ASK_GUESTS
        if num_guests > 20: # Пример ограничения
            await update.message.reply_text("Для бронирования более 8 человек, пожалуйста, свяжитесь с нами по телефону +7 (918) 582-31-51.")
            return ASK_GUESTS
    except ValueError:
        await update.message.reply_text("Пожалуйста, введите количество человек числом (например, 4).")
        return ASK_GUESTS

    reservation_data['num_guests'] = num_guests
    await update.message.reply_text(
        f"Отлично, {num_guests} человек.\n"
        "На какое имя резервируем стол?",
        reply_markup=ReplyKeyboardMarkup([["Отмена"]], one_time_keyboard=True, resize_keyboard=True)
    )
    return ASK_NAME

# 5. Получение имени
async def get_name(update: Update, context):
    text = update.message.text
    reservation_data = context.user_data['reservation_data']

    if text.lower() == "отмена":
        await update.message.reply_text("Бронирование отменено.", reply_markup=ReplyKeyboardRemove())
        context.user_data.pop('reservation_data', None)
        return ConversationHandler.END

    reservation_data['name'] = text
    await update.message.reply_text(
        f"Приятно познакомиться, {text}!\n"
        "Напишите, пожалуйста, Ваш номер телефона для связи (например, +79XXYYYYZZZZ)",
        reply_markup=ReplyKeyboardMarkup([["Отмена"]], one_time_keyboard=True, resize_keyboard=True)
    )
    return ASK_PHONE

# 6. Получение телефона
async def get_phone(update: Update, context):
    text = update.message.text
    reservation_data = context.user_data['reservation_data']

    if text.lower() == "отмена":
        await update.message.reply_text("Бронирование отменено.",reply_markup=ReplyKeyboardRemove())
        context.user_data.pop('reservation_data', None)
        return ConversationHandler.END

    # Простая проверка на то, что это похоже на телефонный номер
    if not re.match(r"^\+?\d{10,15}$", text.replace(" ", "").replace("-", "")):
        await update.message.reply_text("Пожалуйста, введи корректный номер телефона (например, +79XXXXXXXXX).")
        return ASK_PHONE
    else:
        # Стандартизируем номер перед сохранением
        standardized_phone = text.replace(" ", "").replace("-", "")
        # Опционально: если номер начинается с 8, меняем на +7 (для России)
        if standardized_phone.startswith("8") and len(standardized_phone) == 11:
            standardized_phone = "+7" + standardized_phone[1:]

    reservation_data['phone'] = standardized_phone
    await update.message.reply_text(
        "Есть ли у Вас какие-то особые пожелания или комментарии к бронированию? "
        "(например, стол у окна, празднование дня рождения)",
        reply_markup=ReplyKeyboardMarkup([["Нет пожеланий", "День рождения","Стол у окна", "Отмена"]], one_time_keyboard=True, resize_keyboard=True)
    )
    return ASK_WISHES

# 8. Получение особых пожеланий (опционально)
async def get_wishes(update: Update, context):
    text = update.message.text
    reservation_data = context.user_data['reservation_data']

    if text.lower() == "отмена":
        await update.message.reply_text("Бронирование отменено.", reply_markup=ReplyKeyboardRemove())
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
        f"📅 Дата: *{format_date_for_display(reservation_data['date'])}*\n"
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
            f"📅 Дата: *{format_date_for_display(reservation_data['date'])}*\n"
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
                reply_markup=None # Убираем кнопки после подтверждения
            )
        except Exception as e:
            logger.error(f"Не удалось отправить сообщение менеджеру: {e}")
            await query.edit_message_text(
                "Произошла ошибка при отправке запроса менеджеру. Пожалуйста, попробуйте позже.",
                reply_markup=None
            )

    elif query.data == "cancel_reserve":
        await query.edit_message_text("❌ Бронирование отменено.", reply_markup=None)
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
    await update.message.reply_text("Пожалуйста, следуйте инструкциям или нажмите 'Отмена'.")
    return ConversationHandler.END
        
async def make_order_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /order."""
    await update.message.reply_text("Функция онлайн-заказа пока не доступна.Вы можете просмотреть наше меню, а для заказа свяжитесь с нами напрямую по телефону +7 (918) 582-31-51.",
        reply_markup=get_main_keyboard()
    )

async def book_table(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    logger.info(f"Пользователь {user_id} нажал 'Забронировать стол'.")
    # Здесь начнется логика бронирования
    await update.message.reply_text("Отлично! Для бронирования стола мне потребуется несколько деталей. Пожалуйста, выберите дату:")
    return ASK_DATE
    

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
            ASK_DATE: [CallbackQueryHandler(process_date_selection)], # Календарь
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

