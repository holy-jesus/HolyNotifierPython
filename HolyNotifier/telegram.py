import asyncio
from os import getenv
from pprint import pprint
import json

from aiohttp import ClientResponse
from fastapi import Request

from main import twitch
from detabase import Base
from utils import escape_symbols, get, get_session

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
        if not self.token and not self.get_telegram_token():
            return False
        response = await self.make_api_request("GET", "getWebhookInfo")
        json = await response.json()
        return bool(json["result"]["url"])

    async def subscribe(self) -> bool:
        # https://core.telegram.org/bots/api#setwebhook
        if not self.token and not self.get_telegram_token():
            return False
        elif await self.is_subscribed():
            return True
        response = await self.make_api_request(
            "GET",
            "setWebHook",
            params={
                "url": f"https://{getenv('DETA_SPACE_APP_HOSTNAME')}/telegramwebhook"
            },
        )
        await self.set_commands()
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

    async def set_commands(self):
        # https://core.telegram.org/bots/api#setmycommands
        response = await self.make_api_request(
            "POST",
            "setMyCommands",
            json={
                "commands": [
                    {"command": "start", "description": "Пишет состояние бота"},
                    {"command": "id", "description": "ID вашего Telegram аккаунта"},
                    {
                        "command": "subscribe",
                        "description": "Подписывает на стримера на платформе Twitch",
                    },
                    {"command": "settings", "description": "Позволяет настроить бота"},
                    {
                        "command": "check_subscriptions",
                        "description": "Перепроверяет подписки и переподписывается, если необходимо.",
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
                    "Вы забыли вставить Client_Secret, вставьте его с сайта https://dev.twitch.tv/console и попробуйте использовать эту команду ещё раз."
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

    async def process_event(self, request: Request) -> None:
        # https://core.telegram.org/bots/api#update
        event = await request.json()
        if "message" in event and "text" in event["message"]:
            # Command
            text: str = event["message"]["text"].lower()
            chat_id: int = event["message"]["chat"]["id"]
            if text.startswith("/id"):
                await self.send_message(
                    chat_id, f"Ваш ID: `{chat_id}`", parse_mode="MarkdownV2"
                )
            elif text.startswith("/start") or text.startswith("/help"):
                await self.set_commands()
                text = await self.get_start_message(chat_id)
                await self.send_message(chat_id, text, parse_mode="MarkdownV2")
            elif str(chat_id) != getenv("Telegram_Id"):
                await self.send_message(
                    chat_id,
                    "Вы не авторизованы использовать этого бота.\n\nЕсли вы являетесь создателем этого бота, то убедитесь что вставили ID своего аккаунта в поле Telegram_Id.\n\nЧтобы узнать свой ID используйте команду /id",
                )
            elif text.startswith("/subscribe"):
                await self.command_subscribe(chat_id, text)
            elif text.startswith("/check_subscriptions"):
                await self.recheck_subscribe(chat_id)
            elif text.startswith("/settings"):
                await self.settings(chat_id)
        elif "callback_query" in event:
            # Callback (keyboard button)
            if event["callback_query"]["data"].startswith("sb_"):
                await self.choose(event)
            elif event["callback_query"]["data"].startswith("cn_"):
                await self.cont(event)
            elif event["callback_query"]["data"] == "cancel":
                await self.cancel(event)
            elif event["callback_query"]["data"] == "change_message_format":
                await self.change_message_format(event)

    # Commands

    async def command_subscribe(self, chat_id: int, text: str):
        splitted = text.split()
        if len(splitted) == 1 or len(splitted) > 2:
            await self.send_message(
                chat_id, "Пример: /subscribe https://twitch.tv/user"
            )
        elif len(splitted) == 2:
            username = splitted[1]
            if "twitch.tv/" in username:
                username = username.split(".tv/")[-1].split("?")[0]
            user = await twitch.get_users(username)
            if not user:
                await self.send_message(chat_id, "Не смог найти такого пользователя.")
            else:
                data = {
                    "id": user["id"],
                    "on": 0,
                    "of": 0,
                    "up": 0,
                }

                deta_response = await config.query([{"value?contains": data["id"]}])
                for item in deta_response["items"]:
                    data[item["key"][:2]] = 1
                online = data["on"]
                offline = data["of"]
                update = data["up"]
                await self.send_message(
                    chat_id,
                    f"""*Мастер настройки*\n\nНа какие уведомления хотите подписаться?\n\nНачало стрима: {"✅" if online else "❌"}\nКонец стрима: {"✅" if offline else "❌"}\nОбновление категории/названия стрима: {"✅" if update else "❌"}""",
                    parse_mode="MarkdownV2",
                    reply_markup={
                        "inline_keyboard": [
                            [
                                {
                                    "text": "Начало стрима",
                                    "callback_data": f"""sb_{json.dumps({"id": data["id"], "on": int(not online), "of": offline, "up": update}).replace(" ", "")}""",
                                },
                                {
                                    "text": "Конец стрима",
                                    "callback_data": f"""sb_{json.dumps({"id": data["id"], "on": online, "of": int(not offline), "up": update}).replace(" ", "")}""",
                                },
                                {
                                    "text": "Обновление",
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

    async def recheck_subscribe(self, chat_id: int):
        if twitch.client_id and twitch.client_secret:
            subscribed = await twitch.subscribe()
            if subscribed:
                await self.send_message(chat_id, "Переподписался на некоторые каналы.")
            else:
                await self.send_message(chat_id, "Все подписки работают.")

    async def settings(self, chat_id: int):
        await self.send_message(
            chat_id,
            "Настройки:\n\nФормат сообщений: Поменять формат сообщений, в котором присылаются обновления\.\nОтключить/Включить уведомления: Вы все ещё будете получать сообщения, но приходить они будут без звука\.\nДобавлять скриншот: Добавлять скриншот со стрима\.\n\nЧто вы хотите изменить:",
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
                        {
                            "text": "Прикреплять скриншот",
                            "callback_data": "toggle_screenshot",
                        },
                    ],
                ]
            },
        )

    # Callbacks

    async def change_message_format(self, event: dict):
        await self.edit_message(
            event["callback_query"]["message"]["chat"]["id"],
            event["callback_query"]["message"]["message_id"],
            "",
        )

    async def cancel(self, event: dict):
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

    async def cont(self, event: dict):
        tasks = []
        data: dict = json.loads(event["callback_query"]["data"].split("_", 1)[-1])
        await twitch.create_user_if_needed(data["id"])
        tasks.append(
            asyncio.create_task(
                self.edit_message(
                    event["callback_query"]["message"]["chat"]["id"],
                    event["callback_query"]["message"]["message_id"],
                    "Успешно подписался",
                    parse_mode="MarkdownV2",
                )
            )
        )
        db = {"online": [], "offline": [], "update": []}
        deta_response, subscriptions = await asyncio.gather(
            asyncio.create_task(config.query([{"value?contains": data["id"]}])),
            asyncio.create_task(config.get(data["id"])),
        )
        for item in deta_response["items"]:
            db[item["key"]] = item["value"]
        put = []

        if data["id"] not in db["online"] and data["on"]:
            db["online"].append(data["id"])
            put.append({"key": "online", "value": db["online"]})
            tasks.append(
                asyncio.create_task(
                    twitch.create_eventsub_subscription(
                        type="stream.online", broadcaster_user_id=data["id"]
                    )
                )
            )

        elif data["id"] in db["online"] and not data["on"]:
            db["online"].remove(data["id"])
            put.append({"key": "online", "value": db["online"]})
            tasks.append(
                asyncio.create_task(
                    twitch.delete_eventsub_subscription(
                        subscription_id=subscriptions["streamonline"]
                    )
                )
            )

        if data["id"] not in db["offline"] and data["of"]:
            db["offline"].append(data["id"])
            put.append({"key": "offline", "value": db["offline"]})
            tasks.append(
                asyncio.create_task(
                    twitch.create_eventsub_subscription(
                        type="stream.offline", broadcaster_user_id=data["id"]
                    )
                )
            )

        elif data["id"] in db["offline"] and not data["of"]:
            db["offline"].remove(data["id"])
            put.append({"key": "offline", "value": db["offline"]})
            tasks.append(
                asyncio.create_task(
                    twitch.delete_eventsub_subscription(
                        subscription_id=subscriptions["streamoffline"]
                    )
                )
            )

        if data["id"] not in db["update"] and data["up"]:
            db["update"].append(data["id"])
            put.append({"key": "update", "value": db["update"]})
            tasks.append(
                asyncio.create_task(
                    twitch.create_eventsub_subscription(
                        type="channel.update", broadcaster_user_id=data["id"]
                    )
                )
            )

        elif data["id"] in db["update"] and not data["up"]:
            db["update"].remove(data["id"])
            put.append({"key": "update", "value": db["update"]})
            tasks.append(
                asyncio.create_task(
                    twitch.delete_eventsub_subscription(
                        subscription_id=subscriptions["channelupdate"]
                    )
                )
            )

        tasks.append(asyncio.create_task(config.put(put)))
        await asyncio.gather(*tasks)

    async def make_api_request(
        self, method: str, endpoint: str, *args, **kwargs
    ) -> ClientResponse:
        if self.session is None:
            self.session = await get_session()
        return await self.session.request(
            method, f"{self.base_url}/{endpoint}", *args, **kwargs
        )
