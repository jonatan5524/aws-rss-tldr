variable "project_name" {
  type    = string
  default = "aws-news-tldr"
}

variable "region" {
  type    = string
  default = "il-central-1"
}

variable "ssm_telegram_bot_token" {
  type    = string
  default = "telegram_bot_token"
}

variable "ssm_telegram_chat_id" {
  type    = string
  default = "telegram_chat_id"
}

variable "ssm_openrouter_api_key_name" {
  type    = string
  default = "openrouter_api_key"
}

variable "primary_model" {
  type    = string
  default = "google/gemma-4-31b-it:free"
}

# Tried in order (via OpenRouter's `models` fallback array) if the primary
# model is unavailable. Free-tier model availability rotates over time --
# check current options at https://openrouter.ai/models before relying on
# these defaults.
variable "fallback_models" {
  type = list(string)
  default = [
    "nvidia/nemotron-3.5-lightning:free",
    "baidu/ernie-5.5-flash-preview:free",
  ]
}
