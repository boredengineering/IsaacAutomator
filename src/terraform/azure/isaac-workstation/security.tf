resource "azurerm_network_security_group" "sg" {
  name                = "${var.prefix}.sg"
  location            = var.rg.location
  resource_group_name = var.rg.name

  security_rule {
    name                       = "SSH"
    priority                   = 1001
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "22"
    source_address_prefix      = "*"
    destination_address_prefix = "*"
  }

  security_rule {
    name                       = "NoMachine"
    priority                   = 102
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "*"
    source_port_range          = "*"
    destination_port_ranges    = ["4000"]
    source_address_prefix      = "*"
    destination_address_prefix = "*"
  }

  security_rule {
    name                       = "VNC"
    priority                   = 103
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "TCP"
    source_port_range          = "*"
    destination_port_ranges    = ["5900"]
    source_address_prefix      = "*"
    destination_address_prefix = "*"
  }

  security_rule {
    name                       = "noVNC"
    priority                   = 106
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "TCP"
    source_port_range          = "*"
    destination_port_ranges    = ["6080"]
    source_address_prefix      = "*"
    destination_address_prefix = "*"
  }

  # Isaac Sim WebRTC livestream: browser client (8211), signaling (49100) and the
  # media/session ranges. Needed for the stream to be reachable via the public IP
  # (issue #19). protocol "*" covers both the TCP and UDP the stream uses.
  security_rule {
    name                       = "WebRTC"
    priority                   = 107
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "*"
    source_port_range          = "*"
    destination_port_ranges    = ["8211", "47995-48012", "49000-49007", "49100"]
    source_address_prefix      = "*"
    destination_address_prefix = "*"
  }
}

# security rule for custom ssh port
resource "azurerm_network_security_rule" "custom_ssh" {
  name                        = "Custom_SSH"
  priority                    = 104
  direction                   = "Inbound"
  access                      = "Allow"
  protocol                    = "Tcp"
  source_port_range           = "*"
  destination_port_range      = var.ssh_port
  source_address_prefix       = "*"
  destination_address_prefix  = "*"
  network_security_group_name = azurerm_network_security_group.sg.name
  resource_group_name         = var.rg.name
  count                       = var.ssh_port != 22 ? 1 : 0
}
