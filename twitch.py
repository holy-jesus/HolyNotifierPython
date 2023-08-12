import asyncio
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from template import Template
from dateutil.parser import parse
from os import getenv
from time import time, strftime, gmtime
from functools import partial

from fastapi import Request, Response

from detabase import Base
from utils import escape_symbols, get, get_session, smart_escape

config = Base(
    "dev_config" if "ngrok" in getenv("DETA_SPACE_APP_HOSTNAME") else "config"
)


def get_channel_value(key: str, channel: dict, event: dict):
    return channel.get(key, None)

def get_event_value(key: str, channel: dict, event: dict):
    return event["event"].get(key, None)

def game_time(key: str, channel: dict, event: dict):
    if channel["is_live"]:
        game_time = channel["game_time"][channel["category"]] if channel["game_time"] and channel["category"] in channel["game_time"] else 0
        return strftime("%H:%M:%S", gmtime(time() - channel["game_timestamp"] + game_time))
    else:
        return None

def uptime(key: str, channel: dict, event: dict):
    if channel["is_live"]:
        return strftime("%H:%M:%S", gmtime(time() - channel["started_at"]))
    else:
        return None

def stream_url(key: str, channel: dict, event: dict):
    return "https://twitch.tv/" + channel.get("login")

def format_text(channel: dict, event: dict, text: str):
    MAPPING = {
        "username": partial(get_channel_value, "name", channel, event),
        "login": partial(get_channel_value, "login", channel, event),
        "category": partial(get_channel_value, "category", channel, event),
        "title": partial(get_channel_value, "title", channel, event),
        "new_category": partial(get_event_value, "category_name", channel, event),
        "new_title": partial(get_event_value, "title", channel, event),
        "uptime": partial(uptime, None, channel, event),
        "gametime": partial(game_time, None, channel, event),
        "stream_url": partial(stream_url, None, channel, event)
    }
    mapped = {}
    final_text = ""
    for line in text.split("\n"):
        skip_line = False
        template = Template(line)
        identifiers = tuple(map(str.lower, template.get_identifiers()))
        for identifier in identifiers:
            if identifier not in MAPPING:
                continue
            value = MAPPING[identifier]()
            if value is None and identifier in ("gametime", "uptime") and len(identifiers) == 1:
                skip_line = True
                break
            mapped[identifier] = escape_symbols(value or "-")
        if skip_line:
            continue
        final_text += template.safe_substitute(mapped) + "\n"
    return smart_escape(final_text[:-1])


async def stream_online(data: dict):
    # https://dev.twitch.tv/docs/eventsub/eventsub-subscription-types/#streamonline
    # Нужно понимать что одна из подписок может быть отключена, поэтому некоторые поля будут пустые.
    # Технически, мы можем реально не подписываться на отключение стрима и понимать что это другой стрим по айди стрима id в data['event']
    # Но надо ли мне так запариваться?
    global telegram
    if "telegram" not in globals():
        from main import telegram
    channel = await config.get(data["event"]["broadcaster_user_id"])
    await telegram.send_message(
        get("Telegram_Id"),
        "*Начался стрим на канале {username}*\n\nhttps://twitch.tv/{login}",
        parse_mode="MarkdownV2",
    )
    await config.update(
        data["event"]["broadcaster_user_id"],
        set={
            "is_live": True,
            "started_at": int(time()),
            "game_timestamp": int(time()),
            "game_time": {},
        },
    )


async def stream_offline(data: dict):
    # https://dev.twitch.tv/docs/eventsub/eventsub-subscription-types/#streamoffline
    global telegram
    if "telegram" not in globals():
        from main import telegram
    channel = await config.get(data["event"]["broadcaster_user_id"])
    await telegram.send_message(
        get("Telegram_Id"),
        format_text(channel, data, "*Закончился стрим на канале ${username}*\n\nПродолжительность стрима: ${uptime}"),
        parse_mode="MarkdownV2",
    )
    await config.update(
        data["event"]["broadcaster_user_id"],
        set={
            "is_live": False,
            "started_at": None,
            "game_timestamp": None,
            "game_time": {},
        },
    )


