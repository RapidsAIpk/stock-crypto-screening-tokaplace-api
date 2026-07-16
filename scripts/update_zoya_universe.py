# scripts/update_zoya_universe.py


import httpx
import json
import asyncio
from pathlib import Path
import os
from dotenv import load_dotenv

load_dotenv()

ZOYA_API_KEY = os.getenv("ZOYA_API_KEY")
COINMARKETCAP_API_KEY = os.getenv("COINMARKETCAP_API_KEY")

ZOYA_ENDPOINT = "https://api.zoya.finance/graphql"

OUTPUT_FILE = Path("data/zoya_universe.json")


QUERY_TEMPLATE = """
query getReport {
  basicCompliance {
    reports(input: %s) {
      items {
        name
        symbol
        status
        reportDate
        purificationRatio
        exchange
      }
      nextToken
    }
  }
}
"""


async def fetch_page(client, next_token=None):

    if next_token:
        input_block = f'{{nextToken: "{next_token}"}}'
    else:
        input_block = "{}"

    query = QUERY_TEMPLATE % input_block

    response = await client.post(
        ZOYA_ENDPOINT,
        json={"query": query},
        headers={
            "Authorization": ZOYA_API_KEY,
            "Content-Type": "application/json"
        },
        timeout=30
    )

    if response.status_code != 200:
        raise Exception("Zoya request failed")

    payload = response.json()

    if "errors" in payload:
        raise Exception(payload["errors"])

    data = payload["data"]["basicCompliance"]["reports"]

    return data["items"], data["nextToken"]


async def download_all_stocks():

    print("Downloading Zoya universe...")

    all_items = []
    next_token = None

    async with httpx.AsyncClient() as client:

        while True:

            items, next_token = await fetch_page(client, next_token)

            print(f"Fetched {len(items)} stocks")

            all_items.extend(items)

            if not next_token:
                break

    print("Total stocks:", len(all_items))

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    with open(OUTPUT_FILE, "w") as f:
        json.dump(all_items, f, indent=2)

    print("Saved to:", OUTPUT_FILE)


if __name__ == "__main__":
    asyncio.run(download_all_stocks())
