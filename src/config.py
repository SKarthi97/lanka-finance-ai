import os

APP_NAME = "Local Bank Statement Analyzer"

# Ollama runs in Docker and publishes port 11434 on the host.
# Override with environment variables if needed.
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")

OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:1.5b")

DATABASE_PATH = "data/bank_analyzer.db"

SUPPORTED_BANKS = [
    "Bank of Ceylon"
]

CURRENCY = "LKR"
