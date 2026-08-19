# EKS cluster + node groups (S16.3).
module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 20.31"

  cluster_name    = "${var.cluster_name}-${var.environment}"
  cluster_version = var.kubernetes_version

  vpc_id     = module.vpc.vpc_id
  subnet_ids = module.vpc.private_subnets

  # Public endpoint so CI and an operator laptop can reach the API server. Restrict
  # `cluster_endpoint_public_access_cidrs` for a real prod deployment.
  cluster_endpoint_public_access = true

  # Required for IRSA (S16.6): pods assume IAM roles via a projected service-account
  # token instead of node-wide credentials. Without this, every pod on a node inherits
  # the node's permissions — the exact opposite of least privilege.
  enable_irsa = true

  eks_managed_node_groups = {
    # CPU pool: api, ml-service, worker, and the data tier if self-hosted.
    cpu = {
      instance_types = [var.cpu_instance_type]
      min_size       = 2 # >= 2 so a PodDisruptionBudget can ever be satisfied
      max_size       = 6
      desired_size   = 2
    }

    # GPU pool for the self-hosted vLLM venue (D4b, D12). TAINTED so ordinary workloads
    # cannot land on an expensive GPU node — without the taint the scheduler will happily
    # place a 250m-CPU API pod on a $600/mo instance.
    gpu = {
      instance_types = [var.gpu_instance_type]
      ami_type       = "AL2_x86_64_GPU"
      min_size       = 0
      max_size       = 2
      desired_size   = var.gpu_desired_size # 0 by default — see variables.tf

      taints = [{
        key    = "nvidia.com/gpu"
        value  = "true"
        effect = "NO_SCHEDULE"
      }]

      labels = { workload = "inference" }
    }
  }
}
