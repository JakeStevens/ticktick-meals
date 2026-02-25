import sys
from unittest.mock import MagicMock
import unittest

# Mock missing dependencies before importing app
sys.modules["flask"] = MagicMock()
sys.modules["requests"] = MagicMock()
sys.modules["recipe_scrapers"] = MagicMock()
sys.modules["dotenv"] = MagicMock()
sys.modules["openai"] = MagicMock()
sys.modules["database"] = MagicMock()

from app import URL_PATTERN

class TestURLPattern(unittest.TestCase):
    def test_url_matching(self):
        """Test that URL_PATTERN matches various URL formats and excludes trailing punctuation."""
        test_cases = [
            ("http://example.com", ["http://example.com"]),
            ("https://example.com/path?query=1#frag", ["https://example.com/path?query=1#frag"]),
            ("Check out http://example.com!", ["http://example.com"]),
            ("Check out http://example.com?", ["http://example.com"]),
            ("Check out http://example.com.", ["http://example.com"]),
            ("Check out http://example.com,", ["http://example.com"]),
            ("Check out http://example.com:", ["http://example.com"]),
            ("Check out http://example.com;", ["http://example.com"]),
            ("(https://example.com)", ["https://example.com"]),
            ("[https://example.com]", ["https://example.com"]),
            ("<https://example.com>", ["https://example.com"]),
            ("Markdown [link](https://example.com)", ["https://example.com"]),
            ("Multiple http://a.com, and http://b.com!", ["http://a.com", "http://b.com"]),
        ]

        for text, expected in test_cases:
            with self.subTest(text=text):
                matches = URL_PATTERN.findall(text)
                self.assertEqual(matches, expected)

    def test_url_stripping_logic(self):
        """Test the stripping logic used in app.py as an extra safety measure."""
        # Stripping characters used in app.py: ').,!? :;'
        strip_chars = ').,!? :;'

        test_cases = [
            ("http://example.com.", "http://example.com"),
            ("http://example.com,", "http://example.com"),
            ("http://example.com!", "http://example.com"),
            ("http://example.com?", "http://example.com"),
            ("http://example.com)", "http://example.com"),
            ("http://example.com ", "http://example.com"),
            ("http://example.com:", "http://example.com"),
            ("http://example.com;", "http://example.com"),
        ]

        for raw_url, expected in test_cases:
            with self.subTest(raw_url=raw_url):
                self.assertEqual(raw_url.strip(strip_chars), expected)

if __name__ == "__main__":
    unittest.main()
