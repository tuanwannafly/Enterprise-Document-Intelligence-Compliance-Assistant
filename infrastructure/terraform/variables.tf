variable "aws_region" {}
variable "project_name" {}
variable "vpc_id" {}
variable "vpc_private_subnets" { type = list(string) }
variable "container_image" {}
variable "edi_db_password" { sensitive = true }
