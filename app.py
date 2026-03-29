import os
import time
import secrets
import signal
import sys
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
from pint import UnitRegistry

# Initialize Pint unit registry
ureg = UnitRegistry()
# Define a base unit for simple counts
ureg.define('count = [count]')
# Define some common culinary units that might not be in default pint or need aliases
ureg.define('pinch = 0.0625 * teaspoon')
ureg.define('dash = 0.125 * teaspoon')
ureg.define('clove = 1 * count') # garlic cloves
ureg.define('can = 1 * count')
ureg.define('jar = 1 * count')
ureg.define('package = 1 * count')
ureg.define('pkg = 1 * package')
ureg.define('bunch = 1 * count')
ureg.define('head = 1 * count')
ureg.define('bag = 1 * count')
ureg.define('slice = 1 * count')
ureg.define('piece = 1 * count')
ureg.define('box = 1 * count')
ureg.define('container = 1 * count')
ureg.define('bottle = 1 * count')
ureg.define('stalk = 1 * count')
ureg.define('sprig = 1 * count')

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
        timeout=60.0
    )
    LLM_MODEL = "gemini-3-flash-preview"
else:
    llm_client = OpenAI(
        base_url=os.getenv("LLM_HOST"),
        api_key="sk-no-key-required",
        timeout=60.0
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

@app.route("/audit")
def audit():
    logs = database.get_audit_logs(limit=500)
    return render_template("audit.html", logs=logs)

def get_ingredients_from_llm(recipe_name, session_id=None, ignore_recipe=None):
    system_prompt = "You are a helpful culinary assistant. Provide only a simple bulleted list of high-level ingredient names. Do not include any Markdown code blocks, JSON formatting, or preamble/postamble. If no ingredients are needed, return an empty response."
    user_prompt = (
        f"List the ingredients required for a typical version of '{recipe_name}'. \n"
        "GUIDELINES:\n"
        "- Keep ingredients high level (spices can be assumed).\n"
        "- If the input contains multiple distinct dishes or items (e.g., 'Chicken tenders, fries, salad'), treat each one as a 'prepped' item and return them as the ingredients themselves.\n"
        "- IMPORTANT: If an item is commonly sold pre-made or is a 'prepped' dish (e.g., 'Chicken Tenders', 'Salad Kit', 'Frozen Pizza', 'Risotto', 'Mac n Cheese'), **DO NOT break it down**. Return that item name as the sole ingredient.\n"
        "- If the entry is a non-recipe item (e.g., 'left overs', 'takeout', 'date night'), return an empty response."
    )

    if ignore_recipe:
        user_prompt += f"\n- Ignore the ingredients for {ignore_recipe} since its ingredients are extracted separately."

    if session_id:
        database.log_event(session_id, "llm_prompt", {
            "recipe": recipe_name, 
            "user_prompt": user_prompt,
            "system_prompt": system_prompt
        })

    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = llm_client.chat.completions.create(
                model=LLM_MODEL, 
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ]
            )
            content = response.choices[0].message.content
            if content is None:
                content = ""

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
            if "503" in str(e) and attempt < max_retries - 1:
                time.sleep(2 ** attempt) # Exponential backoff
                continue
            print(f"LLM Error: {e}")
            if session_id:
                database.log_event(session_id, "llm_error", {"recipe": recipe_name, "error": str(e)})
            raise e

