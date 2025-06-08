import unittest
import json
import os
from config_loader import load_config

class TestConfigLoader(unittest.TestCase):

    def setUp(self):
        # Create a temporary valid config file
        self.valid_config_path = 'temp_valid_config.json'
        self.valid_config_data = {
            "key": "value",
            "number": 123,
            "nested": {"subkey": "subvalue"}
        }
        with open(self.valid_config_path, 'w') as f:
            json.dump(self.valid_config_data, f)

        # Create a temporary invalid config file (bad JSON)
        self.invalid_json_path = 'temp_invalid_json.json'
        with open(self.invalid_json_path, 'w') as f:
            f.write("{'key': 'value',") # Missing closing brace and uses single quotes

        # Path for a non-existent file
        self.non_existent_path = 'non_existent_config.json'

    def tearDown(self):
        # Clean up temporary files
        if os.path.exists(self.valid_config_path):
            os.remove(self.valid_config_path)
        if os.path.exists(self.invalid_json_path):
            os.remove(self.invalid_json_path)

    def test_load_valid_config(self):
        """Test loading a valid JSON configuration file."""
        config = load_config(self.valid_config_path)
        self.assertIsNotNone(config)
        self.assertEqual(config, self.valid_config_data)

    def test_load_non_existent_config(self):
        """Test loading a non-existent configuration file."""
        # Suppress print output for this test
        import sys
        from io import StringIO
        saved_stdout = sys.stdout
        try:
            sys.stdout = StringIO()
            config = load_config(self.non_existent_path)
            self.assertIsNone(config)
        finally:
            sys.stdout = saved_stdout

    def test_load_invalid_json_config(self):
        """Test loading a configuration file with invalid JSON."""
        # Suppress print output for this test
        import sys
        from io import StringIO
        saved_stdout = sys.stdout
        try:
            sys.stdout = StringIO()
            config = load_config(self.invalid_json_path)
            self.assertIsNone(config)
        finally:
            sys.stdout = saved_stdout

if __name__ == '__main__':
    unittest.main()
