# TickTick Meal Planner & Grocery Generator

A Python Flask application that integrates with the TickTick Open API to streamline meal planning and grocery shopping.

## Features
- **Recipe Scanning**: Scans a specified TickTick list (default: "Meals") for tasks containing recipe URLs.
- **Ingredient Parsing**: Automatically extracts ingredients from recipes using `recipe-scrapers`.
- **Smart Aggregation**: Groups similar ingredients (e.g., "1 cup flour" and "200g flour" -> "Flour") to prevent duplicates.
- **Interactive Vetting**: A "Chatbot-style" web UI to approve or reject ingredients one by one.
- **Grocery List Generation**: Adds approved items to a target TickTick list (default: "Inbox"), either as individual tasks or subtasks of a parent task.

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
   - **First Run**: Access `http://127.0.0.1:5000` to log in via OAuth. This saves a `token.json` locally.
   - **Headless Server**: Use SSH tunneling for the first login: `ssh -L 5000:127.0.0.1:5000 user@server`.
   - **Access**: After login, the app is accessible at `http://0.0.0.0:5000` (e.g., via Tailscale).

## Usage
1. Open the web interface.
2. Enter your **Source List** name (e.g., "Meals") and **Target List** name (e.g., "Shopping").
3. (Optional) Enter a **Parent Task Name** (e.g., "Grocery Run 10/25") to group items as subtasks.
4. Click **Scan** to fetch recipes and review ingredients.
