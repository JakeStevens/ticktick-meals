import unittest
import json
import os
import sqlite3
from unittest.mock import patch, MagicMock
import app
import database

class TestLogging(unittest.TestCase):
    def setUp(self):
        # Use a temporary DB for testing
        self.test_db = "test_meal_planner.db"
        database.DB_FILE = self.test_db
        # Close any existing connection to ensure we use the test DB
        database.close_db()
        # Initialize the DB
        database.init_db()

        self.app = app.app.test_client()
        self.app.testing = True

        # Clear cache
        app.PROJECT_CACHE.clear()

    def tearDown(self):
        if os.path.exists(self.test_db):
            os.remove(self.test_db)

    def test_scan_meals_logging(self):
        # Mock dependencies
        with patch('app.load_token') as mock_load_token, \
             patch('app.requests.get') as mock_get, \
             patch('app.scrape_me') as mock_scrape, \
             patch('app.llm_client.chat.completions.create') as mock_llm_create:

            mock_load_token.return_value = "fake_token"
            with self.app.session_transaction() as sess:
                sess['access_token'] = 'fake_token'

            # Mock finding project
            mock_project_resp = MagicMock()
            mock_project_resp.status_code = 200
            mock_project_resp.json.return_value = [{"id": "p1", "name": "Week's Meal Ideas"}]

            # Mock fetching tasks
            mock_tasks_resp = MagicMock()
            mock_tasks_resp.status_code = 200
            mock_tasks_resp.json.return_value = {
                "tasks": [
                    {"id": "t1", "title": "Pasta", "content": "http://example.com/pasta", "columnId": "c1"}
                ],
                "columns": [{"id": "c1", "name": "Weekly Plan"}]
            }

            mock_get.side_effect = [mock_project_resp, mock_tasks_resp]

            # Mock scraper to fail so LLM is called
            mock_scrape.side_effect = Exception("Scraping failed")

            # Mock LLM response
            mock_llm_response = MagicMock()
            mock_llm_response.choices[0].message.content = "1 cup rice"
            mock_llm_create.return_value = mock_llm_response

            response = self.app.post('/api/scan_meals',
                                     data=json.dumps({"input_list_name": "Week's Meal Ideas"}),
                                     content_type='application/json')

            self.assertEqual(response.status_code, 200)

            # Consume the stream
            data_chunks = []
            for line in response.data.decode('utf-8').split('\n\n'):
                if line.startswith('data: '):
                    data_chunks.append(json.loads(line[6:]))

            # Verify session_id in the last chunk
            last_chunk = data_chunks[-1]
            self.assertIn('ingredients', last_chunk)
            self.assertIn('session_id', last_chunk)
            session_id = last_chunk['session_id']

            # Verify DB logs
            conn = sqlite3.connect(self.test_db)
            c = conn.cursor()

            # Check session created
            c.execute("SELECT * FROM sessions WHERE id=?", (session_id,))
            session = c.fetchone()
            self.assertIsNotNone(session)

            # Check logs
            c.execute("SELECT event_type, data FROM logs WHERE session_id=?", (session_id,))
            logs = c.fetchall()
            event_types = [l[0] for l in logs]

            self.assertIn('start_scan', event_types)
            self.assertIn('raw_ingredients', event_types)
            self.assertIn('normalization', event_types)
            self.assertIn('aggregation', event_types)
            self.assertIn('llm_prompt', event_types)
            self.assertIn('llm_response', event_types)

            conn.close()

    def test_create_grocery_list_logging(self):
        # First, create a session directly in DB
        database.create_session()
        # Retrieve the session id we just created (hacky but works since it's the only one)
        conn = sqlite3.connect(self.test_db)
        c = conn.cursor()
        c.execute("SELECT id FROM sessions")
        session_id = c.fetchone()[0]
        conn.close()

        with patch('app.load_token') as mock_load_token, \
             patch('app.requests.get') as mock_get, \
             patch('app.requests.post') as mock_post:

            mock_load_token.return_value = "fake_token"
            with self.app.session_transaction() as sess:
                sess['access_token'] = 'fake_token'

            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = [{"id": "inbox", "name": "Groceries"}]
            mock_post.return_value.status_code = 200

            payload = {
                "items": ["Item 1"],
                "corrections": [{"original_name": "Bad", "corrected_name": "Good"}],
                "session_id": session_id
            }

            response = self.app.post('/api/create_grocery_list',
                                     data=json.dumps(payload),
                                     content_type='application/json')

            self.assertEqual(response.status_code, 200)

            # Verify DB logs
            conn = sqlite3.connect(self.test_db)
            c = conn.cursor()

            # Check logs for corrections
            c.execute("SELECT data FROM logs WHERE session_id=? AND event_type='corrections'", (session_id,))
            log = c.fetchone()
            self.assertIsNotNone(log)
            self.assertIn("Bad", log[0])

            # Check session complete
            c.execute("SELECT is_complete, completed_at FROM sessions WHERE id=?", (session_id,))
            session = c.fetchone()
            self.assertEqual(session[0], 1)
            self.assertIsNotNone(session[1])

            conn.close()

if __name__ == '__main__':
    unittest.main()
