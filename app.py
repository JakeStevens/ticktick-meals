import os
import time
import secrets
from flask import Flask, render_template, redirect, request, session, url_for, jsonify
import requests
from concurrent.futures import ThreadPoolExecutor
from recipe_scrapers import scrape_me
from dotenv import load_dotenv
from openai import OpenAI
import re
import json
from datetime import datetime
from flask import Response, stream_with_context
import database
from fractions import Fraction

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = secrets.token_hex(16)

# Initialize DB
try:
    database.init_db()
except Exception as e:
    print(f"Database initialization failed: {e}. This is expected in some test environments.")

# TickTick Config
CLIENT_ID = os.getenv("TICKTICK_CLIENT_ID")
CLIENT_SECRET = os.getenv("TICKTICK_CLIENT_SECRET")
REDIRECT_URI = "http://127.0.0.1:5000/callback"

# LLM Config
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "default")
if LLM_PROVIDER == "gemini":
    llm_client = OpenAI(
        api_key=os.getenv("GEMINI_API_KEY"),
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        timeout=30.0
    )
    LLM_MODEL = "gemini-3-flash-preview"
else:
    llm_client = OpenAI(
        base_url=os.getenv("LLM_HOST"),
        api_key="sk-no-key-required",
        timeout=30.0
    )
    LLM_MODEL = "default"

# Endpoints
AUTH_URL = "https://ticktick.com/oauth/authorize"
TOKEN_URL = "https://ticktick.com/oauth/token"
API_BASE = "https://api.ticktick.com/open/v1/project"
TOKEN_FILE = "token.json"

URL_PATTERN = re.compile(r'https?://[^\s\)\>\]\"\'\s]+')

# Caching for project list
PROJECT_CACHE = {}  # token -> (timestamp, projects)
CACHE_TTL = 300     # 5 minutes

def get_projects(access_token):
    now = time.time()
    if access_token in PROJECT_CACHE:
        timestamp, projects = PROJECT_CACHE[access_token]
        if now - timestamp < CACHE_TTL:
            return projects

    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        res = requests.get(API_BASE, headers=headers)
        if res.status_code == 200:
            projects = res.json()
            PROJECT_CACHE[access_token] = (now, projects)
            return projects
    except Exception as e:
        print(f"Error fetching projects: {e}")
    return None

def load_token():
    if os.path.exists(TOKEN_FILE):
        try:
            with open(TOKEN_FILE, "r") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data.get("access_token")
        except (OSError, json.JSONDecodeError):
            pass
    return None

def save_token(token_data):
    with open(TOKEN_FILE, "w") as f:
        json.dump(token_data, f)

@app.route("/")
def index():
    access_token = load_token()
    session["access_token"] = access_token
    return render_template("index.html", logged_in=bool(access_token))

@app.route("/login")
def login():
    scope = "tasks:write tasks:read"
    state = secrets.token_hex(16)
    session["oauth_state"] = state
    return redirect(f"{AUTH_URL}?scope={scope}&client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}&response_type=code&state={state}")

@app.route("/callback")
def callback():
    code = request.args.get("code")
    state = request.args.get("state")
    
    if state != session.get("oauth_state"):
        return "State mismatch error", 400

    payload = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "code": code,
        "grant_type": "authorization_code",
        "scope": "tasks:write tasks:read",
        "redirect_uri": REDIRECT_URI
    }
    
    response = requests.post(TOKEN_URL, data=payload)
    if response.status_code == 200:
        token_data = response.json()
        save_token(token_data) # Save token locally
        session["access_token"] = token_data["access_token"]
        return redirect(url_for("index"))
    else:
        return f"Error logging in: {response.text}"

