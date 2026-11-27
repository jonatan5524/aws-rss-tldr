import os
import re
import json
import html
import time
import random
import logging
import requests
import feedparser
import openai
import boto3
from datetime import datetime, timedelta

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# OpenRouter calls can transiently fail with 429 (rate limited) or 5xx
# (a specific upstream model/provider overloaded). Retry those with
# exponential backoff instead of dropping the whole daily digest on a
# momentary capacity blip. The models/provider fallback list (below)
# already reroutes around a single busy model/host; this retry loop
# covers the case where the whole chain is briefly unavailable.
RETRYABLE_STATUS = {429, 500, 502, 503, 504}
MAX_ATTEMPTS = 8
BACKOFF_BASE_SECONDS = 2
BACKOFF_MAX_SECONDS = 120
# Keep this much time free at the end of the Lambda invocation so the
# final Telegram send (and error logging) always has a chance to run,
# even if we're mid-retry when time starts running out.
LAMBDA_TIME_BUFFER_MS = 60_000

MAX_ARTICLE_SUMMARY_CHARS = 1500

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

ssm = boto3.client("ssm")

SSM_OPENROUTER_API_KEY = os.environ["SSM_OPENROUTER_API_KEY_NAME"]
SSM_TELEGRAM_TOKEN = os.environ["SSM_TELEGRAM_BOT_TOKEN"]
SSM_TELEGRAM_CHAT_ID = os.environ["SSM_TELEGRAM_CHAT_ID"]
PRIMARY_MODEL = os.environ["PRIMARY_MODEL"]
FALLBACK_MODELS = [m for m in os.environ.get("FALLBACK_MODELS", "").split(",") if m]


def send_to_telegram(summary: str):
    """Fallback plain-text sender: used for the 'no news today' message, and
    if the model's output doesn't come back as the structured JSON the
    per-article sender (send_articles_to_telegram) expects."""
    try:
        telegram_token = get_secret(SSM_TELEGRAM_TOKEN)
        chat_id = get_secret(SSM_TELEGRAM_CHAT_ID)

        # Prepare message with proper length handling
        msg_header = "📰 AWS Daily News:\n\n"
        msg_content = summary

        # Telegram limit is 4096 characters
        max_content_length = 4096 - len(msg_header) - 50  # Leave some buffer

        telegram_url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"

        def send_chunk(text, retry_without_markdown=True):
            try:
                resp = requests.post(
                    telegram_url,
                    json={
                        "chat_id": chat_id,
                        "text": text,
                        "parse_mode": "Markdown",
                        "disable_web_page_preview": True,
                        "disable_notification": True,
                    },
                    timeout=30
                )

                # If Markdown parsing fails (Status 400), retry without it
                if resp.status_code == 400 and retry_without_markdown:
                    logger.warning(f"Telegram Markdown failed, retrying raw. Error: {resp.text}")
                    resp = requests.post(
                        telegram_url,
                        json={
                            "chat_id": chat_id,
                            "text": text,
                            # parse_mode omitted
                            "disable_web_page_preview": True,
                            "disable_notification": True,
                        },
                        timeout=30
                    )

                if resp.status_code != 200:
                    logger.error(f"Telegram API response: {resp.text}")
                    # Don't raise immediately on 400 if retried? No, if the retry failed too, or if status != 200
                    raise RuntimeError(f"Telegram API error {resp.status_code}: {resp.text}")
            except Exception as e:
                raise e

        if len(msg_content) <= max_content_length:
            # Message fits in one part
            final_msg = msg_header + msg_content
            logger.info(f"Sending single message of {len(final_msg)} characters")
            send_chunk(final_msg)
        else:
            # Message needs to be split into multiple parts
            parts = []
            remaining_content = msg_content
            part_num = 1

            while remaining_content:
                if part_num == 1:
                    # First part includes the header
                    available_space = max_content_length
                    part_header = msg_header
                else:
                    # Subsequent parts have continuation header
                    part_header = f"📰 AWS Daily News (Part {part_num}):\n\n"
                    available_space = 4096 - len(part_header) - 50

                if len(remaining_content) <= available_space:
                    # Last part
                    parts.append(part_header + remaining_content)
                    break
                else:
                    # Search window
                    search_text = remaining_content[:available_space]

                    # 1. Try to split at article delimiter "---"
                    cut_point = search_text.rfind('\n---')

                    # 2. Fallback to double newline (paragraph break)
                    if cut_point == -1:
                        cut_point = search_text.rfind('\n\n')

                    # 3. Fallback to single newline
                    if cut_point == -1:
                        cut_point = search_text.rfind('\n')

                    # 4. Fallback to space
                    if cut_point == -1:
                        cut_point = search_text.rfind(' ')

                    # 5. Hard cut
                    if cut_point == -1:
                        cut_point = available_space

                    parts.append(part_header + remaining_content[:cut_point])
                    remaining_content = remaining_content[cut_point:].lstrip()
                    part_num += 1

            logger.info(f"Splitting message into {len(parts)} parts")

            # Send each part
            for i, part in enumerate(parts, 1):
                logger.info(f"Sending part {i}/{len(parts)} ({len(part)} characters)")
                send_chunk(part)

                # Small delay between messages to avoid rate limiting
                import time
                if i < len(parts):  # Don't delay after the last message
                    time.sleep(1)

    except Exception as e:
        logger.error(f"Failed to send Telegram message: {e}")
        return {"statusCode": 500, "body": "Telegram send error"}

    # --- Success
    logger.info("Message sent successfully")
    return {"statusCode": 200, "body": "Success"}


