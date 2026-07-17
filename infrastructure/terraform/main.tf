provider "aws" {
  region = var.aws_region
}

# ----------------------------------------------------------------------
# Variables
# ----------------------------------------------------------------------
variable "aws_region" {
  type        = string
  default     = "us-east-1"
  description = "AWS region to deploy into."
}

variable "project_name" {
  type        = string
  default     = "edi-compliance"
  description = "Prefix applied to all resource names."
}

variable "vpc_id" {
  type        = string
  description = "VPC where the ECS service and database will run."
}

variable "vpc_private_subnets" {
  type        = list(string)
  description = "Private subnets for ECS tasks + RDS."
}

variable "container_image" {
  type        = string
  description = "Full URI of the backend container image (e.g. 123.dkr.ecr.us-east-1.amazonaws.com/edi-backend:v1.0.0)."
}

variable "edi_db_password" {
  type        = string
  sensitive   = true
  description = "Master password for the Postgres instance."
}

# ----------------------------------------------------------------------
# ECS — Fargate service running the FastAPI image
# ----------------------------------------------------------------------
resource "aws_ecs_cluster" "this" {
  name = "${var.project_name}-cluster"
}

resource "aws_cloudwatch_log_group" "backend" {
  name              = "/ecs/${var.project_name}/backend"
  retention_in_days = 30
}

resource "aws_iam_role" "task_execution" {
  name               = "${var.project_name}-task-exec"
  assume_role_policy = data.aws_iam_policy_document.ecs_task_assume.json
}

data "aws_iam_policy_document" "ecs_task_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

# Least-privilege execution role: only what's needed to pull the image and
# write to CloudWatch Logs.
resource "aws_iam_role_policy" "task_exec_policy" {
  role = aws_iam_role.task_execution.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["ecr:GetAuthorizationToken"]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "ecr:BatchCheckLayerAvailability",
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchGetImage"
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "${aws_cloudwatch_log_group.backend.arn}:*"
      },
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue"
        ]
        Resource = [
          aws_secretsmanager_secret.db.arn,
          aws_secretsmanager_secret.cognito.arn
        ]
      }
    ]
  })
}

# Least-privilege task role — what the application itself can do at runtime.
# This is intentionally narrow: only the AWS APIs the backend actually uses.
resource "aws_iam_role" "task" {
  name               = "${var.project_name}-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_task_assume.json
}

resource "aws_iam_role_policy" "task_runtime_policy" {
  role = aws_iam_role.task.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "S3ReadWriteOnDocumentsBucket"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject",
          "s3:ListBucket"
        ]
        Resource = [
          aws_s3_bucket.documents.arn,
          "${aws_s3_bucket.documents.arn}/*"
        ]
      },
      {
        Sid    = "TextractAsync"
        Effect = "Allow"
        Action = [
          "textract:StartDocumentTextDetection",
          "textract:GetDocumentTextDetection",
          "textract:DetectDocumentText"
        ]
        Resource = "*"
      },
      {
        Sid    = "ComprehendPII"
        Effect = "Allow"
        Action = [
          "comprehend:DetectPiiEntities"
        ]
        Resource = "*"
      },
      {
        Sid    = "BedrockInvocations"
        Effect = "Allow"
        Action = [
          "bedrock:InvokeModel",
          "bedrock:InvokeModelWithResponseStream"
        ]
        Resource = [
          "arn:aws:bedrock:${var.aws_region}::foundation-model/anthropic.claude-3-haiku-20240307-v1:0",
          "arn:aws:bedrock:${var.aws_region}::foundation-model/amazon.titan-embed-text-v2:0"
        ]
      },
      {
        Sid    = "CognitoIdpLookup"
        Effect = "Allow"
        Action = [
          "cognito-idp:GetUser",
          "cognito-idp:ListUsers"
        ]
        Resource = "*"
      }
    ]
  })
}

