import unittest
import json
import os
import sqlite3
from unittest.mock import patch, MagicMock
from app import app
import database

class TestRejections(unittest.TestCase):
    def setUp(self):
        self.app = app.test_client()
        self.app.testing = True
        self.rejections_file = "rejections.jsonl"
        self.test_db = "test_meal_planner_rejections.db"
        database.DB_FILE = self.test_db
        database.init_db()

        if os.path.exists(self.rejections_file):
            os.remove(self.rejections_file)

    def tearDown(self):
        if os.path.exists(self.rejections_file):
            os.remove(self.rejections_file)
        if os.path.exists(self.test_db):
            os.remove(self.test_db)

    @patch('app.load_token')
    @patch('app.requests.get')
    @patch('app.requests.post')
    def test_save_rejections(self, mock_post, mock_get, mock_load_token):
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
            "items": [],
            "rejected_items": [
                {
                    "name": "Rejected Item 1",
                    "reason": "have_it",
                    "context": ["1 cup Rejected Item 1"]
                },
                {
                    "name": "Rejected Item 2",
                    "reason": "bad_parsing",
                    "context": ["bad text"]
                }
            ],
            "session_id": session_id
        }

        response = self.app.post('/api/create_grocery_list',
                                 data=json.dumps(payload),
                                 content_type='application/json')

        self.assertEqual(response.status_code, 200)

        # Verify rejections.jsonl
        self.assertTrue(os.path.exists(self.rejections_file))
        with open(self.rejections_file, 'r') as f:
            lines = f.readlines()
            self.assertEqual(len(lines), 2)

            data1 = json.loads(lines[0])
            self.assertEqual(data1['name'], "Rejected Item 1")
            self.assertEqual(data1['reason'], "have_it")
            self.assertTrue("timestamp" in data1)

            data2 = json.loads(lines[1])
            self.assertEqual(data2['name'], "Rejected Item 2")
            self.assertEqual(data2['reason'], "bad_parsing")

        # Verify DB logs
        conn = sqlite3.connect(self.test_db)
        c = conn.cursor()
        c.execute("SELECT data FROM logs WHERE session_id=? AND event_type='rejections'", (session_id,))
        log = c.fetchone()
        self.assertIsNotNone(log)
        log_data = json.loads(log[0])
        self.assertEqual(len(log_data), 2)
        self.assertEqual(log_data[0]['name'], "Rejected Item 1")
        conn.close()

if __name__ == '__main__':
    unittest.main()
