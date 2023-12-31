import asyncio
from os import getenv, environ
from pprint import pprint
import json
from functools import partial
from time import time

from aiohttp import ClientResponse
from fastapi import Request

from main import twitch
from detabase import Base
from utils import escape_symbols, get, get_session, format_text

config = Base(
    "dev_config" if "ngrok" in getenv("DETA_SPACE_APP_HOSTNAME") else "config"
)


class Telegram:
    def __init__(self, token: str) -> None:
        # https://core.telegram.org/bots/api
        self.token = token
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        self.session = None

    def get_telegram_token(self) -> bool:
        self.token = get("Telegram_Token")
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        return bool(self.token)

    async def is_subscribed(self) -> bool:
        # https://core.telegram.org/bots/api#getwebhookinfo
        response = await self.make_api_request("GET", "getWebhookInfo")
        json = await response.json()
        return bool(json["result"]["url"])

    async def subscribe(self) -> bool:
        # https://core.telegram.org/bots/api#setwebhook
        if not self.token and not self.get_telegram_token():
            return False
        elif (
            time()
            - int(
                getenv(
                    "telegram_since_last_check",
                    (
                        await config.get(
                            "telegram_since_last_check", {"value": int(time()) - 14401}
                        )
                    )["value"],
                )
            )
        ) < 14400:
            return True
        elif await self.is_subscribed():
            await config.put({"key": "telegram_since_last_check", "value": int(time())})
            environ["telegram_since_last_check"] = str(int(time()))
            return True
        response = await self.make_api_request(
            "GET",
            "setWebHook",
            params={
                "url": f"https://{getenv('DETA_SPACE_APP_HOSTNAME')}/telegramwebhook"
            },
        )
        await self.set_commands()
        await config.put({"key": "telegram_since_last_check", "value": int(time())})
        environ["telegram_since_last_check"] = str(int(time()))
        return await response.json()

    async def send_message(
        self,
        chat_id: int,
        text: str,
        *,
        photo: str = None,
        parse_mode: str = None,
        disable_web_page_preview: bool = False,
        disable_notification: bool = False,
        reply_markup: dict = None,
    ):
        if not self.token and not self.get_telegram_token():
            return False
        json = {"chat_id": chat_id}
        if photo:
            json["photo"] = photo
            json["caption"] = text
        else:
            json["text"] = text
        if parse_mode:
            json["parse_mode"] = parse_mode
        if disable_web_page_preview:
            json["disable_web_page_preview"] = disable_web_page_preview
        if disable_notification:
            json["disable_notification"] = disable_notification
        if reply_markup:
            json["reply_markup"] = reply_markup
        if not photo:
            # https://core.telegram.org/bots/api#sendmessage
            response = await self.make_api_request(
                "POST",
                "sendMessage",
                json=json,
            )
        else:
            # https://core.telegram.org/bots/api#sendphoto
            response = await self.make_api_request(
                "POST",
                "sendPhoto",
                json=json,
            )
        json = await response.json()
        if not json["ok"]:
            pprint(json)

    async def edit_message(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        *,
        parse_mode: str = None,
        disable_web_page_preview: bool = False,
        disable_notification: bool = False,
        reply_markup: dict = None,
    ):
        # https://core.telegram.org/bots/api#editmessagetext
        json = {"chat_id": chat_id, "message_id": message_id, "text": text}
        if parse_mode:
            json["parse_mode"] = parse_mode
        if disable_web_page_preview:
            json["disable_web_page_preview"] = disable_web_page_preview
        if disable_notification:
            json["disable_notification"] = disable_notification
        if reply_markup:
            json["reply_markup"] = reply_markup
        response = await self.make_api_request(
            "POST",
            "editMessageText",
            json=json,
        )
        json = await response.json()
        if not json["ok"]:
            pprint(json)

    async def set_commands(self) -> None:
        # https://core.telegram.org/bots/api#setmycommands
        await self.make_api_request(
            "POST",
            "setMyCommands",
            json={
                "commands": [
                    {"command": "start", "description": "Пишет состояние бота."},
                    {"command": "id", "description": "ID вашего Telegram аккаунта."},
                    {
                        "command": "subscribe",
                        "description": "Подписывает на стримера.",
                    },
                    {
                        "command": "unsubscribe",
                        "description": "Удаляет подписку на стримера.",
                    },
                    {
                        "command": "check_subscriptions",
                        "description": "Перепроверяет подписки и переподписывается, если необходимо.",
                    },
                    {"command": "settings", "description": "Позволяет настроить бота."},
                    {
                        "command": "live",
                        "description": "Пишет онлайн каналы и позволяет получить информацию о стриме.",
                    },
                    {
                        "command": "subscriptions",
                        "description": "Пишет список ваших подписок",
                    },
                ]
            },
        )

    async def get_start_message(self, chat_id: int) -> str:
        if str(chat_id) not in (get("Telegram_Id") or ""):
            return (
                escape_symbols(
                    "Вы не авторизованы.\n\nЕсли вы являетесь создателем бота, то вам надо ставить ваш ID Telegram аккаунта в поле Telegram_Id, тоже самое место, где вы вставили токен этого бота.\n\nВаш ID: "
                )
                + f"`{chat_id}`"
            )
        app_token_status = await twitch.validate_app_token()

        if not app_token_status:
            if twitch.client_id and twitch.client_secret:
                return escape_symbols(
                    "Client_Id или Client_Secret являются недействительными. Вставьте их повторно с сайта https://dev.twitch.tv/console"
                )
            elif twitch.client_id and not twitch.client_secret:
                return escape_symbols(
                    "Вы забыли вставить Client_Secret, вставьте его с сайта https://dev.twitch.tv/console и используйте эту команду ещё раз."
                )
            elif not twitch.client_id and twitch.client_secret:
                return escape_symbols(
                    "Вы забыли вставить Client_Id, вставьте его с сайта https://dev.twitch.tv/console и попробуйте использовать эту команду ещё раз."
                )
            else:
                return escape_symbols(
                    "Вы успешно настроили Telegram бота!\n\nСледующий шаг создать приложение по ссылке https://dev.twitch.tv/console и вставить необходимые значения в тоже самое место, куда вы вставили токен этого бота."
                )
        else:
            return escape_symbols(
                "Всё настроено и готово к работе!\n\nЧтобы подписаться на уведомления, используйте команду /subscribe"
            )

    async def get_keyboard(self, prefix: str) -> dict:
        subscriptions = await config.get("subscriptions", {"value": []})
        inline_keyboard = [[{"text": "Глобально", "callback_data": f"{prefix}_global"}]]
        row = []
        for sub in subscriptions["value"]:
            row.append(
                {
                    "text": sub["login"],
                    "callback_data": f"{prefix}{sub['id']}",
                }
            )
            if len(row) == 4:
                inline_keyboard.append(row)
                row = []
        if row and row not in inline_keyboard:
            inline_keyboard.append(row)
        return {"inline_keyboard": inline_keyboard}

    async def process_event(self, request: Request) -> None:
        # https://core.telegram.org/bots/api#update
        event = await request.json()
        state = (await config.get("state", {"value": None}))["value"]
        if "message" in event and "text" in event["message"]:
            # Command
            text: str = event["message"]["text"].lower()
            chat_id: int = event["message"]["chat"]["id"]
            GLOBAL_COMMANDS = {
                "id": partial(self.id, chat_id),
                "start": partial(self.start, chat_id),
                "help": partial(self.start, chat_id),
            }
            PRIVATE_COMMANDS = {
                "subscribe": partial(self.command_subscribe, chat_id, text, None),
                "unsubscribe": partial(self.command_unsubscribe, chat_id, text, None),
                "check_subscriptions": partial(self.recheck_subscribe, chat_id),
                "settings": partial(self.settings, chat_id),
                "live": partial(self.live, event),
                "subscriptions": partial(self.get_subscriptions, chat_id),
            }
            STATE = {
                "subscribe": partial(self.command_subscribe, chat_id, text, state),
                "unsubscribe": partial(self.command_unsubscribe, chat_id, text, state),
            }
            command = text.split()[0].strip("/") if text.startswith("/") else None
            if command in GLOBAL_COMMANDS:
                if state:
                    await config.put({"key": "subscribe", "value": None})
                return await GLOBAL_COMMANDS[command]()
            elif str(chat_id) != getenv("Telegram_Id"):
                await self.send_message(
                    chat_id,
                    "Вы не авторизованы использовать этого бота.\n\nЕсли вы являетесь создателем этого бота, то убедитесь что вставили ID своего аккаунта в поле Telegram_Id.\n\nЧтобы узнать свой ID используйте команду /id",
                )
            elif command in PRIVATE_COMMANDS:
                if state:
                    await config.put({"key": "subscribe", "value": None})
                return await PRIVATE_COMMANDS[command]()
            elif state:
                return await STATE[state]()
        elif "callback_query" in event:
            # Callback (keyboard button)
            CALLBACK = {
                "y_": self.correct_user,
                "no": self.wrong_user,
                "us_": self.callback_unsubscribe,
                "cancel": self.cancel,
                "change_message_format": self.change_message_format,
                "cmf_": self.callback_change_message_format,
                "live_": self.callback_live,
                "live": self.live,
                "clear": self.clear,
            }
            for startswith, func in CALLBACK.items():
                if event["callback_query"]["data"].startswith(startswith):
                    return await func(event)

    # Commands

    async def get_subscriptions(self, chat_id: int):
        subscriptions = (await config.get("subscriptions", {"value": []}))["value"]
        if subscriptions:
            text = "Активные подписки:\n\n" + "\n".join(
                sub["login"] for sub in subscriptions
            )
        else:
            text = "У вас нету активных подписок. Чтобы подписаться, воспользуйтесь командой /subscribe"
        await self.send_message(chat_id, text)

    async def id(self, chat_id: int):
        await self.send_message(
            chat_id, f"Ваш ID: `{chat_id}`", parse_mode="MarkdownV2"
        )

    async def start(self, chat_id: int):
        text = await self.get_start_message(chat_id)
        await self.send_message(chat_id, text, parse_mode="MarkdownV2")

    async def live(self, event: dict):
        if "message" in event and "text" in event["message"]:
            chat_id = event["message"]["chat"]["id"]
            message_id = None
        else:
            chat_id = event["callback_query"]["message"]["chat"]["id"]
            message_id = event["callback_query"]["message"]["message_id"]
        live_channels = await config.query([{"is_live": True}])
        if not live_channels["items"]:
            if not message_id:
                return await self.send_message(
                    chat_id, "Сейчас нету онлайн каналов, на которые вы подписаны."
                )
            else:
                return await self.edit_message(
                    chat_id,
                    message_id,
                    "Сейчас нету онлайн каналов, на которые вы подписаны.",
                )
        inline_keyboard = []
        row = []
        for channel in live_channels["items"]:
            row.append(
                {"text": channel["login"], "callback_data": f"live_{channel['key']}"}
            )
            if len(row) == 4:
                inline_keyboard.append(row)
                row = []
        if row and row not in inline_keyboard:
            inline_keyboard.append(row)
        if not message_id:
            await self.send_message(
                chat_id,
                "Выберите онлайн канал, о котором хотите получить данные:",
                reply_markup={"inline_keyboard": inline_keyboard},
            )
        else:
            await self.edit_message(
                chat_id,
                message_id,
                "Выберите онлайн канал, о котором хотите получить данные:",
                reply_markup={"inline_keyboard": inline_keyboard},
            )

    async def command_subscribe(self, chat_id: int, text: str, state: str | None):
        # Добавить возможность подписаться на пачку стримеров.
        if text.count(" ") != 2 and not state:
            await self.send_message(
                chat_id,
                "Отправьте название или ссылку на канал в следующем сообщении.",
                reply_markup={
                    "inline_keyboard": [
                        [
                            {
                                "text": "Отмена",
                                "callback_data": f"clear",
                            },
                        ]
                    ]
                },
            )
            await config.put({"key": "state", "value": "subscribe"})
        else:
            username = text.split()[0 if state else 1]
            if "twitch.tv/" in username:
                username = username.split(".tv/")[-1].split("?")[0]
            user = await twitch.get_users(username)
            if not user:
                await self.send_message(chat_id, "Не смог найти такого пользователя.")
            else:
                subscriptions = await config.get("subscriptions", {"value": []})
                if any(user["id"] == sub["id"] for sub in subscriptions["value"]):
                    await self.send_message(
                        chat_id, "Вы уже подписаны на этого пользователя."
                    )  # Добавить кнопку отписаться
                    return
                await self.send_message(
                    chat_id,
                    f"Это правильный пользователь?\n\n*Логин:* {escape_symbols(user['login'])}\n*Описание:* {escape_symbols(user['description'])}\n\nhttps://twitch\.tv/{escape_symbols(user['login'])}",
                    parse_mode="MarkdownV2",
                    reply_markup={
                        "inline_keyboard": [
                            [
                                {
                                    "text": "Да",
                                    "callback_data": f"y_{user['id']}",
                                },
                                {"text": "Нет", "callback_data": "no"},
                            ]
                        ]
                    },
                )

    async def command_unsubscribe(self, chat_id: int, text: str, state: str | None):
        if text.count(" ") != 2 and not state:
            await self.send_message(
                chat_id,
                "Отправьте название или ссылку на канал в следующем сообщении.",
                reply_markup={
                    "inline_keyboard": [
                        [
                            {
                                "text": "Отмена",
                                "callback_data": f"clear",
                            },
                        ]
                    ]
                },
            )
            await config.put({"key": "state", "value": "unsubscribe"})
        else:
            login = text.split()[0 if state else 1].lower()
            if "twitch.tv/" in login:
                login = login.split("twitch.tv/")[1]
            subscriptions = await config.get("subscriptions", {"value": []})
            user = None
            for sub in subscriptions["value"]:
                if login == sub["login"]:
                    user = sub
            if not user:
                await self.send_message(
                    chat_id, "У вас нету подписки на данного стримера."
                )
                return
            await self.send_message(
                chat_id,
                f"Вы точно хотите удалить подписку на {user['login']}?",
                reply_markup={
                    "inline_keyboard": [
                        [
                            {
                                "text": "Да",
                                "callback_data": f"us_{user['id']}",
                            },
                            {"text": "Нет", "callback_data": "cancel"},
                        ]
                    ]
                },
            )

    async def recheck_subscribe(self, chat_id: int):
        if twitch.client_id and twitch.client_secret:
            subscribed = await twitch.subscribe(force=True)
            if subscribed:
                await self.send_message(chat_id, "Переподписался на некоторые каналы.")
            else:
                await self.send_message(chat_id, "Все подписки работают.")

    async def settings(self, chat_id: int):
        await self.send_message(
            chat_id,
            "Настройки:\n\n*Формат сообщений:* Поменять формат сообщений, в котором присылаются обновления\.\n*Переключить уведомления:* Вы все ещё будете получать сообщения, но приходить они будут без звука\.\n*Переключить скриншот:* Добавлять/не добавлять скриншот со стрима\.\n*Предосмотр ссылки:* Включить/выключить предосмотр ссылки\n\nЧто вы хотите настроить:",
            parse_mode="MarkdownV2",
            reply_markup={
                "inline_keyboard": [
                    [
                        {
                            "text": "Формат сообщений",
                            "callback_data": "change_message_format",
                        },
                        {
                            "text": "Переключить уведомления",
                            "callback_data": "toggle_notifications",
                        },
                    ],
                    [
                        {
                            "text": "Переключить скриншот",
                            "callback_data": "toggle_screenshot",
                        },
                        {
                            "text": "Предосмотр ссылки",
                            "callback_data": "toggle_preview",
                        },
                    ],
                ]
            },
        )

    # Callbacks

    async def callback_unsubscribe(self, event: dict):
        id = event["callback_query"]["data"].split("_")[-1]
        tasks = []
        subscriptions = await config.get("subscriptions", {"value": []})
        user = None
        for sub in subscriptions["value"]:
            if id == sub["id"]:
                user = sub
        if not user:
            return
        subscriptions["value"].remove(user)
        channel = await config.get(user["id"])
        for type in ("streamonline", "streamoffline", "channelupdate"):
            tasks.append(
                asyncio.create_task(twitch.delete_eventsub_subscription(channel[type]))
            )
        tasks.append(asyncio.create_task(config.delete(channel["key"])))
        tasks.append(asyncio.create_task(config.put([subscriptions])))
        tasks.append(
            asyncio.create_task(
                self.edit_message(
                    event["callback_query"]["message"]["chat"]["id"],
                    event["callback_query"]["message"]["message_id"],
                    f"Успешно отписался от {channel['login']} 👍",
                )
            )
        )
        await asyncio.gather(*tasks)

    async def correct_user(self, event: dict):
        id: str = event["callback_query"]["data"].split("_")[1]
        login: str = (
            event["callback_query"]["message"]["text"]
            .split("Логин: ")[1]
            .split("\n")[0]
        )
        tasks = []
        subscriptions, global_settings = await config.get_many(
            ["subscriptions", "global"]
        )
        subscriptions = subscriptions["value"] if subscriptions else []
        subscriptions.append({"id": id, "login": login})
        user = (await twitch.combine_channel_data([id]))[id]
        user.update(
            {
                "key": id,
                "login": login,
                "channelupdate": None,
                "streamoffline": None,
                "streamonline": None,
            }
        )
        user.update(**global_settings)
        await config.put(
            [
                user,
                {"key": "subscriptions", "value": subscriptions},
                {"key": "state", "value": None},
            ]
        )
        tasks.append(
            asyncio.create_task(
                self.edit_message(
                    event["callback_query"]["message"]["chat"]["id"],
                    event["callback_query"]["message"]["message_id"],
                    f"Успешно подписался. 👍\n\nЧтобы настроить подписку, используйте кнопку ниже.",
                    reply_markup={
                        "inline_keyboard": [
                            [
                                {
                                    "text": "Перейти к настройкам",
                                    "callback_data": f"settings_{id}",
                                }
                            ],
                        ]
                    },
                )
            )
        )
        tasks.append(
            asyncio.create_task(
                twitch.create_eventsub_subscription(
                    type="stream.online", broadcaster_user_id=id
                )
            )
        )
        tasks.append(
            asyncio.create_task(
                twitch.create_eventsub_subscription(
                    type="stream.offline", broadcaster_user_id=id
                )
            )
        )
        tasks.append(
            asyncio.create_task(
                twitch.create_eventsub_subscription(
                    type="channel.update", broadcaster_user_id=id
                )
            )
        )
        await asyncio.gather(*tasks)

    async def wrong_user(self, event: dict):
        state = (await config.get("state", {"value": None}))["value"]
        await self.edit_message(
            event["callback_query"]["message"]["chat"]["id"],
            event["callback_query"]["message"]["message_id"],
            "Отправьте название или ссылку на канал в следующем сообщении."
            if state
            else "Перепроверьте введенные данные и повторите попытку.",
            reply_markup={
                "inline_keyboard": [
                    [
                        {
                            "text": "Отмена",
                            "callback_data": f"clear",
                        },
                    ]
                ]
            }
            if state
            else None,
        )

    async def change_message_format(self, event: dict):
        await self.edit_message(
            event["callback_query"]["message"]["chat"]["id"],
            event["callback_query"]["message"]["message_id"],
            "Где хотите изменить формат сообщений?",
            reply_markup=await self.get_keyboard("cmf_"),
        )

    async def callback_change_message_format(self, event: dict):
        id = event["callback_query"]["data"].split("_")[1]
        await self.edit_message(
            event["callback_query"]["message"]["chat"]["id"],
            event["callback_query"]["message"]["message_id"],
            text=f"Какое сообщение вы хотите обновить?",
            parse_mode="MarkdownV2",
            reply_markup={
                "inline_keyboard": [
                    [
                        {"text": "Тест онлайн", "callback_data": f"stream.online_{id}"},
                        {
                            "text": "Тест офлайн",
                            "callback_data": f"stream.offline_{id}",
                        },
                        {
                            "text": "Тест обновление",
                            "callback_data": f"channel.update_{id}",
                        },
                    ],
                    [
                        {"text": "Онлайн", "callback_data": f"stream.online_{id}"},
                        {"text": "Офлайн", "callback_data": f"stream.offline_{id}"},
                        {"text": "Обновление", "callback_data": f"channel.update_{id}"},
                    ],
                ]
            },
        )

    async def cancel(self, event: dict):
        await self.edit_message(
            event["callback_query"]["message"]["chat"]["id"],
            event["callback_query"]["message"]["message_id"],
            "Успешно отменил. 👍",
        )

    async def callback_live(self, event: dict):
        id = event["callback_query"]["data"].split("_")[-1]
        channel = await config.get(id)
        if not channel["is_live"]:
            await self.edit_message(
                event["callback_query"]["message"]["chat"]["id"],
                event["callback_query"]["message"]["message_id"],
                "Этот канал уже офлайн.",
                reply_markup={
                    "inline_keyboard": [[{"text": "Назад", "callback_data": "live"}]]
                },
            )
            return
        await self.edit_message(
            event["callback_query"]["message"]["chat"]["id"],
            event["callback_query"]["message"]["message_id"],
            format_text(
                channel,
                channel,
                "*Название стрима:* ${title}\n*Стрим идёт:* ${uptime}\n*Категории:* ${categories}\n\n${stream_url}",
            ),
            parse_mode="MarkdownV2",
            reply_markup={
                "inline_keyboard": [[{"text": "Назад", "callback_data": "live"}]]
            },
        )

    async def clear(self, event: dict):
        await config.put({"key": "state", "value": None})
        await self.edit_message(
            event["callback_query"]["message"]["chat"]["id"],
            event["callback_query"]["message"]["message_id"],
            "Успешно отменил. 👍",
        )

    async def choose(self, event: dict):
        data: dict = json.loads(event["callback_query"]["data"].split("_", 1)[-1])
        online = data["on"]
        offline = data["of"]
        update = data["up"]
        await self.edit_message(
            event["callback_query"]["message"]["chat"]["id"],
            event["callback_query"]["message"]["message_id"],
            f"""*Мастер настройки*\n\nНа какие уведомления хотите подписаться?\n\nНачало стрима: {"✅" if online else "❌"}\nКонец стрима: {"✅" if offline else "❌"}\nОбновление категории/названия стрима: {"✅" if update else "❌"}""",
            parse_mode="MarkdownV2",
            reply_markup={
                "inline_keyboard": [
                    [
                        {
                            "text": f"Начало стрима",
                            "callback_data": f"""sb_{json.dumps({"id": data["id"], "on": int(not online), "of": offline, "up": update}).replace(" ", "")}""",
                        },
                        {
                            "text": f"Конец стрима",
                            "callback_data": f"""sb_{json.dumps({"id": data["id"], "on": online, "of": int(not offline), "up": update}).replace(" ", "")}""",
                        },
                        {
                            "text": f"Обновление",
                            "callback_data": f"""sb_{json.dumps({"id": data["id"], "on": online, "of": offline, "up": int(not update)}).replace(" ", "")}""",
                        },
                    ],
                    [
                        {"text": "Отмена", "callback_data": "cancel"},
                        {
                            "text": "Дальше",
                            "callback_data": f"""cn_{json.dumps(data).replace(" ", "")}""",
                        },
                    ],
                ]
            },
        )

    async def make_api_request(
        self, method: str, endpoint: str, *args, **kwargs
    ) -> ClientResponse:
        if self.session is None:
            self.session = await get_session()
        return await self.session.request(
            method, f"{self.base_url}/{endpoint}", *args, **kwargs
        )
