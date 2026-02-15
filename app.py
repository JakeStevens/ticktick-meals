import os
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

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = secrets.token_hex(16)

# Initialize DB
database.init_db()

# TickTick Config
CLIENT_ID = os.getenv("TICKTICK_CLIENT_ID")
CLIENT_SECRET = os.getenv("TICKTICK_CLIENT_SECRET")
REDIRECT_URI = "http://127.0.0.1:5000/callback"

# LLM Config
llm_client = OpenAI(
    base_url=os.getenv("LLM_HOST"),
    api_key="sk-no-key-required"
)

# Endpoints
AUTH_URL = "https://ticktick.com/oauth/authorize"
TOKEN_URL = "https://ticktick.com/oauth/token"
API_BASE = "https://api.ticktick.com/open/v1/project"
TOKEN_FILE = "token.json"

def load_token():
    if os.path.exists(TOKEN_FILE):
        try:
            with open(TOKEN_FILE, "r") as f:
                return json.load(f).get("access_token")
        except:
            return None
    return None

def save_token(token_data):
    with open(TOKEN_FILE, "w") as f:
        json.dump(token_data, f)

@app.route("/")
def index():
    access_token = load_token()
    if not access_token:
        return render_template("login.html")
    session["access_token"] = access_token
    return render_template("index.html")

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
    prompt = f"List the ingredients required for a typical version of {recipe_name}. Keep the ingredients high level, things like spices can be assumed to be available. Provide the list as a simple bulleted list of ingredient names only. If the entry is something that doesn't need ingredients, such as 'left overs', 'freezer meal', 'takeout', 'Brassica', 'date night', or similar non-recipe items, return an empty response."

    if session_id:
        database.log_event(session_id, "llm_prompt", {"recipe": recipe_name, "prompt": prompt})

    try:
        response = llm_client.chat.completions.create(
            model="default", 
            messages=[
                {"role": "system", "content": "You are a helpful culinary assistant that provides high-level ingredient lists. If a dish doesn't require ingredients to be bought (like leftovers or takeout), you return nothing."},
                {"role": "user", "content": prompt}
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
        return []

def normalize_ingredient(text):
    """
    Heuristic to extract base name, quantity, and unit.
    Returns a dict: {'name': str, 'quantity': str, 'unit': str}
    """
    original_text = text
    text = text.lower()
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
    quantity = quantity_match.group(1).strip() if quantity_match else ""
    
    # Strip quantity from text
    text = re.sub(r'^[\d\s\/\.\-]+', '', text).strip()
    
    words = text.split()
    unit = ""
    if words and words[0] in units:
        unit = words.pop(0)
    
    # Check for "of" (e.g., "1 cup of flour")
    if words and words[0] == "of":
        words.pop(0)
        
    base_name = " ".join(words).strip()
    
    # Fallback for strings that don't match the pattern well
    if not base_name:
        base_name = original_text

    return {
        "name": base_name,
        "quantity": quantity,
        "unit": unit
    }

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
        projects_res = requests.get(f"{API_BASE}", headers=headers)
        target_project_id = None
        
        if projects_res.status_code == 200:
            projects = projects_res.json()
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
        
        aggregated_ingredients = {}

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
            total_tasks = len(plan_tasks)
            
            for i, task in enumerate(plan_tasks):
                title = task.get("title", "")
                content = task.get("content", "")
                desc = task.get("desc", "")
                all_text = f"{title} {content} {desc}"
                urls = re.findall(r'https?://[^\s\)\>\]\"\'\s]+', all_text)
                
                recipe_ingredients = []
                recipe_name = title
                scraped_successfully = False

                if urls:
                    yield f"data: {json.dumps({'status': f'[{i+1}/{total_tasks}] Scraping recipe: {title[:50]}...'})}\n\n"
                    for url in urls:
                        try:
                            clean_url = url.strip(').')
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
                    recipe_ingredients = get_ingredients_from_llm(title, session_id=session_id)
                
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
                    if base_name not in aggregated_ingredients:
                        aggregated_ingredients[base_name] = {
                            "name": base_name,
                            "amounts": [],
                            "details": [], 
                            "raw_lines": [],
                            "original_task_ids": set()
                        }
                    
                    aggregated_ingredients[base_name]["amounts"].append({
                        "quantity": norm["quantity"],
                        "unit": norm["unit"],
                        "source": recipe_name
                    })
                    aggregated_ingredients[base_name]["details"].append(f"{raw_ing} (from {recipe_name})")
                    aggregated_ingredients[base_name]["raw_lines"].append(raw_ing)
                    aggregated_ingredients[base_name]["original_task_ids"].add(task["id"])

        results = []
        for k, v in aggregated_ingredients.items():
            v["original_task_ids"] = list(v["original_task_ids"])
            results.append(v)

        database.log_event(session_id, "aggregation", {"result": results})

        yield f"data: {json.dumps({'ingredients': results, 'session_id': session_id})}\n\n"

    return Response(stream_with_context(generate()), mimetype="text/event-stream")

@app.route("/api/create_grocery_list", methods=["POST"])
def create_grocery_list():
    access_token = session.get("access_token") or load_token()
    if not access_token:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.json
    selected_items = data.get("items", []) 
    corrections = data.get("corrections", [])
    session_id = data.get("session_id")
    output_list_name = "Groceries"

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

    if session_id:
        database.complete_session(session_id)

    if not selected_items:
        return jsonify({"status": "No items to add", "corrections_saved": len(corrections)})

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    
    target_project_id = "inbox" # Default
    projects_res = requests.get(API_BASE, headers=headers)
    if projects_res.status_code == 200:
        for p in projects_res.json():
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
    with ThreadPoolExecutor() as executor:
        responses = list(executor.map(create_task, selected_items))
        
    return jsonify({"status": "success", "count": len(responses)})

if __name__ == "__main__":
    app.run(host="0.0.0.0", debug=True)
