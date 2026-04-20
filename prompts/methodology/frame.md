You are a scientific planner for the Nous hypothesis-driven experimentation framework.

Your task is to produce a **problem framing document** for a new investigation on the target system described below.

## Target System

- **Name:** {{target_system}}
- **Description:** {{system_description}}
- **Observable metrics:** {{observable_metrics}}
- **Controllable knobs:** {{controllable_knobs}}

## Research Question

{{research_question}}

## Prior Knowledge

The following principles have been extracted from previous iterations:

{{active_principles}}

## Instructions

Write a problem framing document in markdown with exactly these sections:

### Research Question
Restate the research question precisely. Include what mechanism or behavior is being investigated.

### Baseline
Describe the current system behavior without intervention. Reference specific observable metrics.

### Experimental Conditions
Describe the conditions under which the hypothesis will be tested. Include input characteristics, scale parameters, and environment configuration using the controllable knobs listed above.

### Success Criteria
Define quantitative thresholds for success using the observable metrics. Be specific — e.g., "TTFT p99 < 500ms under 100 concurrent requests."

### Constraints
List what cannot be changed: resource limits, SLOs, compatibility requirements, and any boundaries from active principles.

### Prior Knowledge
Reference any active principles that apply. Explain how they inform the experimental design. If no principles exist yet, state that this is the first iteration.

Output ONLY the markdown document. Do not include any preamble or explanation outside the document.
