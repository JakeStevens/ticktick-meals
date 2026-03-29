import database
import json
from collections import Counter
import re

def analyze_system_logs():
    conn = database.get_connection()
    c = conn.cursor()
    c.execute("SELECT event_type, data FROM logs")
    rows = c.fetchall()
    
    if not rows:
        print("No system logs found.")
        return

    print("### System Log Trend Analysis")
    print(f"\n**Total Events:** {len(rows)}")

    event_counts = Counter(r[0] for r in rows)
    print("\n#### Event Types")
    for event, count in event_counts.items():
        print(f"- {event}: {count}")

    # Analyze Normalizations
    normalizations = [json.loads(r[1]) for r in rows if r[0] == 'normalization']
    if normalizations:
        print("\n#### Normalization Trends")
        raw_to_norm = []
        for n in normalizations:
            # Handle both list and dict formats if they vary
            input_val = n.get('input')
            output_val = n.get('output', {})
            if isinstance(output_val, dict):
                norm_name = output_val.get('name')
                raw_to_norm.append((input_val, norm_name))
        
        common_norms = Counter(raw_to_norm).most_common(10)
        print("Top 10 Normalizations (Raw -> Norm):")
        for (raw, norm), count in common_norms:
            print(f"- '{raw}' -> '{norm}' (count: {count})")

    # Analyze LLM Responses (if available)
    llm_responses = [json.loads(r[1]) for r in rows if r[0] == 'llm_response']
    if llm_responses:
        print("\n#### LLM Ingredient Extractions")
        all_extracted = []
        for resp in llm_responses:
            content = resp.get('content', '')
            # Simple bullet point extraction
            ingredients = [re.sub(r'^[\-\*\s]+', '', line).strip() for line in content.split('\n') if line.strip()]
            all_extracted.extend(ingredients)
        
        common_extracted = Counter(all_extracted).most_common(10)
        print("Top 10 LLM Extracted Ingredients:")
        for ing, count in common_extracted:
            print(f"- {ing} ({count})")

if __name__ == "__main__":
    analyze_system_logs()
