from pathlib import Path
import unittest
from image_inputs import recipe_files
class ProfilesTests(unittest.TestCase):
    def test_all_published_profile_clients_belong_to_recipe(self):
        files=recipe_files()
        for path in ('examples/files/local_reader.py','examples/files/remote_client.py','examples/files/compose.local.yml','examples/files/nginx.downloads.conf'):
            self.assertIn(path,files)
    def test_remote_client_uses_file_id_and_verified_transport(self):
        text=(Path(__file__).resolve().parents[1]/'examples/files/remote_client.py').read_text()
        self.assertIn('file_id',text)
        self.assertNotIn('_create_unverified_context',text)
