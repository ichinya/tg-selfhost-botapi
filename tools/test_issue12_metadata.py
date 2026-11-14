import unittest
from release_metadata import parse_installed, validate_packages


class InventoryTests(unittest.TestCase):
    def test_inventory_and_architecture(self):
        packages = parse_installed('P:zlib\nV:1.3.1-r2\nA:x86_64\no:zlib\n\nP:base\nV:1-r0\nA:noarch\n')
        self.assertEqual(packages[1]['version'], '1.3.1-r2')
        validate_packages(packages, {'zlib'}, 'x86_64')
        with self.assertRaises(ValueError):
            validate_packages(packages, {'zlib'}, 'aarch64')
        with self.assertRaises(ValueError):
            validate_packages(packages, {'absent'}, 'x86_64')

    def test_rejects_bad_inventory(self):
        for text in ('', 'P:x\nV:1\nA:x86_64', 'P:x\nV:1-r0',
                     'P:x\nV:1-r0\nA:x86_64\n\nP:x\nV:1-r0\nA:x86_64', 'bad'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_installed(text)


if __name__ == '__main__':
    unittest.main()
