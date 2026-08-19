output "cluster_name" {
  value = module.eks.cluster_name
}

output "cluster_endpoint" {
  value = module.eks.cluster_endpoint
}

output "configure_kubectl" {
  description = "Run this to point kubectl at the cluster."
  value       = "aws eks update-kubeconfig --region ${var.region} --name ${module.eks.cluster_name}"
}

# Connection details feed the Helm chart's `secrets.*` values (values-aws.yaml). Marked
# sensitive so they are not echoed into CI logs on every apply.
output "database_endpoint" {
  value     = aws_db_instance.main.endpoint
  sensitive = true
}

output "redis_endpoint" {
  value     = aws_elasticache_replication_group.main.primary_endpoint_address
  sensitive = true
}

output "sqs_queue_url" {
  value = aws_sqs_queue.ingest.url
}

output "worker_role_arn" {
  description = "Annotate the worker ServiceAccount with this for IRSA."
  value       = module.worker_irsa.iam_role_arn
}
