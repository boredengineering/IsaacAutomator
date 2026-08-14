# Isaac Automator - Flex-start Integration Plan

## 1. Terraform Variables Update

Modify `terraform/gcp/variables.tf` to introduce the optional flag.

```hcl
variable "use_flex_start" {
  description = "Deploy using GCP Flex-start (Dynamic Workload Scheduler) to improve capacity availability"
  type        = bool
  default     = false
}
```

## 2. Terraform Main Configuration Update

Modify the `google_compute_instance` resource in `terraform/gcp/main.tf` using dynamic blocks to conditionally apply the Flex-start scheduling configuration. Note the addition of `automatic_restart = false`.

```hcl
  dynamic "scheduling" {
    for_each = var.use_flex_start ? [1] : []
    content {
      provisioning_model          = "FLEX_START"
      instance_termination_action = "STOP"
      automatic_restart           = false

      max_run_duration {
        seconds = 604800 # 7 days max allowed duration
      }
    }
  }

  dynamic "scheduling" {
    for_each = var.use_flex_start ? [] : [1]
    content {
      provisioning_model = "STANDARD"
      # automatic_restart defaults to true for STANDARD
    }
  }
```

## 3. CLI Wrapper Update

Update the root `./deploy-gcp` bash script to accept the new flag and pass it as a Terraform variable.

```bash
# Add to the argument parsing while loop
      --flex-start)
        USE_FLEX_START=true
        shift
        ;;

# ... later in the script, right before terraform apply ...

TF_VARS=""
if [ "$USE_FLEX_START" = true ]; then
  TF_VARS="$TF_VARS -var=\"use_flex_start=true\""
fi

# Apply the infrastructure
terraform apply $TF_VARS -auto-approve
```

## 4. Flex-start VM Cycling Script

Create `cycle-vm.sh` in the repository root to automatically manage the 7-day limit. (This includes a python patch to safely parse ISO timestamps containing `Z`, ensuring cross-platform compatibility).

```bash
#!/bin/bash
# cycle-vm.sh
# Safely cycles a GCP Flex-start VM if it is approaching its 7-day maximum run duration.

INSTANCE_NAME="renan-test"
ZONE="us-central1-b"
PROJECT="cybernetic-renan"
MAX_AGE_SECONDS=561600 # 6.5 days in seconds

echo "Checking uptime for $INSTANCE_NAME in $ZONE..."

# Fetch the last start timestamp in ISO format
START_TIME_ISO=$(gcloud compute instances describe $INSTANCE_NAME \
    --zone=$ZONE \
    --project=$PROJECT \
    --format="value(lastStartTimestamp)")

if [ -z "$START_TIME_ISO" ]; then
    echo "Error: Could not retrieve start time. Is the VM running?"
    exit 1
fi

# Convert ISO timestamp to epoch seconds securely on both Mac and Linux
START_EPOCH=$(python3 -c "import datetime; print(int(datetime.datetime.fromisoformat('$START_TIME_ISO'.replace('Z', '+00:00')).timestamp()))")
CURRENT_EPOCH=$(date +%s)
UPTIME_SECONDS=$((CURRENT_EPOCH - START_EPOCH))

echo "Current uptime: $((UPTIME_SECONDS / 86400)) days, $(((UPTIME_SECONDS % 86400) / 3600)) hours."

if [ "$UPTIME_SECONDS" -ge "$MAX_AGE_SECONDS" ]; then
    echo "Warning: VM uptime has exceeded 6.5 days. Initiating cycle to reset Flex-start timer..."
    
    ./stop
    echo "VM successfully stopped. Waiting 30 seconds for state to settle..."
    sleep 30
    
    ./start
    echo "VM successfully started. The 7-day limit has been reset."
else
    echo "VM is well within the 7-day limit. No action required."
fi
```

## 5. Usage Examples

### Deploying with Flex-start Enabled

Deploy a new GCP Isaac Workstation utilizing GCP Flex-start (Dynamic Workload Scheduler) to improve GPU availability:

```bash
# Non-interactive CLI deployment
./deploy-gcp \
  --deployment-name gcp-flex-ws \
  --zone us-central1-a \
  --project my-gcp-project \
  --instance-type g2-standard-8 \
  --isaac-workstation-gpu-count 1 \
  --flex-start \
  --existing replace
```

### Checking VM Uptime & Flex-start Status

Inspect the running instance to view elapsed uptime, days remaining before the 7-day max duration, and whether cycling is needed:

```bash
# Check uptime without stopping or modifying state
./cycle-vm gcp-flex-ws --check-only
```

### Automated Cycling (Resetting 7-Day Limit)

Run the cycling utility periodically (or via a cron / scheduled job) to automatically stop and restart the instance if uptime exceeds 6.5 days (156 hours):

```bash
# Cycles only if uptime >= 6.5 days (156h threshold)
./cycle-vm gcp-flex-ws

# Force an immediate cycle and quick-start
./cycle-vm gcp-flex-ws --force --quick

# Custom threshold (e.g. 5 days / 120 hours)
./cycle-vm gcp-flex-ws --max-age-hours 120
```

### Standard Pause & Resume

Pause compute billing when idle and resume when needed:

```bash
# Pause compute billing (preserves disk and static IP)
./stop gcp-flex-ws

# Resume compute and re-run autorun / apps
./start gcp-flex-ws --quick
```

