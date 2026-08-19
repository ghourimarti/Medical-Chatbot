# IRSA — IAM Roles for Service Accounts (S16.6).
#
# WHY THIS EXISTS. Without IRSA, pods use the NODE's instance profile, so every pod on a
# node shares one identity: the api pod, the worker, and anything else scheduled there all
# get the union of permissions any of them need. That is the opposite of least privilege,
# and it means a compromise of the least-important pod yields the most-privileged
# credentials on the node.
#
# IRSA binds an IAM role to ONE Kubernetes ServiceAccount via a projected OIDC token, so
# the worker can read its SQS queue and the api cannot.

data "aws_iam_policy_document" "worker_sqs" {
  statement {
    # Exactly the actions an SQS consumer performs — no wildcards. `sqs:*` would include
    # DeleteQueue, which no consumer has any business calling.
    actions = [
      "sqs:ReceiveMessage",
      "sqs:DeleteMessage",
      "sqs:GetQueueAttributes",
      "sqs:ChangeMessageVisibility",
    ]
    resources = [aws_sqs_queue.ingest.arn]
  }
}

resource "aws_iam_policy" "worker_sqs" {
  name   = "${var.cluster_name}-${var.environment}-worker-sqs"
  policy = data.aws_iam_policy_document.worker_sqs.json
}

module "worker_irsa" {
  source  = "terraform-aws-modules/iam/aws//modules/iam-role-for-service-accounts-eks"
  version = "~> 5.48"

  role_name = "${var.cluster_name}-${var.environment}-worker"

  role_policy_arns = { sqs = aws_iam_policy.worker_sqs.arn }

  oidc_providers = {
    main = {
      provider_arn = module.eks.oidc_provider_arn
      # Binds to ONE service account. The api's service account is deliberately absent:
      # the api never touches the ingestion queue.
      namespace_service_accounts = ["default:medbot-worker"]
    }
  }
}