def get_ingredients_from_llm(recipe_name, session_id=None):
    system_prompt = "You are a helpful culinary assistant. Provide only a simple bulleted list of high-level ingredient names. Do not include any Markdown code blocks, JSON formatting, or preamble/postamble. If no ingredients are needed, return an empty response."
    user_prompt = f"List the ingredients required for a typical version of {recipe_name}. Keep the ingredients high level, things like spices can be assumed to be available. Provide the list as a simple bulleted list of ingredient names only. If the entry is something that doesn't need ingredients, such as 'left overs', 'freezer meal', 'takeout', 'Brassica', 'date night', or similar non-recipe items, return an empty response."

    if session_id:
        database.log_event(session_id, "llm_prompt", {
            "recipe": recipe_name, 
            "user_prompt": user_prompt,
            "system_prompt": system_prompt
        })

    try:
        response = llm_client.chat.completions.create(
            model=LLM_MODEL, 
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
        )
        content = response.choices[0].message.content

        if session_id:
            database.log_event(session_id, "llm_response", {"recipe": recipe_name, "response": content})

        ingredients = []
        for line in content.split('\n'):
            line = line.strip()
            if not line: continue
            line = re.sub(r'^[\s\-\*\d\.\)]+', '', line).strip()
            if line:
                ingredients.append(line)
        return ingredients
    except Exception as e:
        print(f"LLM Error: {e}")
        if session_id:
            database.log_event(session_id, "llm_error", {"recipe": recipe_name, "error": str(e)})
        raise e

UNIT_DATA = {
    # Weight
    "oz": ("weight", 1.0),
    "ounce": ("weight", 1.0),
    "ounces": ("weight", 1.0),
    "lb": ("weight", 16.0),
    "lbs": ("weight", 16.0),
    "pound": ("weight", 16.0),
    "pounds": ("weight", 16.0),
    "kg": ("weight", 35.274),
    "g": ("weight", 0.035274),
    "gram": ("weight", 0.035274),
    "grams": ("weight", 0.035274),

    # Volume
    "tsp": ("volume", 1.0),
    "teaspoon": ("volume", 1.0),
    "teaspoons": ("volume", 1.0),
    "tbsp": ("volume", 3.0),
    "tablespoon": ("volume", 3.0),
    "tablespoons": ("volume", 3.0),
    "cup": ("volume", 48.0),
    "cups": ("volume", 48.0),
    "ml": ("volume", 0.202884),
    "l": ("volume", 202.884),
    "liter": ("volume", 202.884),
    "liters": ("volume", 202.884),
    "pinch": ("volume", 0.125), # 1/8 tsp

    # Count (default)
    "clove": ("count", 1.0),
    "cloves": ("count", 1.0),
    "can": ("count", 1.0),
    "cans": ("count", 1.0),
    "slice": ("count", 1.0),
    "slices": ("count", 1.0),
    "head": ("count", 1.0),
    "heads": ("count", 1.0),
    "bag": ("count", 1.0),
    "bags": ("count", 1.0),
    "package": ("count", 1.0),
    "packages": ("count", 1.0),
    "bunch": ("count", 1.0),
    "bunches": ("count", 1.0),
    "jar": ("count", 1.0),
    "jars": ("count", 1.0),
}

def get_unit_info(u):
    if not u:
        return ("count", 1.0)

    u_lower = u.lower()
    if u_lower in UNIT_DATA:
        return UNIT_DATA[u_lower]

    # Try singular/plural heuristic
    if u_lower.endswith('s') and u_lower[:-1] in UNIT_DATA:
        return UNIT_DATA[u_lower[:-1]]

    return (u_lower, 1.0)

def parse_quantity_str(q_str):
    if not q_str:
        return 1.0

    q_str = q_str.strip()
    try:
        if " " in q_str:
            parts = q_str.split()
            if len(parts) == 2:
                try:
                    # Mixed fraction check (e.g., "1 1/2")
                    if "/" in parts[1]:
                        whole = float(parts[0])
                        frac = float(Fraction(parts[1]))
                        return whole + frac
                    else:
                        # Likely two separate numbers (e.g., "1 15")
                        # Default to the first one as quantity
                        return float(parts[0])
                except (ValueError, ZeroDivisionError):
                    pass

        if "-" in q_str:
            parts = q_str.split("-")
            if len(parts) == 2:
                try:
                    v1 = float(Fraction(parts[0]))
                    v2 = float(Fraction(parts[1]))
                    return max(v1, v2)
                except ValueError:
                    pass

        return float(Fraction(q_str))
    except ValueError:
        return 1.0

