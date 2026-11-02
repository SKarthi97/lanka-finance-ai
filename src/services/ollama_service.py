import requests

from config import OLLAMA_URL, OLLAMA_MODEL


def get_ollama_status():

    try:

        response = requests.get(
            f"{OLLAMA_URL}/api/tags",
            timeout=3
        )

        response.raise_for_status()

        return response.json()

    except requests.RequestException:
        return None


def get_installed_models():

    status = get_ollama_status()

    if not status:
        return []

    return [
        model.get("name", "")
        for model in status.get("models", [])
    ]


def is_model_available(model=OLLAMA_MODEL):

    installed = get_installed_models()

    return any(
        name == model or name.split(":")[0] == model
        for name in installed
    )


def ask_ollama(prompt, model=OLLAMA_MODEL):

    try:

        response = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "stream": False
            },
            timeout=120
        )

        response.raise_for_status()

        return response.json().get("response", "")

    except requests.RequestException as error:

        raise RuntimeError(
            f"Ollama request failed: {error}"
        )