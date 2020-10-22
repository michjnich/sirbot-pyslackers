import re
import json
import pprint
import logging
import datetime

from slack import methods
from aiohttp import ClientResponseError
from slack.events import Message
from slack.exceptions import SlackAPIError
from asyncpg.exceptions import UniqueViolationError

from .utils import ADMIN_CHANNEL, HELP_FIELD_DESCRIPTIONS

LOG = logging.getLogger(__name__)
STOCK_REGEX = re.compile(
    r"\b(?P<asset_class>[cs])\$(?P<symbol>\^?[A-Z.]{1,5})(-(?P<currency>[A-Z]{3}))?\b"
)
TELL_REGEX = re.compile("tell (<(#|@)(?P<to_id>[A-Z0-9]*)(|.*)?>) (?P<msg>.*)")
FIAT_CURRENCY = {
    "USD": "$",
    "GBP": "£",
    "EUR": "€",
}


def create_endpoints(plugin):
    plugin.on_message("hello", hello, flags=re.IGNORECASE, mention=True)
    plugin.on_message("^tell", tell, flags=re.IGNORECASE, mention=True, admin=True)
    plugin.on_message(".*", mention, flags=re.IGNORECASE, mention=True)
    plugin.on_message(".*", save_in_database, wait=False)
    plugin.on_message(".*", channel_topic, subtype="channel_topic")
    plugin.on_message(
        "^inspect", inspect, flags=re.IGNORECASE, mention=True, admin=True
    )
    plugin.on_message("^help", help_message, flags=re.IGNORECASE, mention=True)
    # stock tickers are 1-5 capital characters, with a dot allowed. To keep
    # this from triggering with random text we require a leading '$'
    plugin.on_message(STOCK_REGEX.pattern, stock_quote, wait=False)
    plugin.on_message(
        "^channels", channels, flags=re.IGNORECASE, mention=True, admin=True
    )
    plugin.on_message("^cleanup", cleanup, flags=re.IGNORECASE, mention=True)


async def stock_quote(message, app):
    stocks = app["plugins"]["stocks"]
    match = STOCK_REGEX.search(message.get("text", ""))
    if not match:
        return

    asset_class, symbol, currency = (
        match.group("asset_class"),
        match.group("symbol"),
        match.group("currency"),
    )

    currency = match.group("currency") if match.group("currency") in FIAT_CURRENCY.keys() else "USD"
    currency_symbol = FIAT_CURRENCY[currency]
    LOG.debug(
        "Fetching stock quotes for symbol %s in asset class %s", symbol, asset_class
    )

    if asset_class == "c":
        LOG.debug(f"Fetching a crypto quote, setting {currency} as the pair's quote price.")
        symbol = f"{symbol}-{currency}"

    response = message.response()
    try:
        quote = await stocks.price(symbol)
        LOG.debug("Quote from API: %s", quote)
    except ClientResponseError as e:
        if e.status == 404:
            response["text"] = f"Unable to find ticker {symbol}"
        else:
            LOG.exception("Error retrieving stock quotes.")
            response["text"] = "Unable to retrieve quotes right now."
    else:
        if quote is None:
            response["text"] = f"Unable to find ticker '{symbol}'"
        else:
            color = "gray"
            if quote.change > 0:
                color = "good"
            elif quote.change < 0:
                color = "danger"

            response.update(
                attachments=[
                    {
                        "color": color,
                        "title": f"{quote.symbol} ({quote.company}): {currency_symbol}{quote.price:,.4f}",
                        "title_link": f"https://finance.yahoo.com/quote/{quote.symbol}",
                        "fields": [
                            {
                                "title": "Change",
                                "value": f"{currency_symbol}{quote.change:,.4f} ({quote.change_percent:,.4f}%)",
                                "short": True,
                            },
                            {
                                "title": "Volume",
                                "value": f"{quote.volume:,}",
                                "short": True,
                            },
                            {
                                "title": "Open",
                                "value": f"{currency_symbol}{quote.market_open:,.4f}",
                                "short": True,
                            },
                            {
                                "title": "Close",
                                "value": f"{currency_symbol}{quote.market_close:,.4f}",
                                "short": True,
                            },
                            {
                                "title": "Low",
                                "value": f"{currency_symbol}{quote.low:,.4f}",
                                "short": True,
                            },
                            {
                                "title": "High",
                                "value": f"{currency_symbol}{quote.high:,.4f}",
                                "short": True,
                            },
                        ],
                        "footer_icon": quote.logo,
                        "ts": int(quote.time.timestamp()),
                    }
                ]
            )

    await app["plugins"]["slack"].api.query(
        url=methods.CHAT_POST_MESSAGE, data=response
    )


