import logging
import json
import os
from dotenv import load_dotenv; load_dotenv()
load_dotenv()
import datetime
from uuid import uuid4


from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, ContextTypes, filters
)
from telegram.error import BadRequest

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- КОНФИГУРАЦИЯ БОТА ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID"))
           
# --------------------------

# Состояния для ConversationHandler
MENU_CATEGORY, MENU_ITEM = range(2)
FAQ_QUESTION = 0
REVIEW_TEXT = 0
PROBLEM_TEXT = 0
LIVE_CHAT_USER, LIVE_CHAT_ADMIN_REPLY = range(2)

# Пути к файлам данных
DATA_DIR = 'data'
MENU_FILE = os.path.join(DATA_DIR, 'menu.json')
FAQ_FILE = os.path.join(DATA_DIR, 'faq.json')
REVIEWS_FILE = os.path.join(DATA_DIR, 'reviews.json')
PROBLEMS_FILE = os.path.join(DATA_DIR, 'problems.json')
USER_STATES_FILE = os.path.join(DATA_DIR, 'user_states.json')

menu_data = {} # Глобальная переменная для хранения данных меню

# Убедимся, что директория data существует
os.makedirs(DATA_DIR, exist_ok=True)

# --- Функции для работы с данными (загрузка/сохранение) ---

async def get_file_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.photo:
        file_id = update.message.photo[-1].file_id
        await update.message.reply_text(f"File ID для этой фотографии: '{file_id}' \n\nИспользуйте его в menu.json", parse_mode='Markdown')
    elif update.message.document:
        file_id = update.message.document.file_id
        await update.message.reply_text(f"File ID для этого документа: '{file_id}' \n\nИспользуйте его в menu.json", parse_mode='Markdown')
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

