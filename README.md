# AWS RSS TL;DR

A serverless bot that fetches AWS news from RSS, summarizes it via OpenRouter, and posts to Telegram.

📢 **Live Channel:** [https://t.me/awsmewstldr](https://t.me/awsmewstldr)

## Architecture

- **AWS Lambda** - Runs daily to fetch and summarize news
- **EventBridge** - Schedules daily execution
- **DynamoDB** - Stores processed articles
- **OpenRouter** - Generates summaries, with model/provider fallback on capacity errors
- **Telegram Bot** - Delivers summaries

## Prerequisites

- AWS Account
- Terraform >= 1.6.0
- Telegram Bot Token (from [@BotFather](https://t.me/botfather))
- OpenRouter API Key (from [openrouter.ai](https://openrouter.ai/keys))

## Setup

1. **Create SSM Parameters** in AWS Console (these are the bare parameter names
   Terraform looks up via `variables.tf` — no path prefix):
   - `telegram_bot_token`
   - `telegram_chat_id`
   - `openrouter_api_key` (type `SecureString`)

   The default model and fallback models (`variables.tf`) are free-tier OpenRouter
   models as of the last update — free-tier availability rotates, so check
   [openrouter.ai/models](https://openrouter.ai/models) and override `primary_model`/
   `fallback_models` if needed.

2. **Create S3 bucket** for Terraform state:
   ```bash
   aws s3api create-bucket --bucket aws-news-tldr-terraform-state --region il-central-1
   ```

3. **Deploy**:
   ```bash
   terraform init
   terraform apply
   ```

## GitHub Actions

The workflow deploys automatically on push to `main`. Configure these secrets:
- `AWS_ACCOUNT_ID` - Your AWS account ID

## License

MIT
