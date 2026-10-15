terraform {
  required_version = "= 1.16.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "= 6.69.0"
    }
  }
  backend "s3" {
    encrypt      = true
    use_lockfile = true
  }
}

provider "aws" {
  region              = "ap-northeast-1"
  allowed_account_ids = [var.aws_account_id]
  default_tags {
    tags = {
      Project     = "schedula-demo"
      Environment = "production"
      ManagedBy   = "Terraform"
    }
  }
}
