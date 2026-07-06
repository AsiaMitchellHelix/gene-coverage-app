resource "aws_db_subnet_group" "main" {
  name       = var.app_name
  subnet_ids = var.private_subnet_ids
}

resource "aws_security_group" "rds" {
  name   = "${var.app_name}-rds"
  vpc_id = var.vpc_id

  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.ecs.id]
  }
}

resource "aws_db_instance" "postgres" {
  identifier              = var.app_name
  engine                  = "postgres"
  engine_version          = "16.2"
  instance_class          = "db.t3.medium"
  allocated_storage       = 20
  storage_encrypted       = true
  db_name                 = "genecoverage"
  username                = "gcovadmin"
  password                = var.db_password
  db_subnet_group_name    = aws_db_subnet_group.main.name
  vpc_security_group_ids  = [aws_security_group.rds.id]
  skip_final_snapshot     = false
  final_snapshot_identifier = "${var.app_name}-final"
  backup_retention_period = 7
  deletion_protection     = true
}
