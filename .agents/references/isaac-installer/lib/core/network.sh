#!/usr/bin/env bash
# ==============================================================================
# network.sh - Network Connectivity, CDN Latency & Download Speed Benchmarking
# ==============================================================================

test_cdn_endpoint() {
    local name="$1"
    local url="$2"
    
    local http_code
    local time_total
    
    if command -v curl &>/dev/null; then
        local response
        response=$(curl -s -o /dev/null -w "%{http_code}|%{time_total}" --connect-timeout 4 "$url" 2>/dev/null || echo "000|0")
        http_code=$(echo "$response" | cut -d'|' -f1)
        time_total=$(echo "$response" | cut -d'|' -f2)
        
        if [[ "$http_code" =~ ^(200|301|302|403|404)$ ]]; then
            local latency_ms
            latency_ms=$(awk "BEGIN {printf \"%.0f\", ${time_total} * 1000}")
            echo -e "  ${CLR_GREEN}✔ ${name}:${CLR_RESET} Reachable (${latency_ms} ms)"
            return 0
        else
            echo -e "  ${CLR_YELLOW}⚠ ${name}:${CLR_RESET} Unreachable / Slow (HTTP ${http_code})"
            return 1
        fi
    else
        echo -e "  ${CLR_GRAY}ℹ ${name}:${CLR_RESET} Skipped (curl not found)"
        return 0
    fi
}

benchmark_network_preflight() {
    log_step "Benchmarking CDN & Repository Connectivity..."
    test_cdn_endpoint "NVIDIA Omniverse CDN (Isaac Sim 15GB)" "https://download.isaacsim.omniverse.nvidia.com"
    test_cdn_endpoint "Hugging Face Hub (LeRobot Models)" "https://huggingface.co"
    test_cdn_endpoint "GitHub (Repositories & Releases)" "https://github.com"
    test_cdn_endpoint "Ubuntu Package Mirrors" "http://archive.ubuntu.com"
}