def escape_html(text) -> str:
    return html.escape(str(text or ""), quote=False)


def build_article_message(article: dict):
    """Build the (text, reply_markup) pair for one article's Telegram message.

    Overview/before/now go in an expandable blockquote so the message reads
    as a short headline + what's-new line, with detail collapsed under a tap.
    """
    service = escape_html(article.get("service", ""))
    title = escape_html(article.get("title", ""))
    whats_new = escape_html(article.get("whats_new", ""))
    overview = escape_html(article.get("service_overview", ""))
    before = escape_html(article.get("before", ""))
    now_ = escape_html(article.get("now", ""))
    link = article.get("link", "")

    text = (
        f"<b>🌐 {service} – {title}</b>\n\n"
        f"🚀 <b>What's New?</b> {whats_new}\n\n"
        f"<blockquote expandable>"
        f"🏗️ <b>Service Overview:</b> {overview}\n\n"
        f"⏳ <b>Before:</b> {before}\n\n"
        f"🔄 <b>Now:</b> {now_}"
        f"</blockquote>"
    )

    reply_markup = None
    if link:
        reply_markup = {"inline_keyboard": [[{"text": "🔗 Read on AWS", "url": link}]]}

    return text, reply_markup


def send_articles_to_telegram(articles: list):
    """Send one Telegram message per article: HTML formatting, an inline
    'Read on AWS' button per article, collapsed detail via an expandable
    blockquote, and silent delivery for a daily digest."""
    try:
        telegram_token = get_secret(SSM_TELEGRAM_TOKEN)
        chat_id = get_secret(SSM_TELEGRAM_CHAT_ID)
        telegram_url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"

        def post(payload):
            resp = requests.post(telegram_url, json=payload, timeout=30)
            if resp.status_code != 200:
                logger.error(f"Telegram API response: {resp.text}")
                raise RuntimeError(f"Telegram API error {resp.status_code}: {resp.text}")

        count = len(articles)
        post({
            "chat_id": chat_id,
            "text": f"📰 <b>AWS Daily News</b> — {count} update{'s' if count != 1 else ''} today",
            "parse_mode": "HTML",
            "disable_notification": True,
        })

        for i, article in enumerate(articles, 1):
            text, reply_markup = build_article_message(article)
            payload = {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
                "disable_notification": True,
            }
            if reply_markup:
                payload["reply_markup"] = reply_markup

            logger.info(f"Sending article {i}/{count}")
            post(payload)

            if i < count:
                time.sleep(1)

    except Exception as e:
        logger.error(f"Failed to send Telegram message: {e}")
        return {"statusCode": 500, "body": "Telegram send error"}

    logger.info("Digest sent successfully")
    return {"statusCode": 200, "body": "Success"}


def parse_articles_json(raw: str) -> list:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.IGNORECASE)
    data = json.loads(cleaned)
    if not isinstance(data, list):
        raise ValueError("Expected a JSON array of articles")
    return data


def get_secret(name):
    return ssm.get_parameter(Name=name, WithDecryption=True)["Parameter"]["Value"]


