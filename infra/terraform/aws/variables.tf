variable "region" {
  type    = string
  default = "us-east-1"
}

variable "environment" {
  type = string
  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "environment must be dev, staging, or prod."
  }
}

variable "cluster_name" {
  type    = string
  default = "medbot"
}

variable "kubernetes_version" {
  type    = string
  default = "1.31"
}

# Multi-AZ is not optional at the 99.9% SLO (43.8 min/month error budget): a single-AZ
# cluster makes one AZ failure a total outage, which spends the whole month's budget.
variable "azs" {
  type    = list(string)
  default = ["us-east-1a", "us-east-1b", "us-east-1c"]
}

variable "vpc_cidr" {
  type    = string
  default = "10.20.0.0/16"
}

variable "cpu_instance_type" {
  type    = string
  default = "t3.large"
}

variable "gpu_instance_type" {
  # g6.xlarge = 1x L4 (24GB). The S3b/S14 venue for self-hosted vLLM (D4b, D12).
  type    = string
  default = "g6.xlarge"
}

variable "gpu_desired_size" {
  # ZERO by default, deliberately. A forgotten 24/7 GPU node is ~$600/mo — measured in
  # S3b as the single biggest waste vector in this system (D20). Scale up for a
  # benchmark window, scale back to zero after.
  type    = number
  default = 0
}

variable "db_instance_class" {
  type    = string
  default = "db.t4g.micro"
}

# PITR. This is a P5.4.10 REQUIREMENT, not a preference: the backup/restore drill measured
# RTO but showed RPO was unbounded without point-in-time recovery. Any value > 0 enables
# continuous WAL archiving; 0 would silently disable PITR entirely.
variable "db_backup_retention_days" {
  type    = number
  default = 7
  validation {
    condition     = var.db_backup_retention_days >= 1
    error_message = "PITR requires backup retention >= 1 day (P5.4.10)."
  }
}

variable "redis_node_type" {
  type    = string
  default = "cache.t4g.micro"
}
