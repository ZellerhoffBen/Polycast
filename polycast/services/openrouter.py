import os

import requests


def request(endpoint, payload):
    key = os.environ.get("API_KEY")
    if not key:
        raise ValueError("Der OpenRouter-API-Key fehlt in der .env-Datei des Backends.")
    # Both text and speech go through the same provider settings and timeout.
    response = requests.post(
        f"https://openrouter.ai/api/v1/{endpoint}",
        headers={"Authorization": f"Bearer {key}"},
        json={**payload, "provider": {"data_collection": "deny"}},
        timeout=(10, 180),
    )
    response.raise_for_status()
    return response
