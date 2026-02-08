import os
import secrets
from flask import Flask, render_template, redirect, request, session, url_for, jsonify
import requests
from recipe_scrapers import scrape_me
from dotenv import load_dotenv

import json

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = secrets.token_hex(16)

# TickTick Config
CLIENT_ID = os.getenv("TICKTICK_CLIENT_ID")
CLIENT_SECRET = os.getenv("TICKTICK_CLIENT_SECRET")
REDIRECT_URI = "http://127.0.0.1:5000/callback"

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

import re



# ... (Previous imports remain, keeping them implicit for the tool to find context if needed, but since I am replacing the whole file content in my head, I need to be careful. 

# actually, the tool 'replace' works on exact string matching. I should use 'write_file' if I am rewriting significant logic, or 'replace' carefully. 

# The changes are scattered (helper function, updated endpoints). 'write_file' is safer and cleaner here given the extent of logic changes.)



@app.route("/api/scan_meals", methods=["POST"])

def scan_meals():

    access_token = session.get("access_token") or load_token()

    if not access_token:

        return jsonify({"error": "Unauthorized"}), 401

    

    data = request.json or {}

    input_list_name = data.get("input_list_name", "Meals")



    headers = {"Authorization": f"Bearer {access_token}"}

    

    # 1. Find Project ID by Name

    projects_res = requests.get(f"{API_BASE}", headers=headers)

    target_project_id = None

    

    if projects_res.status_code == 200:

        projects = projects_res.json()

        for p in projects:

            if p.get("name", "").lower() == input_list_name.lower():

                target_project_id = p["id"]

                break

    

    if not target_project_id:

        return jsonify({"error": f"Could not find list named '{input_list_name}'"}), 404



    # 2. Fetch Tasks

    tasks_url = f"{API_BASE}/{target_project_id}/data"

    tasks_res = requests.get(tasks_url, headers=headers)

    

    aggregated_ingredients = {}



    if tasks_res.status_code == 200:

        data = tasks_res.json()

        tasks = data.get("tasks", [])

        

        for task in tasks:

            content = task.get("content", "") + " " + task.get("desc", "")

            words = content.split()

            urls = [w for w in words if w.startswith("http")]

            

            for url in urls:

                try:

                    scraper = scrape_me(url)

                    ingredients = scraper.ingredients()

                    recipe_name = scraper.title()

                    

                    for raw_ing in ingredients:

                        base_name = normalize_ingredient(raw_ing)

                        

                        if base_name not in aggregated_ingredients:

                            aggregated_ingredients[base_name] = {

                                "name": base_name,

                                "details": [], # List of strings like "1 cup (Lasagna)"

                                "raw_lines": [],

                                "original_task_ids": set()

                            }

                        

                        aggregated_ingredients[base_name]["details"].append(f"{raw_ing} (from {recipe_name})")

                        aggregated_ingredients[base_name]["raw_lines"].append(raw_ing)

                        aggregated_ingredients[base_name]["original_task_ids"].add(task["id"])



                except Exception as e:

                    print(f"Failed to scrape {url}: {e}")



    # Convert sets to lists for JSON serialization

    results = []

    for k, v in aggregated_ingredients.items():

        v["original_task_ids"] = list(v["original_task_ids"])

        results.append(v)



    return jsonify({"ingredients": results})



def normalize_ingredient(text):

    """

    Simple heuristic to extract the 'main' ingredient name.

    1. Lowercase.

    2. Remove text in parens.

    3. Remove leading numbers and common units.

    """

    text = text.lower()

    text = re.sub(r'\([^)]*\)', '', text) # Remove (optional)

    

    # Common units/measurements to strip

    units = [

        "cup", "cups", "tbsp", "tsp", "tablespoon", "teaspoon", 

        "oz", "ounce", "ounces", "lb", "lbs", "pound", "pounds", 

        "g", "gram", "grams", "kg", "ml", "l", "liter", "pinch", 

        "slice", "slices", "clove", "cloves", "can", "cans", "jar", "jars",

        "package", "packages", "bunch", "bunches", "large", "small", "medium"

    ]

    

    # Regex to match: Start -> Number/Fraction -> Unit (optional) -> "of" (optional) -> Rest

    # e.g. "1/2 cup of flour" -> "flour"

    # e.g. "2 onions" -> "onions"

    

    # Remove leading numbers/fractions/ranges (e.g. 1, 1/2, 1-2, 1.5)

    text = re.sub(r'^[\d\s\/\.\-]+', '', text).strip()

    

    words = text.split()

    if not words: return text

    

    # Check if first word is a unit

    if words[0] in units:

        words.pop(0)

    

    # Check for "of"

    if words and words[0] == "of":

        words.pop(0)

        

    return " ".join(words).strip()



@app.route("/api/create_grocery_list", methods=["POST"])

def create_grocery_list():

    access_token = session.get("access_token") or load_token()

    if not access_token:

        return jsonify({"error": "Unauthorized"}), 401



    data = request.json

    selected_items = data.get("items", []) # List of objects {name: "Flour", details: [...]}

    output_list_name = data.get("output_list_name", "Inbox")

    parent_task_name = data.get("parent_task_name", "").strip()



    if not selected_items:

        return jsonify({"status": "No items to add"})



    headers = {

        "Authorization": f"Bearer {access_token}",

        "Content-Type": "application/json"

    }

    

    # 1. Find Target Project

    target_project_id = "inbox" # Default

    if output_list_name.lower() != "inbox":

        projects_res = requests.get(API_BASE, headers=headers)

        if projects_res.status_code == 200:

            for p in projects_res.json():

                if p.get("name", "").lower() == output_list_name.lower():

                    target_project_id = p["id"]

                    break

    

    # 2. Logic: One Parent Task with Subtasks OR Individual Tasks

    if parent_task_name:

        # Create/Find Parent Task

        # For simplicity, we just create a new one every time to avoid searching complexity

        # (User can name it "Groceries 10/25")

        

        parent_payload = {

            "projectId": target_project_id,

            "title": parent_task_name,

            "items": []

        }

        

        for item in selected_items:

            # Item is expected to be the 'base name' or a formatted string from the UI

            # We can include the raw lines in the subtask title or just the base name

            # Let's use the Base Name + maybe total count?

            # User wants aggregation, so "Flour" is the item.

            # If they want details, maybe put them in description? TickTick subtasks are simple.

            # Let's just put the name.

            parent_payload["items"].append({

                "title": item, # e.g. "Flour"

                "status": 0

            })

            

        res = requests.post("https://api.ticktick.com/open/v1/task", json=parent_payload, headers=headers)

        return jsonify({"status": "success", "mode": "subtasks", "data": res.json()})

        

    else:

        # Create Individual Tasks for each item

        responses = []

        for item in selected_items:

            task_payload = {

                "projectId": target_project_id,

                "title": item,

                "status": 0

            }

            res = requests.post("https://api.ticktick.com/open/v1/task", json=task_payload, headers=headers)

            responses.append(res.status_code)

            

        return jsonify({"status": "success", "mode": "tasks", "count": len(responses)})



if __name__ == "__main__":
    app.run(host="0.0.0.0", debug=True)
