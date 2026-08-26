# Bare-Metal Workstation Bootstrap Walkthrough

1. **Probe System & Conflict Matrix**:
   ```bash
   isaac-installer doctor --json
   isaac-installer plan
   ```

2. **Provision Full Physical AI Stack**:
   ```bash
   sudo isaac-installer install --profile full \
     --workspace-dir ~/Documents/GitHub \
     --workspace-owner BoredEngineer
   ```

3. **Verify Submodule Editable Bridge**:
   ```bash
   isaac-installer arena submodules editable-bridge
   isaac-installer test arena
   ```

4. **Launch GR00T Policy Server & Closed-Loop Simulation**:
   ```bash
   isaac-installer gr00t server 5556
   isaac-installer arena play pick_and_place_table --policy gr00t --port 5556
   ```
