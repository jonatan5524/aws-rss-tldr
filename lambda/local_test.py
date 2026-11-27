"""Run lambda_handler locally without AWS: secrets come from env vars
instead of SSM, so you need no AWS credentials and nothing gets deployed.

Usage:
    cd lambda
    pip install -r requirements.txt
    export TEST_OPENROUTER_API_KEY=...
    export TEST_TELEGRAM_BOT_TOKEN=...
    export TEST_TELEGRAM_CHAT_ID=...   # your own chat/test group, NOT the live channel
    python local_test.py
"""
import os
from unittest import mock

os.environ.setdefault("AWS_DEFAULT_REGION", "il-central-1")
os.environ.setdefault("SSM_OPENROUTER_API_KEY_NAME", "local_openrouter_key")
os.environ.setdefault("SSM_TELEGRAM_BOT_TOKEN", "local_telegram_token")
os.environ.setdefault("SSM_TELEGRAM_CHAT_ID", "local_telegram_chat_id")
os.environ.setdefault("PRIMARY_MODEL", "google/gemma-4-31b-it:free")
os.environ.setdefault(
    "FALLBACK_MODELS",
    "nvidia/nemotron-3.5-lightning:free,baidu/ernie-5.5-flash-preview:free",
)

import handler  # noqa: E402  (must import after env vars are set)

_SECRETS = {
    os.environ["SSM_OPENROUTER_API_KEY_NAME"]: os.environ["TEST_OPENROUTER_API_KEY"],
    os.environ["SSM_TELEGRAM_BOT_TOKEN"]: os.environ["TEST_TELEGRAM_BOT_TOKEN"],
    os.environ["SSM_TELEGRAM_CHAT_ID"]: os.environ["TEST_TELEGRAM_CHAT_ID"],
}


def fake_get_secret(name):
    return _SECRETS[name]


class FakeLambdaContext:
    def get_remaining_time_in_millis(self):
        return 600_000


if __name__ == "__main__":
    with mock.patch("handler.get_secret", side_effect=fake_get_secret):
        result = handler.lambda_handler({}, FakeLambdaContext())
        print(result)
