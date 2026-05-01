import os
import random
import requests
import time

from dotenv import load_dotenv
from typing import List, Optional, Union, Dict, Any

load_dotenv()

class LLMClient:
    """Client to chat using OpenRouter models"""

    DEFAULT_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"

    def __init__(
        self,
        api_key_env: str = "OPENROUTER_API_KEY",
        api_key: Optional[str] = None,
        endpoint: Optional[str] = None,
        default_model: str = "openai/gpt-oss-20b:free",
    ):
        self.api_key = api_key or os.environ.get(api_key_env) or ""

        self.endpoint = endpoint or self.DEFAULT_ENDPOINT
        self.default_model = default_model

        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
        )

    def _build_messages(
        self,
        system: Optional[Union[str, List[str]]],
        user: Union[str, List[str]],
        extra: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        messages: List[Dict[str, Any]] = []
        if system:
            if isinstance(system, list):
                for s in system:
                    messages.append({"role": "system", "content": s})
            else:
                messages.append({"role": "system", "content": system})

        if isinstance(user, list):
            for u in user:
                messages.append({"role": "user", "content": u})
        else:
            messages.append({"role": "user", "content": user})

        if extra:
            messages.extend(extra)
        return messages

    def chat(
        self,
        system: Optional[Union[str, List[str]]] = None,
        user: Union[str, List[str]] = "",
        model: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: int = 512,
        stop: Optional[List[str]] = None,
        extra_messages: Optional[List[Dict[str, Any]]] = None,
        raw_response: bool = False,
    ) -> Union[str, Dict[str, Any]]:

        fallback_models = [
            "openai/gpt-oss-20b:free",
            "google/gemma-4-26b-a4b-it:free",
            "meta-llama/llama-3.3-70b-instruct:free",
            "nvidia/nemotron-3-nano-30b-a3b:free"
            "openrouter/free"
        ]

        # If user passed a model, try it first
        models_to_try = [model] + fallback_models if model else fallback_models

        payload_base = {
            "messages": self._build_messages(system, user, extra_messages),
            "temperature": float(temperature),
            "max_tokens": int(max_tokens),
        }
        if stop:
            payload_base["stop"] = stop

        last_error = None

        for model_name in models_to_try:
            print(f"Trying model: {model_name}")
            if model_name is None:
                continue

            payload = {**payload_base, "model": model_name}

            max_retries = 1

            for attempt in range(max_retries):
                try:
                    resp = self.session.post(
                        self.endpoint,
                        json=payload,  
                        timeout=60
                    )

                    if resp.status_code == 429:
                        if attempt == max_retries - 1:
                            raise RuntimeError(f"429 Rate limit (model={model_name})")
                        time.sleep(0.5)
                        continue

                    resp.raise_for_status()
                    data = resp.json()
                    print(f"LLM Data: {data}")
                    if raw_response:
                        return data

                    choices = data.get("choices") or []
                    if not choices:
                        if "output" in data:
                            return data["output"]
                        raise RuntimeError(f"Unexpected response shape: {data}")

                    contents = []
                    for ch in choices:
                        msg = ch.get("message") or {}
                        contents.append(msg.get("content") or "")

                    final_response = "\n".join(contents).strip()

                    if not final_response:
                        raise RuntimeError(f"Empty response from model {model_name}")
                    return final_response

                except Exception as e:
                    last_error = e

                    # If last retry → break to next model
                    if attempt == max_retries - 1:
                        break

                    time.sleep(0.5)

            # Try next model if current failed
            continue

        raise RuntimeError(f"All models failed. Last error: {last_error}")

# Helper
def get_llm_client(**kwargs) -> LLMClient:
    return LLMClient(**kwargs)