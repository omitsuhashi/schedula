data "aws_ssm_parameter" "foundation" {
  for_each        = toset(["aws-account-id", "github-oidc-provider-arn"])
  name            = "/the3/production/foundation/v1/${each.key}"
  with_decryption = false
  lifecycle {
    postcondition {
      condition     = self.value == (each.key == "aws-account-id" ? var.aws_account_id : "arn:aws:iam::${var.aws_account_id}:oidc-provider/token.actions.githubusercontent.com")
      error_message = "foundation契約が構築先accountと一致しない。"
    }
  }
}

data "aws_ssm_parameter" "edge" {
  name            = "/the3/production/company/v1/edge"
  with_decryption = false
  lifecycle {
    postcondition {
      condition = try(
        jsondecode(self.value).schema_version == 1 &&
        jsondecode(self.value).aws_account_id == var.aws_account_id &&
        jsondecode(self.value).host == "the3.co.jp" &&
        can(regex("^arn:aws:cloudfront::${var.aws_account_id}:distribution/[A-Z0-9]+$", jsondecode(self.value).distribution_arn)),
        false
      )
      error_message = "会社の接続契約は構築先accountのthe3.co.jp用Distributionである必要がある。"
    }
  }
}

locals {
  edge         = try(jsondecode(nonsensitive(data.aws_ssm_parameter.edge.value)), {})
  function     = "the3-schedula-demo-production"
  prefix       = "products/schedula/"
  runtime      = var.image_digest == null ? [] : [true]
  function_arn = "arn:aws:lambda:ap-northeast-1:${var.aws_account_id}:function:${local.function}"
}

resource "aws_s3_bucket" "demo" {
  bucket_prefix = "the3-schedula-demo-production-"
  force_destroy = false
  lifecycle {
    prevent_destroy = true
  }
}
resource "aws_s3_bucket_public_access_block" "demo" {
  bucket                  = aws_s3_bucket.demo.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
resource "aws_s3_bucket_ownership_controls" "demo" {
  bucket = aws_s3_bucket.demo.id
  rule { object_ownership = "BucketOwnerEnforced" }
}
resource "aws_s3_bucket_versioning" "demo" {
  bucket = aws_s3_bucket.demo.id
  versioning_configuration { status = "Enabled" }
}
resource "aws_s3_bucket_server_side_encryption_configuration" "demo" {
  bucket = aws_s3_bucket.demo.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}
resource "aws_s3_bucket_policy" "demo" {
  bucket = aws_s3_bucket.demo.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow", Principal = { Service = "cloudfront.amazonaws.com" }, Action = "s3:GetObject"
        Resource  = "${aws_s3_bucket.demo.arn}/${local.prefix}*"
        Condition = { StringEquals = { "AWS:SourceArn" = try(local.edge.distribution_arn, "invalid") } }
      },
      {
        Effect    = "Deny", Principal = "*", Action = "s3:*"
        Resource  = [aws_s3_bucket.demo.arn, "${aws_s3_bucket.demo.arn}/*"]
        Condition = { Bool = { "aws:SecureTransport" = "false" } }
      }
    ]
  })
}

resource "aws_ecr_repository" "demo" {
  name                 = "the3-schedula-demo-production"
  image_tag_mutability = "IMMUTABLE"
  force_delete         = false
  image_scanning_configuration { scan_on_push = true }
  encryption_configuration { encryption_type = "AES256" }
  lifecycle { prevent_destroy = true }
}

resource "aws_ecr_repository_policy" "runtime" {
  repository = aws_ecr_repository.demo.name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow", Principal = { Service = "lambda.amazonaws.com" }
      Action    = ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"]
      Condition = { ArnLike = { "aws:SourceArn" = "${local.function_arn}*" } }
    }]
  })
}

resource "aws_cloudwatch_log_group" "demo" {
  name              = "/aws/lambda/${local.function}"
  retention_in_days = 14
}
resource "aws_iam_role" "runtime" {
  name = "${local.function}-runtime"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "lambda.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })
}
resource "aws_iam_role_policy" "runtime" {
  role = aws_iam_role.runtime.id
  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = "${aws_cloudwatch_log_group.demo.arn}:*" }]
  })
}

