
resource "google_compute_network" "default" {
  name = "${var.prefix}-network"
}

# Static external IP so the instance keeps the same public address
# across stop/start cycles. An ephemeral IP would be released on stop.
resource "google_compute_address" "static_ip" {
  name   = "${var.prefix}-ip"
  region = var.region
}

# all egress
resource "google_compute_firewall" "egress" {
  name    = "${var.prefix}-fwrules-egress"
  network = google_compute_network.default.self_link

  allow {
    protocol = "all"
  }

  direction          = "EGRESS"
  destination_ranges = ["0.0.0.0/0"]
}

# ssh
resource "google_compute_firewall" "ssh" {
  name    = "${var.prefix}-fwrules-ssh"
  network = google_compute_network.default.self_link

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }

  source_ranges = var.ingress_cidrs
}

# nomachine
resource "google_compute_firewall" "nomachine" {
  name    = "${var.prefix}-fwrules-nomachine"
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
  name    = "${var.prefix}-fwrules-vnc"
  network = google_compute_network.default.self_link

  allow {
    protocol = "tcp"
    ports    = ["5900"]
  }

  source_ranges = var.ingress_cidrs
}

# novnc
resource "google_compute_firewall" "novnc" {
  name    = "${var.prefix}-fwrules-novnc"
  network = google_compute_network.default.self_link

  allow {
    protocol = "tcp"
    ports    = ["6080"]
  }

  source_ranges = var.ingress_cidrs
}

# Isaac Sim WebRTC livestream: browser client (8211), signaling (49100) and the
# media/session port ranges. Without these open the stream works on localhost
# (inside the desktop) but not via the instance's public IP (see issue #19).
# Scoped to ingress_cidrs like every other rule - the stream is unauthenticated,
# so keep it restricted to your client IP(s).
resource "google_compute_firewall" "webrtc" {
  name    = "${var.prefix}-fwrules-webrtc"
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
  name    = "${var.prefix}-fwrules-ssh-custom"
  network = google_compute_network.default.self_link

  allow {
    protocol = "tcp"
    ports    = ["${var.ssh_port}"]
  }

  source_ranges = var.ingress_cidrs
}

# KasmVNC (HTTPS WebRTC)
resource "google_compute_firewall" "kasmvnc" {
  name    = "${var.prefix}-fwrules-kasmvnc"
  network = google_compute_network.default.self_link

  allow {
    protocol = "tcp"
    ports    = ["8444"]
  }

  source_ranges = var.ingress_cidrs
}

# NICE DCV (TCP & UDP)
resource "google_compute_firewall" "dcv" {
  name    = "${var.prefix}-fwrules-dcv"
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
  name    = "${var.prefix}-fwrules-xrdp"
  network = google_compute_network.default.self_link

  allow {
    protocol = "tcp"
    ports    = ["3389"]
  }

  source_ranges = var.ingress_cidrs
}

# Sunshine / Moonlight streaming
resource "google_compute_firewall" "sunshine" {
  name    = "${var.prefix}-fwrules-sunshine"
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
  name    = "${var.prefix}-fwrules-parsec"
  network = google_compute_network.default.self_link

  allow {
    protocol = "udp"
    ports    = ["8000-8040"]
  }

  source_ranges = var.ingress_cidrs
}
