# Analysis & Actionable Updates Guide

This guide outlines how to analyze the Meal Planner's audit and system logs to identify patterns and derive actionable improvements for the extraction and normalization pipeline.

## 1. Locating Data
- **Active Database:** Located at `/app/data/meal_planner.db` inside the `jake_ticktick_1` container (mapped from the `ticktick-data` Podman volume).
- **Bad Info Logs:** Stored at `/app/data/bad_info.jsonl`. This is the primary source for identifying LLM failures and manual user corrections.

## 2. Analysis Tools
Use the following scripts to identify trends:
- `python3 audit_analysis.py`: Summarizes outcome distributions, top rejections, and common LLM corrections.
- `python3 system_analysis.py`: Analyzes event types and provides a deep dive into normalization and extraction patterns.

## 3. Deriving Actionable Updates
When analyzing logs, look for the following "Actionable Signals":

### A. High Frequency of Manual Corrections
Check `bad_info.jsonl` for the `manual_correction` action.
- **Signal:** Users consistently changing a specific unit (e.g., "0.5 cup" -> "1 unit").
- **Action:** Update the Normalization Prompt to prioritize "grocery-friendly" units for that ingredient.

### B. Aggregation Failures
Check the `aggregation` events in the system logs.
- **Signal:** Similar items (e.g., "Parmesan" and "Parmesan cheese") appearing as separate entries.
- **Action:** Refine the Normalization Prompt to use more generic singular nouns for the base names of those categories.

### C. Ingredient Breakdown (Over-Extraction)
Check `llm_response` for "prepped" items that were split into raw components.
- **Signal:** "Chicken Tenders" becoming "Chicken breast, flour, oil."
- **Action:** Add the specific item to the "Prepped Items" list in the `get_ingredients_from_llm` prompt.

### D. Component Redundancy
Look for ingredients that are part of another item.
- **Signal:** "Oil from sun-dried tomatoes" appearing alongside "Sun-dried tomatoes in oil."
- **Action:** Update the "Component Awareness" section of the Normalization Prompt to map subsets to their parent items.

## 4. Validation Workflow
After updating prompts based on the above signals:
1. Run `test_bad_info.py` to ensure core logging functionality remains intact.
2. Run a "Test Scan" with the reproduction input to confirm the fix (e.g., verifying "Chicken Tenders" are no longer broken down).
