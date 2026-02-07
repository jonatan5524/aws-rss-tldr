terraform {
  required_version = ">= 1.6.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.60"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
  }
}

provider "aws" {
  region = var.region
}

locals {
  lambda_name = "${var.project_name}-lambda"
  rss_url     = "https://aws.amazon.com/about-aws/whats-new/recent/feed/"
  package_hash = md5(join("", [
    filemd5("${path.module}/lambda/handler.py"),
    filemd5("${path.module}/lambda/requirements.txt")
  ]))
  archive_path = "${path.module}/lambda_build/lambda_package_${local.package_hash}.zip"
}

data "aws_caller_identity" "current" {}

resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${local.lambda_name}"
  retention_in_days = 3
}

resource "aws_iam_role" "lambda_role" {
  name = "${var.project_name}-lambda-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action   = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_policy" "lambda_policy" {
  name   = "${var.project_name}-lambda-policy"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream","logs:PutLogEvents"]
        Resource = "arn:aws:logs:${var.region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/lambda/${local.lambda_name}:*"
      },
      {
        Effect   = "Allow"
        Action   = ["ssm:GetParameter"]
        Resource = [
          "arn:aws:ssm:${var.region}:${data.aws_caller_identity.current.account_id}:parameter/${var.ssm_gemini_api_key_name}",
          "arn:aws:ssm:${var.region}:${data.aws_caller_identity.current.account_id}:parameter/${var.ssm_telegram_bot_token}",
          "arn:aws:ssm:${var.region}:${data.aws_caller_identity.current.account_id}:parameter/${var.ssm_telegram_chat_id}",
        ]
      },
      {
        Effect   = "Allow"
        Action   = ["kms:Decrypt"]
        Resource = "*"
        Condition = {
          "ForAnyValue:StringEquals" = { "kms:ViaService" = "ssm.${var.region}.amazonaws.com" }
        }
      },
			{
        Effect = "Allow",
        Action = ["kms:Decrypt"],
        Resource = "arn:aws:kms:${var.region}:${data.aws_caller_identity.current.account_id}:alias/aws/lambda"
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "attach" {
  role       = aws_iam_role.lambda_role.name
  policy_arn = aws_iam_policy.lambda_policy.arn
}


# --- Auto-install Python deps and zip Lambda ---
resource "null_resource" "build_lambda" {
  # Trigger rebuild if handler.py or requirements.txt changes
  triggers = {
    package_hash = local.package_hash
  }
	
  provisioner "local-exec" {
    command = <<EOT
			docker run --rm --entrypoint /bin/bash -u $(id -u):$(id -g) -v "$PWD":/app -w /app public.ecr.aws/lambda/python:3.12 \
			-c "
			rm -rf lambda_build &&
			mkdir -p lambda_build &&
			pip install -r lambda/requirements.txt -t lambda_build --upgrade &&
			cp lambda/*.py lambda_build/"

			cd lambda_build 
			zip -r lambda_package_${local.package_hash}.zip .
			cd -
    EOT
    interpreter = ["/bin/bash", "-c"]
  }
}

resource "aws_lambda_function" "fn" {
  function_name = local.lambda_name
  role          = aws_iam_role.lambda_role.arn
  handler       = "handler.lambda_handler"
  runtime       = "python3.12"
  filename      = local.archive_path
  timeout       = 60
  memory_size   = 256

  environment {
    variables = {
      RSS_URL                     = local.rss_url
      GEMINI_MODEL                = var.gemini_model
      SSM_GEMINI_API_KEY_NAME     = var.ssm_gemini_api_key_name
      SSM_TELEGRAM_BOT_TOKEN 			= var.ssm_telegram_bot_token
			SSM_TELEGRAM_CHAT_ID        = var.ssm_telegram_chat_id
    }
  }

  depends_on = [aws_cloudwatch_log_group.lambda, null_resource.build_lambda]
}

resource "aws_cloudwatch_event_rule" "daily" {
  name                = "${var.project_name}-daily"
  schedule_expression = "cron(20 5 * * ? *)"
}

resource "aws_cloudwatch_event_target" "invoke_lambda" {
  rule      = aws_cloudwatch_event_rule.daily.name
  target_id = "lambda"
  arn       = aws_lambda_function.fn.arn
}

resource "aws_lambda_permission" "allow_events" {
  statement_id  = "AllowExecutionFromEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.fn.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.daily.arn
}
