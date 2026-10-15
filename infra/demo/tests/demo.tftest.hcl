mock_provider "aws" {
  override_during = plan
  mock_resource "aws_cloudwatch_log_group" {
    defaults = { arn = "arn:aws:logs:ap-northeast-1:123456789012:log-group:/aws/lambda/the3-schedula-demo-production" }
  }
  mock_resource "aws_s3_bucket" {
    defaults = {
      id                          = "the3-schedula-demo-production-test"
      arn                         = "arn:aws:s3:::the3-schedula-demo-production-test"
      bucket_regional_domain_name = "the3-schedula-demo-production-test.s3.ap-northeast-1.amazonaws.com"
    }
  }
  mock_resource "aws_ecr_repository" {
    defaults = {
      arn            = "arn:aws:ecr:ap-northeast-1:123456789012:repository/the3-schedula-demo-production"
      repository_url = "123456789012.dkr.ecr.ap-northeast-1.amazonaws.com/the3-schedula-demo-production"
    }
  }
  mock_resource "aws_lambda_function" {
    defaults = { version = "1", function_name = "the3-schedula-demo-production" }
  }
  mock_resource "aws_lambda_alias" {
    defaults = { arn = "arn:aws:lambda:ap-northeast-1:123456789012:function:the3-schedula-demo-production:live" }
  }
  mock_resource "aws_lambda_function_url" {
    defaults = { function_url = "https://example.lambda-url.ap-northeast-1.on.aws/" }
  }
}

override_data {
  target = data.aws_ssm_parameter.foundation["aws-account-id"]
  values = { value = "123456789012" }
}
override_data {
  target = data.aws_ssm_parameter.foundation["github-oidc-provider-arn"]
  values = { value = "arn:aws:iam::123456789012:oidc-provider/token.actions.githubusercontent.com" }
}
override_data {
  target = data.aws_ssm_parameter.edge
  values = { value = "{\"schema_version\":1,\"aws_account_id\":\"123456789012\",\"host\":\"the3.co.jp\",\"distribution_arn\":\"arn:aws:cloudfront::123456789012:distribution/E123EXAMPLE\"}" }
}

variables { aws_account_id = "123456789012" }

run "bootstrap_without_image_or_product_contract" {
  command = plan
  assert {
    condition     = length(aws_lambda_function.demo) == 0 && length(aws_ssm_parameter.origins) == 0 && aws_ecr_repository.demo.image_tag_mutability == "IMMUTABLE"
    error_message = "初回はECRを先に構築し、実在しないイメージやURLの契約を公開しない。"
  }
}

run "private_origin_and_bounded_runtime" {
  command = plan
  variables { image_digest = "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" }
  assert {
    condition     = aws_lambda_function.demo[0].timeout == 30 && aws_lambda_function.demo[0].memory_size == 2048 && aws_lambda_function.demo[0].reserved_concurrent_executions == 2 && one(aws_lambda_function.demo[0].architectures) == "x86_64" && endswith(aws_lambda_function.demo[0].image_uri, "@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
    error_message = "固定digest・総期限・メモリ・並行数を制限する。"
  }
  assert {
    condition     = aws_lambda_function_url.demo[0].authorization_type == "AWS_IAM" && aws_lambda_function_url.demo[0].qualifier == "live" && alltrue([for permission in aws_lambda_permission.cloudfront : permission.source_arn == "arn:aws:cloudfront::123456789012:distribution/E123EXAMPLE" && permission.qualifier == "live"])
    error_message = "会社Distributionだけがlive aliasを呼び出せる。"
  }
  assert {
    condition     = aws_s3_bucket_public_access_block.demo.block_public_policy && aws_s3_bucket_public_access_block.demo.restrict_public_buckets && jsondecode(aws_s3_bucket_policy.demo.policy).Statement[0].Condition.StringEquals["AWS:SourceArn"] == "arn:aws:cloudfront::123456789012:distribution/E123EXAMPLE" && endswith(jsondecode(aws_s3_bucket_policy.demo.policy).Statement[0].Resource, "/products/schedula/*")
    error_message = "静的ファイルの読取は会社Distributionと公開prefixへ限定する。"
  }
  assert {
    condition     = jsondecode(aws_ssm_parameter.origins[0].value).function_url_domain == "example.lambda-url.ap-northeast-1.on.aws" && jsondecode(aws_ssm_parameter.origins[0].value).schema_version == 1 && jsondecode(aws_ssm_parameter.origins[0].value).static_origin_domain == "the3-schedula-demo-production-test.s3.ap-northeast-1.amazonaws.com"
    error_message = "会社rootが受理するOrigin契約を公開する。"
  }
  assert {
    condition     = jsondecode(aws_iam_role.deploy.assume_role_policy).Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:sub"] == "repo:the3-inc@249383711/schedula@1403742307:environment:production" && !strcontains(aws_iam_role_policy.deploy.policy, "cloudfront:") && !strcontains(aws_iam_role_policy.deploy.policy, "ssm:") && !strcontains(aws_iam_role_policy.deploy.policy, "iam:") && length(jsondecode(aws_iam_role_policy.runtime.policy).Statement) == 1
    error_message = "公開ロールに会社設定やSSM管理を許可せず、実行ロールはログだけに制限する。"
  }
}

run "rejects_wrong_company_account" {
  command = plan
  override_data {
    target = data.aws_ssm_parameter.edge
    values = { value = "{\"schema_version\":1,\"aws_account_id\":\"999999999999\",\"host\":\"the3.co.jp\",\"distribution_arn\":\"arn:aws:cloudfront::999999999999:distribution/E123EXAMPLE\"}" }
  }
  expect_failures = [data.aws_ssm_parameter.edge]
}

run "rejects_unrelated_distribution" {
  command = plan
  override_data {
    target = data.aws_ssm_parameter.edge
    values = { value = "{\"schema_version\":1,\"aws_account_id\":\"123456789012\",\"host\":\"other.example.com\",\"distribution_arn\":\"arn:aws:cloudfront::123456789012:distribution/E123EXAMPLE\"}" }
  }
  expect_failures = [data.aws_ssm_parameter.edge]
}

run "rejects_wrong_foundation" {
  command = plan
  override_data {
    target = data.aws_ssm_parameter.foundation["github-oidc-provider-arn"]
    values = { value = "arn:aws:iam::999999999999:oidc-provider/token.actions.githubusercontent.com" }
  }
  expect_failures = [data.aws_ssm_parameter.foundation["github-oidc-provider-arn"]]
}

run "rejects_mutable_image_tag" {
  command = plan
  variables { image_digest = "latest" }
  expect_failures = [var.image_digest]
}
