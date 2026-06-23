import datetime
import html
import re

import aiogram.types as agtypes

from .const import MsgType


def get_user_locale(user: agtypes.User | agtypes.Chat | None) -> str | None:
    """
    Return Telegram user's locale normalized for config lookup.
    """
    if not user:
        return None

    locale = getattr(user, 'language_code', None)
    return locale.lower().replace('-', '_') if locale else None


def localized_cfg(bot, key: str, user: agtypes.User | agtypes.Chat | None) -> str:
    """
    Read a config value localized by Telegram user's locale, with fallback.
    """
    locale = get_user_locale(user)
    messages = bot.cfg.messages_by_locale

    if locale:
        for candidate in (locale, locale.split('_', maxsplit=1)[0]):
            if candidate in messages and key in messages[candidate]:
                return messages[candidate][key]

    return getattr(bot.cfg, key)


async def make_user_info(user: agtypes.User, bot=None, tguser=None) -> str:
    """
    Text representation of a user
    """
    name = f'<b>{html.escape(user.full_name)}</b>'
    username = f'@{user.username}' if user.username else 'No username'
    userid = f'<b>ID</b>: <code>{user.id}</code>'
    fields = [name, username, userid]

    if lang := getattr(user, 'language_code', None):
        fields.append(f'Language code: {lang}')
    if premium := getattr(user, 'is_premium', None):
        fields.append(f'Premium: {premium}')

    if bot:
        uinfo = await bot.get_chat(user.id)
        fields.append(f'<b>Bio</b>: {html.escape(uinfo.bio)}' if uinfo.bio else 'No bio')

        if uinfo.active_usernames and len(uinfo.active_usernames) > 1:
            fields.append(f'Active usernames: @{", @".join(uinfo.active_usernames)}')

    if tguser and tguser.subject:
        fields.append(f'<b>Subject</b>: {tguser.subject}')

    return '\n\n'.join(fields)


def make_short_user_info(user: agtypes.User | None=None, tguser=None) -> str:
    """
    Short text representation of a user
    """
    if user:
        user_id = user.id
    elif tguser:
        user_id = tguser.user_id
        user = tguser

    fullname = html.escape(user.full_name or '')
    tech_part = f'@{user.username}, id {user_id}' if user.username else f'id {user_id}'
    return f'{fullname} ({tech_part})'


def determine_msg_type(msg: agtypes.Message) -> str:
    """
    Determine a type of the message by inspecting its content
    """
    if msg.photo:
        return MsgType.PHOTO
    elif msg.video:
        return MsgType.VIDEO
    elif msg.animation:
        return MsgType.ANIMATION
    elif msg.sticker:
        return MsgType.STICKER
    elif msg.audio:
        return MsgType.AUDIO
    elif msg.voice:
        return MsgType.VOICE
    elif msg.document:
        return MsgType.DOCUMENT
    elif msg.video_note:
        return MsgType.VIDEO_NOTE
    elif msg.contact:
        return MsgType.CONTACT
    elif msg.location:
        return MsgType.LOCATION
    elif msg.venue:
        return MsgType.VENUE
    elif msg.poll:
        return MsgType.POLL
    elif msg.dice:
        return MsgType.DICE
    else:
        return MsgType.REGULAR_OR_OTHER


def _clean_log_value(value) -> str:
    """
    Keep user-provided log fields on one line.
    """
    return re.sub(r'\s+', ' ', str(value or '')).strip()


def _message_log_text(msg: agtypes.Message, msg_type: str) -> str:
    """
    Return a compact content summary for a Telegram message.
    """
    if text := msg.text or msg.caption:
        return f'text="{_clean_log_value(text)}"'

    if msg_type in (MsgType.document, MsgType.audio, MsgType.video):
        media = getattr(msg, msg_type)
        return f'file="{_clean_log_value(getattr(media, "file_name", ""))}"'

    if msg_type == MsgType.photo:
        return f'photos={len(msg.photo)}'
    if msg_type == MsgType.sticker:
        return f'sticker="{_clean_log_value(msg.sticker.emoji)}"'
    if msg_type == MsgType.contact:
        return f'contact_phone="{_clean_log_value(msg.contact.phone_number)}"'
    if msg_type == MsgType.location:
        return f'location="{msg.location.latitude},{msg.location.longitude}"'
    if msg_type == MsgType.venue:
        return f'venue="{_clean_log_value(msg.venue.title)}"'
    if msg_type == MsgType.poll:
        return f'poll="{_clean_log_value(msg.poll.question)}"'
    if msg_type == MsgType.dice:
        return f'dice="{_clean_log_value(msg.dice.emoji)}:{msg.dice.value}"'

    return 'text=""'


def format_user_message_log(msg: agtypes.Message) -> str:
    """
    Format a user message for the application log.
    """
    user = msg.from_user or msg.chat
    msg_type = determine_msg_type(msg)
    user_info = make_short_user_info(user=user)
    content = _message_log_text(msg, msg_type)
    return (
        f'user_message message_id={msg.message_id} '
        f'user="{_clean_log_value(user_info)}" '
        f'chat_id={msg.chat.id} '
        f'date="{msg.date.isoformat()}" '
        f'type={msg_type} '
        f'forward={"yes" if msg.forward_origin else "no"} '
        f'{content}'
    )


async def destruct_messages(bots: list) -> None:
    """
    Delete messages for users, if a bot is set up to do so
    """
    for bot in bots:
        destructed = 0

        for var in 'destruct_user_messages_for_user', 'destruct_bot_messages_for_user':
            if val := getattr(bot.cfg, var):
                error_reported = False
                by_bot = var == 'destruct_bot_messages_for_user'
                before = datetime.datetime.utcnow() - datetime.timedelta(hours=val)
                msgs = await bot.db.msgtodel.get_many(before, by_bot)

                for msg in msgs:
                    try:
                        await bot.delete_message(msg.chat_id, msg.msg_id)
                        destructed += 1
                    except Exception as exc:
                        if not error_reported:
                            await bot.log_error(exc)
                        error_reported = True

                await bot.db.msgtodel.remove(msgs)

        if destructed:
            await bot.log(f'Messages destructed: {destructed}')


async def save_for_destruction(msg, bot, chat_id=None):
    """
    Save msg id to destruct the msg later, if required
    """
    if not msg:
        return

    if chat_id:  # special case when there is no full msg object
        if bot.cfg.destruct_bot_messages_for_user:
            await bot.db.msgtodel.add(msg, chat_id=chat_id)
        return

    var = 'destruct_user_messages_for_user'
    if msg.from_user.is_bot:
        var = 'destruct_bot_messages_for_user'

    if getattr(bot.cfg, var):
        await bot.db.msgtodel.add(msg)
