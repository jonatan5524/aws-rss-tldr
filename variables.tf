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

variable "ssm_gemini_api_key_name" {
  type    = string
  default = "gemini_api_key"
}


variable "gemini_model" {
  type    = string
  default = "gemini-2.5-flash"
}
