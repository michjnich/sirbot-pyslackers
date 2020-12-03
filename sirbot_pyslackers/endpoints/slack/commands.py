import json
import logging

from slack import methods
from slack.events import Message

from .utils import HELP_FIELD_DESCRIPTIONS

LOG = logging.getLogger(__name__)


def create_endpoints(plugin):
    plugin.on_command("/admin", tell_admin)
    plugin.on_command("/sirbot", sirbot_help)
    plugin.on_command("/howtoask", ask)
    plugin.on_command("/justask", just_ask)
    plugin.on_command("/pypi", pypi_search)
    plugin.on_command("/sponsors", sponsors)
    plugin.on_command("/snippet", snippet)
    plugin.on_command("/report", report)


async def just_ask(command, app):
    slack = app.plugins["slack"]
    response = Message()
    response["channel"] = command["channel_id"]
    response["unfurl_links"] = False

    response["text"] = (
        "If you have a question, please just ask it. Please do not ask for topic experts;  "
        "do not DM or ping random users. We cannot begin to answer a question until we actually get a question. \n\n"
        "<http://sol.gfxile.net/dontask.html|*Asking Questions*>"
    )

    await slack.api.query(url=methods.CHAT_POST_MESSAGE, data=response)


async def sirbot_help(command, app):
    slack = app.plugins["slack"]
    response = Message()
    response["channel"] = command["channel_id"]
    response["unfurl_links"] = False

    response["text"] = "Community Slack Commands"
    response["attachments"] = [{"color": "good", "fields": HELP_FIELD_DESCRIPTIONS}]

    await slack.api.query(url=methods.CHAT_POST_MESSAGE, data=response)


async def ask(command, app):
    slack = app.plugins["slack"]
    response = Message()
    response["channel"] = command["channel_id"]
    response["unfurl_links"] = True

    response["text"] = (
        "Knowing how to ask a good question is a highly invaluable skill that "
        "will benefit you greatly in any career. Two good resources for "
        "suggestions and strategies to help you structure and phrase your "
        "question to make it easier for those here to understand your problem "
        "and help you work to a solution are:\n\n"
        "• <https://www.mikeash.com/getting_answers.html>\n"
        "• <https://stackoverflow.com/help/how-to-ask>\n"
    )

    await slack.api.query(url=methods.CHAT_POST_MESSAGE, data=response)


async def sponsors(command, app):
    slack = app.plugins["slack"]
    response = Message()
    response["channel"] = command["channel_id"]
    response["unfurl_links"] = False

    response["text"] = (
        "Thanks to our sponsors, <https://platform.sh|Platform.sh> and "
        "<https://sentry.io|Sentry> for providing hosting & services helping us "
        "host our <https://www.pyslackers.com|website> and Sir Bot-a-lot.\n"
        "If you are planning on using <https://sentry.io|Sentry> please use our <https://sentry.io/?utm_source=referral&utm_content=pyslackers&utm_campaign=community|"
        "referral code>."
    )

    await slack.api.query(url=methods.CHAT_POST_MESSAGE, data=response)


async def report(command, app):

    data = {
        "trigger_id": command["trigger_id"],
        "dialog": {
            "callback_id": "report",
            "title": "Report user",
            "elements": [
                {
                    "label": "Offending user",
                    "name": "user",
                    "type": "select",
                    "data_source": "users",
                },
                {
                    "label": "Channel",
                    "name": "channel",
                    "type": "select",
                    "data_source": "channels",
                    "optional": True,
                },
                {
                    "label": "Comment",
                    "name": "comment",
                    "type": "textarea",
                    "value": command["text"],
                },
            ],
        },
    }

    await app.plugins["slack"].api.query(url=methods.DIALOG_OPEN, data=data)


async def pypi_search(command, app):
    response = Message()
    response["channel"] = command["channel_id"]

    if not command["text"]:
        response["response_type"] = "ephemeral"
        response["text"] = "Please enter the package name you wish to find"
    else:
        results = await app.plugins["pypi"].search(command["text"])
        if results:
            response["response_type"] = "in_channel"
            response["attachments"] = [
                {
                    "title": f'<@{command["user_id"]}> Searched PyPi for `{command["text"]}`',
                    "fallback": f'Pypi search of {command["text"]}',
                    "fields": [],
                }
            ]

            for result in results[:3]:
                response["attachments"][0]["fields"].append(
                    {
                        "title": result["name"],
                        "value": f'<{app.plugins["pypi"].PROJECT_URL.format(result["name"])}|{result["summary"]}>',
                    }
                )

            if len(results) == 4:
                response["attachments"][0]["fields"].append(
                    {
                        "title": results[3]["name"],
                        "value": f'<{app.plugins["pypi"].PROJECT_URL.format(results[3]["name"])}|{results[3]["summary"]}>',
                    }
                )
            elif len(results) > 3:
                response["attachments"][0]["fields"].append(
                    {
                        "title": "More results",
                        "value": f'<{app.plugins["pypi"].RESULT_URL.format(command["text"])}|'
                        f"{len(results) - 3} more results..>",
                    }
                )

        else:
            response["response_type"] = "ephemeral"
            response[
                "text"
            ] = f"Could not find anything on PyPi matching `{command['text']}`"

    await app.plugins["slack"].api.query(url=methods.CHAT_POST_MESSAGE, data=response)


async def snippet(command, app):
    """Post a message to the current channel about using snippets and backticks to visually
    format code."""
    response = Message()
    response["channel"] = command["channel_id"]
    response["unfurl_links"] = False

    response["text"] = (
        "Please use the snippet feature, or backticks, when sharing code. \n"
        "To include a snippet, click the :paperclip: on the left and hover over "
        "`Create new...` then select `Code or text snippet`.\n"
        "By wrapping the text/code with backticks (`) you get:\n"
        "`text formatted like this`\n"
        "By wrapping a multiple line block with three backticks (```) you can get:\n"
    )

    await app.plugins["slack"].api.query(url=methods.CHAT_POST_MESSAGE, data=response)

    response["text"] = (
        "```\n"
        "A multiline codeblock\nwhich is great for short snippets!\n"
        "```\n"
        "For more information on snippets, click "
        "<https://get.slack.help/hc/en-us/articles/204145658-Create-a-snippet|here>.\n"
        "For more information on inline code formatting with backticks click "
        "<https://get.slack.help/hc/en-us/articles/202288908-Format-your-messages#inline-code|here>."
    )

    await app.plugins["slack"].api.query(url=methods.CHAT_POST_MESSAGE, data=response)


async def tell_admin(command, app):

    data = {
        "trigger_id": command["trigger_id"],
        "dialog": {
            "callback_id": "tell_admin",
            "title": "Message the admin team",
            "elements": [
                {
                    "label": "Message",
                    "name": "message",
                    "type": "textarea",
                    "value": command["text"],
                }
            ],
        },
    }

    await app.plugins["slack"].api.query(url=methods.DIALOG_OPEN, data=data)
