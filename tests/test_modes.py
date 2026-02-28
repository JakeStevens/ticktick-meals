import unittest
import json
import os
import sqlite3
from unittest.mock import patch, MagicMock
import app
import database

class TestAppTestMode(unittest.TestCase):
    def setUp(self):
        self.test_db = "test_meal_planner_mode.db"
        database.DB_FILE = self.test_db
        database.close_db()
        database.init_db()
        self.app = app.app.test_client()
        self.app.testing = True

    def tearDown(self):
        if os.path.exists(self.test_db):
            os.remove(self.test_db)

    def test_test_scan_endpoint(self):
        # Mock LLM and scraper
        with patch('app.scrape_me') as mock_scrape, \
             patch('app.llm_client.chat.completions.create') as mock_llm_create:

            # 1. Test with scraping
            mock_scraper = MagicMock()
            mock_scraper.ingredients.return_value = ["1 cup flour", "2 eggs"]
            mock_scraper.title.return_value = "Pancakes"
            mock_scrape.return_value = mock_scraper

            payload = {"text": "https://example.com/pancakes"}
            response = self.app.post('/api/test_scan',
                                     data=json.dumps(payload),
                                     content_type='application/json')

            self.assertEqual(response.status_code, 200)

            # Check response stream
            data_chunks = []
            for line in response.data.decode('utf-8').split('\n\n'):
                if line.startswith('data: '):
                    data_chunks.append(json.loads(line[6:]))

            last_chunk = data_chunks[-1]
            self.assertIn('ingredients', last_chunk)
            # Flatten ingredients to check names
            ing_names = [i['name'] for i in last_chunk['ingredients']]
            self.assertTrue(any('flour' in name for name in ing_names))
            self.assertTrue(any('eggs' in name for name in ing_names))

            # 2. Test with LLM (raw text)
            mock_llm_response = MagicMock()
            mock_llm_response.choices[0].message.content = "1 slice bread\n1 slice cheese"
            mock_llm_create.return_value = mock_llm_response

            payload = {"text": "Grilled Cheese"}
            response = self.app.post('/api/test_scan',
                                     data=json.dumps(payload),
                                     content_type='application/json')

            data_chunks = []
            for line in response.data.decode('utf-8').split('\n\n'):
                if line.startswith('data: '):
                    data_chunks.append(json.loads(line[6:]))

            last_chunk = data_chunks[-1]
            self.assertIn('ingredients', last_chunk)
            ingredients = {item['name'] for item in last_chunk['ingredients']}
            self.assertTrue(any('bread' in name for name in ingredients))
            self.assertTrue(any('cheese' in name for name in ingredients))

    def test_create_grocery_list_test_mode(self):
        # Create a session
        database.create_session()
        conn = sqlite3.connect(self.test_db)
        c = conn.cursor()
        c.execute("SELECT id FROM sessions")
        session_id = c.fetchone()[0]
        conn.close()

        payload = {
            "items": ["Item 1"],
            "session_id": session_id,
            "test_mode": True
        }

        # We don't need to mock requests.post because it shouldn't be called
        # But we can patch it just to assert it's NOT called
        with patch('app.requests.post') as mock_post:
            response = self.app.post('/api/create_grocery_list',
                                     data=json.dumps(payload),
                                     content_type='application/json')

            self.assertEqual(response.status_code, 200)
            data = json.loads(response.data)
            self.assertEqual(data.get("test_mode"), True)
            self.assertEqual(data.get("status"), "success")

            mock_post.assert_not_called()

            # Verify DB logging
            conn = sqlite3.connect(self.test_db)
            c = conn.cursor()
            c.execute("SELECT is_complete FROM sessions WHERE id=?", (session_id,))
            self.assertEqual(c.fetchone()[0], 1)
            conn.close()

if __name__ == '__main__':
    unittest.main()
