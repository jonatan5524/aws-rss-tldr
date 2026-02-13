terraform {
  backend "s3" {
    bucket  = "aws-news-tldr-terraform-state"
    key     = "terraform.tfstate"
    region  = "il-central-1"
    encrypt = true
  }
}
