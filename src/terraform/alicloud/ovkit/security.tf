resource "alicloud_security_group" "default" {
  name   = "${var.prefix}-sg"
  vpc_id = var.vpc.id
}

# security rule for ssh
resource "alicloud_security_group_rule" "allow_ssh" {
  priority          = 1
  security_group_id = alicloud_security_group.default.id
  type              = "ingress"
  ip_protocol       = "tcp"
  nic_type          = "intranet"
  policy            = "accept"
  port_range        = "22/22"
  cidr_ip           = "0.0.0.0/0"
}

# security rule for novnc
resource "alicloud_security_group_rule" "allow_novnc" {
  priority          = 2
  security_group_id = alicloud_security_group.default.id
  type              = "ingress"
  ip_protocol       = "tcp"
  nic_type          = "intranet"
  policy            = "accept"
  port_range        = "6080/6080"
  cidr_ip           = "0.0.0.0/0"
}

# security rule for ping
resource "alicloud_security_group_rule" "allow_ping" {
  priority          = 3
  security_group_id = alicloud_security_group.default.id
  type              = "ingress"
  ip_protocol       = "icmp"
  nic_type          = "intranet"
  policy            = "accept"
  port_range        = "-1/-1"
  cidr_ip           = "0.0.0.0/0"
}

# security rule for nomachine
resource "alicloud_security_group_rule" "allow_nomachine" {
  priority          = 4
  security_group_id = alicloud_security_group.default.id
  type              = "ingress"
  ip_protocol       = "tcp"
  nic_type          = "intranet"
  policy            = "accept"
  port_range        = "4000/4000"
  cidr_ip           = "0.0.0.0/0"
}

# custom ssh port
resource "alicloud_security_group_rule" "custom_ssh" {
  priority          = 5
  count             = var.ssh_port != 22 ? 1 : 0
  security_group_id = alicloud_security_group.default.id
  type              = "ingress"
  ip_protocol       = "tcp"
  nic_type          = "intranet"
  policy            = "accept"
  port_range        = "${var.ssh_port}/${var.ssh_port}"
  cidr_ip           = "0.0.0.0/0"
}

# Isaac Sim WebRTC livestream: browser client (8211), signaling (49100) and the
# media/session ranges, over both TCP and UDP. Needed for the stream to be
# reachable via the public IP (issue #19). One rule per protocol/range - Alibaba
# security-group rules take a single protocol and port range each.
locals {
  webrtc_rules = {
    tcp_client   = { proto = "tcp", range = "8211/8211" }
    tcp_signal   = { proto = "tcp", range = "49100/49100" }
    tcp_media_a  = { proto = "tcp", range = "47995/48012" }
    tcp_media_b  = { proto = "tcp", range = "49000/49007" }
    udp_media_a  = { proto = "udp", range = "47995/48012" }
    udp_media_b  = { proto = "udp", range = "49000/49007" }
    kasmvnc      = { proto = "tcp", range = "8444/8444" }
    dcv_tcp      = { proto = "tcp", range = "8443/8443" }
    dcv_udp      = { proto = "udp", range = "8443/8443" }
    xrdp         = { proto = "tcp", range = "3389/3389" }
    sunshine_web = { proto = "tcp", range = "47990/47990" }
    sunshine_a   = { proto = "tcp", range = "47984/47984" }
    sunshine_b   = { proto = "tcp", range = "47989/47989" }
    sunshine_c   = { proto = "tcp", range = "48010/48010" }
    sunshine_u   = { proto = "udp", range = "47990/47990" }
    parsec       = { proto = "udp", range = "8000/8040" }
  }
}

resource "alicloud_security_group_rule" "webrtc" {
  for_each          = local.webrtc_rules
  priority          = 6
  security_group_id = alicloud_security_group.default.id
  type              = "ingress"
  ip_protocol       = each.value.proto
  nic_type          = "intranet"
  policy            = "accept"
  port_range        = each.value.range
  cidr_ip           = "0.0.0.0/0"
}
