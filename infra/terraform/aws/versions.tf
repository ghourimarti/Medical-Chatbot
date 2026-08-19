# Provider + backend pinning (S16.1).
#
# Versions are pinned with `~>` (not floating): an unpinned provider means `terraform init`
# on a different day produces a different plan for identical code, which destroys the one
# property IaC exists to give you — reproducibility.
terraform {
  required_version = "~> 1.15"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.80"
    }
  }

  # Remote state, commented until the bucket exists (Track D).
  #
  # State must NOT live on a laptop: it holds resource IDs and (despite best efforts)
  # sensitive values, and a local state file means exactly one person can ever apply.
  # S3 + native lockfile gives durability, versioning, and concurrent-apply protection.
  # backend "s3" {
  #   bucket       = "medbot-tfstate-<account-id>"
  #   key          = "aws/terraform.tfstate"
  #   region       = "us-east-1"
  #   encrypt      = true
  #   use_lockfile = true   # S3-native locking; no DynamoDB table needed since TF 1.10
  # }
}

provider "aws" {
  region = var.region

  default_tags {
    # Every resource tagged at the provider level. Untagged resources are how a cloud bill
    # becomes unattributable — and P7.11/P8.7 require measuring cost per environment.
    tags = {
      Project     = "medbot"
      Environment = var.environment
      ManagedBy   = "terraform"
      Repo        = "P5-Medical-Chatbot"
    }
  }
}