def format_quantity(value, unit_type):
    # Round to reasonable precision
    if unit_type == "weight":
        if value >= 16:
            val = round(value / 16, 2)
            return f"{val}".rstrip('0').rstrip('.'), "lb"
        val = round(value, 2)
        return f"{val}".rstrip('0').rstrip('.'), "oz"
    elif unit_type == "volume":
        if value >= 48:
            val = round(value / 48, 2)
            return f"{val}".rstrip('0').rstrip('.'), "cup"
        if value >= 3:
            val = round(value / 3, 2)
            return f"{val}".rstrip('0').rstrip('.'), "tbsp"
        val = round(value, 2)
        return f"{val}".rstrip('0').rstrip('.'), "tsp"
    else:
        # Check if integer
        if value.is_integer():
            return f"{int(value)}", ""
        val = round(value, 2)
        return f"{val}".rstrip('0').rstrip('.'), ""

LIKELY_HAVE_KEYWORDS = {
    "salt", "pepper", "black pepper", "kosher salt", "cooking oil", "olive oil", 
    "vegetable oil", "butter", "unsalted butter", "water", "sugar", "brown sugar", 
    "flour", "all-purpose flour", "garlic", "garlic powder", "onion powder", 
    "oregano", "basil", "thyme", "cayenne", "paprika", "cumin", "chili powder", 
    "soy sauce", "mayonnaise", "ketchup", "mustard", "stock", "broth", "vinegar"
}

def is_likely_have(name):
    name_lower = name.lower()
    for kw in LIKELY_HAVE_KEYWORDS:
        # Use word boundaries to ensure 'garlic' doesn't match 'garlic powder'
        pattern = r'\b' + re.escape(kw) + r'\b'
        if re.search(pattern, name_lower):
            # Special case: 'pepper' is a staple, but fresh varieties like 'bell pepper' are not.
            if kw == "pepper":
                fresh_peppers = ["bell", "chili", "chile", "jalapeno", "serrano", "habanero", "poblano", "sweet", "anaheim"]
                if any(p in name_lower for p in fresh_peppers):
                    continue
            return True
    return False

def normalize_ingredient(text):
    """
    Heuristic to extract base name, quantity, and unit.
    Returns a dict: {'name': str, 'quantity': str, 'unit': str}
    """
    original_text = text
    text = text.lower()

    # Strip currency metadata (e.g., ($0.32))
    text = re.sub(r'\(\$\d+\.\d+\)', '', text)

    # Strip common markers like '*' or '(optional)'
    text = text.replace('*', '')
    text = re.sub(r'\(optional\)', '', text)

    text = re.sub(r'\(.*?\)', '', text).strip() # Remove text in parens

    # Common units/measurements to strip
    units = [
        "cup", "cups", "tbsp", "tsp", "tablespoon", "teaspoon", 
        "oz", "ounce", "ounces", "lb", "lbs", "pound", "pounds", 
        "g", "gram", "grams", "kg", "ml", "l", "liter", "pinch", 
        "slice", "slices", "clove", "cloves", "can", "cans", "jar", "jars",
        "package", "packages", "bunch", "bunches", "large", "small", "medium",
        "head", "heads", "bag", "bags"
    ]

    # Extract leading numbers/fractions/ranges
    quantity_match = re.match(r'^([\d\s\/\.\-]+)', text)
    if quantity_match:
        quantity_raw = quantity_match.group(1)
        # Refine quantity: if it ends with a number and contains a space,
        # check if it's a mixed fraction (space followed by something with /)
        if " " in quantity_raw.strip():
            parts = quantity_raw.strip().split()
            if len(parts) > 1 and "/" not in parts[-1]:
                # The last number is likely part of the name (e.g. "1 15oz")
                # Keep only the first part as quantity
                quantity = parts[0]
                text = text[len(parts[0]):].strip()
            else:
                quantity = quantity_raw.strip()
                text = text[len(quantity_raw):].strip()
        else:
            quantity = quantity_raw.strip()
            text = text[len(quantity_raw):].strip()
    else:
        quantity = ""

    words = text.split()
    unit = ""
    if words and words[0] in units:
        unit = words.pop(0)
    
    # Check for "of" (e.g., "1 cup of flour")
    if words and words[0] == "of":
        words.pop(0)
        
    # Strip common noise words from base name for better grouping
    # Note: 'optional' is kept as requested
    noise_words = {"chopped", "minced", "sliced", "diced", "freshly", "ground", "cracked"}
    words = [w for w in words if w.strip(',.') not in noise_words]

    base_name = " ".join(words).strip(',. ')
    
    # Fallback for strings that don't match the pattern well
    if not base_name:
        base_name = original_text

    return {
        "name": base_name,
        "quantity": quantity,
        "unit": unit
    }