def normalize_ingredients_batch(recipe_ingredients, session_id=None):
    if not recipe_ingredients:
        return []
    
    ingredients = [i['raw'] for i in recipe_ingredients]
    
    system_prompt = (
        "You are a culinary data specialist. Your task is to normalize raw ingredient strings into structured JSON. \n"
        "Return a JSON object with an 'ingredients' key containing an array of objects. \n"
        "Each object must have 'name', 'quantity', 'unit', and 'original_index'. \n"
        "GUIDELINES:\n"
        "- 'name': Use the most generic singular noun (e.g., 'Parmesan cheese' -> 'parmesan', 'cannellini beans' -> 'white beans', 'garlic cloves' -> 'garlic').\n"
        "  CRITICAL (Component Awareness): If an item is a component of another (e.g., 'oil from sun-dried tomatoes'), normalize it to the parent item (e.g., 'sun-dried tomatoes in oil') to ensure they aggregate into a single purchase.\n"
        "  CRITICAL (Compound Items): If an input has multiple items (e.g., 'Cilantro and avocado'), split them into separate objects with the same 'original_index'.\n"
        "- 'quantity': A numeric string (e.g., '1', '0.5'). Ignore leading redundant numbers (e.g., '1 15oz can' -> quantity '15').\n"
        "- 'unit': Standardize to 'cup', 'tbsp', 'oz', 'lb', 'gram', 'clove', 'can', 'pkg', 'piece', 'box', or 'count' (for simple counts).\n"
        "- 'original_index': The integer index (0-based) from the input list.\n"
        "CRITICAL: Strip prices (e.g., '($0.63)') and return ONLY the JSON object."
    )
    
    user_prompt = "Normalize these ingredients:\n" + "\n".join([f"{i}: {ing}" for i, ing in enumerate(ingredients)])

    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = llm_client.chat.completions.create(
                model=LLM_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                response_format={"type": "json_object"}
            )
            data = json.loads(response.choices[0].message.content)
            normalized_list = data.get("ingredients", [])
            
            # Match back to original list using original_index
            results = []
            indexed_norms = {}
            for norm in normalized_list:
                idx = int(norm.get("original_index", -1))
                if idx not in indexed_norms:
                    indexed_norms[idx] = []
                indexed_norms[idx].append({
                    "name": str(norm.get("name", "unknown")),
                    "quantity": str(norm.get("quantity", "1")),
                    "unit": str(norm.get("unit", "count"))
                })

            for i, item in enumerate(recipe_ingredients):
                norms = indexed_norms.get(i)
                if norms:
                    for n in norms:
                        results.append((item, n))
                else:
                    results.append((item, {"name": item['raw'], "quantity": "1", "unit": "count"}))
            return results
        except Exception as e:
            if "503" in str(e) and attempt < max_retries - 1:
                time.sleep(2 ** attempt)
                continue
            print(f"Batch Normalization LLM Error: {e}")
            return [(item, {"name": item['raw'], "quantity": "1", "unit": "count"}) for item in recipe_ingredients]

def normalize_ingredient(text, session_id=None):
    """
    Fallback/Single version - now uses batch version.
    """
    results = normalize_ingredients_batch([{"raw": text, "source": "manual", "type": "manual"}], session_id=session_id)
    return results[0][1]

import math

def format_quantity(quantity_obj):
    """Formats a Pint Quantity object into a readable string and unit."""
    try:
        # If it's a volume, try to simplify to cups/tbsp/tsp
        if quantity_obj.check('[volume]'):
            if quantity_obj >= ureg.cup:
                val = quantity_obj.to(ureg.cup)
                return f"{round(val.magnitude, 2)}".rstrip('0').rstrip('.'), "cup"
            if quantity_obj >= ureg.tablespoon:
                val = quantity_obj.to(ureg.tablespoon)
                return f"{round(val.magnitude, 2)}".rstrip('0').rstrip('.'), "tbsp"
            val = quantity_obj.to(ureg.teaspoon)
            return f"{round(val.magnitude, 2)}".rstrip('0').rstrip('.'), "tsp"
        
        # If it's a weight, try to simplify to lbs/oz
        if quantity_obj.check('[mass]'):
            if quantity_obj >= ureg.pound:
                val = quantity_obj.to(ureg.pound)
                return f"{round(val.magnitude, 2)}".rstrip('0').rstrip('.'), "lb"
            val = quantity_obj.to(ureg.ounce)
            return f"{round(val.magnitude, 2)}".rstrip('0').rstrip('.'), "oz"
            
        # Default fallback
        m = round(quantity_obj.magnitude, 2)
        m_str = f"{m}".rstrip('0').rstrip('.')
        u_str = str(quantity_obj.units)
        if u_str == "count": u_str = ""
        return m_str, u_str
    except:
        return str(round(quantity_obj.magnitude, 2)), str(quantity_obj.units)

