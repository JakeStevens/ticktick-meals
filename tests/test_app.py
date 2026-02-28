import sys
from unittest.mock import MagicMock, patch, mock_open
import unittest
import json

# Mock missing dependencies before importing app
# mock_flask = MagicMock()
# sys.modules["flask"] = mock_flask
# sys.modules["requests"] = MagicMock()
# sys.modules["recipe_scrapers"] = MagicMock()
# sys.modules["dotenv"] = MagicMock()
# sys.modules["openai"] = MagicMock()

# Now we can import load_token from app
from app import load_token, TOKEN_FILE

class TestLoadToken(unittest.TestCase):

    @patch("os.path.exists")
    def test_load_token_success(self, mock_exists):
        # Case: token.json exists and has access_token
        mock_exists.return_value = True
        token_data = {"access_token": "test-token-123"}

        with patch("builtins.open", mock_open(read_data=json.dumps(token_data))):
            token = load_token()
            self.assertEqual(token, "test-token-123")

    @patch("os.path.exists")
    def test_load_token_file_not_found(self, mock_exists):
        # Case: token.json does not exist
        mock_exists.return_value = False

        token = load_token()
        self.assertIsNone(token)

    @patch("os.path.exists")
    def test_load_token_invalid_json(self, mock_exists):
        # Case: token.json exists but is invalid JSON
        mock_exists.return_value = True

        with patch("builtins.open", mock_open(read_data="invalid json")):
            token = load_token()
            self.assertIsNone(token)

    @patch("os.path.exists")
    def test_load_token_missing_key(self, mock_exists):
        # Case: token.json exists but is missing access_token key
        mock_exists.return_value = True
        token_data = {"other_key": "some-value"}

        with patch("builtins.open", mock_open(read_data=json.dumps(token_data))):
            token = load_token()
            self.assertIsNone(token)

    @patch("os.path.exists")
    def test_load_token_not_a_dict(self, mock_exists):
        # Case: token.json exists but contains a list instead of a dict
        mock_exists.return_value = True
        token_data = ["not", "a", "dict"]

        with patch("builtins.open", mock_open(read_data=json.dumps(token_data))):
            token = load_token()
            self.assertIsNone(token)

if __name__ == "__main__":
    unittest.main()
