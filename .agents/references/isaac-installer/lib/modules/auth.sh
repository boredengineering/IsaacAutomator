#!/usr/bin/env bash
# ==============================================================================
# auth.sh - Unified OAuth, API Key, Cloud Hub & Local Permissions Manager
# ==============================================================================

check_auth_status() {
    AUTH_ITEMS=()
    detect_target_user

    # 1. Git Global Identity
    local git_name
    git_name="$(sudo -H -u "${TARGET_USER}" git config --global user.name 2>/dev/null || echo "")"
    local git_email
    git_email="$(sudo -H -u "${TARGET_USER}" git config --global user.email 2>/dev/null || echo "")"
    local git_status="Configured"
    local git_id="${git_name} <${git_email}>"
    if [[ -z "$git_name" || -z "$git_email" ]]; then
        git_status="Not Set"
        git_id="Missing user.name/email"
    fi
    AUTH_ITEMS+=("Git Author Identity|${git_status}|${git_id}|~/.gitconfig")

    # 2. SSH Keypair (GitHub/GitLab)
    local ssh_status="Not Found"
    local ssh_id="No ed25519/rsa key"
    if [[ -f "${TARGET_HOME}/.ssh/id_ed25519.pub" ]]; then
        ssh_status="Active"
        ssh_id="$(ssh-keygen -lf "${TARGET_HOME}/.ssh/id_ed25519.pub" 2>/dev/null | awk '{print $2, $4}' || echo "ed25519 Key")"
    elif [[ -f "${TARGET_HOME}/.ssh/id_rsa.pub" ]]; then
        ssh_status="Active"
        ssh_id="$(ssh-keygen -lf "${TARGET_HOME}/.ssh/id_rsa.pub" 2>/dev/null | awk '{print $2, $4}' || echo "RSA Key")"
    fi
    AUTH_ITEMS+=("SSH Public Key|${ssh_status}|${ssh_id}|~/.ssh/")

    # 3. GitHub Auth & Credential Helper
    local gh_status="Not Logged In"
    local gh_user="None"
    local gh_type="None"
    if command -v gh &>/dev/null; then
        local gh_out
        set +e
        gh_out="$(sudo -H -u "${TARGET_USER}" gh auth status 2>&1)"
        local gh_rc=$?
        set -e
        if [[ $gh_rc -eq 0 ]]; then
            gh_status="Logged In"
            gh_user="$(echo "$gh_out" | grep -o "account [^ ]*" | head -n 1 | awk '{print $2}' || echo "Active User")"
            gh_type="OAuth / gh CLI"
        fi
    elif [[ -n "${GITHUB_TOKEN:-}" || -n "${GH_TOKEN:-}" ]]; then
        gh_status="Logged In"
        gh_user="Environment Token"
        gh_type="Token Export"
    fi
    AUTH_ITEMS+=("GitHub (gh CLI)|${gh_status}|${gh_user}|${gh_type}")

    # 4. Hugging Face Hub Auth
    local hf_status="Not Logged In"
    local hf_user="None"
    local hf_type="None"
    local hf_token_file="${TARGET_HOME}/.cache/huggingface/token"
    if [[ -f "${hf_token_file}" ]]; then
        hf_status="Logged In"
        hf_user="Token Active"
        hf_type="~/.cache/huggingface/token"
    elif [[ -n "${HF_TOKEN:-}" || -n "${HUGGINGFACE_TOKEN:-}" ]]; then
        hf_status="Logged In"
        hf_user="Environment Token"
        hf_type="Token Export"
    fi
    AUTH_ITEMS+=("Hugging Face Hub|${hf_status}|${hf_user}|${hf_type}")

    # 5. NVIDIA NGC & nvcr.io Registry Auth
    local ngc_status="Not Logged In"
    local ngc_user="None"
    local ngc_type="None"
    local docker_cfg="${TARGET_HOME}/.docker/config.json"
    if [[ -f "${TARGET_HOME}/.ngc/config" ]]; then
        ngc_status="Logged In"
        ngc_user="NGC CLI Configured"
        ngc_type="~/.ngc/config"
    fi
    if [[ -f "${docker_cfg}" ]] && grep -q "nvcr.io" "${docker_cfg}" 2>/dev/null; then
        ngc_status="Logged In"
        ngc_user="nvcr.io Active"
        ngc_type="Docker Config"
    elif [[ -n "${NGC_API_KEY:-}" ]]; then
        ngc_status="Logged In"
        ngc_user="Environment API Key"
        ngc_type="Token Export"
    fi
    AUTH_ITEMS+=("NVIDIA NGC (nvcr.io)|${ngc_status}|${ngc_user}|${ngc_type}")

    # 6. Weights & Biases (WandB)
    local wandb_status="Not Logged In"
    local wandb_user="None"
    local wandb_type="None"
    if [[ -f "${TARGET_HOME}/.netrc" ]] && grep -q "api.wandb.ai" "${TARGET_HOME}/.netrc" 2>/dev/null; then
        wandb_status="Logged In"
        wandb_user="Netrc Configured"
        wandb_type="~/.netrc"
    elif [[ -n "${WANDB_API_KEY:-}" ]]; then
        wandb_status="Logged In"
        wandb_user="Environment API Key"
        wandb_type="Token Export"
    fi
    AUTH_ITEMS+=("Weights & Biases|${wandb_status}|${wandb_user}|${wandb_type}")

    # 7. Google Cloud (GCP ADC / gcloud)
    local gcp_status="Not Logged In"
    local gcp_user="None"
    local gcp_type="None"
    local gcp_adc="${TARGET_HOME}/.config/gcloud/application_default_credentials.json"
    if [[ -f "${gcp_adc}" ]]; then
        gcp_status="Logged In"
        gcp_user="ADC Active"
        gcp_type="gcloud ADC"
    elif [[ -n "${GOOGLE_APPLICATION_CREDENTIALS:-}" && -f "${GOOGLE_APPLICATION_CREDENTIALS:-}" ]]; then
        gcp_status="Logged In"
        gcp_user="Service Account JSON"
        gcp_type="Env Credentials"
    fi
    AUTH_ITEMS+=("Google Cloud (GCP)|${gcp_status}|${gcp_user}|${gcp_type}")

    # 8. AWS
    local aws_status="Not Logged In"
    local aws_user="None"
    local aws_type="None"
    if [[ -f "${TARGET_HOME}/.aws/credentials" ]]; then
        aws_status="Logged In"
        aws_user="Profile Configured"
        aws_type="~/.aws/credentials"
    elif [[ -n "${AWS_ACCESS_KEY_ID:-}" ]]; then
        aws_status="Logged In"
        aws_user="Environment Keys"
        aws_type="Token Export"
    fi
    AUTH_ITEMS+=("Amazon Web Services|${aws_status}|${aws_user}|${aws_type}")

    # 9. RunPod
    local runpod_status="Not Logged In"
    local runpod_user="None"
    local runpod_type="None"
    if [[ -f "${TARGET_HOME}/.runpod/config.toml" ]]; then
        runpod_status="Logged In"
        runpod_user="Config File"
        runpod_type="~/.runpod/config.toml"
    elif [[ -n "${RUNPOD_API_KEY:-}" ]]; then
        runpod_status="Logged In"
        runpod_user="Environment API Key"
        runpod_type="Token Export"
    fi
    AUTH_ITEMS+=("RunPod GPU Cloud|${runpod_status}|${runpod_user}|${runpod_type}")

    # 10. Local Hardware & Docker User Groups
    local perms_status="Fully Configured"
    local missing_groups=()
    for grp in docker dialout plugdev input video; do
        if ! id -nG "${TARGET_USER}" 2>/dev/null | grep -qw "$grp"; then
            missing_groups+=("$grp")
        fi
    done
    if [[ ${#missing_groups[@]} -gt 0 ]]; then
        perms_status="Missing: ${missing_groups[*]}"
    fi
    AUTH_ITEMS+=("Local Hardware Groups|${perms_status}|User: ${TARGET_USER}|/etc/group")
}

print_auth_dashboard() {
    log_header "Physical AI & Cloud Hub Authentication Status"
    check_auth_status

    printf "${CLR_BOLD}%-24s | %-16s | %-24s | %-26s${CLR_RESET}\n" \
        "Provider / Service" "Auth Status" "Active Identity" "Credential Source"
    echo "--------------------------------------------------------------------------------------------------"

    for row in "${AUTH_ITEMS[@]}"; do
        IFS='|' read -r prov status ident source <<< "$row"
        
        local status_color="${CLR_RESET}"
        case "$status" in
            "Logged In"|"Fully Configured"|"Configured"|"Active") status_color="${CLR_GREEN}" ;;
            "Not Logged In"|"Missing"*|"Not Set"|"Not Found")    status_color="${CLR_YELLOW}" ;;
        esac

        printf "%-24s | ${status_color}%-16s${CLR_RESET} | %-24s | %-26s\n" \
            "$prov" "$status" "$ident" "$source"
    done

    echo "--------------------------------------------------------------------------------------------------"
    echo -e "\n${CLR_BOLD}To authenticate or configure any provider, run:${CLR_RESET}"
    echo -e "  ${CLR_CYAN}./bin/isaac-installer auth login <provider>${CLR_RESET}  (github | huggingface | ngc | wandb | gcp | aws | git)"
    echo -e "  ${CLR_CYAN}./bin/isaac-installer auth gen-ssh${CLR_RESET}           (Generate ed25519 SSH keypair)"
    echo -e "  ${CLR_CYAN}sudo ./bin/isaac-installer auth check-perms${CLR_RESET}   (Repair local hardware group memberships)\n"
}

export_auth_json() {
    check_auth_status
    python3 -c "
import json
rows = []
raw = '''$(for r in "${AUTH_ITEMS[@]}"; do echo "$r"; done)'''.strip().split('\n')
for line in raw:
    if not line: continue
    parts = line.split('|')
    rows.append({
        'provider': parts[0],
        'status': parts[1],
        'identity': parts[2],
        'credential_source': parts[3]
    })
print(json.dumps({'user': '${TARGET_USER}', 'auth_providers': rows}, indent=2))
"
}

auth_generate_ssh_key() {
    detect_target_user
    log_step "Generating ed25519 SSH Keypair for ${TARGET_USER}..."
    local ssh_dir="${TARGET_HOME}/.ssh"
    mkdir -p "${ssh_dir}"
    chmod 700 "${ssh_dir}"

    if [[ -f "${ssh_dir}/id_ed25519" ]]; then
        log_info "SSH key already exists at ${ssh_dir}/id_ed25519.pub"
    else
        sudo -H -u "${TARGET_USER}" ssh-keygen -t ed25519 -C "${TARGET_USER}@$(hostname)" -f "${ssh_dir}/id_ed25519" -N ""
        log_success "Generated SSH key at ${ssh_dir}/id_ed25519.pub"
    fi

    echo -e "\n${CLR_BOLD}Public SSH Key:${CLR_RESET}"
    cat "${ssh_dir}/id_ed25519.pub"
    echo ""

    if command -v gh &>/dev/null; then
        if sudo -H -u "${TARGET_USER}" gh auth status &>/dev/null; then
            read -r -p "Upload this SSH key to your GitHub account? [Y/n]: " choice
            case "$choice" in
                [nN]*) ;;
                *) sudo -H -u "${TARGET_USER}" gh ssh-key add "${ssh_dir}/id_ed25519.pub" --title "$(hostname) Workstation" 2>/dev/null || true
                   log_success "SSH key uploaded to GitHub." ;;
            esac
        fi
    fi
}

