import os
import logging
import requests
import feedparser
import google.generativeai as genai
import boto3
from datetime import datetime, timedelta

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

ssm = boto3.client("ssm")

SSM_GEMINI_API_KEY = os.environ["SSM_GEMINI_API_KEY_NAME"]
SSM_TELEGRAM_TOKEN = os.environ["SSM_TELEGRAM_BOT_TOKEN"]
SSM_TELEGRAM_CHAT_ID = os.environ["SSM_TELEGRAM_CHAT_ID"]
GEMINI_MODEL = os.environ["GEMINI_MODEL"]


def get_secret(name):
    return ssm.get_parameter(Name=name, WithDecryption=True)["Parameter"]["Value"]

def lambda_handler(event, context):
    try:
        # --- Load secrets
        telegram_token = get_secret(SSM_TELEGRAM_TOKEN)
        chat_id = get_secret(SSM_TELEGRAM_CHAT_ID)

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
        rss_links = []
        
        for entry in feed.entries:
            # Parse the published date
            if hasattr(entry, 'published_parsed') and entry.published_parsed:
                entry_date = datetime(*entry.published_parsed[:6])
                if entry_date >= past_24h:
                    link = entry.get("link", "")
                    if link:
                        rss_links.append(link)
        
        if not rss_links:
            logger.info("No AWS news found in the past 24 hours")
            return {"statusCode": 200, "body": "No new content"}

        # --- Step 2: Summarize with Gemini
        try:
            # Configure Gemini
            genai.configure(api_key=get_secret(SSM_GEMINI_API_KEY))
            model = genai.GenerativeModel(GEMINI_MODEL)
            
            aws_news_prompt = """
You are my AWS news assistant. I will paste AWS RSS news links, and you will return
a structured TLDR summary for each one.

🎯 Background about me (to tailor explanations):
- I'm an AWS Landing Zone platform manager 👨‍💻, so I care about multi-account governance, networking, security, IAM, and operations.
- I'm training to become a strong AWS Solutions Architect 🌍, so I want to understand tradeoffs, design patterns, and how new services/features affect architecture.
- I follow AWS announcements daily 📢, so skip fluff and focus on what *really* changes.
- I like answers that are concise but insightful — short TLDRs with enough depth to take action.
- I enjoy visually clear, structured explanations with emojis ✅.

📝 For each AWS news link, explain in this structure:

---
🌐 [Service / Feature Name] – [Short Title]  
- 🚀 **What's New?** → Summarize the new announcement.  
- 📅 **When:** Date of the announcement.  
- ⏳ **Before:** What was possible/limited before.  
- 🔄 **Now:** What changed.  
- 💡 **Why It Matters:** Why this update is useful in real-world AWS architecture, governance, or operations.  
- 👥 **Impact:** Who benefits (e.g., enterprises, devs, security teams).  
- 🔗 **Link:** URL of the news article
---

⚠️ Rules:
- Only summarize AWS news from the provided links.
- Always include emojis and nice formatting to make it easy to scan.  
- Keep it professional but approachable.  
- Assume I want to quickly understand how this affects AWS Landing Zone operations and broader Solutions Architect responsibilities.  
- Don't just copy AWS marketing text — give me a *useful TLDR*.  
"""
            
            response = model.generate_content(aws_news_prompt + "\n\nHere are the news links:\n" + "\n".join(rss_links))
            summary = response.text
        except Exception as e:
            logger.error(f"Gemini summarization failed: {e}")
            return {"statusCode": 500, "body": "Gemini error"}

        # --- Step 3: Send to Telegram
        try:
            # Prepare message with proper length handling
            msg_header = "📰 AWS Daily News:\n\n"
            msg_content = summary
            
            # Telegram limit is 4096 characters
            max_content_length = 4096 - len(msg_header) - 50  # Leave some buffer
            
            telegram_url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
            
            if len(msg_content) <= max_content_length:
                # Message fits in one part
                final_msg = msg_header + msg_content
                logger.info(f"Sending single message of {len(final_msg)} characters")
                
                resp = requests.post(
                    telegram_url,
                    json={
                        "chat_id": chat_id, 
                        "text": final_msg,
                        "parse_mode": "Markdown",
                        "disable_web_page_preview": True
                    },
                    timeout=30
                )
                if resp.status_code != 200:
                    logger.error(f"Telegram API response: {resp.text}")
                    raise RuntimeError(f"Telegram API error {resp.status_code}: {resp.text}")
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
                        # Find a good break point (preferably at line break)
                        cut_point = remaining_content[:available_space].rfind('\n')
                        if cut_point == -1:  # No line break found, cut at space
                            cut_point = remaining_content[:available_space].rfind(' ')
                        if cut_point == -1:  # No space found, hard cut
                            cut_point = available_space
                        
                        parts.append(part_header + remaining_content[:cut_point])
                        remaining_content = remaining_content[cut_point:].lstrip()
                        part_num += 1
                
                logger.info(f"Splitting message into {len(parts)} parts")
                
                # Send each part
                for i, part in enumerate(parts, 1):
                    logger.info(f"Sending part {i}/{len(parts)} ({len(part)} characters)")
                    
                    resp = requests.post(
                        telegram_url,
                        json={
                            "chat_id": chat_id, 
                            "text": part,
                            "parse_mode": "Markdown",
                            "disable_web_page_preview": True
                        },
                        timeout=30
                    )
                    if resp.status_code != 200:
                        logger.error(f"Telegram API response for part {i}: {resp.text}")
                        raise RuntimeError(f"Telegram API error {resp.status_code} on part {i}: {resp.text}")
                    
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

    except Exception as e:
        logger.exception(f"Unhandled error: {e}")
        return {"statusCode": 500, "body": "Internal error"}
