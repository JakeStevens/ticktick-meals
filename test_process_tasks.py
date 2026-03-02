import json
import app
from unittest.mock import patch, MagicMock

class DummyScraper:
    def ingredients(self): return ["1 lb ground beef", "1 cup ketchup"]
    def title(self): return "Sloppy Joes II"

def dummy_scrape_me(url):
    return DummyScraper()

def dummy_get_llm(text, session_id=None, ignore_recipe=None):
    if ignore_recipe:
        print(f"Mock LLM called with text: '{text}', ignoring: '{ignore_recipe}'")
    else:
        print(f"Mock LLM called with text: '{text}'")
    return ["shrimp", "smiley face fries"]

with patch('app.scrape_me', side_effect=dummy_scrape_me), \
     patch('app.get_ingredients_from_llm', side_effect=dummy_get_llm):

    tasks = [
        {
            "id": "1",
            "title": "Monday: https://www.allrecipes.com/recipe/24264/sloppy-joes-ii/",
            "desc": "sloppy Joe, shrimp, smiley face fries"
        },
        {
            "id": "2",
            "title": "Tuesday: sloppy Joe, shrimp smiley face fries,",
            "desc": "https://www.allrecipes.com/recipe/24264/sloppy-joes-ii/"
        }
    ]

    generator = app.process_tasks(tasks, "fake_session")
    for item in generator:
        if item.startswith("data: "):
            data = json.loads(item[6:])
            if 'ingredients' in data:
                print("\nFINAL RESULT:")
                print(json.dumps(data['ingredients'], indent=2))
            else:
                print(data)
