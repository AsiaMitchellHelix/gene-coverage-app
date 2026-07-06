variable "aws_region" {
  default = "us-east-1"
}

variable "app_name" {
  default = "gene-coverage-app"
}

variable "db_password" {
  description = "RDS master password"
  sensitive   = true
}

variable "ses_sender_email" {
  description = "Verified SES sender address"
}

variable "vpc_id" {
  description = "VPC to deploy into"
}

variable "private_subnet_ids" {
  type        = list(string)
  description = "Private subnets for ECS and RDS"
}

variable "public_subnet_ids" {
  type        = list(string)
  description = "Public subnets for ALB"
}

variable "container_image" {
  description = "ECR image URI for the FastAPI backend"
}