auth_configure_git() {
    detect_target_user
    log_step "Configuring Global Git Identity..."
    read -r -p "Enter your Full Name (e.g. Jane Doe): " gname
    read -r -p "Enter your Email (e.g. jane@example.com): " gemail

    if [[ -n "$gname" ]]; then
        sudo -H -u "${TARGET_USER}" git config --global user.name "$gname"
    fi
    if [[ -n "$gemail" ]]; then
        sudo -H -u "${TARGET_USER}" git config --global user.email "$gemail"
    fi
    sudo -H -u "${TARGET_USER}" git config --global init.defaultBranch main
    log_success "Git identity saved to ${TARGET_HOME}/.gitconfig"
}

auth_login_provider() {
    local provider="${1:-all}"
    detect_target_user

    case "$provider" in
        git|identity)
            auth_configure_git
            ;;
        ssh|gen-ssh)
            auth_generate_ssh_key
            ;;
        github|gh)
            log_step "Authenticating GitHub with Browser OAuth..."
            if ! command -v gh &>/dev/null; then
                log_info "Installing GitHub CLI..."
                install_github_cli
            fi
            if command -v gh &>/dev/null; then
                sudo -H -u "${TARGET_USER}" gh auth login -w -s "repo,read:org,workflow"
                sudo -H -u "${TARGET_USER}" gh auth setup-git
                log_success "GitHub authentication and git credential helper configured."
            fi
            ;;
        huggingface|hf)
            log_step "Authenticating Hugging Face Hub..."
            local conda_bin="$(resolve_conda_bin 2>/dev/null || echo "")"
            local conda_root="$(dirname "$(dirname "$conda_bin")" 2>/dev/null || echo "${TARGET_HOME}/miniconda3")"
            sudo -H -u "${TARGET_USER}" bash -c "
                source '${conda_root}/etc/profile.d/conda.sh' 2>/dev/null || true
                if conda info --envs 2>/dev/null | grep -q 'lerobot'; then
                    conda run -n lerobot huggingface-cli login
                elif command -v huggingface-cli &>/dev/null; then
                    huggingface-cli login
                elif command -v pip3 &>/dev/null; then
                    pip3 install --upgrade huggingface_hub[cli] && huggingface-cli login
                else
                    echo 'Please install python3-pip or conda to use huggingface-cli'
                fi
            "
            ;;
        ngc|nvcr)
            log_step "Authenticating NVIDIA NGC & nvcr.io Container Registry..."
            echo -e "\nGenerate your NGC API key at: ${CLR_CYAN}https://org.ngc.nvidia.com/setup/personal-keys${CLR_RESET}\n"
            read -r -s -p "Enter NVIDIA NGC API Key: " ngc_key
            echo ""
            if [[ -n "$ngc_key" ]]; then
                echo "$ngc_key" | docker login nvcr.io -u '$oauthtoken' --password-stdin 2>/dev/null || true
                mkdir -p "${TARGET_HOME}/.ngc"
                cat << NGC_CFG > "${TARGET_HOME}/.ngc/config"
