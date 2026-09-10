variable "repo" {
  type        = string
  description = "owner/name of the repository"
}

variable "policy" {
  type        = string
  default     = "adopt"
  description = "observe | adopt | enforce"
}

variable "provider_name" {
  type        = string
  default     = "auto"
  description = "Review model provider"
}

variable "monthly_cap" {
  type        = number
  default     = 0
}

variable "team" {
  type        = string
  default     = ""
}

output "quality_toml" {
  value = <<-EOT
  [quality]
  policy = "${var.policy}"

  [quality.review]
  provider = "${var.provider_name}"

  [quality.cost]
  monthly_cap = ${var.monthly_cap}
  EOT
}

output "repo" {
  value = var.repo
}

output "team" {
  value = var.team
}
