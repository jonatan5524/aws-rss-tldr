# AWS RSS TL;DR

A serverless bot that fetches AWS news from RSS, summarizes with Gemini AI, and posts to Telegram.

📢 **Live Channel:** [https://t.me/awsmewstldr](https://t.me/awsmewstldr)

## Architecture

- **AWS Lambda** - Runs daily to fetch and summarize news
- **EventBridge** - Schedules daily execution
- **DynamoDB** - Stores processed articles
- **Gemini AI** - Generates summaries
- **Telegram Bot** - Delivers summaries

## Prerequisites

- AWS Account
- Terraform >= 1.6.0
- Telegram Bot Token (from [@BotFather](https://t.me/botfather))
- Gemini API Key

## Setup

1. **Create SSM Parameters** in AWS Console:
   - `/aws-news-tldr/telegram_bot_token`
   - `/aws-news-tldr/telegram_chat_id`
   - `/aws-news-tldr/gemini_api_key`

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
