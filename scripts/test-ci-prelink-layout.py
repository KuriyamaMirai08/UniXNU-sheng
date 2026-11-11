"""Exercise occupied DATA prefixes and insufficient capacity in the real allocator."""
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

root = Path(os.environ.get('UNIXNU_ROOT', Path(__file__).resolve().parents[2] / 'UniXNU'))
sys.path.insert(0, str(root / 'kits/XnuPrelink'))
from fileset_layout import Layout


class DataPlacement(unittest.TestCase):
    def layout(self, occupied):
        obj = Layout.__new__(Layout)
        obj.roots = {'__DATA': {'va': 0x10000, 'size': 0x40000}}
        obj.occupied = occupied
        return obj

    def test_retained_prefix_moves_native_data_to_free_pages(self):
        obj = self.layout([(0x10000, 0x18000), (0x30000, 0x34000)])
        self.assertEqual(obj.hole('__DATA', 0x10000), 0x18000)

    def test_fragmented_space_cannot_silently_cross_retained_data(self):
        obj = self.layout([(0x18000, 0x24000), (0x30000, 0x48000)])
        with self.assertRaisesRegex(ValueError, 'No room'):
            obj.hole('__DATA', 0x10000)

    def test_insufficient_total_capacity_is_still_rejected(self):
        with self.assertRaisesRegex(ValueError, 'No room'):
            self.layout([]).hole('__DATA', 0x44000)


if __name__ == '__main__':
    unittest.main()
