import asyncio
import secrets
import string
import traceback
from os import getenv, environ

import aiofiles
from deta import Base
from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse

from utils import get, escape_symbols

from twitch import Twitch

twitch = Twitch(get("Client_Id"), get("Client_Secret"))

from telegram import Telegram

telegram = Telegram(get("Telegram_Token"))


app = FastAPI()
app.mount("/static", StaticFiles(directory="./static"), name="static")

config = Base(
    "dev_config" if "ngrok" in getenv("DETA_SPACE_APP_HOSTNAME") else "config"
)
if not getenv("secret", None):
    secret = config.get("secret")
    if not secret:
        alphabet = string.ascii_letters + string.digits
        secret = "".join(secrets.choice(alphabet) for i in range(99))
        config.put(secret, "secret")
    else:
        secret = secret["value"]
    environ["secret"] = secret

    global_settings = config.get("global")
    if not global_settings:
        config.put(
            {
                "message": {
                    "stream.online": "*Начался стрим на канале ${username}*\n\n*Название стрима:* ${title}\n*Категория:* ${category}\n\n${stream_url}",
                    "stream.offline": "*Закончился стрим на канале ${username}*\n\nПродолжительность стрима: ${uptime}",
                    "channel.update": "*Обновление на канале ${username}*\n\n*Новое название стрима:* ${new_title}\n*Новая категория:* ${new_category}\n*Стрим идёт:* ${uptime}\n*Категории:* ${categories}\n\n${stream_url}",
                },
                "screenshot": {
                    "stream.online": True,
                    "stream.offline": True,
                    "channel.update": True,
                },
                "disable_preview": {
                    "stream.online": False,
                    "stream.offline": False,
                    "channel.update": False,
                },
                "disable_notifications": {
                    "stream.online": False,
                    "stream.offline": False,
                    "channel.update": False,
                },
            },
            "global",
        )


@app.get("/")
async def index():
    # Переписать?
    if not telegram.token and telegram.get_telegram_token():
        await telegram.subscribe()
    if (
        not twitch.client_id
        or not twitch.client_secret
        and twitch.get_client_id_and_client_secret()
    ):
        await twitch.subscribe()
    async with aiofiles.open("index.html", "r") as f:
        return HTMLResponse(await f.read())


@app.post("/twitchwebhook")
async def twitchwebhook(request: Request, response: Response):
    try:
        return await twitch.process_event(request, response)
    except Exception as e:
        name = str(e)
        text = "".join(traceback.format_tb(e.__traceback__))
        print(name, "\n", text)
        chat_id = get("Telegram_Id")
        if chat_id:
            await telegram.send_message(
                chat_id,
                f"Exception occurred: {escape_symbols(name)}\\.\n```{escape_symbols(text)}```",
                parse_mode="MarkdownV2",
            )
    finally:
        response.status_code = 200
        response.init_headers()
        return response


@app.post("/telegramwebhook")
async def telegramwebhook(request: Request, response: Response):
    try:
        await telegram.process_event(request)
    except Exception as e:
        name = str(e)
        text = "".join(traceback.format_tb(e.__traceback__))
        print(name, "\n", text)
        chat_id = get("Telegram_Id")
        if chat_id:
            await telegram.send_message(
                chat_id,
                f"Exception occurred: {escape_symbols(name)}\\.\n```{escape_symbols(text)}```",
                parse_mode="MarkdownV2",
            )
    finally:
        response.status_code = 200
        response.init_headers()
        return response

@app.post("/__space/v0/actions")
async def space_actions(request: Request):
    data = await request.json()
    if data["event"]["id"] == "check":
        await twitch.subscribe()
        await telegram.subscribe()


if "ngrok" in getenv("DETA_SPACE_APP_HOSTNAME") and False:
    loop = asyncio.get_event_loop()
    asyncio.set_event_loop(loop)
    loop.create_task(space_actions())
