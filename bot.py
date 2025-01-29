import os
from dotenv import load_dotenv
import time
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    CallbackQueryHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
import asyncio
import pytz

# Carregar variáveis de ambiente do arquivo .env
load_dotenv()

API_ID = os.getenv('API_ID')
API_HASH = os.getenv('API_HASH')
BOT_TOKEN = os.getenv('BOT_TOKEN')
YOUR_PHONE = os.getenv('YOUR_PHONE')
TIMEZONE = os.getenv('TIMEZONE', 'America/Sao_Paulo')

LOCAL_TIMEZONE = pytz.timezone(TIMEZONE)

if not all([API_ID, API_HASH, BOT_TOKEN, YOUR_PHONE]):
    raise ValueError("Por favor, defina todas as variáveis de ambiente: API_ID, API_HASH, BOT_TOKEN, YOUR_PHONE.")

client = TelegramClient('session_name', API_ID, API_HASH)

# Estados da conversação
LINK, INTERVAL = range(2)

# Armazenar as configurações
settings = {
    'message_link': None,
    'referral_link': None,
}

# Armazenar o job atual
current_job = None

# Estatísticas do bot
statistics = {
    'messages_sent': 0,
    'active_campaigns': 0,
    'total_campaigns': 0,
    'groups_forwarded': 0,
    'average_execution_time': 0,
}

participants_cache = {}
group_list = []

# Autenticação para enviar mensagens
async def authenticate():
    await client.start()
    if not await client.is_user_authorized():
        try:
            await client.send_code_request(YOUR_PHONE)
            code = input('Digite o código recebido: ')
            await client.sign_in(YOUR_PHONE, code)
        except SessionPasswordNeededError:
            password = input('Digite sua senha: ')
            await client.sign_in(YOUR_PHONE, password)

# Função para obter participantes com cache
async def get_participants(group):
    if group.id not in participants_cache:
        participants_cache[group.id] = await client.get_participants(group)
    return participants_cache[group.id]

# Função para pré-carregar os grupos
async def preload_groups():
    global group_list
    group_list.clear()
    async for dialog in client.iter_dialogs():
        if dialog.is_group and not dialog.archived:
            group_list.append(dialog.entity)
    print(f"{len(group_list)} grupos pré-carregados.")

# Função para encaminhar a mensagem com contagem de sucesso
async def forward_message_with_formatting(context: ContextTypes.DEFAULT_TYPE):
    start_time = time.time()
    successful_tasks = 0
    try:
        if settings['message_link'] is None:
            print("Nenhum link de mensagem configurado para encaminhar.")
            return

        parts = settings['message_link'].split('/')
        chat = parts[-2]
        message_id = int(parts[-1])

        message = await client.get_messages(chat, ids=message_id)
        me = await client.get_me()
        tasks = []

        for group in group_list:
            participants = await get_participants(group)
            if any(participant.id == me.id for participant in participants):
                tasks.append(client.forward_messages(group, message))

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            successful_tasks = sum(1 for result in results if not isinstance(result, Exception))
            statistics['messages_sent'] += successful_tasks
            statistics['groups_forwarded'] += len(group_list)
            print(f"{successful_tasks} mensagens encaminhadas com sucesso.")
        else:
            print("Nenhuma mensagem foi encaminhada.")
    except Exception as e:
        print(f"Erro ao encaminhar mensagem: {e}")
    finally:
        end_time = time.time()
        duration = end_time - start_time
        statistics['average_execution_time'] = duration
        print(f"Duração total do job: {duration:.2f} segundos")

