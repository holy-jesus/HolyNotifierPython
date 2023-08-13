import asyncio
from os import getenv
from urllib.parse import quote

from utils import get_session


class Base:
    def __init__(self, base_name: str) -> None:
        # I know that https://github.com/jnsougata/deta exists, but i like to do all by myself :)  
        self.session = None
        self.project_key = getenv("DETA_PROJECT_KEY", "")
        self.project_id = self.project_key.split("_")[0]
        self.base_name = base_name

    async def put(self, items: list[dict]):
        # https://deta.space/docs/en/build/reference/http-api/base#put-items
        if isinstance(items, dict):
            items = [items]
        return await self.make_api_request("PUT", "items", json={"items": items})

    async def get(self, key: str, default = None) -> dict:
        # https://deta.space/docs/en/build/reference/http-api/base#get-item
        response = await self.make_api_request("GET", f"items/{quote(key)}")
        return response if len(response) > 1 else default

    async def get_many(self, keys: list[str]):
        loop = asyncio.get_event_loop()
        tasks = []
        for key in keys:        
            tasks.append(loop.create_task(self.get(key)))
        return await asyncio.gather(*tasks)

    async def delete(self, key: str) -> None:
        # https://deta.space/docs/en/build/reference/http-api/base#delete-item
        await self.make_api_request("DELETE", f"items/{quote(key)}")

    async def update(
        self,
        key: str,
        *,
        set: dict = None,
        increment: dict = None,
        append: dict = None,
        prepend: dict = None,
        delete: list[str] = None,
    ):
        # https://deta.space/docs/en/build/reference/http-api/base#update-item
        payload = {}
        if set:
            payload["set"] = set
        if increment:
            payload["increment"] = increment
        if append:
            payload["append"] = append
        if prepend:
            payload["prepend"] = prepend
        if delete:
            payload["delete"] = delete
        return await self.make_api_request(
            "PATCH", f"items/{quote(key)}", json=payload or None
        )

    async def query(self, query: list = None, limit: int = None, last: str = None):
        # https://deta.space/docs/en/build/reference/http-api/base#query-items
        # https://deta.space/docs/en/build/reference/deta-base/queries
        payload = {}
        if query:
            payload["query"] = query
        if limit:
            payload["limit"] = limit
        if last:
            payload["last"] = last
        return await self.make_api_request("POST", "query", json=payload or None)

    async def make_api_request(
        self, method: str, endpoint: str, json: dict = None
    ) -> dict:
        if self.session is None:
            self.session = await get_session()
        response = await self.session.request(
            method,
            f"https://database.deta.sh/v1/{self.project_id}/{self.base_name}/{endpoint}",
            headers={"X-API-Key": self.project_key, "Content-Type": "application/json"},
            json=json,
        )
        return await response.json()


if __name__ == "__main__":
    import asyncio

    async def main():
        base = Base("dev_config")

    asyncio.run(main())
