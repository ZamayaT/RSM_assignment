"""Checks the assistant's model configuration: does the configured model answer, and does it call tools?

    python -m app.assistant.probe --list-free     # OpenRouter: free models that support tools (no key needed)
    python -m app.assistant.probe                 # check the model set in .env
    python -m app.assistant.probe --model NAME    # check another model without editing .env

It sends two short requests: a plain question, then a question that needs a sample tool, and gives the tool's
result back. The key is only sent to the configured API; it is never printed or logged.
"""
import argparse
import json
import sys
import time

import httpx

from app.config import get_settings

SAMPLE_TOOL = {
    "type": "function",
    "function": {
        "name": "get_trip_name",
        "description": "Returns the name of a trip. Use it whenever the user asks for the name of a trip.",
        "parameters": {
            "type": "object",
            "properties": {"trip_id": {"type": "string", "description": "The trip identifier."}},
            "required": ["trip_id"],
        },
    },
}


def chat(base_url: str, key: str, body: dict, timeout: float) -> httpx.Response:
    return httpx.post(
        f"{base_url.rstrip('/')}/chat/completions",
        json=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        timeout=timeout,
    )


def explain(response: httpx.Response) -> str:
    """A short reason for a failed request, without echoing anything secret."""
    if response.status_code == 401 or response.status_code == 403:
        return "the provider rejected the key (check LLM_API_KEY)"
    if response.status_code == 404:
        return "model or endpoint not found (check LLM_MODEL and LLM_BASE_URL)"
    try:
        detail = response.json().get("error", {})
        message = detail.get("message") if isinstance(detail, dict) else str(detail)
        upstream = (detail.get("metadata") or {}).get("raw") if isinstance(detail, dict) else None
    except ValueError:
        message, upstream = response.text[:200], None
    if response.status_code == 429:
        retry = response.headers.get("Retry-After")
        reason = f"rate limited by the provider: {message}"
        if upstream:
            reason += f" (upstream said: {str(upstream)[:160]})"
        return reason + (f"; retry after {retry}s" if retry else "; wait a minute or try another model")
    return f"HTTP {response.status_code}: {message}"


def list_free(base_url: str, timeout: float) -> int:
    """OpenRouter's public model list: models that cost nothing and say they support tools."""
    try:
        response = httpx.get(f"{base_url.rstrip('/')}/models", timeout=timeout)
        response.raise_for_status()
        models = response.json()["data"]
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        print(f"Could not read the model list from {base_url}: {exc}")
        return 1
    free = [
        m
        for m in models
        if str(m.get("pricing", {}).get("prompt")) == "0"
        and str(m.get("pricing", {}).get("completion")) == "0"
        and "tools" in (m.get("supported_parameters") or [])
    ]
    if not free:
        print("No free model with tool support was listed (this command only works with OpenRouter).")
        return 1
    print(f"{len(free)} free model(s) that support tools (set one as LLM_MODEL, then run the probe):")
    for m in sorted(free, key=lambda item: -(item.get("context_length") or 0)):
        print(f"  {m['id']}   context {m.get('context_length')}")
    return 0


def check_model(base_url: str, key: str, model: str, timeout: float) -> int:
    results: list[tuple[str, bool, str]] = []

    def step(name: str, ok: bool, detail: str) -> bool:
        results.append((name, ok, detail))
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}: {detail}")
        return ok

    print(f"Model {model} at {base_url}")
    started = time.monotonic()
    try:
        plain = chat(base_url, key, {"model": model, "messages": [{"role": "user", "content": "Reply with the single word: ready"}]}, timeout)
    except httpx.TimeoutException:
        step("plain answer", False, f"no answer within {timeout:.0f} s (raise LLM_TIMEOUT_SECONDS or pick a faster model)")
        return 1
    except httpx.HTTPError as exc:
        step("plain answer", False, f"cannot reach the API: {exc.__class__.__name__}")
        return 1
    if plain.status_code != 200:
        step("plain answer", False, explain(plain))
        return 1
    text = (plain.json()["choices"][0]["message"].get("content") or "").strip()
    step("plain answer", bool(text), f"{text[:60]!r} in {time.monotonic() - started:.1f} s")

    messages = [{"role": "user", "content": "What is the name of the trip with id trip-42? Use the tool."}]
    started = time.monotonic()
    try:
        first = chat(base_url, key, {"model": model, "messages": messages, "tools": [SAMPLE_TOOL], "tool_choice": "auto"}, timeout)
    except httpx.HTTPError as exc:
        step("tool call", False, f"request failed: {exc.__class__.__name__}")
        return 1
    if first.status_code != 200:
        step("tool call", False, explain(first))
        return 1
    message = first.json()["choices"][0]["message"]
    calls = message.get("tool_calls") or []
    if not calls:
        step("tool call", False, "the model answered without calling the tool (it may not support tools well)")
        return 1
    call = calls[0]
    try:
        arguments = json.loads(call["function"]["arguments"] or "{}")
    except ValueError:
        arguments = None
    valid = call["function"]["name"] == "get_trip_name" and isinstance(arguments, dict) and arguments.get("trip_id") == "trip-42"
    step("tool call", valid, f"{call['function']['name']}({call['function']['arguments']}) in {time.monotonic() - started:.1f} s")
    if not valid:
        return 1

    messages += [message, {"role": "tool", "tool_call_id": call["id"], "content": json.dumps({"name": "Lisbon in spring"})}]
    try:
        final = chat(base_url, key, {"model": model, "messages": messages, "tools": [SAMPLE_TOOL]}, timeout)
    except httpx.HTTPError as exc:
        step("answer from the tool result", False, f"request failed: {exc.__class__.__name__}")
        return 1
    if final.status_code != 200:
        step("answer from the tool result", False, explain(final))
        return 1
    answer = (final.json()["choices"][0]["message"].get("content") or "").strip()
    step("answer from the tool result", "lisbon" in answer.lower(), answer[:80].replace("\n", " "))
    ok = all(passed for _, passed, _ in results)
    print("The model is usable for the assistant." if ok else "The model is not reliable enough: try another one.")
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Check the assistant's model configuration.")
    parser.add_argument("--list-free", action="store_true", help="list free OpenRouter models that support tools")
    parser.add_argument("--model", help="model to check instead of LLM_MODEL")
    args = parser.parse_args()
    settings = get_settings()
    if args.list_free:
        return list_free(settings.llm_base_url, 15)
    model = args.model or settings.llm_model
    key = settings.llm_api_key.get_secret_value()
    if not key or not model:
        missing = [name for name, value in (("LLM_API_KEY", key), ("LLM_MODEL", model)) if not value]
        print(f"The assistant is not configured: set {' and '.join(missing)} in .env (see .env.example).")
        return 1
    return check_model(settings.llm_base_url, key, model, settings.llm_timeout_seconds)


if __name__ == "__main__":
    sys.exit(main())
