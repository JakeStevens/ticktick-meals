import unittest
from unittest.mock import patch
import runpy
import sys
import os

class TestDebugMode(unittest.TestCase):
    def test_debug_mode_default_false(self):
        """Test that debug mode is False by default when FLASK_DEBUG is not set."""
        with patch('flask.Flask.run') as mock_run:
            # Ensure FLASK_DEBUG is not set
            with patch.dict(os.environ, {}, clear=True):
                # Set necessary env vars for app to import successfully
                os.environ['TICKTICK_CLIENT_ID'] = 'test_id'
                os.environ['TICKTICK_CLIENT_SECRET'] = 'test_secret'
                os.environ['LLM_HOST'] = 'http://localhost:11434'

                # Run app.py
                runpy.run_path("app.py", run_name="__main__")

                # Check call args
                args, kwargs = mock_run.call_args
                self.assertFalse(kwargs.get('debug'), "Debug mode should be False by default")

    def test_debug_mode_enabled(self):
        """Test that debug mode is True when FLASK_DEBUG is set to true."""
        with patch('flask.Flask.run') as mock_run:
            with patch.dict(os.environ, {'FLASK_DEBUG': 'true'}, clear=True):
                # Set necessary env vars for app to import successfully
                os.environ['TICKTICK_CLIENT_ID'] = 'test_id'
                os.environ['TICKTICK_CLIENT_SECRET'] = 'test_secret'
                os.environ['LLM_HOST'] = 'http://localhost:11434'

                # Run app.py
                runpy.run_path("app.py", run_name="__main__")

                # Check call args
                args, kwargs = mock_run.call_args
                self.assertTrue(kwargs.get('debug'), "Debug mode should be True when FLASK_DEBUG=true")

if __name__ == '__main__':
    unittest.main()
