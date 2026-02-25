import unittest
from unittest.mock import patch, MagicMock
import json
import app
import database

class TestAggregation(unittest.TestCase):
    def test_process_tasks_instances_structure(self):
        # Setup dummy tasks
        tasks = [
            {"id": "t1", "title": "Pasta", "content": "http://example.com/pasta", "desc": ""}
        ]

        # Mock dependencies
        with patch('app.scrape_me') as mock_scrape, \
             patch('database.log_event') as mock_log:

            # Mock scraper to return ingredients
            mock_scraper = MagicMock()
            mock_scraper.ingredients.return_value = ["1 cup flour"]
            mock_scraper.title.return_value = "Pasta Recipe"
            mock_scrape.return_value = mock_scraper

            # Run process_tasks
            generator = app.process_tasks(tasks, "session_123")

            # Consume generator
            results = []
            for chunk in generator:
                if chunk.startswith("data: "):
                    data = json.loads(chunk[6:])
                    if 'ingredients' in data:
                        results = data['ingredients']

            # Verify structure
            self.assertTrue(len(results) > 0)
            first_group = results[0]

            # Check for 'instances' key
            self.assertIn('instances', first_group)
            self.assertIsInstance(first_group['instances'], list)

            # Check instance content
            instance = first_group['instances'][0]
            self.assertIn('raw', instance)
            self.assertEqual(instance['raw'], "1 cup flour")
            self.assertIn('quantity', instance)
            self.assertEqual(instance['quantity'], "1")
            self.assertIn('unit', instance)
            self.assertEqual(instance['unit'], "cup")
            self.assertIn('source', instance)
            self.assertEqual(instance['source'], "Pasta Recipe")

            # Verify old keys are gone (optional, but good practice if we want strict cleanup)
            self.assertNotIn('amounts', first_group)
            self.assertNotIn('details', first_group)
            self.assertNotIn('raw_lines', first_group)

if __name__ == '__main__':
    unittest.main()
