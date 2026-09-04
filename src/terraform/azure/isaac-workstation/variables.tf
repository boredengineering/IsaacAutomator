variable "prefix" {
  default = null
}

variable "rg" {
  default = null
}

variable "subnet" {
  default = null
}

variable "ssh_key" {
  default = null
}

variable "vm_type" {
  type = string
}

variable "from_image" {
  default = false
  type    = bool
}

variable "ssh_port" {
  type = number
}

variable "os_username" {
  type    = string
  default = "ubuntu"
}

variable "security_profile" {
  description = "Security profile tier: simple, team, or enterprise"
  type        = string
  default     = "simple"
}

variable "ingress_cidrs" {
  description = "CIDR blocks for ingress traffic"
  type        = list(string)
  default     = ["0.0.0.0/0"]
}
