"""Source-level guards for the promises in the docs: no SQL built from text, nothing leaves the machine."""

import re
from pathlib import Path

from .test_extraction import run_pipeline
from .test_planning import september

APP = Path(__file__).resolve().parents[1] / "app"
SOURCES = {p: p.read_text(encoding="utf-8") for p in APP.rglob("*.py")}

# Modules allowed to open network connections, and why: they talk to the local model only
# (the address comes from OLLAMA_BASE_URL); the worker only asks for its own host name.
NETWORK_IMPORT = re.compile(r"^\s*(?:import|from)\s+(httpx|requests|urllib|socket|http\.client|aiohttp|smtplib|ftplib)\b", re.M)
ALLOWED_NETWORK = {
    "services/embeddings.py", "services/flags.py", "services/llm_classifier.py", "services/llm_json.py",
    "services/merchants.py", "services/ollama.py", "services/search.py", "services/summary.py",
    "worker.py",  # socket.gethostname() only
}


def rel(path: Path) -> str:
    return path.relative_to(APP).as_posix()


def test_only_the_local_model_modules_touch_the_network():
    offenders = {rel(p) for p, text in SOURCES.items() if NETWORK_IMPORT.search(text)} - ALLOWED_NETWORK
    assert not offenders, f"new network code outside the allowed modules: {sorted(offenders)}"


def test_model_clients_get_their_address_from_the_settings():
    for name in ALLOWED_NETWORK - {"worker.py"}:
        text = SOURCES[APP / name]
        assert not re.search(r"https?://(?!127\.|localhost)", text.replace("http://ollama", "")), name


def test_no_sql_is_built_from_strings():
    risky = re.compile(r"""(?:execute|text|exec_driver_sql)\(\s*(?:f["']|["'][^"']*["']\s*(?:%|\+|\.format))""")
    found = [rel(p) for p, text in SOURCES.items() if risky.search(text)]
    assert not found, f"SQL built from a string in: {found}"


def test_percent_and_underscore_in_a_search_are_not_wildcards(logged_in, session_factory, test_settings):
    client, csrf = logged_in
    run_pipeline(client, csrf, session_factory, test_settings, september())
    everything = client.get("/api/transactions?limit=50").json()["total"]
    assert everything >= 2
    for q in ("%", "_", "ATM_CASH", "100%"):
        assert client.get("/api/transactions", params={"q": q, "limit": 50}).json()["total"] == 0, q
    assert client.get("/api/transactions", params={"q": "ATM CASH", "limit": 50}).json()["total"] == 1
