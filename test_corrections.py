import unittest
import json
import os
from unittest.mock import patch, MagicMock
from app import app

class TestCorrections(unittest.TestCase):
    def setUp(self):
        self.app = app.test_client()
        self.app.testing = True
        self.corrections_file = "corrections.jsonl"
        if os.path.exists(self.corrections_file):
            os.remove(self.corrections_file)

    def tearDown(self):
        if os.path.exists(self.corrections_file):
            os.remove(self.corrections_file)

    @patch('app.load_token')
    @patch('app.requests.get')
    @patch('app.requests.post')
    def test_save_corrections(self, mock_post, mock_get, mock_load_token):
        # Mock authentication
        mock_load_token.return_value = "fake_token"
        with self.app.session_transaction() as sess:
            sess['access_token'] = 'fake_token'

        # Mock TickTick API calls to avoid errors
        # Mock finding project list
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = [{"id": "inbox", "name": "Groceries"}]

        # Mock creating task
        mock_post.return_value.status_code = 200

        payload = {
            "items": ["Corrected Item"],
            "corrections": [
                {
                    "original_name": "Wrong Item",
                    "corrected_name": "Corrected Item",
                    "context": ["1 cup Wrong Item"]
                }
            ]
        }

        response = self.app.post('/api/create_grocery_list',
                                 data=json.dumps(payload),
                                 content_type='application/json')

        self.assertEqual(response.status_code, 200)

        # Verify corrections.jsonl
        self.assertTrue(os.path.exists(self.corrections_file))
        with open(self.corrections_file, 'r') as f:
            lines = f.readlines()
            self.assertEqual(len(lines), 1)
            data = json.loads(lines[0])
            self.assertEqual(data['original_name'], "Wrong Item")
            self.assertEqual(data['corrected_name'], "Corrected Item")
            self.assertTrue("timestamp" in data)

if __name__ == '__main__':
    unittest.main()