resource "aws_lambda_function" "demo" {
  count                          = length(local.runtime)
  function_name                  = local.function
  role                           = aws_iam_role.runtime.arn
  package_type                   = "Image"
  image_uri                      = "${aws_ecr_repository.demo.repository_url}@${var.image_digest}"
  architectures                  = ["x86_64"]
  memory_size                    = 2048
  timeout                        = 30
  reserved_concurrent_executions = 2
  publish                        = true
  depends_on                     = [aws_iam_role_policy.runtime, aws_ecr_repository_policy.runtime]
  lifecycle {
    ignore_changes = [image_uri]
  }
}
resource "aws_lambda_alias" "live" {
  count            = length(local.runtime)
  name             = "live"
  function_name    = aws_lambda_function.demo[0].function_name
  function_version = aws_lambda_function.demo[0].version
  lifecycle {
    ignore_changes = [function_version]
  }
}
resource "aws_lambda_function_url" "demo" {
  count              = length(local.runtime)
  function_name      = aws_lambda_function.demo[0].function_name
  qualifier          = aws_lambda_alias.live[0].name
  authorization_type = "AWS_IAM"
}
resource "aws_lambda_permission" "cloudfront" {
  for_each                 = var.image_digest == null ? toset([]) : toset(["lambda:InvokeFunctionUrl", "lambda:InvokeFunction"])
  statement_id             = each.key == "lambda:InvokeFunctionUrl" ? "CloudFrontUrl" : "CloudFrontInvoke"
  action                   = each.key
  function_name            = aws_lambda_function.demo[0].function_name
  qualifier                = aws_lambda_alias.live[0].name
  principal                = "cloudfront.amazonaws.com"
  source_arn               = try(local.edge.distribution_arn, "invalid")
  function_url_auth_type   = each.key == "lambda:InvokeFunctionUrl" ? "AWS_IAM" : null
  invoked_via_function_url = each.key == "lambda:InvokeFunction" ? true : null
}
resource "aws_ssm_parameter" "origins" {
  count = length(local.runtime)
  name  = "/the3/production/products/schedula/v1/origins"
  type  = "String"
  value = jsonencode({
    schema_version       = 1
    aws_account_id       = var.aws_account_id
    region               = "ap-northeast-1"
    static_origin_domain = aws_s3_bucket.demo.bucket_regional_domain_name
    function_url_domain  = trimsuffix(trimprefix(aws_lambda_function_url.demo[0].function_url, "https://"), "/")
    function_alias_arn   = aws_lambda_alias.live[0].arn
  })
  lifecycle { prevent_destroy = true }
}

resource "aws_iam_role" "deploy" {
  name = "${local.function}-deploy"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = nonsensitive(data.aws_ssm_parameter.foundation["github-oidc-provider-arn"].value) }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = { StringEquals = {
        "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
        "token.actions.githubusercontent.com:sub" = "repo:the3-inc@249383711/schedula@1403742307:environment:production"
      } }
    }]
  })
}
resource "aws_iam_role_policy" "deploy" {
  role = aws_iam_role.deploy.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["s3:ListBucket"], Resource = aws_s3_bucket.demo.arn, Condition = { StringLike = { "s3:prefix" = [local.prefix, "${local.prefix}*"] } } },
      { Effect = "Allow", Action = ["s3:PutObject", "s3:DeleteObject", "s3:AbortMultipartUpload"], Resource = "${aws_s3_bucket.demo.arn}/${local.prefix}*" },
      { Effect = "Allow", Action = ["ecr:GetAuthorizationToken"], Resource = "*" },
      { Effect = "Allow", Action = ["ecr:BatchCheckLayerAvailability", "ecr:InitiateLayerUpload", "ecr:UploadLayerPart", "ecr:CompleteLayerUpload", "ecr:PutImage", "ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer", "ecr:DescribeImages"], Resource = aws_ecr_repository.demo.arn },
      { Effect = "Allow", Action = ["lambda:GetFunction", "lambda:GetFunctionConfiguration", "lambda:UpdateFunctionCode", "lambda:PublishVersion"], Resource = local.function_arn },
      { Effect = "Allow", Action = ["lambda:GetAlias", "lambda:UpdateAlias"], Resource = "${local.function_arn}:live" }
    ]
  })
}
