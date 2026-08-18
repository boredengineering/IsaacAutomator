# security group for isaac-workstation
resource "aws_security_group" "sg" {
  name   = "${var.prefix}.sg"
  vpc_id = var.vpc.id

  tags = {
    Name = "${var.prefix}.sg"
  }

  # ssh
  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = var.ingress_cidrs
  }

  # nomachine
  ingress {
    from_port   = 4000
    to_port     = 4000
    protocol    = "tcp"
    cidr_blocks = var.ingress_cidrs
  }
  ingress {
    from_port   = 4000
    to_port     = 4000
    protocol    = "udp"
    cidr_blocks = var.ingress_cidrs
  }

  # vnc
  ingress {
    from_port   = 5900
    to_port     = 5900
    protocol    = "tcp"
    cidr_blocks = var.ingress_cidrs
  }

  # novnc
  ingress {
    from_port   = 6080
    to_port     = 6080
    protocol    = "tcp"
    cidr_blocks = var.ingress_cidrs
  }

  # Isaac Sim WebRTC livestream (browser client 8211, signaling 49100, media/session
  # ranges). Without these the stream works on localhost but not via the public IP
  # (issue #19). Unauthenticated, so scoped to ingress_cidrs like the rest.
  ingress {
    from_port   = 8211
    to_port     = 8211
    protocol    = "tcp"
    cidr_blocks = var.ingress_cidrs
  }
  ingress {
    from_port   = 47995
    to_port     = 48012
    protocol    = "tcp"
    cidr_blocks = var.ingress_cidrs
  }
  ingress {
    from_port   = 47995
    to_port     = 48012
    protocol    = "udp"
    cidr_blocks = var.ingress_cidrs
  }
  ingress {
    from_port   = 49000
    to_port     = 49007
    protocol    = "tcp"
    cidr_blocks = var.ingress_cidrs
  }
  ingress {
    from_port   = 49000
    to_port     = 49007
    protocol    = "udp"
    cidr_blocks = var.ingress_cidrs
  }
  ingress {
    from_port   = 49100
    to_port     = 49100
    protocol    = "tcp"
    cidr_blocks = var.ingress_cidrs
  }

  # KasmVNC (HTTPS WebRTC)
  ingress {
    from_port   = 8444
    to_port     = 8444
    protocol    = "tcp"
    cidr_blocks = var.ingress_cidrs
  }

  # NICE DCV
  ingress {
    from_port   = 8443
    to_port     = 8443
    protocol    = "tcp"
    cidr_blocks = var.ingress_cidrs
  }
  ingress {
    from_port   = 8443
    to_port     = 8443
    protocol    = "udp"
    cidr_blocks = var.ingress_cidrs
  }

  # xrdp (Microsoft Remote Desktop)
  ingress {
    from_port   = 3389
    to_port     = 3389
    protocol    = "tcp"
    cidr_blocks = var.ingress_cidrs
  }

  # Sunshine / Moonlight
  ingress {
    from_port   = 47984
    to_port     = 47984
    protocol    = "tcp"
    cidr_blocks = var.ingress_cidrs
  }
  ingress {
    from_port   = 47989
    to_port     = 47990
    protocol    = "tcp"
    cidr_blocks = var.ingress_cidrs
  }
  ingress {
    from_port   = 47990
    to_port     = 47990
    protocol    = "udp"
    cidr_blocks = var.ingress_cidrs
  }
  ingress {
    from_port   = 47998
    to_port     = 48000
    protocol    = "udp"
    cidr_blocks = var.ingress_cidrs
  }

  # Parsec (UDP peer-to-peer range)
  ingress {
    from_port   = 8000
    to_port     = 8040
    protocol    = "udp"
    cidr_blocks = var.ingress_cidrs
  }

  # allow outbound traffic

  egress {
    from_port        = 0
    to_port          = 0
    protocol         = "-1"
    cidr_blocks      = ["0.0.0.0/0"]
    ipv6_cidr_blocks = ["::/0"]
  }
}

# custom ssh port
resource "aws_security_group_rule" "custom_ssh" {
  count             = var.ssh_port != 22 ? 1 : 0
  type              = "ingress"
  security_group_id = aws_security_group.sg.id
  from_port         = var.ssh_port
  to_port           = var.ssh_port
  protocol          = "tcp"
  cidr_blocks       = var.ingress_cidrs
}