resource "aws_ecs_task_definition" "backend" {
  family                   = "${var.project_name}-backend"
  cpu                      = 1024
  memory                   = 2048
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  execution_role_arn       = aws_iam_role.task_execution.arn
  task_role_arn            = aws_iam_role.task.arn

  container_definitions = jsonencode([
    {
      name      = "backend"
      image     = var.container_image
      essential = true
      portMappings = [{ containerPort = 8000 }]
      environment = [
        { name = "APP_ENV", value = "production" },
        { name = "VECTOR_STORE", value = "qdrant" },
        { name = "AWS_REGION", value = var.aws_region },
        { name = "DOCUMENTS_BUCKET", value = aws_s3_bucket.documents.id }
      ]
      secrets = [
        {
          name      = "DATABASE_URL"
          valueFrom = "${aws_secretsmanager_secret.db.arn}:DATABASE_URL::"
        },
        {
          name      = "COGNITO_USER_POOL_ID"
          valueFrom = "${aws_secretsmanager_secret.cognito.arn}:COGNITO_USER_POOL_ID::"
        },
        {
          name      = "COGNITO_APP_CLIENT_ID"
          valueFrom = "${aws_secretsmanager_secret.cognito.arn}:COGNITO_APP_CLIENT_ID::"
        },
        {
          name      = "COGNITO_JWKS_URL"
          valueFrom = "${aws_secretsmanager_secret.cognito.arn}:COGNITO_JWKS_URL::"
        }
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.backend.name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "backend"
        }
      }
      healthCheck = {
        command     = ["CMD-SHELL", "curl -fsS http://localhost:8000/api/v1/health || exit 1"]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 30
      }
    }
  ])
}

resource "aws_security_group" "backend" {
  name        = "${var.project_name}-backend-sg"
  description = "Allow inbound HTTP from the ALB only."
  vpc_id      = var.vpc_id

  ingress {
    from_port   = 8000
    to_port     = 8000
    protocol    = "TCP"
    cidr_blocks = ["10.0.0.0/8"]   # tighten to ALB SG in real deployments
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# ----------------------------------------------------------------------
# RDS Postgres instance (separate from the Fargate task — easiest RLS story)
# ----------------------------------------------------------------------
resource "aws_db_subnet_group" "this" {
  name       = "${var.project_name}-db-subnets"
  subnet_ids = var.vpc_private_subnets
}

resource "aws_security_group" "db" {
  name        = "${var.project_name}-db-sg"
  description = "Allow Postgres from the backend task SG only."
  vpc_id      = var.vpc_id

  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "TCP"
    security_groups = [aws_security_group.backend.id]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_rds_instance" "postgres" {
  identifier              = "${var.project_name}-postgres"
  engine                  = "postgres"
  engine_version          = "16.3"
  instance_class          = "db.t4g.medium"
  allocated_storage       = 50
  max_allocated_storage   = 200
  db_name                 = "edi"
  username                = "edi_owner"
  password                = var.edi_db_password
  db_subnet_group_name    = aws_db_subnet_group.this.name
  vpc_security_group_ids  = [aws_security_group.db.id]
  skip_final_snapshot     = true
  multi_az                = false
  backup_retention_period = 14
  deletion_protection     = false
}

# ----------------------------------------------------------------------
# S3 documents bucket
# ----------------------------------------------------------------------
resource "aws_s3_bucket" "documents" {
  bucket        = "${var.project_name}-documents-${var.aws_region}"
  force_destroy = false
}

resource "aws_s3_bucket_server_side_encryption_configuration" "documents" {
  bucket = aws_s3_bucket.documents.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}

resource "aws_s3_bucket_public_access_block" "documents" {
  bucket                  = aws_s3_bucket.documents.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# ----------------------------------------------------------------------
# Secrets Manager — DB URL, Cognito config
# ----------------------------------------------------------------------
resource "aws_secretsmanager_secret" "db" {
  name                    = "${var.project_name}/db"
  description             = "Production database connection string for the EDI compliance service"
  recovery_window_in_days = 7
}

resource "aws_secretsmanager_secret" "cognito" {
  name                    = "${var.project_name}/cognito"
  description             = "Cognito User Pool / App Client configuration"
  recovery_window_in_days = 7
}

output "ecs_cluster_name" { value = aws_ecs_cluster.this.name }
output "task_role_arn" { value = aws_iam_role.task.arn }
output "documents_bucket" { value = aws_s3_bucket.documents.id }
output "db_endpoint" { value = aws_rds_instance.postgres.endpoint }
