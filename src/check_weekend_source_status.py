import unittest
from datetime import datetime
from weekend_source_status import date_window, statement, summarize, TABLES

class SourceTests(unittest.TestCase):
    def test_year_boundary(self):
        self.assertEqual(date_window(datetime(2026, 12, 28)), ('20261228', '20270111'))

    def test_special_never_substitutes(self):
        tables = {name: [] for name in TABLES}
        tables['tokubetsu_torokubagoto_joho'] = [{'day': '20261010', 'rows': 92, 'races': 6}]
        result = summarize(tables, '20261007', '20261021')
        self.assertEqual(result['confirmed_runner_rows'], 0)
        self.assertEqual(result['special_registration_rows'], 92)
        self.assertEqual(result['state'], 'awaiting_confirmed_race_cards')

    def test_table_whitelist(self):
        with self.assertRaises(ValueError):
            statement('anything; DROP DATABASE x', 2026)

if __name__ == '__main__':
    unittest.main()
