terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

data "aws_ami" "al2023" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-*-x86_64"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

data "http" "my_ip" {
  url = "https://checkip.amazonaws.com"
}

resource "aws_key_pair" "claws" {
  key_name   = "claws-${var.project_name}"
  public_key = file(pathexpand(var.ssh_public_key_path))
}

resource "aws_security_group" "claws" {
  name        = "claws-${var.project_name}"
  description = "claws EC2 security group"

  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["${chomp(data.http.my_ip.response_body)}/32"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_iam_role" "claws" {
  name = "claws-${var.project_name}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "claws_ssm" {
  name = "claws-ssm"
  role = aws_iam_role.claws.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "ssm:GetParameter",
        "ssm:GetParametersByPath",
      ]
      Resource = "arn:aws:ssm:${var.aws_region}:*:parameter/claws/${var.project_name}/*"
    }]
  })
}

resource "aws_iam_instance_profile" "claws" {
  name = "claws-${var.project_name}"
  role = aws_iam_role.claws.name
}

resource "aws_instance" "claws" {
  ami                    = data.aws_ami.al2023.id
  instance_type          = var.instance_type
  key_name               = aws_key_pair.claws.key_name
  iam_instance_profile   = aws_iam_instance_profile.claws.name
  vpc_security_group_ids = [aws_security_group.claws.id]

  user_data = replace(
    replace(
      replace(file("${path.module}/user_data.sh"), "%%project_name%%", var.project_name),
      "%%github_repo%%", var.github_repo
    ),
    "%%aws_region%%", var.aws_region
  )

  tags = {
    Name    = "claws-${var.project_name}"
    Project = var.project_name
  }
}

locals {
  ssm_prefix = "/claws/${var.project_name}"
}

resource "aws_ssm_parameter" "telegram_bot_token" {
  name  = "${local.ssm_prefix}/telegram/bot-token"
  type  = "SecureString"
  value = "placeholder"

  lifecycle { ignore_changes = [value] }
}

resource "aws_ssm_parameter" "telegram_allowed_user_ids" {
  name  = "${local.ssm_prefix}/telegram/allowed-user-ids"
  type  = "String"
  value = "placeholder"

  lifecycle { ignore_changes = [value] }
}

resource "aws_ssm_parameter" "github_token" {
  name  = "${local.ssm_prefix}/github/token"
  type  = "SecureString"
  value = "placeholder"

  lifecycle { ignore_changes = [value] }
}

resource "aws_ssm_parameter" "github_org" {
  name  = "${local.ssm_prefix}/github/org"
  type  = "String"
  value = "placeholder"

  lifecycle { ignore_changes = [value] }
}

resource "aws_ssm_parameter" "github_repo" {
  name  = "${local.ssm_prefix}/github/repo"
  type  = "String"
  value = "placeholder"

  lifecycle { ignore_changes = [value] }
}

resource "aws_ssm_parameter" "github_project_number" {
  name  = "${local.ssm_prefix}/github/project-number"
  type  = "String"
  value = "placeholder"

  lifecycle { ignore_changes = [value] }
}

resource "aws_ssm_parameter" "github_project_id" {
  name  = "${local.ssm_prefix}/github/project-id"
  type  = "String"
  value = "placeholder"

  lifecycle { ignore_changes = [value] }
}

resource "aws_ssm_parameter" "github_status_field_id" {
  name  = "${local.ssm_prefix}/github/status-field-id"
  type  = "String"
  value = "placeholder"

  lifecycle { ignore_changes = [value] }
}

resource "aws_ssm_parameter" "github_status_ready" {
  name  = "${local.ssm_prefix}/github/status-ready"
  type  = "String"
  value = "placeholder"

  lifecycle { ignore_changes = [value] }
}

resource "aws_ssm_parameter" "github_status_in_progress" {
  name  = "${local.ssm_prefix}/github/status-in-progress"
  type  = "String"
  value = "placeholder"

  lifecycle { ignore_changes = [value] }
}

resource "aws_ssm_parameter" "github_status_blocked" {
  name  = "${local.ssm_prefix}/github/status-blocked"
  type  = "String"
  value = "placeholder"

  lifecycle { ignore_changes = [value] }
}

resource "aws_ssm_parameter" "github_status_in_review" {
  name  = "${local.ssm_prefix}/github/status-in-review"
  type  = "String"
  value = "placeholder"

  lifecycle { ignore_changes = [value] }
}

resource "aws_ssm_parameter" "github_status_approved" {
  name  = "${local.ssm_prefix}/github/status-approved"
  type  = "String"
  value = "placeholder"

  lifecycle { ignore_changes = [value] }
}

resource "aws_ssm_parameter" "anthropic_api_key" {
  name  = "${local.ssm_prefix}/anthropic/api-key"
  type  = "SecureString"
  value = "placeholder"

  lifecycle { ignore_changes = [value] }
}
