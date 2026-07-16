import os

import requests

api_key = os.environ["COINMARKETCAP_API_KEY"]
url = 'https://pro-api.coinmarketcap.com/v2/cryptocurrency/market-pairs/latest'

parameters = {
  'id': '1', # 1 is for Bitcoin
  'limit': '10' # Number of exchanges to return
}

headers = {
  'Accepts': 'application/json',
  'X-CMC_PRO_API_KEY': api_key,
}

response = requests.get(url, params=parameters, headers=headers)
data = response.json()
print(data)