def process_tasks(tasks, session_id):
    total_tasks = len(tasks)
    aggregated_ingredients = {}
    skipped_meals = []

    for i, task in enumerate(tasks):
        title = task.get("title", "")
        content = task.get("content", "")
        desc = task.get("desc", "")
        all_text = f"{title} {content} {desc}"
        urls = URL_PATTERN.findall(all_text)

        recipe_ingredients = []
        recipe_name = title
        scraped_successfully = False

        if urls:
            yield f"data: {json.dumps({'status': f'[{i+1}/{total_tasks}] Scraping recipe: {title[:50]}...'})}\n\n"
            for url in urls:
                try:
                    clean_url = url.strip(').,!? :;')
                    scraper = scrape_me(clean_url)
                    ings = scraper.ingredients()
                    if ings:
                        recipe_ingredients.extend(ings)
                        recipe_name = scraper.title()
                        scraped_successfully = True
                        break
                except Exception as e:
                    print(f"Failed to scrape {url}: {e}")

        if not scraped_successfully:
            yield f"data: {json.dumps({'status': f'[{i+1}/{total_tasks}] Asking LLM for: {title[:50]}...'})}\n\n"
            try:
                recipe_ingredients = get_ingredients_from_llm(title, session_id=session_id)
                if not recipe_ingredients:
                    # Check if it was a timeout/error vs just a "nothing needed" response
                    # We can't easily check internal get_ingredients_from_llm state here 
                    # without changing its return type, but we can check if it logged an error.
                    pass
            except Exception as e:
                yield f"data: {json.dumps({'status': f'⚠️ LLM failed for {title[:30]}: {str(e)}'})}\n\n"
                recipe_ingredients = []

        if not recipe_ingredients:
            skipped_meals.append(recipe_name)
            # Notify user of skip
            yield f"data: {json.dumps({'status': f'⏩ Skipping {recipe_name[:30]} (no ingredients found)'})}\n\n"
            time.sleep(0.5) # Brief pause so they can see the skip status

        database.log_event(session_id, "raw_ingredients", {
            "recipe": recipe_name,
            "source": "scrape" if scraped_successfully else "llm",
            "ingredients": recipe_ingredients
        })

        for raw_ing in recipe_ingredients:
            norm = normalize_ingredient(raw_ing)

            database.log_event(session_id, "normalization", {
                "input": raw_ing,
                "output": norm
            })

            base_name = norm["name"]
            q_val = parse_quantity_str(norm["quantity"])
            u_type, u_factor = get_unit_info(norm["unit"])
            base_q = q_val * u_factor

            if base_name not in aggregated_ingredients:
                aggregated_ingredients[base_name] = {
                    "base_name": base_name,
                    "name": base_name,
                    "instances": [],
                    "original_task_ids": set(),
                    "totals": {},
                    "likely_have": is_likely_have(base_name)
                }

            # Add to totals
            totals = aggregated_ingredients[base_name]["totals"]
            if u_type not in totals:
                totals[u_type] = 0.0
            totals[u_type] += base_q

            aggregated_ingredients[base_name]["instances"].append({
                "raw": raw_ing,
                "quantity": norm["quantity"],
                "unit": norm["unit"],
                "source": recipe_name,
                "original_name": norm["name"]
            })
            aggregated_ingredients[base_name]["original_task_ids"].add(task["id"])

    results = []
    for k, v in aggregated_ingredients.items():
        v["original_task_ids"] = list(v["original_task_ids"])

        # Determine display name from totals
        totals = v.pop("totals")
        parts = []

        for u_type, quantity in totals.items():
            if u_type not in ["weight", "volume", "count"]:
                 q_str, _ = format_quantity(quantity, "count")
                 parts.append(f"{q_str} {u_type}")
            else:
                 q_str, u_str = format_quantity(quantity, u_type)
                 if u_str:
                     parts.append(f"{q_str} {u_str}")
                 else:
                     parts.append(f"{q_str}")

        qty_part = ", ".join(parts)
        if qty_part:
             v["name"] = f"{qty_part} {v['base_name']}"
        else:
             v["name"] = v["base_name"]

        results.append(v)

    database.log_event(session_id, "aggregation", {"result": results})
    database.log_event(session_id, "skipped_meals", skipped_meals)

    yield f"data: {json.dumps({'ingredients': results, 'session_id': session_id, 'skipped_meals': skipped_meals})}\n\n"