PACKAGE_SIZES = [
    {"keywords": ["pasta", "penne", "spaghetti", "linguine", "fusilli", "rotini", "macaroni", "noodles"], "size": 16 * ureg.ounce, "unit": "box"},
    {"keywords": ["tuna"], "size": 5 * ureg.ounce, "unit": "can"},
    {"keywords": ["black beans", "kidney beans", "garbanzo beans", "chickpeas", "cannellini beans"], "size": 15 * ureg.ounce, "unit": "can"},
    {"keywords": ["diced tomatoes", "crushed tomatoes", "tomato sauce", "tomato puree"], "size": 14.5 * ureg.ounce, "unit": "can"},
    {"keywords": ["broth", "stock"], "size": 32 * ureg.ounce, "unit": "carton"},
    {"keywords": ["rice"], "size": 32 * ureg.ounce, "unit": "bag"},
]

def format_ingredient_quantity(name, qty_obj):
    """Formats quantity, rounding up to common package sizes if applicable."""
    if not qty_obj:
        return name
    
    name_lower = name.lower()
    for entry in PACKAGE_SIZES:
        if any(kw in name_lower for kw in entry['keywords']):
            try:
                # Ensure dimensions match (e.g., both mass)
                pkg_size = entry['size']
                if qty_obj.check(pkg_size.dimensionality):
                    total_in_pkg_unit = qty_obj.to(pkg_size.units).magnitude
                    pkg_size_mag = pkg_size.magnitude
                    num_pkgs = math.ceil(total_in_pkg_unit / pkg_size_mag)
                    
                    q_str, u_str = format_quantity(qty_obj)
                    total_desc = f" ({q_str} {u_str})" if u_str else f" ({q_str})"
                    
                    unit_name = entry['unit']
                    if num_pkgs > 1:
                        if unit_name.endswith('x'): unit_name += "es"
                        else: unit_name += "s"
                    
                    return f"{num_pkgs} {unit_name} {name}{total_desc}"
            except Exception as e:
                print(f"Error calculating package size for {name}: {e}")
                break

    q_str, u_str = format_quantity(qty_obj)
    if u_str:
        return f"{q_str} {u_str} {name}"
    return f"{q_str} {name}"

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
        pattern = r'\b' + re.escape(kw) + r'\b'
        if re.search(pattern, name_lower):
            if kw == "pepper":
                fresh_peppers = ["bell", "chili", "chile", "jalapeno", "serrano", "habanero", "poblano", "sweet", "anaheim"]
                if any(p in name_lower for p in fresh_peppers):
                    continue
            return True
    return False

