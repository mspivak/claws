variable "project_name" {
  description = "Used as SSM prefix and name tag"
}

variable "aws_region" {
  description = "AWS region — no default, must be explicit"
}

variable "instance_type" {
  description = "EC2 instance type"
  default     = "t3.nano"
}

variable "github_repo" {
  description = "org/repo to clone on the box"
}

variable "ssh_public_key_path" {
  default = "~/.ssh/id_rsa.pub"
}
