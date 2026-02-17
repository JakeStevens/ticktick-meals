import unittest
from unittest.mock import patch, MagicMock
import json
import sys

# Mock modules before importing app
sys.modules['database'] = MagicMock()
sys.modules['database'].create_session.return_value = 'test_session_id'

# We also need to mock openai and recipe_scrapers if they try to do things on import or init
sys.modules['openai'] = MagicMock()
sys.modules['recipe_scrapers'] = MagicMock()

# Now import app
import app

class TestSkippedMeals(unittest.TestCase):

    @patch('app.requests.get')
    @patch('app.get_ingredients_from_llm')
    @patch('app.scrape_me')
    def test_scan_meals_skips_empty_ingredients(self, mock_scraper, mock_llm, mock_get):
        # Setup Mocks
        mock_llm.return_value = [] # Return empty ingredients
        mock_scraper.side_effect = Exception("Scraping failed")

        # Mock projects response
        mock_project_response = MagicMock()
        mock_project_response.status_code = 200
        mock_project_response.json.return_value = [{"id": "p1", "name": "Week's Meal Ideas"}]

        # Mock tasks response
        mock_tasks_response = MagicMock()
        mock_tasks_response.status_code = 200
        mock_tasks_response.json.return_value = {
            "tasks": [
                {"id": "t1", "title": "Pizza", "columnId": "c1"},
                {"id": "t2", "title": "Leftovers", "columnId": "c1"}
            ],
            "columns": [{"id": "c1", "name": "Weekly Plan"}]
        }

        mock_get.side_effect = [mock_project_response, mock_tasks_response]

        # Setup request context
        with app.app.test_client() as client:
            with client.session_transaction() as sess:
                sess['access_token'] = 'fake_token'

            response = client.post('/api/scan_meals', json={"input_list_name": "Week's Meal Ideas"})

            self.assertEqual(response.status_code, 200)

            # response.data contains the full stream
            stream_str = response.data.decode('utf-8')

            # Parse the final JSON line
            lines = stream_str.strip().split('\n\n')
            final_line = lines[-1]

            # Ensure we got data
            self.assertTrue(final_line.startswith("data: "))
            final_json = json.loads(final_line[6:])

            # Verify 'skipped_meals' is present and correct
            self.assertIn('skipped_meals', final_json)
            self.assertEqual(final_json['skipped_meals'], ['Pizza', 'Leftovers'])
            self.assertEqual(final_json['ingredients'], [])

if __name__ == '__main__':
    unittest.main()
