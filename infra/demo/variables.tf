variable "aws_account_id" {
  description = "構築先のAWS account ID。"
  type        = string
  validation {
    condition     = can(regex("^[0-9]{12}$", var.aws_account_id))
    error_message = "12桁のAWS account IDを指定する。"
  }
}

variable "image_digest" {
  description = "同じrootのECRへ初期投入したコンテナーの固定digest。"
  type        = string
  default     = null
  nullable    = true
  validation {
    condition     = var.image_digest == null ? true : can(regex("^sha256:[a-f0-9]{64}$", var.image_digest))
    error_message = "sha256の固定digestを指定する。"
  }
}