# Função para iniciar a campanha
async def start_campaign(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global current_job, statistics

    if current_job is not None:
        current_job.schedule_removal()
        current_job = None
        settings['message_link'] = None
        statistics['active_campaigns'] -= 1
        print("Campanha anterior cancelada.")

    statistics['active_campaigns'] += 1
    statistics['total_campaigns'] += 1
    query = update.callback_query
    await query.answer()
    await query.message.edit_text('Envie o link da mensagem que deseja encaminhar:')
    print("Esperando o link da mensagem.")

    return LINK

# Função para definir o link da mensagem
async def set_message_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return ConversationHandler.END

    settings['message_link'] = update.message.text
    await update.message.reply_text(f"Link configurado: {settings['message_link']}\nAgora envie o intervalo em minutos:")

    return INTERVAL

# Função para definir o intervalo
async def set_interval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return ConversationHandler.END

    try:
        interval = int(update.message.text)
    except ValueError:
        await update.message.reply_text("Por favor, insira um número válido.")
        return INTERVAL

    global current_job
    if current_job is not None:
        current_job.schedule_removal()

    await preload_groups()

    current_job = context.application.job_queue.run_repeating(
        forward_message_with_formatting,
        interval=interval * 60,
        first=0
    )

    await update.message.reply_text(f"Configuração realizada com intervalo de {interval} minutos.")
    return ConversationHandler.END

# Função para cancelar o encaminhamento
async def cancel_campaign(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global current_job, statistics
    if current_job is not None:
        current_job.schedule_removal()
        current_job = None
        settings['message_link'] = None
        statistics['active_campaigns'] -= 1
        await update.callback_query.answer()
        await update.callback_query.message.edit_text("Campanha cancelada.")
    else:
        await update.callback_query.answer()
        await update.callback_query.message.edit_text("Nenhuma campanha ativa para cancelar.")

# Função para exibir estatísticas do bot
async def show_statistics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()

    active_campaigns = 1 if current_job is not None else 0
    last_time = datetime.now(LOCAL_TIMEZONE).strftime('%d/%m/%Y %H:%M:%S')

    stats_message = (
        "📊 **Estatísticas do Bot** 📊\n\n"
        f"💬 **Mensagens enviadas:** {statistics['messages_sent']}\n"
        f"📈 **Campanhas ativas:** {active_campaigns}\n"
        f"📂 **Total de campanhas:** {statistics['total_campaigns']}\n"
        f"📤 **Grupos encaminhados:** {statistics['groups_forwarded']}\n"
        f"🕒 **Tempo médio de execução:** {statistics['average_execution_time']:.2f} segundos\n"
        f"📅 **Última campanha:** {last_time}\n"
        f"⏰ **Hora local:** {datetime.now(LOCAL_TIMEZONE).strftime('%d/%m/%Y %H:%M:%S')}\n"
    )
    await update.callback_query.message.edit_text(stats_message, parse_mode='Markdown')

# Função para definir o link de referência
async def set_referral_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    user_id = update.callback_query.from_user.id
    settings['referral_link'] = f"https://t.me/SEUBOT?start=ref_{user_id}"
    await update.callback_query.message.reply_text(f"Seu link de referência: {settings['referral_link']}")

# Função para responder ao comando /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    now = datetime.now()
    welcome_message = (
        f"BEM-VINDO AO BOT!\n\n"
        f"Data e Hora de Entrada: {now.strftime('%d/%m/%Y %H:%M:%S')}\n"
        f"Seu ID: {user_id}\n"
        "👉 Toque no botão abaixo para começar sua jornada!"
    )

    keyboard = [
        [InlineKeyboardButton("🚀 INICIAR UMA NOVA CAMPANHA 🚀", callback_data='create_campaign')],
        [InlineKeyboardButton("🛑 CANCELAR CAMPANHA 🛑", callback_data='cancel_campaign')],
        [InlineKeyboardButton("📊 VER ESTATÍSTICAS DO BOT 📊", callback_data='statistics')],
        [InlineKeyboardButton("LINK DE REFERÊNCIA", callback_data='referral')],
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(welcome_message, reply_markup=reply_markup)

# Função principal para configurar o bot
def main():
    loop = asyncio.get_event_loop()

    try:
        loop.run_until_complete(authenticate())
        print("BOT CONECTADO")

        application = ApplicationBuilder().token(BOT_TOKEN).build()

        campaign_handler = ConversationHandler(
            entry_points=[CallbackQueryHandler(start_campaign, pattern='create_campaign')],
            states={
                LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_message_link)],
                INTERVAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_interval)],
            },
            fallbacks=[CommandHandler('cancel', cancel_campaign)],
        )

        application.add_handler(CommandHandler("start", start))
        application.add_handler(CallbackQueryHandler(show_statistics, pattern='statistics'))
        application.add_handler(CallbackQueryHandler(set_referral_link, pattern='referral'))
        application.add_handler(CallbackQueryHandler(cancel_campaign, pattern='cancel_campaign'))
        application.add_handler(campaign_handler)

        application.run_polling()
    finally:
        loop.run_until_complete(client.disconnect())
        loop.close()

if __name__ == "__main__":
    main()
