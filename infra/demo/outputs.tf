output "aws_account_id" { value = var.aws_account_id }
output "aws_region" { value = "ap-northeast-1" }
output "site_bucket" { value = aws_s3_bucket.demo.id }
output "ecr_repository" { value = aws_ecr_repository.demo.repository_url }
output "lambda_function" { value = local.function }
output "deploy_role_arn" { value = aws_iam_role.deploy.arn }
output "public_url" { value = "https://the3.co.jp/products/schedula/demo/" }