async def hello(message, app):
    response = message.response()
    response["text"] = "Hello <@{user}>".format(user=message["user"])
    await app["plugins"]["slack"].api.query(
        url=methods.CHAT_POST_MESSAGE, data=response
    )


async def help_message(message, app):
    response = message.response()
    response["text"] = "Sir Bot-a-lot help"
    response["attachments"] = [{"color": "good", "fields": HELP_FIELD_DESCRIPTIONS}]

    await app["plugins"]["slack"].api.query(
        url=methods.CHAT_POST_MESSAGE, data=response
    )


async def tell(message, app):
    match = TELL_REGEX.match(message["text"])
    response = message.response()

    if match:
        to_id = match.group("to_id")
        msg = match.group("msg")

        if to_id.startswith(("C", "U")):
            response["text"] = msg
            response["channel"] = to_id
        else:
            response["text"] = "Sorry I can not understand the destination."
    else:
        response["text"] = "Sorry I can not understand"

    await app["plugins"]["slack"].api.query(
        url=methods.CHAT_POST_MESSAGE, data=response
    )


async def mention(message, app):
    try:
        if message["user"] != app["plugins"]["slack"].bot_user_id:
            await app["plugins"]["slack"].api.query(
                url=methods.REACTIONS_ADD,
                data={
                    "name": "sirbot",
                    "channel": message["channel"],
                    "timestamp": message["ts"],
                },
            )
    except SlackAPIError as e:
        if e.error != "already_reacted":
            raise


async def save_in_database(message, app):
    if "pg" in app["plugins"]:
        LOG.debug('Saving message "%s" to database.', message["ts"])

        if message["ts"]:  # We sometimes receive message without a timestamp. See #45
            try:
                async with app["plugins"]["pg"].connection() as pg_con:
                    await pg_con.execute(
                        """INSERT INTO slack.messages (id, text, "user", channel, raw, time)
                        VALUES ($1, $2, $3, $4, $5, $6)""",
                        message["ts"],
                        message.get("text"),
                        message.get("user"),
                        message.get("channel"),
                        dict(message),
                        datetime.datetime.fromtimestamp(
                            int(message["ts"].split(".")[0])
                        ),
                    )
            except UniqueViolationError:
                LOG.debug('Message "%s" already in database.', message["ts"])


async def channel_topic(message, app):

    if (
        message["user"] not in app["plugins"]["slack"].admins
        and message["user"] != app["plugins"]["slack"].bot_user_id
    ):

        async with app["plugins"]["pg"].connection() as pg_con:
            channel = await pg_con.fetchrow(
                """SELECT raw FROM slack.channels WHERE id = $1""", message["channel"]
            )
            LOG.debug(channel)
            if channel:
                old_topic = channel["raw"]["topic"]["value"]
            else:
                old_topic = "Original topic not found"

        response = Message()
        response["channel"] = ADMIN_CHANNEL
        response["attachments"] = [
            {
                "fallback": "Channel topic changed notice: old topic",
                "title": f'<@{message["user"]}> changed <#{message["channel"]}> topic.',
                "fields": [
                    {"title": "Previous topic", "value": old_topic},
                    {"title": "New topic", "value": message["topic"]},
                ],
            }
        ]

        if channel:
            response["attachments"][0]["callback_id"] = "topic_change"
            response["attachments"][0]["actions"] = [
                {
                    "name": "validate",
                    "text": "Validate",
                    "style": "primary",
                    "type": "button",
                },
                {
                    "name": "revert",
                    "text": "Revert",
                    "style": "danger",
                    "value": json.dumps(
                        {"channel": message["channel"], "old_topic": old_topic}
                    ),
                    "type": "button",
                },
            ]

        await app["plugins"]["slack"].api.query(
            url=methods.CHAT_POST_MESSAGE, data=response
        )