def get_main_keyboard():
    """Возвращает клавиатуру главного меню."""
    keyboard = [
        [InlineKeyboardButton("🍽️ Меню", callback_data="menu")],
        [InlineKeyboardButton("❓ Вопросы", callback_data="faq")],
        [InlineKeyboardButton("✍️ Оставить отзыв", callback_data="review")],
        [InlineKeyboardButton("⚠️ Сообщить о проблеме", callback_data="problem")],
        [InlineKeyboardButton("🗣️ Связаться со службой поддержки", callback_data="support")]
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
    keyboard.append([InlineKeyboardButton("🔙 Назад в главное меню", callback_data="start")])

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

async def start_review(update: Update, context:
ContextTypes.DEFAULT_TYPE) -> int:
    """Начинает процесс сбора отзыва."""
    query = update.callback_query
    if query:
        await query.answer()
        await query.edit_message_text(
            "Пожалуйста, напишите ваш отзыв. Он очень важен для нас! "
            "Чтобы отменить, нажмите /cancel.",
            reply_markup=ReplyKeyboardRemove() # Убираем инлайн-клавиатуру
        )
    else: # Если команда вызвана напрямую
        await update.message.reply_text(
            "Пожалуйста, напишите ваш отзыв. Он очень важен для нас! "
            "Чтобы отменить, нажмите /cancel.",
            reply_markup=ReplyKeyboardRemove() # Убираем инлайн-клавиатуру
        )
    return REVIEW_TEXT

async def process_review(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обрабатывает полученный отзыв."""
    user = update.effective_user
    review_text = update.message.text

    review_entry = {
        "user_id": user.id,
        "username": user.username if user.username else user.full_name,
        "date": datetime.datetime.now().isoformat(),
        "text": review_text
    }
    reviews_data.append(review_entry)
    save_data(REVIEWS_FILE, reviews_data)

    await update.message.reply_text(
        "Спасибо за ваш отзыв! Мы обязательно его учтем.",
        reply_markup=get_main_keyboard()
    )
    # Уведомляем админов
    await context.bot.send_message(
        chat_id=ADMIN_CHAT_ID,
        text=f"📢 *НОВЫЙ ОТЗЫВ ОТ КЛИЕНТА:*\n\n"
             f"От: {user.mention_html()} (ID: Ⓝ{user.id}Ⓝ)\n"
             f"Отзыв: _{review_text}_",
        parse_mode="HTML"
    )
    return ConversationHandler.END

async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отменяет текущую ConversationHandler."""
    await update.message.reply_text(
        "Действие отменено.",
        reply_markup=get_main_keyboard()
    )
    return ConversationHandler.END

# --- Функции Проблем ---

async def start_problem(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Начинает процесс сбора описания проблемы."""
    query = update.callback_query
    if query:
        await query.answer()
        await query.edit_message_text(
            "Опишите, пожалуйста, вашу проблему как можно подробнее. "
            "Это поможет нам быстрее ее решить. Чтобы отменить, нажмите /cancel.",
            reply_markup=ReplyKeyboardRemove()
        )
    else:
        await update.message.reply_text(
            "Опишите, пожалуйста, вашу проблему как можно подробнее. "
            "Это поможет нам быстрее ее решить. Чтобы отменить, нажмите /cancel.",
            reply_markup=ReplyKeyboardRemove()
        )
    return PROBLEM_TEXT

async def process_problem(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обрабатывает полученное описание проблемы."""
    user = update.effective_user
    problem_text = update.message.text

    problem_entry = {
        "user_id": user.id,
        "username": user.username if user.username else user.full_name,
        "date": datetime.datetime.now().isoformat(),
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
        text=f"🚨 *НОВАЯ ПРОБЛЕМА ОТ КЛИЕНТА:*\n\n"
             f"От: {user.mention_html()} (ID: Ⓝ{user.id}Ⓝ)\n"
             f"Проблема: _{problem_text}_",
        parse_mode="HTML"
    )
    return ConversationHandler.END

# --- Функции Live Chat (Служба поддержки) ---

async def start_live_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Начинает чат пользователя с поддержкой."""
    query = update.callback_query
    user = update.effective_user
    user_id = str(user.id)

    if query:
        await query.answer()
        if user_id in user_states_data and user_states_data[user_id].get("state") == "chat_active":
            await query.edit_message_text(
                "Вы уже в активном чате с поддержкой. Пожалуйста, дождитесь ответа или отправьте ваше сообщение.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🚫 Завершить чат", callback_data="end_chat")]])
            )
            return LIVE_CHAT_USER

        await query.edit_message_text(
            "Вы подключены к службе поддержки. Опишите ваш вопрос, оператор скоро ответит. "
            "Чтобы завершить чат, нажмите '🚫 Завершить чат'.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🚫 Завершить чат", callback_data="end_chat")]])
        )
    else: # Если команда вызвана напрямую
         if user_id in user_states_data and user_states_data[user_id].get("state") == "chat_active":
            await update.message.reply_text(
                "Вы уже в активном чате с поддержкой. Пожалуйста, дождитесь ответа или отправьте ваше сообщение.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🚫 Завершить чат", callback_data="end_chat")]])
            )
            return LIVE_CHAT_USER

         await update.message.reply_text(
            "Вы подключены к службе поддержки. Опишите ваш вопрос, оператор скоро ответит. "
            "Чтобы завершить чат, нажмите '🚫 Завершить чат'.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🚫 Завершить чат", callback_data="end_chat")]])
        )

    # Сохраняем состояние пользователя
    user_states_data[user_id] = {"state": "chat_active", "admin_chat_id": ADMIN_CHAT_ID}
    save_data(USER_STATES_FILE, user_states_data)

    # Уведомляем админов о новом запросе
    await context.bot.send_message(
        chat_id=ADMIN_CHAT_ID,
        text=f"🗣️ *НОВЫЙ ЗАПРОС В ПОДДЕРЖКУ:*\n\n"
             f"От: {user.mention_html()} (ID: Ⓝ{user.id}Ⓝ)\n"
             f"Напишите Ⓝ/reply {user.id} Ваш_ответⓃ для ответа пользователю.",
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
            text=f"💬 *Сообщение от клиента {user.mention_html()} (ID: Ⓝ{user_id}Ⓝ):*\n\n"
                 f"_{message_text}_",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🚫 Завершить этот чат", callback_data=f"admin_end_chat_{user_id}")]])
        )
        await update.message.reply_text("Ваше сообщение отправлено оператору.")
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
            text=f"ℹ️ *Клиент {user.mention_html()} (ID: Ⓝ{user.id}Ⓝ) завершил чат.*",
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
                text="Оператор завершил чат с вами. Если у вас есть другие вопросы, воспользуйтесь главным меню.",
                reply_markup=get_main_keyboard()
            )
        except Exception as e:
            logger.error(f"Could not send message to user {user_to_end_id}: {e}")

        await query.edit_message_text(f"Чат с клиентом ID Ⓝ{user_to_end_id}Ⓝ завершен.")
    else:
        await query.edit_message_text(f"Активный чат с клиентом ID Ⓝ{user_to_end_id}Ⓝ не найден.")
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
            "Использование: Ⓝ/reply <user_id> <текст_ответа>Ⓝ\n"
            "Пример: Ⓝ/reply 123456789 Привет, чем могу помочь?Ⓝ",
            parse_mode="Markdown"
        )
        return

    user_to_reply_id = args[0]
    reply_text = " ".join(args[1:])

    if user_to_reply_id in user_states_data and user_states_data[user_to_reply_id].get("state") == "chat_active":
        try:
            await context.bot.send_message(
                chat_id=int(user_to_reply_id),
                text=f"💬 *Ответ службы поддержки:*\n_{reply_text}_",
                parse_mode="Markdown"
            )
            await update.message.reply_text(f"Ответ отправлен клиенту ID Ⓝ{user_to_reply_id}Ⓝ.")
        except Exception as e:
            await update.message.reply_text(f"Не удалось отправить ответ клиенту ID Ⓝ{user_to_reply_id}Ⓝ: {e}")
            logger.error(f"Error sending reply to user {user_to_reply_id}: {e}")
    else:
        await update.message.reply_text(f"Клиент ID Ⓝ{user_to_reply_id}Ⓝ не находится в активном чате или не найден.")


async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ответ на неизвестные команды."""
    await update.message.reply_text("Извините, я не понял эту команду. Пожалуйста, используйте кнопки или /help.")
    await send_main_menu(update, context)


async def reserve_table_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /reserve."""
    await update.message.reply_text(
        "Извините, функция бронирования столика пока находится в разработке. Пожалуйста, позвоните нам по номеру +7 (918) 582-31-51 для бронирования. Вернуться в главное меню: /start",
        reply_markup=get_main_keyboard()
    )

async def make_order_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /order."""
    await update.message.reply_text("Функция онлайн-заказа пока не доступна.Вы можете просмотреть наше меню, а для заказа свяжитесь с нами напрямую по телефону +7 (918) 582-31-51. Вернуться в главное меню: /start",
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
    review_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_review, pattern="^review$")],
        states={
            REVIEW_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_review)],
        },
        fallbacks=[CommandHandler("cancel", cancel_conversation),
                   CallbackQueryHandler(send_main_menu, pattern="^start$"),
                   CommandHandler("start", start)]
    )
    application.add_handler(review_conv_handler)

    # ConversationHandler для проблем
    problem_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_problem, pattern="^problem$")],
        states={
            PROBLEM_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_problem)],
        },
        fallbacks=[CommandHandler("cancel", cancel_conversation),
                   CallbackQueryHandler(send_main_menu, pattern="^start$"),
                   CommandHandler("start", start)]
    )
    application.add_handler(problem_conv_handler)

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

    # Основные команды
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))

    # Команды из BotFather:
    application.add_handler(CommandHandler("menu", send_main_menu)) # Теперь /menu сразу ведет к категориям
    application.add_handler(CommandHandler("review", start_review))       # Теперь /review сразу начинает отзыв
    # Новые команды, для которых пока нет полной реализации
    application.add_handler(CommandHandler("reserve", reserve_table_command)) # Добавляем новый обработчик
    application.add_handler(CommandHandler("order", make_order_command))     # Добавляем новый обработчик

    application.add_handler(CommandHandler("menu", send_main_menu)) # Добавляем возможность прямого вызова меню
    application.add_handler(CommandHandler("faq", show_faq_questions)) # Добавляем возможность прямого вызова FAQ
    application.add_handler(CommandHandler("review", start_review))
    application.add_handler(CommandHandler("problem", start_problem))
    application.add_handler(CommandHandler("support", start_live_chat))

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