async def channel_update(data: dict):
    # https://dev.twitch.tv/docs/eventsub/eventsub-subscription-types/#channelupdate
    global telegram
    if "telegram" not in globals():
        from main import telegram
    set = {}
    channel = await config.get(data["event"]["broadcaster_user_id"])
    if (
        (channel["category"] != None and data["event"]["category_name"] != "")
        and channel["category"] != data["event"]["category_name"]
    ) and channel["title"] != data["event"]["title"]:
        text = "*Обновление на канале ${username}*\n\n*Новое название стрима:* ${new_title}\n*Новая категория:* ${new_category}\n*Стрим идёт:* ${uptime}\n*Прошлая категория шла:* ${gametime}\n\nhttps://twitch\\.tv/${login}"
        if channel["is_live"]:
            if not channel["game_time"]:
                set["game_time"] = {
                    channel["category"]: int(time()) - channel["game_timestamp"]
                }
            elif channel["category"] not in channel["game_time"]:
                channel["game_time"][channel["category"]] = (
                    int(time()) - channel["game_timestamp"]
                )
                set["game_time"] = channel["game_time"]
            else:
                channel["game_time"][channel["category"]] += (
                    int(time()) - channel["game_timestamp"]
                )
                set["game_time"] = channel["game_time"]
            set["game_timestamp"] = int(time())
        set["title"] = data["event"]["title"]
        set["category"] = data["event"]["category_name"]
    elif (
        channel["category"] != None and data["event"]["category_name"] != ""
    ) and channel["category"] != data["event"]["category_name"]:
        text = "*Обновление на канале ${username}*\n\n*Новая категория:* ${new_category}\n*Стрим идёт:* ${uptime}\n*Прошлая категория шла:* ${gametime}\n\nhttps://twitch\\.tv/${login}"
        if channel["is_live"]:
            if not channel["game_time"]:
                set["game_time"] = {
                    channel["category"]: int(time()) - channel["game_timestamp"]
                }
            elif channel["category"] not in channel["game_time"]:
                channel["game_time"][channel["category"]] = (
                    int(time()) - channel["game_timestamp"]
                )
                set["game_time"] = channel["game_time"]
            else:
                channel["game_time"][channel["category"]] += (
                    int(time()) - channel["game_timestamp"]
                )
                set["game_time"] = channel["game_time"]
            set["game_timestamp"] = int(time())
        set["category"] = data["event"]["category_name"]
    elif channel["title"] != data["event"]["title"]:
        text = "*Обновление на канале ${username}*\n\n*Новое название стрима:* ${new_title}\n*Стрим идёт:* ${uptime}\n*Категория идёт:* ${gametime}\n\nhttps://twitch\\.tv/${login}"
        set["title"] = data["event"]["title"]
    else:
        return

    await telegram.send_message(
        get("Telegram_Id"),
        format_text(channel, data, text),
        parse_mode="MarkdownV2",
    )
    await config.update(
        data["event"]["broadcaster_user_id"],
        set=set,
    )


VERSION = {"channel.update": "2", "stream.online": "1", "stream.offline": "1"}
EVENTS = {
    "stream.online": stream_online,
    "stream.offline": stream_offline,
    "channel.update": channel_update,
}


