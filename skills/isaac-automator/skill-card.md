## Description: <br>
Deploy and operate a cloud Isaac Workstation with Isaac Automator: provision a GPU VM running Isaac Sim, Isaac Lab, and/or Isaac Lab Arena on AWS, GCP, Azure, or Alibaba Cloud, connect to it, move data in and out, control cost with stop/start, repair, import existing deployments, and destroy. <br>

This skill is ready for commercial/non-commercial use. <br>

## Owner
NVIDIA <br>

### License/Terms of Use: <br>
Apache 2.0 <br>
## Use Case: <br>
Developers and engineers use this skill to stand up a ready-to-use remote Isaac workstation in the cloud, connect to it, run workloads, control cost with stop/start, and tear it down, all via the Isaac Automator CLI. <br>

### Deployment Geography for Use: <br>
Global <br>

## Known Risks and Mitigations: <br>
Risk: Isaac Automator provisions real, billable cloud infrastructure; misuse could incur cost or leave resources running. <br>
Mitigation: The skill instructs the agent to use the cheapest viable instance, pass options non-interactively, and always stop or destroy deployments when finished. <br>
Risk: Review before execution as proposals could introduce incorrect or misleading guidance into skills. <br>
Mitigation: Review and scan skill before deployment. <br>

## Reference(s): <br>
- [Isaac Automator Repository](https://github.com/isaac-sim/IsaacAutomator) <br>
- [Isaac Sim Documentation](https://docs.isaacsim.omniverse.nvidia.com/) <br>
- [Isaac Lab Documentation](https://isaac-sim.github.io/IsaacLab/) <br>

## Skill Output: <br>
**Output Type(s):** [Shell commands, Configuration instructions, Analysis] <br>
**Output Format:** [Markdown with inline bash code blocks] <br>
**Output Parameters:** [1D] <br>
**Other Properties Related to Output:** [None] <br>

## Evaluation Agents Used: <br>
Pending NVSkills-Eval run. <br>

## Evaluation Tasks: <br>
Authored dataset of 5 evaluation tasks (3 positive skill-activation, 2 negative) in `evals/evals.json`. Not yet executed through NVSkills-Eval. <br>

## Evaluation Metrics Used: <br>
To be reported from an NVSkills-Eval run (Security, Correctness, Discoverability, Effectiveness, Efficiency). <br>

## Evaluation Results: <br>
Pending NVSkills-Eval run. Results table to be generated at publication. <br>

## Testing Completed: <br>
**[ ] Agent Red-Teaming** <br>
**[ ] Network Security** <br>
**[ ] Product Security** <br>

## Skill Version(s): <br>
0.1.0 <br>

## Ethical Considerations: <br>
NVIDIA believes Trustworthy AI is a shared responsibility and we have established policies and practices to enable development for a wide array of AI applications. When downloaded or used in accordance with our terms of service, developers should work with their internal team to ensure this skill meets requirements for the relevant industry and use case and addresses unforeseen product misuse. <br>

(For Release on NVIDIA Platforms Only) <br>
Please report quality, risk, security vulnerabilities or NVIDIA AI Concerns [here](https://app.intigriti.com/programs/nvidia/nvidiavdp/detail). <br>
