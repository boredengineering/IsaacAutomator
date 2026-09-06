resource "google_compute_network" "default" {
  name                    = "${var.prefix}-network"
  auto_create_subnetworks = false
}

# Dedicated subnetwork with Private Google Access (PGA)
resource "google_compute_subnetwork" "default" {
  name                     = "${var.prefix}-subnet"
  ip_cidr_range            = "10.10.0.0/24"
  region                   = var.region
  network                  = google_compute_network.default.id
  private_ip_google_access = true
}

# Static external IP so the instance keeps the same public address
# across stop/start cycles. Omitted when enable_iap_only is true (zero public IP).
resource "google_compute_address" "static_ip" {
  count  = var.enable_iap_only ? 0 : 1
  name   = "${var.prefix}-ip"
  region = var.region
}

# Cloud Router & NAT for outbound package downloads on private instances
resource "google_compute_router" "router" {
  count   = var.enable_iap_only ? 1 : 0
  name    = "${var.prefix}-router"
  region  = var.region
  network = google_compute_network.default.id
}

resource "google_compute_router_nat" "nat" {
  count                              = var.enable_iap_only ? 1 : 0
  name                               = "${var.prefix}-nat"
  router                             = google_compute_router.router[0].name
  region                             = var.region
  nat_ip_allocate_option             = "AUTO_ONLY"
  source_subnetwork_ip_ranges_to_nat = "ALL_SUBNETWORKS_ALL_IP_RANGES"
}

locals {
  # GCP firewall rules have a strict 63 character maximum length.
  # Truncate prefix if necessary to guarantee all rule names remain <= 63 chars.
  fw_prefix = trimsuffix(substr(var.prefix, 0, 42), "-")
}

# Identity-Aware Proxy (IAP) TCP Forwarding Ingress Rule
resource "google_compute_firewall" "iap_ingress" {
  count   = var.enable_iap_only ? 1 : 0
  name    = "${local.fw_prefix}-fw-iap"
  network = google_compute_network.default.self_link

  direction     = "INGRESS"
  source_ranges = ["35.235.240.0/20"] # Official Google IAP CIDR Block

  allow {
    protocol = "tcp"
    ports    = ["22", "8443", "8444", "6080", "4000"]
  }
}

# all egress
resource "google_compute_firewall" "egress" {
  name    = "${local.fw_prefix}-fw-egress"
  network = google_compute_network.default.self_link

  allow {
    protocol = "all"
  }

  direction          = "EGRESS"
  destination_ranges = ["0.0.0.0/0"]
}

# Public ingress firewall rules (Omitted when enable_iap_only is true)

# ssh
resource "google_compute_firewall" "ssh" {
  count   = var.enable_iap_only ? 0 : 1
  name    = "${local.fw_prefix}-fw-ssh"
  network = google_compute_network.default.self_link

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }

  source_ranges = var.ingress_cidrs
}

# nomachine
resource "google_compute_firewall" "nomachine" {
  count   = var.enable_iap_only ? 0 : 1
  name    = "${local.fw_prefix}-fw-nomachine"
  network = google_compute_network.default.self_link

  allow {
    protocol = "udp"
    ports    = ["4000"]
  }

  allow {
    protocol = "tcp"
    ports    = ["4000"]
  }

  source_ranges = var.ingress_cidrs
}

# vnc
resource "google_compute_firewall" "vnc" {
  count   = var.enable_iap_only ? 0 : 1
  name    = "${local.fw_prefix}-fw-vnc"
  network = google_compute_network.default.self_link

  allow {
    protocol = "tcp"
    ports    = ["5900"]
  }

  source_ranges = var.ingress_cidrs
}

# novnc
resource "google_compute_firewall" "novnc" {
  count   = var.enable_iap_only ? 0 : 1
  name    = "${local.fw_prefix}-fw-novnc"
  network = google_compute_network.default.self_link

  allow {
    protocol = "tcp"
    ports    = ["6080"]
  }

  source_ranges = var.ingress_cidrs
}

# Isaac Sim WebRTC livestream
resource "google_compute_firewall" "webrtc" {
  count   = var.enable_iap_only ? 0 : 1
  name    = "${local.fw_prefix}-fw-webrtc"
  network = google_compute_network.default.self_link

  allow {
    protocol = "tcp"
    ports    = ["8211", "47995-48012", "49000-49007", "49100"]
  }

  allow {
    protocol = "udp"
    ports    = ["47995-48012", "49000-49007"]
  }

  source_ranges = var.ingress_cidrs
}

# custom ssh port
resource "google_compute_firewall" "ssh_custom" {
  count   = var.enable_iap_only ? 0 : 1
  name    = "${local.fw_prefix}-fw-ssh-custom"
  network = google_compute_network.default.self_link

  allow {
    protocol = "tcp"
    ports    = ["${var.ssh_port}"]
  }

  source_ranges = var.ingress_cidrs
}

# KasmVNC (HTTPS WebRTC)
resource "google_compute_firewall" "kasmvnc" {
  count   = var.enable_iap_only ? 0 : 1
  name    = "${local.fw_prefix}-fw-kasmvnc"
  network = google_compute_network.default.self_link

  allow {
    protocol = "tcp"
    ports    = ["8444"]
  }

  source_ranges = var.ingress_cidrs
}

# NICE DCV (TCP & UDP)
resource "google_compute_firewall" "dcv" {
  count   = var.enable_iap_only ? 0 : 1
  name    = "${local.fw_prefix}-fw-dcv"
  network = google_compute_network.default.self_link

  allow {
    protocol = "tcp"
    ports    = ["8443"]
  }

  allow {
    protocol = "udp"
    ports    = ["8443"]
  }

  source_ranges = var.ingress_cidrs
}

# xrdp (Microsoft Remote Desktop)
resource "google_compute_firewall" "xrdp" {
  count   = var.enable_iap_only ? 0 : 1
  name    = "${local.fw_prefix}-fw-xrdp"
  network = google_compute_network.default.self_link

  allow {
    protocol = "tcp"
    ports    = ["3389"]
  }

  source_ranges = var.ingress_cidrs
}

# Sunshine / Moonlight streaming
resource "google_compute_firewall" "sunshine" {
  count   = var.enable_iap_only ? 0 : 1
  name    = "${local.fw_prefix}-fw-sunshine"
  network = google_compute_network.default.self_link

  allow {
    protocol = "tcp"
    ports    = ["47984", "47989", "47990", "48010"]
  }

  allow {
    protocol = "udp"
    ports    = ["47990", "47998-48000"]
  }

  source_ranges = var.ingress_cidrs
}

# Parsec (UDP peer-to-peer range)
resource "google_compute_firewall" "parsec" {
  count   = var.enable_iap_only ? 0 : 1
  name    = "${local.fw_prefix}-fw-parsec"
  network = google_compute_network.default.self_link

  allow {
    protocol = "udp"
    ports    = ["8000-8040"]
  }

  source_ranges = var.ingress_cidrs
}