class Twitch:
    def __init__(self, client_id: str, client_secret: str) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.expires = 0
        self.headers = {"Client-Id": client_id, "Authorization": None}
        self.session = None

    async def create_user_if_needed(self, id: str) -> None:
        user = await config.get(id)
        if user:
            return
        user = (await self.combine_channel_data([id]))[id]
        user.update({"key": id, "channelupdate": None, "streamoffline": None, "streamonline": None})
        await config.put(user)

    async def subscribe(self) -> bool:
        tasks = []
        put = []
        online = await config.get("online")  # stream.online
        if online is None:
            online = []
            put.append({"key": "online", "value": []})
        else:
            online = online["value"]
        offline = await config.get("offline")  # stream.offline
        if offline is None:
            offline = []
            put.append({"key": "offline", "value": []})
        else:
            offline = offline["value"]
        update = await config.get("update")  # channel.update
        if update is None:
            update = []
            put.append({"key": "update", "value": []})
        else:
            update = update["value"]

        if put:
            tasks.append(asyncio.create_task(config.put(put)))
        
        subscriptions = (
            await self.get_eventsub_subscriptions()
        )  # Брать отсюда айдишники подписок и вбивать навсякий в БД
        # ИЛИ
        # Получать их каждый запуск
        sub_ids = {}
        for sub in subscriptions:
            if sub["condition"]["broadcaster_user_id"] not in sub_ids:
                sub_ids[sub["condition"]["broadcaster_user_id"]] = {}
            sub_ids[sub["condition"]["broadcaster_user_id"]][
                sub["type"].replace(".", "")
            ] = sub["id"]
            if (
                sub["type"] == "stream.online"
                and sub["condition"]["broadcaster_user_id"] in online
            ):
                online.remove(sub["condition"]["broadcaster_user_id"])
            elif (
                sub["type"] == "stream.offline"
                and sub["condition"]["broadcaster_user_id"] in offline
            ):
                offline.remove(sub["condition"]["broadcaster_user_id"])
            elif (
                sub["type"] == "channel.update"
                and sub["condition"]["broadcaster_user_id"] in update
            ):
                update.remove(sub["condition"]["broadcaster_user_id"])

        channels = await self.combine_channel_data(list(set(online + offline + update)))
        for id, channel in channels.items():
            await config.update(id, set=channel)


        for user_id, subs in sub_ids.items():
            tasks.append(asyncio.create_task(config.update(user_id, set=subs)))

        for channel in online:
            tasks.append(
                asyncio.create_task(
                    self.create_eventsub_subscription("stream.online", channel)
                )
            )
        for channel in offline:
            tasks.append(
                asyncio.create_task(
                    self.create_eventsub_subscription("stream.offline", channel)
                )
            )
        for channel in update:
            tasks.append(
                asyncio.create_task(
                    self.create_eventsub_subscription("channel.update", channel)
                )
            )
        await asyncio.gather(*tasks)
        return bool(online + offline + update)

    def get_client_id_and_client_secret(self) -> bool:
        self.client_id = get("Client_Id")
        self.client_secret = get("Client_Secret")
        if self.client_id:
            self.headers["Client-Id"] = self.client_id
        return self.client_id and self.client_secret

    async def create_app_token(self) -> bool:
        if not self.client_id or not self.client_secret:
            if not self.get_client_id_and_client_secret():
                return False
        app_access_token = await config.get(
            "dev_app_token"
            if "ngrok" in getenv("DETA_SPACE_APP_HOSTNAME")
            else "app_token"
        )
        if app_access_token and app_access_token["expires"] > time():
            self.expires = app_access_token["expires"]
            self.headers["Authorization"] = "Bearer " + app_access_token["access_token"]
            return True
        response = await self.session.post(
            "https://id.twitch.tv/oauth2/token",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data=f"client_id={self.client_id}&client_secret={self.client_secret}&grant_type=client_credentials",
        )
        # print("token", response.status, await response.json())
        if response.status == 200:
            app_access_token = await response.json()
            self.expires = int(time()) + app_access_token["expires_in"] - 30
            self.headers["Authorization"] = "Bearer " + app_access_token["access_token"]
            await config.put(
                {
                    "access_token": app_access_token["access_token"],
                    "expires": self.expires,
                    "key": "dev_app_token"
                    if "ngrok" in getenv("DETA_SPACE_APP_HOSTNAME")
                    else "app_token",
                }
            )
            return True
        else:
            return False
            # {'status': 400, 'message': 'invalid client'}

    async def validate_app_token(self) -> bool:
        # True if everything is okay else returns False
        # https://dev.twitch.tv/docs/authentication/validate-tokens/
        if (
            not self.client_id
            or not self.client_secret
            and not self.get_client_id_and_client_secret()
        ):
            return False
        response = await self.make_api_request(
            "GET", "https://id.twitch.tv/oauth2/validate"
        )
        data = await response.json()
        if (
            not response
            or "client_id" not in data
            or data["client_id"] != self.client_id
        ):
            return False
        return True

    async def create_eventsub_subscription(self, type: str, broadcaster_user_id: str):
        # https://dev.twitch.tv/docs/api/reference/#create-eventsub-subscription
        if "localhost" in getenv("DETA_SPACE_APP_HOSTNAME"):
            return True
        response = await self.make_api_request(
            "POST",
            "https://api.twitch.tv/helix/eventsub/subscriptions",
            json={
                "type": type,
                "version": VERSION[type],
                "condition": {"broadcaster_user_id": broadcaster_user_id},
                "transport": {
                    "method": "webhook",
                    "callback": f"https://{getenv('DETA_SPACE_APP_HOSTNAME')}/twitchwebhook",
                    "secret": getenv("secret"),
                },
            },
        )
        return response

    async def delete_eventsub_subscription(self, subscription_id: str) -> None:
        # https://dev.twitch.tv/docs/api/reference/#delete-eventsub-subscription
        response = await self.make_api_request(
            "DELETE",
            "https://api.twitch.tv/helix/eventsub/subscriptions",
            params={"id": subscription_id},
        )

    async def get_eventsub_subscriptions(self) -> list:
        # https://dev.twitch.tv/docs/api/reference/#get-eventsub-subscriptions
        subscriptions = []
        response = await self.make_api_request(
            "GET",
            "https://api.twitch.tv/helix/eventsub/subscriptions",
            params={"status": "enabled"},
        )
        if not response or response.status != 200:
            return []
        json_response = await response.json()
        subscriptions += json_response["data"]
        while "cursor" in json_response["pagination"]:
            response = await self.make_api_request(
                "GET",
                "https://api.twitch.tv/helix/eventsub/subscriptions",
                params={
                    "status": "enabled",
                    "after": json_response["pagination"]["cursor"],
                },
            )
            json_response = await response.json()
            subscriptions += json_response["data"]
        return subscriptions

    async def get_users(self, login: str):
        # https://dev.twitch.tv/docs/api/reference/#get-users
        response = await self.make_api_request(
            "GET", "https://api.twitch.tv/helix/users", params={"login": login}
        )
        users = await response.json()
        if response.status != 200 or "data" not in users or not users["data"]:
            return None
        return users["data"][0]

    async def get_channel_information(self, ids: list) -> dict:
        # https://dev.twitch.tv/docs/api/reference/#get-channel-information
        if not ids:
            return {"data": []}
        query = "broadcaster_id=" + "&broadcaster_id=".join(ids)
        response = await self.make_api_request(
            "GET", f"https://api.twitch.tv/helix/channels?{query}"
        )
        if response.status != 200:
            return {"data": []}
        return await response.json()

    async def get_streams(self, ids: list) -> dict:
        # https://dev.twitch.tv/docs/api/reference/#get-streams
        if not ids:
            return {"data": []}
        query = "user_id=" + "&user_id=".join(ids)
        response = await self.make_api_request(
            "GET", f"https://api.twitch.tv/helix/streams?{query}"
        )
        if response.status != 200:
            return {"data": []}
        return await response.json()

    async def combine_channel_data(self, ids: list) -> dict:
        data = {id: {} for id in ids}
        streams = await self.get_streams(ids)
        for stream in streams["data"]:
            ids.remove(stream["user_id"])
            data[stream["user_id"]] = {
                "login": stream["user_login"],
                "name": stream["user_name"],
                "title": stream["title"],
                "category": stream["game_name"],
                "is_live": True,
                "started_at": parse(stream["started_at"]).timestamp(),
                "game_timestamp": parse(stream["started_at"]).timestamp(),
                "game_time": {},
            }
        channels = await self.get_channel_information(ids)
        for channel in channels["data"]:
            data[channel["broadcaster_id"]] = {
                "login": channel["broadcaster_login"],
                "name": channel["broadcaster_name"],
                "title": channel["title"],
                "category": channel["game_name"],
                "is_live": False,
                "started_at": None,
                "game_timestamp": None,
                "game_time": {},
            }
        return data

    async def make_api_request(
        self,
        method: str,
        url: str,
        *,
        params: dict = None,
        json: dict = None,
        retry: bool = False,
    ):
        if self.session is None:
            self.session = await get_session()
        if time() >= self.expires or not self.headers["Authorization"]:
            if not (await self.create_app_token()):
                return None
        response = await self.session.request(
            method, url, headers=self.headers, params=params, json=json
        )
        if response.status == 401 and not retry:
            await self.create_app_token()
            return await self.make_api_request(
                method, url, params=params, json=json, retry=True
            )
        elif response.status == 429 and not retry:
            time_to_sleep = int(response.headers.get("Ratelimit-Reset", time())) - int(
                time()
            )
            if time_to_sleep <= 0:
                time_to_sleep = 1
            await asyncio.sleep(time_to_sleep)
            return await self.make_api_request(
                method, url, params=params, json=json, retry=True
            )
        return response

    async def process_event(self, request: Request, response: Response) -> Response:
        response.status_code = 204
        body = await request.body()
        try:
            event = json.loads(body)
        except json.JSONDecodeError:
            response.status_code = 400
            response.init_headers()
            return response
        message_type = request.headers.get("Twitch-Eventsub-Message-Type", "")
        type = event["subscription"]["type"]
        user_id = event["subscription"]["condition"]["broadcaster_user_id"]
        wrong_request = (
            (not self.verify_hmac(request, body))
            + (not self.verify_time(request))
            + (type not in EVENTS)
            + (
                message_type
                not in ("notification", "webhook_callback_verification", "revocation")
            )
        )
        if wrong_request != 0:
            response.status_code = 403
        elif message_type == "notification":
            await EVENTS[type](event)
        elif message_type == "webhook_callback_verification":
            challenge = event["challenge"]
            response.status_code = 200
            response.media_type = "text/plain"
            response.body = response.render(challenge)
            await config.update(
                user_id, set={type.replace(".", ""): event["subscription"]["id"]}
            )
        elif message_type == "revocation":
            await config.update(user_id, set={type.replace(".", ""): None})
            if type == "stream.online":
                online = (await config.get("online"))["value"]
                online.remove(user_id)
                await config.put({"key": "online", "value": online})
            elif type == "stream.offline":
                offline = (await config.get("offline"))["value"]
                offline.remove(user_id)
                await config.put({"key": "offline", "value": offline})
            elif type == "channel.update":
                update = (await config.get("update"))["value"]
                update.remove(user_id)
                await config.put({"key": "update", "value": update})

        response.init_headers()
        return response

    @staticmethod
    def verify_hmac(request: Request, body: bytes) -> bool:
        twitch_hmac = request.headers.get(
            "Twitch-Eventsub-Message-Signature", ""
        ).replace("sha256=", "")
        my_hmac = hmac.digest(
            getenv("secret").encode(),
            request.headers.get("Twitch-Eventsub-Message-Id", "").encode()
            + request.headers.get("Twitch-Eventsub-Message-Timestamp", "").encode()
            + body,
            hashlib.sha256,
        ).hex()
        return hmac.compare_digest(twitch_hmac, my_hmac)

    @staticmethod
    def verify_time(request: Request) -> bool:
        twitch_time = parse(
            request.headers.get(
                "Twitch-Eventsub-Message-Timestamp", "2000-01-01T00:00:00Z"
            )
        )

        my_time = datetime.utcnow().replace(tzinfo=timezone.utc)
        return my_time - twitch_time < timedelta(days=0, seconds=600)


if __name__ == "__main__":
    import asyncio

    async def main():
        twitch = Twitch(get("Client_Id"), get("Client_Secret"))
        print(await twitch.combine_channel_data(["240473610"]))

    asyncio.run(main())
