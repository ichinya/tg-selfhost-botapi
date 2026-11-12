from pathlib import Path
import tempfile
import unittest
from check_docs import private_site_paths

ROOT=Path(__file__).resolve().parents[1]


class SecretDocs(unittest.TestCase):
    def test_nested_configs_and_dossiers_cannot_be_published(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            names=('docs/nginx-main.conf','docs/docker-compose.secrets.yml','logs/migration/raw.txt',
                   'docs/secrets/token','.issue-flow/report.json')
            for name in names:
                p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('synthetic')
            found={p.as_posix() for p in private_site_paths(root)}
            self.assertTrue(set(names)<=found)
            (root/'renamed.html').write_text('synthetic_publication_marker')
            self.assertIn(Path('renamed.html'),set(private_site_paths(root,['synthetic_publication_marker'])))
        config=(ROOT/'_config.yml').read_text()
        for name in ('docker-compose.secrets.yml','nginx-main.conf'):
            self.assertIn('  - '+name,config)

    def test_paired_examples_do_not_expand_token_in_child_argv(self):
        for language in ('en','ru'):
            for name in ('getting-started','migration'):
                text=(ROOT/'docs'/language/(name+'.md')).read_text(encoding='utf-8')
                self.assertNotIn('"$BOT_TOKEN"',text)
                self.assertNotIn('/bot$BOT_TOKEN/',text)
            self.assertIn('0400',(ROOT/'docs'/language/'configuration.md').read_text(encoding='utf-8'))
