# Data tier: RDS + ElastiCache + SQS (S16.4, S16.5).

resource "aws_db_subnet_group" "main" {
  name       = "${var.cluster_name}-${var.environment}"
  subnet_ids = module.vpc.database_subnets
}

resource "aws_security_group" "rds" {
  name   = "${var.cluster_name}-${var.environment}-rds"
  vpc_id = module.vpc.vpc_id

  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [module.eks.node_security_group_id] # cluster nodes only
  }
}

resource "aws_db_instance" "main" {
  identifier     = "${var.cluster_name}-${var.environment}"
  engine         = "postgres"
  engine_version = "16"
  instance_class = var.db_instance_class

  allocated_storage     = 20
  max_allocated_storage = 100 # storage autoscaling; avoids a 3am disk-full incident
  storage_encrypted     = true

  db_name  = "medbot"
  username = "medbot"
  # Managed rotation instead of a Terraform-held password: a password in state is a
  # password in every backup of that state.
  manage_master_user_password = true

  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.rds.id]

  # ── P5.4.10 REQUIREMENT: point-in-time recovery ──────────────────────────────────
  # The backup/restore drill measured RTO (0.5s for a dump restore) but exposed an
  # unbounded RPO: a nightly dump means up to 24h of lost chat history and audit trail.
  # Postgres is this system's only SYSTEM OF RECORD (D1, D9), so unbounded RPO is a
  # compliance problem, not a convenience one. Retention > 0 enables continuous WAL
  # archiving, which is what makes restore-to-any-second possible.
  backup_retention_period = var.db_backup_retention_days
  backup_window           = "03:00-04:00"
  copy_tags_to_snapshot   = true

  # Multi-AZ in prod only: it doubles the instance cost for a synchronous standby, which
  # is right for the 99.9% SLO and wrong for a dev database nobody is paged for.
  multi_az = var.environment == "prod"

  deletion_protection       = var.environment == "prod"
  skip_final_snapshot       = var.environment != "prod"
  final_snapshot_identifier = var.environment == "prod" ? "${var.cluster_name}-final" : null

  performance_insights_enabled = true
}

resource "aws_security_group" "redis" {
  name   = "${var.cluster_name}-${var.environment}-redis"
  vpc_id = module.vpc.vpc_id

  ingress {
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [module.eks.node_security_group_id]
  }
}

resource "aws_elasticache_subnet_group" "main" {
  name       = "${var.cluster_name}-${var.environment}"
  subnet_ids = module.vpc.private_subnets
}

resource "aws_elasticache_replication_group" "main" {
  replication_group_id = "${var.cluster_name}-${var.environment}"
  description          = "medbot cache + rate-limit counters"

  engine             = "redis"
  node_type          = var.redis_node_type
  num_cache_clusters = var.environment == "prod" ? 2 : 1

  subnet_group_name  = aws_elasticache_subnet_group.main.name
  security_group_ids = [aws_security_group.redis.id]

  # NO snapshots, deliberately (P5.4.9): every key here is a cache entry or a rate-limit
  # counter — derived state, reconstructible on demand. Backing it up would buy nothing
  # and cost storage plus operational noise.
  snapshot_retention_limit = 0

  automatic_failover_enabled = var.environment == "prod"
  at_rest_encryption_enabled = true
  transit_encryption_enabled = true
}

# ── Ingestion queue (D11) ───────────────────────────────────────────────────────────
resource "aws_sqs_queue" "ingest_dlq" {
  name = "${var.cluster_name}-${var.environment}-ingest-dlq"
  # 14 days: a poison message must survive a weekend plus an investigation, or the
  # evidence of why ingestion failed is gone before anyone looks.
  message_retention_seconds = 1209600
}

resource "aws_sqs_queue" "ingest" {
  name = "${var.cluster_name}-${var.environment}-ingest"

  # Must exceed the longest ingestion run, or SQS redelivers a job that is still being
  # processed and two workers race to rebuild the same index. Matches
  # worker_visibility_timeout (900s) in medcore config.
  visibility_timeout_seconds = 900
  receive_wait_time_seconds  = 20 # long polling: fewer empty receives, lower cost

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.ingest_dlq.arn
    # Matches worker_max_receives = 3. A message that fails three times is not going to
    # succeed on the fourth; parking it in the DLQ stops an infinite retry loop from
    # burning embedding compute forever.
    maxReceiveCount = 3
  })
}
