import unittest
import json
import os
import sqlite3
from unittest.mock import patch, MagicMock
from app import app
import database

class TestBadInfo(unittest.TestCase):
    def setUp(self):
        self.app = app.test_client()
        self.app.testing = True
        self.bad_info_file = "bad_info.jsonl"
        self.test_db = "test_meal_planner_badinfo.db"
        database.close_db()
        database.DB_FILE = self.test_db
        database.init_db()

        if os.path.exists(self.bad_info_file):
            os.remove(self.bad_info_file)

    def tearDown(self):
        if os.path.exists(self.bad_info_file):
            os.remove(self.bad_info_file)
        if os.path.exists(self.test_db):
            os.remove(self.test_db)

    @patch('app.load_token')
    @patch('app.requests.get')
    @patch('app.requests.post')
    def test_save_bad_info(self, mock_post, mock_get, mock_load_token):
        # Create a session to link logs to
        session_id = database.create_session()

        # Mock authentication
        mock_load_token.return_value = "fake_token"
        with self.app.session_transaction() as sess:
            sess['access_token'] = 'fake_token'

        # Mock TickTick API calls
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = [{"id": "inbox", "name": "Groceries"}]
        mock_post.return_value.status_code = 200

        payload = {
            "items": ["Onion"],
            "bad_info_items": [
                {
                    "name": "Onion",
                    "raw_context": ["1 cup bad onion"],
                    "source_recipes": ["Test Recipe"],
                    "action": "added_to_list"
                }
            ],
            "session_id": session_id
        }

        response = self.app.post('/api/create_grocery_list',
                                 data=json.dumps(payload),
                                 content_type='application/json')

        self.assertEqual(response.status_code, 200)

        # Verify bad_info.jsonl
        self.assertTrue(os.path.exists(self.bad_info_file))
        with open(self.bad_info_file, 'r') as f:
            lines = f.readlines()
            self.assertEqual(len(lines), 1)
            data = json.loads(lines[0])
            self.assertEqual(data['name'], "Onion")
            self.assertEqual(data['action'], "added_to_list")
            self.assertEqual(data['raw_context'], ["1 cup bad onion"])

        # Verify DB logs
        conn = sqlite3.connect(self.test_db)
        c = conn.cursor()
        c.execute("SELECT data FROM logs WHERE session_id=? AND event_type='bad_info_flagged'", (session_id,))
        log = c.fetchone()
        self.assertIsNotNone(log)
        log_data = json.loads(log[0])
        self.assertEqual(len(log_data), 1)
        self.assertEqual(log_data[0]['name'], "Onion")
        conn.close()

if __name__ == '__main__':
    unittest.main()