def process_tasks(tasks, session_id):
    try:
        total_tasks = len(tasks)
        aggregated_ingredients = {}
        skipped_meals = []

        days_pattern = re.compile(r'\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|mon|tue|wed|thu|fri|sat|sun)\b[:\-]?\s*', re.IGNORECASE)

        for i, task in enumerate(tasks):
            title = task.get("title", "")
            content = task.get("content", "")
            desc = task.get("desc", "")
            all_text = f"{title} {content} {desc}"

            all_text = days_pattern.sub('', all_text)
            urls = URL_PATTERN.findall(all_text)

            recipe_ingredients = []
            recipe_name = title
            scraped_successfully = False
            scraped_title = None

            if urls:
                yield f"data: {json.dumps({'status': f'[{i+1}/{total_tasks}] Scraping recipe: {title[:50]}...'})}\n\n"
                for url in urls:
                    try:
                        clean_url = url.strip(').,!? :;')
                        scraper = scrape_me(clean_url)
                        ings = scraper.ingredients()
                        if ings:
                            scraped_title = scraper.title()
                            for ing in ings:
                                recipe_ingredients.append({"raw": ing, "source": scraped_title, "type": "scrape"})
                            recipe_name = scraped_title
                            scraped_successfully = True
                            break
                    except Exception as e:
                        print(f"Failed to scrape {url}: {e}")

            # Extract remaining text after scraping URLs
            remaining_text = all_text
            for url in urls:
                remaining_text = remaining_text.replace(url, "")
            remaining_text = remaining_text.strip('., :-\t\n\r')

            if remaining_text:
                # Skip LLM if text is likely just the recipe name we already scraped
                skip_llm = False
                if scraped_successfully:
                    clean_rem = remaining_text.lower().strip(': ')
                    if not clean_rem or len(clean_rem) < 3:
                        skip_llm = True
                    elif scraped_title and (clean_rem in scraped_title.lower() or scraped_title.lower() in clean_rem):
                        skip_llm = True
                
                if not skip_llm:
                    yield f"data: {json.dumps({'status': f'[{i+1}/{total_tasks}] Asking LLM for: {remaining_text[:50]}...'})}\n\n"
                    try:
                        llm_ings = get_ingredients_from_llm(remaining_text, session_id=session_id, ignore_recipe=scraped_title if scraped_successfully else None)
                        if llm_ings:
                            for ing in llm_ings:
                                recipe_ingredients.append({"raw": ing, "source": f"LLM: {remaining_text[:30]}", "type": "llm"})
                    except Exception as e:
                        yield f"data: {json.dumps({'status': f'⚠️ LLM failed for {remaining_text[:30]}: {str(e)}'})}\n\n"

            if not recipe_ingredients:
                skipped_meals.append(recipe_name)
                yield f"data: {json.dumps({'status': f'⏩ Skipping {recipe_name[:30]} (no ingredients found)'})}\n\n"
                continue

            # Batch normalize all ingredients for this recipe
            yield f"data: {json.dumps({'status': f'[{i+1}/{total_tasks}] Normalizing {len(recipe_ingredients)} ingredients...'})}\n\n"
            
            # Returns list of (item, norm)
            normalized_results = normalize_ingredients_batch(recipe_ingredients, session_id=session_id)

            types = list(set(i['type'] for i in recipe_ingredients))
            source_type = "mixed" if len(types) > 1 else (types[0] if types else "unknown")

            database.log_event(session_id, "raw_ingredients", {
                "recipe": recipe_name,
                "source": source_type,
                "ingredients": [r['raw'] for r in recipe_ingredients]
            })

            for item, norm in normalized_results:
                raw_ing = item["raw"]
                source_name = item["source"]

                database.log_event(session_id, "normalization", {
                    "input": raw_ing,
                    "output": norm
                })

                base_name = norm["name"]
                
                # Create Pint quantity
                try:
                    # Handle fractions or ranges in quantity
                    qty_str = norm["quantity"]
                    if "/" in qty_str and " " in qty_str:
                        parts = qty_str.split()
                        qty_val = float(parts[0]) + float(Fraction(parts[1]))
                    elif "/" in qty_str:
                        qty_val = float(Fraction(qty_str))
                    elif "-" in qty_str:
                        qty_val = float(qty_str.split("-")[-1]) # Take upper bound
                    else:
                        qty_val = float(qty_str)
                    
                    unit_str = norm["unit"] if norm["unit"] else "count"
                    item_qty = qty_val * ureg(unit_str)
                except Exception as e:
                    print(f"Pint parsing error for {norm}: {e}")
                    item_qty = 1 * ureg.count

                if base_name not in aggregated_ingredients:
                    aggregated_ingredients[base_name] = {
                        "base_name": base_name,
                        "name": base_name,
                        "instances": [],
                        "original_task_ids": set(),
                        "total_qty": None,
                        "likely_have": is_likely_have(base_name)
                    }

                # Add to totals
                if aggregated_ingredients[base_name]["total_qty"] is None:
                    aggregated_ingredients[base_name]["total_qty"] = item_qty
                else:
                    try:
                        aggregated_ingredients[base_name]["total_qty"] += item_qty
                    except Exception as e:
                        try:
                            aggregated_ingredients[base_name]["total_qty"] += item_qty.to(aggregated_ingredients[base_name]["total_qty"].units)
                        except:
                            pass

                aggregated_ingredients[base_name]["instances"].append({
                    "raw": raw_ing,
                    "quantity": norm["quantity"],
                    "unit": norm["unit"],
                    "source": source_name,
                    "original_name": norm["name"]
                })
                aggregated_ingredients[base_name]["original_task_ids"].add(task["id"])

        results = []
        for k, v in aggregated_ingredients.items():
            v["original_task_ids"] = list(v["original_task_ids"])

            qty_obj = v.pop("total_qty")
            v["name"] = format_ingredient_quantity(v["base_name"], qty_obj)

            results.append(v)

        database.log_event(session_id, "aggregation", {"result": results})
        database.log_event(session_id, "skipped_meals", skipped_meals)

        yield f"data: {json.dumps({'ingredients': results, 'session_id': session_id, 'skipped_meals': skipped_meals})}\n\n"
    except Exception as e:
        import traceback
        error_msg = f"CRITICAL ERROR in process_tasks: {str(e)}\n{traceback.format_exc()}"
        print(error_msg)
        yield f"data: {json.dumps({'error': 'A critical error occurred during processing.'})}\n\n"

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
    tasks_data = data.get("tasks", [])
    raw_text = data.get("text", "")

    def generate():
        session_id = database.create_session()
        database.log_event(session_id, "start_test_scan", {"input_tasks": tasks_data, "input_text": raw_text})

        # Parse text into dummy tasks
        tasks = []

        if tasks_data:
            for i, task_data in enumerate(tasks_data):
                tasks.append({
                    "id": f"test-task-{i}",
                    "title": task_data.get("title", ""),
                    "content": "",
                    "desc": task_data.get("desc", "")
                })
        else:
            lines = [l.strip() for l in raw_text.split('\n') if l.strip()]
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
    bad_info_items = data.get("bad_info_items", [])
    rejected_items = data.get("rejected_items", [])
    session_id = data.get("session_id")
    output_list_name = "Groceries"

    if session_id and manual_items:
        database.log_event(session_id, "manual_items", manual_items)

    # Determine log directory from DB_PATH
    db_path = os.getenv("DB_PATH", "meal_planner.db")
    log_dir = os.path.dirname(db_path) if os.path.dirname(db_path) else "."
    bad_info_path = os.path.join(log_dir, "bad_info.jsonl")
    rejections_path = os.path.join(log_dir, "rejections.jsonl")

    # Save Bad Info flags if any
    if bad_info_items:
        try:
            timestamp = datetime.now().isoformat()
            log_entries = []
            for item in bad_info_items:
                log_entries.append({
                    "timestamp": timestamp,
                    "name": item.get("name"),
                    "raw_context": item.get("raw_context", []),
                    "source_recipes": item.get("source_recipes", []),
                    "action": item.get("action")
                })

            with open(bad_info_path, "a") as f:
                for entry in log_entries:
                    f.write(json.dumps(entry) + "\n")
        except Exception as e:
            print(f"Error saving bad info: {e}")

        if session_id:
            database.log_event(session_id, "bad_info_flagged", bad_info_items)

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

            with open(rejections_path, "a") as f:
                for rejection in file_rejections:
                    f.write(json.dumps(rejection) + "\n")
        except Exception as e:
            print(f"Error saving rejections: {e}")

        if session_id:
            database.log_event(session_id, "rejections", rejected_items)

    # Audit Log: Record all selected items
    if session_id:
        # First, mark session complete
        database.complete_session(session_id)

        selected_objects = data.get("selected_objects", [])
        
        # Collect raw ingredients flagged as bad info to merge into outcomes
        bad_info_raws = set()
        for item in bad_info_items:
            for raw in item.get("raw_context", []):
                bad_info_raws.add(raw)

        # 1. Approved items
        for obj in selected_objects:
            final_name = obj.get('name')
            base_name = obj.get('base_name')
            
            for inst in obj.get('instances', []):
                raw = inst.get('raw')
                outcome = "added"
                if raw in bad_info_raws:
                    outcome += "_ai_error"
                
                database.log_audit(
                    session_id, 
                    raw, 
                    base_name, 
                    final_name, 
                    inst.get('source'), 
                    outcome
                )

        # 2. Rejections
        for rej in rejected_items:
            for raw in rej.get('context', []):
                outcome = f"rejected_{rej.get('reason')}"
                if raw in bad_info_raws:
                    outcome += "_ai_error"
                    
                database.log_audit(session_id, raw, rej.get('name'), rej.get('name'), "Unknown", outcome)

        # 3. Manual items
        for item in manual_items:
             database.log_audit(session_id, "N/A", item, item, "Manual Entry", "added_manual")

    if not selected_items:
        return jsonify({"status": "No items to add", "bad_info_saved": len(bad_info_items)})

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

def graceful_shutdown(sig, frame):
    print("Shutting down gracefully...")
    database.close_db()
    sys.exit(0)

signal.signal(signal.SIGINT, graceful_shutdown)
signal.signal(signal.SIGTERM, graceful_shutdown)

if __name__ == "__main__":
    app.run(host="0.0.0.0", debug=True)
