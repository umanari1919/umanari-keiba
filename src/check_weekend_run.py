import unittest
from weekend_run import summarize
class Tests(unittest.TestCase):
    def test_empty_is_waiting_not_forecast(self):
        self.assertEqual(summarize({},dict(predicted_races=0))['state'],'awaiting_entries')
    def test_forecasts_never_promote_research(self):
        r=summarize({},dict(predicted_races=1,predicted_runners=12));self.assertEqual(r['state'],'predictions_saved');self.assertFalse(r['production_promotion'])
if __name__=='__main__':unittest.main()