;
; NGC configuration file
;
[CURRENT]
apikey = ${ngc_key}
format_type = ascii
org = default
NGC_CFG
                chown -R "${TARGET_USER}:${TARGET_USER}" "${TARGET_HOME}/.ngc"
                chmod 600 "${TARGET_HOME}/.ngc/config"
                log_success "NVIDIA NGC configured and nvcr.io Docker registry authenticated."
            fi
            ;;
        wandb)
            log_step "Authenticating Weights & Biases..."
            echo -e "\nGet your WandB API key at: ${CLR_CYAN}https://wandb.ai/authorize${CLR_RESET}\n"
            local conda_bin="$(resolve_conda_bin 2>/dev/null || echo "")"
            local conda_root="$(dirname "$(dirname "$conda_bin")" 2>/dev/null || echo "${TARGET_HOME}/miniconda3")"
            sudo -H -u "${TARGET_USER}" bash -c "
                source '${conda_root}/etc/profile.d/conda.sh' 2>/dev/null || true
                if command -v wandb &>/dev/null; then
                    wandb login
                elif command -v pip3 &>/dev/null; then
                    pip3 install wandb && wandb login
                fi
            "
            ;;
        gcp)
            log_step "Authenticating Google Cloud Platform (ADC)..."
            if ! command -v gcloud &>/dev/null; then
                log_info "gcloud CLI not found. Installing Google Cloud SDK..."
                install_gcp_cli
            fi
            if command -v gcloud &>/dev/null; then
                sudo -H -u "${TARGET_USER}" gcloud auth application-default login
            fi
            ;;
        aws)
            log_step "Configuring Amazon Web Services (AWS CLI)..."
            if ! command -v aws &>/dev/null; then
                log_info "aws CLI not found. Installing AWS CLI v2..."
                install_aws_cli
            fi
            if command -v aws &>/dev/null; then
                sudo -H -u "${TARGET_USER}" aws configure
            fi
            ;;
        all)
            auth_login_provider github
            auth_login_provider huggingface
            auth_login_provider ngc
            auth_login_provider wandb
            ;;
        *)
            log_error "Unknown provider: ${provider}. Supported: github, huggingface, ngc, wandb, gcp, aws, git, ssh, all"
            ;;
    esac
}

auth_fix_permissions() {
    log_step "Auditing and Repairing Local User Permissions..."
    detect_target_user

    if [[ "$EUID" -ne 0 ]]; then
        log_fatal "Repairing system permissions requires root. Please run: sudo ./bin/isaac-installer auth check-perms"
    fi

    for grp in docker dialout plugdev input video; do
        if ! getent group "$grp" >/dev/null; then
            groupadd "$grp" 2>/dev/null || true
        fi
        usermod -aG "$grp" "${TARGET_USER}"
    done

    # Ensure uinput permissions
    if [[ -e /dev/uinput ]]; then
        chmod 0660 /dev/uinput
        chgrp input /dev/uinput 2>/dev/null || true
    fi

    log_success "User '${TARGET_USER}' added to groups: docker, dialout, plugdev, input, video."
    log_info "Note: If you were just added to these groups, log out and log back in (or run 'newgrp docker') to activate."
}
