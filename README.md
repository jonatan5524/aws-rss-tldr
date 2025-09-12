# AWS RSS TLDR Bot

A serverless AWS Lambda function that fetches AWS news RSS feed daily, summarizes it using Google Gemini AI, and sends the summary via Telegram.

## Features

- 📰 Fetches AWS news from official RSS feed
- 🤖 AI-powered summaries using Google Gemini
- 📱 Sends notifications via Telegram
- ⚡ Serverless architecture (AWS Lambda)
- 🔒 Secure secret management (AWS SSM)
- 💰 Designed for AWS Free Tier

## Setup

### Prerequisites

- AWS CLI configured
- Terraform >= 1.6.0
- Docker (for Lambda packaging)

### 1. Clone Repository

```bash
git clone <repo-url>
cd aws-rss-tldr
```

### 2. Create Telegram Bot

1. Message [@BotFather](https://t.me/botfather) on Telegram
2. Send `/newbot` and follow instructions
3. Save the bot token

### 3. Get Your Telegram Chat ID

1. Start chat with your bot
2. Send any message
3. Visit: `https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates`
4. Find your chat ID in the response

### 4. Get Gemini API Key

1. Go to [Google AI Studio](https://aistudio.google.com/app/apikey)
2. Create new API key
3. Save the key

### 5. Store Secrets in AWS SSM

```bash
# Store Gemini API key
aws ssm put-parameter \
    --name "gemini_api_key" \
    --value "YOUR_GEMINI_API_KEY" \
    --type "SecureString" \
    --region il-central-1

# Store Telegram bot token
aws ssm put-parameter \
    --name "telegram_bot_token" \
    --value "YOUR_TELEGRAM_BOT_TOKEN" \
    --type "SecureString" \
    --region il-central-1

# Store Telegram chat ID
aws ssm put-parameter \
    --name "telegram_chat_id" \
    --value "YOUR_CHAT_ID" \
    --type "SecureString" \
    --region il-central-1
```

### 6. Deploy Infrastructure

```bash
# Initialize Terraform
terraform init

# Plan deployment
terraform plan -out=tfplan

# Apply changes
terraform apply tfplan
```

## Configuration

### Variables (variables.tf)

- `region`: AWS region (default: il-central-1)
- `project_name`: Project name prefix
- `gemini_model`: Gemini model to use (default: gemini-1.5-flash)
- `ssm_*`: SSM parameter names for secrets

### Schedule

The Lambda runs daily at 08:20 UTC+3 (configurable in `main.tf`).

## Cost

Designed to operate within AWS Free Tier:

- **Lambda**: 1M free requests/month
- **EventBridge**: 14M free events/month  
- **SSM**: Standard parameters are free
- **Gemini**: 1,500 free requests/day
- **Telegram**: Completely free

