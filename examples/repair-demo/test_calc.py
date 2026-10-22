import unittest
from calc import add


class AdditionTests(unittest.TestCase):
    def test_positive(self):
        self.assertEqual(add(2, 3), 5)

    def test_negative(self):
        self.assertEqual(add(-4, -2), -6)

    def test_identity(self):
        self.assertEqual(add(9, 0), 9)
