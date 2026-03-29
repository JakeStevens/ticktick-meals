import database
import json
from collections import Counter

def perform_audit():
    # Fetch a larger sample for analysis
    logs = database.get_audit_logs(limit=1000)
    
    if not logs:
        print("No audit logs found.")
        return

    # 1. Outcome Distribution
    outcomes = Counter(l['outcome'] for l in logs)
    
    # 2. Correction Analysis (LLM Normalization)
    corrections = [l for l in logs if l['correction_made']]
    common_corrections = Counter((l['ingredient_raw'], l['ingredient_final']) for l in corrections).most_common(10)
    
    # 3. Rejection Analysis
    rejections = [l for l in logs if l['outcome'].startswith('rejected')]
    common_rejections = Counter(l['ingredient_raw'] for l in rejections).most_common(10)
    
    # 4. Source Analysis
    sources = Counter(l['source_recipe'] for l in logs).most_common(5)

    # 5. Summary Report
    print("### Audit Log Trend Analysis")
    print(f"\n**Total Samples Analyzed:** {len(logs)}")
    
    print("\n#### Outcome Distribution")
    for outcome, count in outcomes.items():
        percent = (count / len(logs)) * 100
        print(f"- {outcome}: {count} ({percent:.1f}%)")

    print("\n#### Top 10 LLM Corrections (Raw -> Final)")
    for (raw, final), count in common_corrections:
        print(f"- '{raw}' -> '{final}' (count: {count})")

    print("\n#### Top 10 Rejections")
    for raw, count in common_rejections:
        print(f"- '{raw}' (count: {count})")

    print("\n#### Top 5 Recipe Sources")
    for source, count in sources:
        print(f"- {source}: {count} ingredients")

if __name__ == "__main__":
    perform_audit()
