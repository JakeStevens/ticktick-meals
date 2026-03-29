# Analysis & Debugging Guide

This guide describes the tooling and procedures for analyzing the Meal Planner's operational data to improve extraction and normalization.

## 1. Execution Environment
Most analysis must be performed **inside the running container** to access the active database and dependencies.

- **Command:** `sudo podman exec -it jake_ticktick_1 /bin/bash`
- **Working Directory:** `/app`

## 2. Key File Locations (Inside Container)
- **Active Database:** `/app/data/meal_planner.db` (Persistent SQLite DB)
- **Bad Info Log:** `/app/data/bad_info.jsonl` (Append-only record of AI errors and manual corrections)
- **Rejections Log:** `/app/data/rejections.jsonl` (Append-only record of skipped items)

## 3. Analysis Tooling
The following scripts are available in the repository for data-driven debugging:

### `audit_analysis.py`
Provides a high-level summary of user outcomes. Use this to identify:
- Distribution of item outcomes (Added, Have It, Skipped).
- Most common ingredients requiring manual correction.
- Top recipe sources by ingredient volume.

### `system_analysis.py`
Provides a technical breakdown of the pipeline's internals. Use this to identify:
- Event type distribution (normalization, aggregation, raw extraction).
- Common normalization patterns (Raw -> Normalized base name).
- Trends in LLM extraction responses.

## 4. Maintenance Workflow
1. **Identify Patterns:** Use the analysis tools inside the pod to find recurring errors (e.g., failed merges, incorrect units).
2. **Modify Prompts:** Update the `system_prompt` variables in `app.py` for extraction or normalization.
3. **Validate:**
   - Use **Test Mode** in the web UI to reproduce the scenario.
   - Run `python3 test_bad_info.py` to ensure log persistence remains functional.
4. **Deploy:** Restart the container suite to apply prompt changes:
   `sudo podman pod rm -f pod_jake && sudo podman-compose up -d --build`
