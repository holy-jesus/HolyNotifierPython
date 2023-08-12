from os import getenv
from aiohttp import ClientSession
from time import perf_counter


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


if __name__ == "__main__":
    start = perf_counter()
    print(smart_escape("*[Olesha] поменял название*\n*Новое название"))
    print(perf_counter() - start)
