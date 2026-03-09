# terraform/modules/networking/main.tf
# VPC, subnets, NAT gateway, VPC endpoints for Databricks on AWS

locals {
  az_count = length(var.availability_zones)
}

# ─── VPC ───────────────────────────────────────────────────────────────────
resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = merge(var.tags, {
    Name = "${var.prefix}-databricks-vpc"
  })
}

# ─── PUBLIC SUBNETS ────────────────────────────────────────────────────────
resource "aws_subnet" "public" {
  count             = local.az_count
  vpc_id            = aws_vpc.main.id
  cidr_block        = cidrsubnet(var.vpc_cidr, 4, count.index)
  availability_zone = var.availability_zones[count.index]

  tags = merge(var.tags, {
    Name = "${var.prefix}-public-${var.availability_zones[count.index]}"
    Tier = "public"
  })
}

# ─── PRIVATE SUBNETS (Databricks clusters) ─────────────────────────────────
resource "aws_subnet" "private" {
  count             = local.az_count
  vpc_id            = aws_vpc.main.id
  cidr_block        = cidrsubnet(var.vpc_cidr, 4, count.index + local.az_count)
  availability_zone = var.availability_zones[count.index]

  tags = merge(var.tags, {
    Name = "${var.prefix}-private-${var.availability_zones[count.index]}"
    Tier = "private"
  })
}

# ─── INTERNET GATEWAY ──────────────────────────────────────────────────────
resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id
  tags   = merge(var.tags, { Name = "${var.prefix}-igw" })
}

# ─── ELASTIC IPS for NAT ───────────────────────────────────────────────────
resource "aws_eip" "nat" {
  count  = local.az_count
  domain = "vpc"
  tags   = merge(var.tags, { Name = "${var.prefix}-nat-eip-${count.index}" })
}

# ─── NAT GATEWAYS ──────────────────────────────────────────────────────────
resource "aws_nat_gateway" "main" {
  count         = local.az_count
  allocation_id = aws_eip.nat[count.index].id
  subnet_id     = aws_subnet.public[count.index].id

  tags = merge(var.tags, {
    Name = "${var.prefix}-nat-${var.availability_zones[count.index]}"
  })

  depends_on = [aws_internet_gateway.main]
}

# ─── ROUTE TABLES ──────────────────────────────────────────────────────────
resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }

  tags = merge(var.tags, { Name = "${var.prefix}-public-rt" })
}

resource "aws_route_table" "private" {
  count  = local.az_count
  vpc_id = aws_vpc.main.id

  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.main[count.index].id
  }

  tags = merge(var.tags, {
    Name = "${var.prefix}-private-rt-${var.availability_zones[count.index]}"
  })
}

resource "aws_route_table_association" "public" {
  count          = local.az_count
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table_association" "private" {
  count          = local.az_count
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private[count.index].id
}

# ─── VPC ENDPOINTS ─────────────────────────────────────────────────────────
# S3 Gateway endpoint (free, keeps S3 traffic inside AWS backbone)
resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.main.id
  service_name      = "com.amazonaws.${var.region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = aws_route_table.private[*].id

  tags = merge(var.tags, { Name = "${var.prefix}-s3-endpoint" })
}

# KMS Interface endpoint
resource "aws_vpc_endpoint" "kms" {
  vpc_id              = aws_vpc.main.id
  service_name        = "com.amazonaws.${var.region}.kms"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = aws_subnet.private[*].id
  security_group_ids  = [aws_security_group.vpc_endpoints.id]
  private_dns_enabled = true

  tags = merge(var.tags, { Name = "${var.prefix}-kms-endpoint" })
}

# Secrets Manager Interface endpoint
resource "aws_vpc_endpoint" "secretsmanager" {
  vpc_id              = aws_vpc.main.id
  service_name        = "com.amazonaws.${var.region}.secretsmanager"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = aws_subnet.private[*].id
  security_group_ids  = [aws_security_group.vpc_endpoints.id]
  private_dns_enabled = true

  tags = merge(var.tags, { Name = "${var.prefix}-secretsmanager-endpoint" })
}

# ─── SECURITY GROUPS ───────────────────────────────────────────────────────
resource "aws_security_group" "databricks_cluster" {
  name        = "${var.prefix}-databricks-cluster-sg"
  description = "Security group for Databricks cluster nodes"
  vpc_id      = aws_vpc.main.id

  # Intra-cluster communication
  ingress {
    from_port = 0
    to_port   = 0
    protocol  = "-1"
    self      = true
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(var.tags, { Name = "${var.prefix}-cluster-sg" })
}

resource "aws_security_group" "vpc_endpoints" {
  name        = "${var.prefix}-vpc-endpoints-sg"
  description = "Security group for VPC interface endpoints"
  vpc_id      = aws_vpc.main.id

  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }

  tags = merge(var.tags, { Name = "${var.prefix}-vpc-endpoints-sg" })
}