async def inspect(message, app):
    if (
        message["channel"] != ADMIN_CHANNEL
        or "text" not in message
        or not message["text"]
    ):
        return

    response = message.response()
    match = re.search("<@(.*)>", message["text"])

    if match:
        user_id = match.group(1)

        async with app["plugins"]["pg"].connection() as pg_con:
            data = await pg_con.fetchrow(
                """SELECT raw, join_date FROM slack.users WHERE id = $1""", user_id
            )

        if data:
            user = data["raw"]
            user["join_date"] = data["join_date"].isoformat()
        else:
            data = await app["plugins"]["slack"].api.query(
                url=methods.USERS_INFO, data={"user": user_id}
            )
            user = data["user"]

        response[
            "text"
        ] = f"<@{user_id}> profile information \n```{pprint.pformat(user)}```"
    else:
        response["text"] = f"Sorry I couldn't figure out which user to inspect"

    await app["plugins"]["slack"].api.query(
        url=methods.CHAT_POST_MESSAGE, data=response
    )


async def channels(message, app):
    if message["channel"] == ADMIN_CHANNEL and "text" in message and message["text"]:
        async with app["plugins"]["pg"].connection() as pg_con:
            rows = await pg_con.fetch(
                """with channels as (
  SELECT DISTINCT ON (channels.id) channels.id,
                                   channels.raw ->> 'name' as name,
                                   messages.time,
                                   age(messages.time)      as age
  FROM slack.channels
         LEFT JOIN slack.messages ON messages.channel = slack.channels.id
  WHERE (channels.raw ->> 'is_archived')::boolean is FALSE
  ORDER BY channels.id, messages.time DESC
)
SELECT * FROM channels WHERE age > interval '31 days'
"""
            )

        if rows:
            text = f"""```{pprint.pformat([dict(row) for row in rows])}```"""
        else:
            text = f"""There is no channel without messages in the last 31 days"""

        response = message.response()
        response["text"] = text

        await app["plugins"]["slack"].api.query(
            url=methods.CHAT_POST_MESSAGE, data=response
        )


async def cleanup(message, app):

    if (
        message["channel"] != ADMIN_CHANNEL
        or "text" not in message
        or not message["text"]
    ):
        return

    response = message.response()
    match = re.search("<@(.*)>", message["text"])

    if match:
        user_id = match.group(1)

        async with app["plugins"]["pg"].connection() as pg_con:
            messages = await pg_con.fetchrow(
                """SELECT count(id) FROM slack.messages WHERE "user" = $1""", user_id
            )

        response["channel"] = ADMIN_CHANNEL
        response["attachments"] = [
            {
                "fallback": "User cleanup",
                "title": f'Confirm cleanup of <@{user_id}> {messages["count"]} messages.',
                "callback_id": "user_cleanup",
                "actions": [
                    {
                        "name": "cancel",
                        "text": "Cancel",
                        "style": "primary",
                        "type": "button",
                    },
                    {
                        "name": "confirm",
                        "text": "Burn baby burn !",
                        "style": "danger",
                        "type": "button",
                        "value": user_id,
                    },
                ],
            }
        ]

        await app["plugins"]["slack"].api.query(
            url=methods.CHAT_POST_MESSAGE, data=response
        )
