# TickTick Meal Planner & Grocery Generator

A Python Flask application that integrates with the TickTick Open API to streamline meal planning and grocery shopping.

## Features
- **Recipe Scanning**: Scans a specified TickTick list (default: "Meals") for tasks containing recipe URLs.
- **Ingredient Parsing**: Automatically extracts ingredients from recipes using `recipe-scrapers`.
- **Smart Aggregation**: Groups similar ingredients (e.g., "1 cup flour" and "200g flour" -> "Flour") to prevent duplicates.
- **Interactive Vetting**: A "Chatbot-style" web UI to approve or reject ingredients one by one.
- **Grocery List Generation**: Adds approved items to a target TickTick list (default: "Inbox"), either as individual tasks or subtasks of a parent task.

## System Design & Pipeline

The application operates as a linear pipeline that transforms TickTick tasks into a curated grocery list.

### 1. Input (TickTick Tasks)
- **Source**: A TickTick project (e.g., "Week's Meal Ideas") and a specific column (e.g., "Weekly Plan").
- **Task Schema**:
  ```json
  {
    "title": "Recipe Name or Meal Idea",
    "content": "Optional Markdown or URL",
    "desc": "Optional Description or URL",
    "id": "Task ID",
    "columnId": "Section ID"
  }
  ```

### 2. Extraction (Scraping & LLM)
- **Process**:
  - **Scraper**: If a URL is detected in `title`, `content`, or `desc`, it uses `recipe-scrapers` to pull the precise ingredient list.
  - **LLM**: If no URL is found, it queries a configured LLM (`LLM_HOST`) to generate a high-level ingredient list based on the task title.
- **Extracted Schema**: A simple list of strings: `["1 cup of flour", "2 eggs", ...]`.

### 3. Normalization & Aggregation
- **Process**: Heuristically strips units (cup, tbsp, etc.), numbers, and parentheticals to identify the "base" ingredient.
- **Normalized Schema (Single Item)**:
  ```json
  {
    "base_name": "flour",
    "quantity": "1",
    "unit": "cup",
    "raw_text": "1 cup of flour",
    "source_task_id": "task_uuid_1"
  }
  ```
- **Aggregated Schema (Collection)**:
  ```json
  {
    "flour": {
      "name": "flour",
      "amounts": [
        {"quantity": "1", "unit": "cup", "source": "Pizza"},
        {"quantity": "200", "unit": "g", "source": "Bread"}
      ],
      "details": ["1 cup of flour (from Pizza)", "200g flour (from Bread)"],
      "raw_lines": ["1 cup of flour", "200g flour"],
      "original_task_ids": ["task_uuid_1", "task_uuid_2"]
    }
  }
  ```

### 4. Output (TickTick Grocery List)
- **Destination**: A TickTick project (default: "Groceries").
- **Action**: Creates a new task for each selected ingredient from the vetting UI.

## Setup

1. **Prerequisites**
   - Python 3.8+
   - A TickTick Account
   - [TickTick App Credentials](https://developer.ticktick.com/manage) (Client ID & Secret)

2. **Installation**
   ```bash
   # Clone the repo (if applicable)
   # git clone ...

   # Create virtual environment
   python -m venv ticktick
   source ticktick/bin/activate  # Linux/Mac
   # ticktick\Scripts\activate   # Windows

   # Install dependencies
   pip install -r requirements.txt
   ```

3. **Configuration**
   - Rename `.env.example` to `.env`.
   - Add your `TICKTICK_CLIENT_ID` and `TICKTICK_CLIENT_SECRET`.
   - Ensure `REDIRECT_URI` matches your developer console (default: `http://127.0.0.1:5000/callback`).

4. **Running**
   ```bash
   python app.py
   ```

## Headless / Tailscale Deployment
If you are running this on a headless server (like a Raspberry Pi or VPS) and accessing via Tailscale:

1.  **Initial Login (One-Time Setup)**
    Since the app is configured for `localhost` redirection (for security), you must perform the first login via an SSH tunnel.
    *   **On your laptop:** Run `ssh -L 5000:127.0.0.1:5000 user@your-server-ip`
    *   **On the server:** Run `python app.py`
    *   **Browser:** Open `http://127.0.0.1:5000`, log in, and authorize TickTick.
    *   This saves a `token.json` file on the server.

2.  **Regular Usage**
    *   Once `token.json` exists, stop the SSH tunnel.
    *   Run `python app.py` on the server again (or keep it running).
    *   Access the app from any device on your Tailscale network: `http://<tailscale-ip>:5000`

## Usage
1. Open the web interface.
2. Enter your **Source List** name (e.g., "Meals") and **Target List** name (e.g., "Shopping").
3. (Optional) Enter a **Parent Task Name** (e.g., "Grocery Run 10/25") to group items as subtasks.
4. Click **Scan** to fetch recipes and review ingredients.
