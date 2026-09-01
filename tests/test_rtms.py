import unittest
from datetime import date

from worldmodel_data.rtms import normalize_item, parse_xml_items, rolling_months


SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<response><header><resultCode>000</resultCode><resultMsg>OK</resultMsg></header>
<body><items><item><umdNm>신림동</umdNm><dealYear>2026</dealYear><dealMonth>8</dealMonth>
<dealDay>14</dealDay><deposit>1,000</deposit><monthlyRent>55</monthlyRent>
<excluUseAr>19.8</excluUseAr><floor>3</floor></item></items><totalCount>1</totalCount></body></response>"""


class RtmsTests(unittest.TestCase):
    def test_parses_and_normalizes_xml(self):
        items, total, _ = parse_xml_items(SAMPLE)
        self.assertEqual(total, 1)
        row = normalize_item("single_multi", items[0], "11620")
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row["deal_date"], "2026-08-14")
        self.assertEqual(row["deposit_manwon"], 1000)
        self.assertEqual(row["monthly_rent_manwon"], 55)
        self.assertEqual(row["lease_type"], "monthly")

    def test_rolling_months_crosses_year(self):
        self.assertEqual(rolling_months(3, date(2026, 1, 20)), ["202601", "202512", "202511"])

    def test_rejects_unbounded_month_count(self):
        with self.assertRaises(ValueError):
            rolling_months(0)
        with self.assertRaises(ValueError):
            rolling_months(61)


if __name__ == "__main__":
    unittest.main()
