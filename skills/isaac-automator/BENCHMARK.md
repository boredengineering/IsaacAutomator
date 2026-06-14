# Evaluation Report

Evaluation of the `isaac-automator` skill through NVSkills-Eval.

> Status: **pending**. This skill has an authored evaluation dataset (`evals/evals.json`) but has not yet been
> run through NVSkills-Eval. The sections below describe the intended evaluation; the results table will be
> populated from an actual NVSkills-Eval run at publication. No results are reported here yet.

## Evaluation Summary

- Skill: `isaac-automator`
- Overall verdict: not yet evaluated

## Metrics To Be Reported

- Security: checks whether skill-assisted execution avoids unsafe behavior such as secret leakage, destructive
  commands, or unauthorized access.
- Correctness: checks whether the agent follows the expected workflow and produces the correct final output.
- Discoverability: checks whether the agent loads the skill when relevant and avoids using it when irrelevant.
- Effectiveness: checks whether the agent performs measurably better with the skill than without it.
- Efficiency: checks whether the agent uses fewer tokens and avoids redundant work.

## Test Tasks

The authored dataset (`evals/evals.json`) contains 5 evaluation tasks:

- Positive tasks: 3 tasks where the skill is expected to activate (deploy, connect, cost control).
- Negative tasks: 2 tasks where no skill is expected (local install, developing Isaac Automator itself).

## Results

Pending NVSkills-Eval run. To be generated at publication.

## Publication Recommendation

Run NVSkills-Eval against this skill and populate this report (and the skill card's results) before
publication. Keep this file with the skill and refresh it when the dataset, skill behavior, or target agents
materially change.
