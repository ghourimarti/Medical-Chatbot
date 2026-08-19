# VPC + subnets (S16.2).
#
# Community module rather than hand-rolled: a VPC is ~40 resources (subnets, route tables,
# NAT, IGW, associations) whose interactions are well understood and easy to get subtly
# wrong. Hand-rolling one is not a demonstration of skill, it is a demonstration of
# appetite for avoidable bugs.
module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.16"

  name = "${var.cluster_name}-${var.environment}"
  cidr = var.vpc_cidr
  azs  = var.azs

  # Public: load balancers only. Private: every workload. Nothing that runs our code is
  # directly addressable from the internet.
  public_subnets   = [for i in range(length(var.azs)) : cidrsubnet(var.vpc_cidr, 8, i)]
  private_subnets  = [for i in range(length(var.azs)) : cidrsubnet(var.vpc_cidr, 8, i + 10)]
  database_subnets = [for i in range(length(var.azs)) : cidrsubnet(var.vpc_cidr, 8, i + 20)]

  enable_nat_gateway = true
  # ONE NAT gateway in dev, one per AZ in prod. This is a deliberate cost/availability
  # trade: NAT is ~$32/mo each plus data processing, so three of them is real money for an
  # environment nobody is paged for. In prod, a single NAT makes one AZ's failure take out
  # egress for all three — unacceptable against the 99.9% SLO.
  single_nat_gateway = var.environment != "prod"

  enable_dns_hostnames = true
  enable_dns_support   = true

  # Tags EKS requires to auto-discover subnets for load balancers. Without them, a
  # Service of type LoadBalancer provisions nothing and gives no useful error.
  public_subnet_tags  = { "kubernetes.io/role/elb" = 1 }
  private_subnet_tags = { "kubernetes.io/role/internal-elb" = 1 }
}
