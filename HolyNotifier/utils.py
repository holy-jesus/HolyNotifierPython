from os import getenv
from aiohttp import ClientSession
from template import Template
from functools import partial
import time


def escape_symbols(input_string):
    symbols_to_escape = [
        "_",
        "*",
        "[",
        "]",
        "(",
        ")",
        "~",
        "`",
        ">",
        "#",
        "+",
        "-",
        "=",
        "|",
        "{",
        "}",
        ".",
        "!",
    ]
    escaped_string = input_string
    for symbol in symbols_to_escape:
        escaped_string = escaped_string.replace(symbol, "\\" + symbol)
    return escaped_string


def get(key: str):
    value = getenv(key)
    if value and "Insert " in value and " here" in value:
        value = None
    return value


def get_channel_value(key: str, channel: dict, event: dict):
    return channel.get(key, None)


def get_event_value(key: str, channel: dict, event: dict):
    DICT = {"category_name": "category"}
    return (
        event["event"].get(key, None)
        if channel[DICT.get(key, key)] != event["event"].get(key, None)
        else None
    )


def gametime(key: str, channel: dict, event: dict):
    if channel["is_live"]:
        game_time = (
            channel["game_time"][channel["category"]]
            if channel["game_time"] and channel["category"] in channel["game_time"]
            else 0
        )
        if not game_time:
            return time.strftime(
                "%H:%M:%S", time.gmtime(time.time() - channel["game_timestamp"])
            )
        return time.strftime("%H:%M:%S", time.gmtime(game_time))
    else:
        return None


def games(key: str, channel: dict, event: dict):
    if channel["is_live"]:
        if channel["game_time"]:
            games = ""
            for game, gametime in channel["game_time"].items():
                played_time = gametime
                if game == channel["category"]:
                    played_time += time.time() - channel["game_timestamp"]
                if played_time < 60:
                    continue
                games += (
                    f'{game} [{time.strftime("%H:%M:%S", time.gmtime(played_time))}] | '
                )
            if channel["category"] not in channel["game_time"]:
                games += f'{channel["category"]} [{time.strftime("%H:%M:%S", time.gmtime(time.time() - channel["game_timestamp"]))}] | '
            games = games[:-3]
        else:
            games = f'{channel["category"]} [{time.strftime("%H:%M:%S", time.gmtime(time.time() - channel["game_timestamp"]))}]'
        return games
    else:
        return None


def uptime(key: str, channel: dict, event: dict):
    if channel["is_live"]:
        return time.strftime(
            "%H:%M:%S", time.gmtime(time.time() - channel["started_at"])
        )
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
        "categories": partial(games, None, channel, event),
        "gametime": partial(gametime, None, channel, event),
        "stream_url": partial(stream_url, None, channel, event),
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
            if (
                value is None
                and identifier in ("gametime", "uptime", "categories", "new_category", "new_title")
                and len(identifiers) == 1
            ):
                skip_line = True
                break
            mapped[identifier] = escape_symbols(value or "-")
        if skip_line:
            continue
        final_text += template.safe_substitute(mapped) + "\n"
    return smart_escape(final_text[:-1])


session = None


async def get_session() -> ClientSession:
    global session
    if session is None:
        session = ClientSession()
    return session


def smart_escape(text: str) -> str:
    og_text = text
    # Добавить поддержку ``````
    for symbol in [">", "#", "+", "-", "=", "{", "}", ".", "!"]:
        text = text.replace(symbol, f"\\{symbol}")
    if "|" in text:
        text = text.replace("|", "\\|")
        if text.count("\\|\\|") % 2 == 0:
            text = text.replace("\\|\\|", "||")
    new = ""
    for line in text.split("\n"):
        for symbol in ["*", "_", "~", "`"]:
            aline = line.replace(f"\\{symbol}", "")
            if aline.count(symbol) % 2:
                line = line.replace(symbol, f"\\{symbol}")
        if "[" in line and "](" in line and ")" in line:
            if "[]" in line or "()" in line:
                for symbol in "[]()":
                    line = line.replace(symbol, f"\\{symbol}")
            else:
                for symbol in "[](://)":
                    aline = line.replace(f"\\{symbol}", "")
                wrong = False
                i = -1
                prev_i = -1
                for symbol in "[](://)":
                    i = aline.find(symbol, i + 1)
                    if i == -1 or i < prev_i:
                        wrong = True
                        break
                if wrong:
                    for symbol in "[]()":
                        line = line.replace(symbol, f"\\{symbol}")
        elif "[" in line or "]" in line or "(" in line or ")" in line:
            for symbol in "[]()":
                line = line.replace(symbol, f"\\{symbol}")
        new += line + "\n"
    new = new[:-1]
    while "\\\\" in new:
        # Использовать og_text для того чтобы игнорировать \\\\, если они есть в оригинальном тексте
        new = new.replace("\\\\", "\\")
    cant_be_empty = ["*", "||", "__", "~", "`"]
    for symbol in cant_be_empty:
        if symbol * 2 in new:
            new = new.replace(symbol * 2, ("\\" + "\\".join(symbol)) * 2)
    return new