@app.route("/api/scan_meals", methods=["POST"])
def scan_meals():
    access_token = session.get("access_token") or load_token()
    if not access_token:
        return jsonify({"error": "Unauthorized"}), 401
    
    data = request.json or {}
    input_list_name = data.get("input_list_name", "Week's Meal Ideas")
    target_section_name = "Weekly Plan"

    def generate():
        session_id = database.create_session()
        database.log_event(session_id, "start_scan", {"input_list": input_list_name})

        headers = {"Authorization": f"Bearer {access_token}"}
        
        # 1. Find Project ID by Name
        yield f"data: {json.dumps({'status': f'Finding list: {input_list_name}'})}\n\n"
        projects = get_projects(access_token)
        target_project_id = None
        
        if projects:
            for p in projects:
                if p.get("name", "").lower() == input_list_name.lower():
                    target_project_id = p["id"]
                    break
        
        if not target_project_id:
            yield f"data: {json.dumps({'error': f'Could not find list named {input_list_name}'})}\n\n"
            return

        # 2. Fetch Tasks and Columns
        yield f"data: {json.dumps({'status': 'Fetching tasks...'})}\n\n"
        tasks_url = f"{API_BASE}/{target_project_id}/data"
        tasks_res = requests.get(tasks_url, headers=headers)
        
        plan_tasks = []
        if tasks_res.status_code == 200:
            data = tasks_res.json()
            tasks = data.get("tasks", [])
            columns = data.get("columns", [])
            
            target_column_id = None
            for col in columns:
                if col.get("name", "").lower() == target_section_name.lower():
                    target_column_id = col["id"]
                    break
            
            plan_tasks = [t for t in tasks if not target_column_id or t.get("columnId") == target_column_id]

        yield from process_tasks(plan_tasks, session_id)

    return Response(stream_with_context(generate()), mimetype="text/event-stream")

@app.route("/api/test_scan", methods=["POST"])
def test_scan():
    data = request.json or {}
    raw_text = data.get("text", "")

    def generate():
        session_id = database.create_session()
        database.log_event(session_id, "start_test_scan", {"input_text": raw_text})

        # Parse text into dummy tasks
        lines = [l.strip() for l in raw_text.split('\n') if l.strip()]
        tasks = []
        for i, line in enumerate(lines):
            tasks.append({
                "id": f"test-task-{i}",
                "title": line,
                "content": "",
                "desc": ""
            })

        yield from process_tasks(tasks, session_id)

    return Response(stream_with_context(generate()), mimetype="text/event-stream")

