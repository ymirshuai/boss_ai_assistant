
import requests

def call_master(title, content, key="PQVm8D2MwdJmbmrWQv3hHD"):
    url = f"https://api.day.app/{key}/{title}/{content}"
    requests.get(url).raise_for_status()