def generate_summary_with_retry(client, prompt, context):
    """Call OpenRouter, retrying transient overload/rate-limit errors with backoff.

    OpenRouter's `models` list already fails over to a different model/host
    on most errors (provider-level routing is automatic; model-level routing
    is this explicit fallback list). This retry loop covers the case where
    the whole fallback chain is briefly unavailable at once.

    Backoff is capped by how much Lambda execution time is left, so we never
    get killed mid-sleep with no error logged and nothing sent to Telegram.
    """
    models = [PRIMARY_MODEL] + FALLBACK_MODELS
    last_exc = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = client.chat.completions.create(
                model=models[0],
                messages=[{"role": "user", "content": prompt}],
                extra_body={"models": models} if len(models) > 1 else {},
            )
            logger.info(f"Summary generated by model: {response.model}")
            return response.choices[0].message.content
        except openai.APIStatusError as e:
            status = e.status_code
            if status not in RETRYABLE_STATUS or attempt == MAX_ATTEMPTS:
                raise
            last_exc = e

            remaining_ms = context.get_remaining_time_in_millis()
            if remaining_ms <= LAMBDA_TIME_BUFFER_MS:
                logger.warning(
                    f"OpenRouter call failed (status {status}) but only {remaining_ms}ms "
                    "remain in this invocation; giving up instead of retrying"
                )
                raise

            base_sleep = min(
                BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)),
                BACKOFF_MAX_SECONDS,
            )
            sleep_seconds = base_sleep * (0.5 + random.random())  # jitter
            max_sleep_seconds = (remaining_ms - LAMBDA_TIME_BUFFER_MS) / 1000
            sleep_seconds = min(sleep_seconds, max_sleep_seconds)

            logger.warning(
                f"OpenRouter call failed (status {status}, attempt {attempt}/{MAX_ATTEMPTS}); "
                f"retrying in {sleep_seconds:.1f}s"
            )
            time.sleep(sleep_seconds)
    # Should be unreachable, but re-raise the last error defensively.
    raise last_exc


def strip_html(text: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", text or "")).strip()

def lambda_handler(event, context):
    try:

        # --- Step 1: Fetch AWS News RSS

        rss_url = "https://aws.amazon.com/about-aws/whats-new/recent/feed/"
        try:
            feed = feedparser.parse(rss_url)
            if not feed.entries:
                raise ValueError("No entries found in AWS RSS feed")
        except Exception as e:
            logger.error(f"Failed to fetch/parse RSS: {e}")
            return {"statusCode": 500, "body": "RSS fetch error"}

        # Filter entries from the past 24 hours
        now = datetime.now()
        past_24h = now - timedelta(hours=24)
        article_blocks = []

        for entry in feed.entries:
            # Parse the published date
            if hasattr(entry, 'published_parsed') and entry.published_parsed:
                entry_date = datetime(*entry.published_parsed[:6])
                if entry_date >= past_24h:
                    link = entry.get("link", "")
                    title = entry.get("title", "")
                    body = strip_html(entry.get("summary", ""))[:MAX_ARTICLE_SUMMARY_CHARS]
                    if link:
                        article_blocks.append(f"Title: {title}\nLink: {link}\nContent: {body}")

        if not article_blocks:
            logger.info("No AWS news found in the past 24 hours")
            return send_to_telegram("No AWS news found in the past 24 hours")

        # --- Step 2: Summarize with OpenRouter
        try:
            client = openai.OpenAI(
                base_url=OPENROUTER_BASE_URL,
                api_key=get_secret(SSM_OPENROUTER_API_KEY),
            )
            aws_news_prompt = """
You are an expert AWS news assistant. I will provide AWS RSS news articles (title, link, and
article content). Return ONLY a raw JSON array — no markdown code fences, no extra text before
or after it — where each element is an object with exactly these string fields:
- "service": the AWS service or feature name
- "title": a short, specific headline for the announcement
- "whats_new": 1-2 sentences summarizing the new announcement
- "service_overview": brief explanation of what this AWS service does and its primary use cases
- "before": what was possible/limited before this change
- "now": what changed
- "link": the article URL, copied exactly from the input

🎯 Audience: AWS developers, architects, and operations engineers who care about technical
details, architectural impact, and practical utility. Skip marketing fluff.

⚠️ Rules:
- Base every field on the article content provided — never guess from the title alone.
- Only include AWS news from the provided articles.
- Keep each field concise (1-3 sentences) but technically useful — a *real* TLDR, not copied
  marketing text.
"""

            raw_response = generate_summary_with_retry(
                client,
                aws_news_prompt + "\n\nHere are the news articles:\n\n" + "\n\n".join(article_blocks),
                context,
            )
        except Exception as e:
            logger.error(f"OpenRouter summarization failed: {e}")
            # Re-raise (instead of returning a 500 body) so this counts as a
            # failed invocation and EventBridge's async retry of the Lambda
            # kicks in, rather than being swallowed as a "successful" 500.
            raise

        # --- Step 3: Send to Telegram
        try:
            articles = parse_articles_json(raw_response)
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"Model didn't return valid article JSON ({e}); falling back to plain text")
            return send_to_telegram(raw_response)

        if not articles:
            return send_to_telegram("No AWS news found in the past 24 hours")

        return send_articles_to_telegram(articles)

    except Exception:
        logger.exception("Unhandled error")
        raise