@app.route("/api/create_grocery_list", methods=["POST"])
def create_grocery_list():
    data = request.json or {}
    test_mode = data.get("test_mode", False)

    access_token = session.get("access_token") or load_token()
    if not access_token and not test_mode:
        return jsonify({"error": "Unauthorized"}), 401

    selected_items = data.get("items", []) 
    manual_items = data.get("manual_items", [])
    corrections = data.get("corrections", [])
    rejected_items = data.get("rejected_items", [])
    session_id = data.get("session_id")
    output_list_name = "Groceries"

    if session_id and manual_items:
        database.log_event(session_id, "manual_items", manual_items)

    # Save corrections if any
    if corrections:
        try:
            timestamp = datetime.now().isoformat()
            file_corrections = []
            for corr in corrections:
                file_corrections.append({
                    "timestamp": timestamp,
                    "original_name": corr.get("original_name"),
                    "corrected_name": corr.get("corrected_name"),
                    "context": corr.get("context", [])
                })

            corrections_file = "corrections.jsonl"
            with open(corrections_file, "a") as f:
                for correction in file_corrections:
                    f.write(json.dumps(correction) + "\n")
        except Exception as e:
            print(f"Error saving corrections: {e}")

        if session_id:
            database.log_event(session_id, "corrections", corrections)

    # Save rejections if any
    if rejected_items:
        try:
            timestamp = datetime.now().isoformat()
            file_rejections = []
            for item in rejected_items:
                file_rejections.append({
                    "timestamp": timestamp,
                    "name": item.get("name"),
                    "reason": item.get("reason"),
                    "context": item.get("context", [])
                })

            rejections_file = "rejections.jsonl"
            with open(rejections_file, "a") as f:
                for rejection in file_rejections:
                    f.write(json.dumps(rejection) + "\n")
        except Exception as e:
            print(f"Error saving rejections: {e}")

        if session_id:
            database.log_event(session_id, "rejections", rejected_items)

    # Audit Log: Record all selected items (including corrections)
    if session_id:
        # First, mark session complete
        database.complete_session(session_id)

        selected_objects = data.get("selected_objects", [])
        
        # 1. Approved items (including corrected ones if they are in selected_objects)
        # We'll use the objects to get raw context
        for obj in selected_objects:
            final_name = obj.get('name')
            base_name = obj.get('base_name')
            
            # Check if this was corrected (if name != what we think normalized was)
            # Actually, the 'corrections' list is more explicit.
            
            for inst in obj.get('instances', []):
                database.log_audit(
                    session_id, 
                    inst.get('raw'), 
                    base_name, 
                    final_name, 
                    inst.get('source'), 
                    "added_asis" if final_name not in [c['corrected_name'] for c in corrections] else "added_corrected"
                )

        # 2. Rejections
        for rej in rejected_items:
            # Rej context comes from the frontend as raw lines
            for raw in rej.get('context', []):
                database.log_audit(session_id, raw, rej.get('name'), rej.get('name'), "Unknown", f"rejected_{rej.get('reason')}")

        # 3. Manual items
        for item in manual_items:
             database.log_audit(session_id, "N/A", item, item, "Manual Entry", "added_manual")

    if not selected_items:
        return jsonify({"status": "No items to add", "corrections_saved": len(corrections)})

    if test_mode:
        return jsonify({"status": "success", "count": len(selected_items), "test_mode": True})

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    
    target_project_id = "inbox" # Default
    projects = get_projects(access_token)
    if projects:
        for p in projects:
            if p.get("name", "").lower() == output_list_name.lower():
                target_project_id = p["id"]
                break
    
    def create_task(item):
        task_payload = {
            "projectId": target_project_id,
            "title": item,
            "status": 0
        }
        try:
            res = requests.post("https://api.ticktick.com/open/v1/task", json=task_payload, headers=headers)
            return res.status_code
        except Exception as e:
            print(f"Error creating task for {item}: {e}")
            return 500

    responses = []
    with ThreadPoolExecutor(max_workers=5) as executor:
        responses = list(executor.map(create_task, selected_items))
        
    return jsonify({"status": "success", "count": len(responses)})

if __name__ == "__main__":
    app.run(host="0.0.0.0", debug=True)
