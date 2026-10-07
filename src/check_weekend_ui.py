"""Render contracts and execution of the actual panel script with a small DOM fixture."""
import json
import re
import shutil
import subprocess
import unittest
from datetime import datetime
from html.parser import HTMLParser
from unittest.mock import patch
import publish_weekend_ui as ui
import weekend_personal_forecast as forecast


NOW = '2026-10-10T09:00:00+09:00'


def race():
    return dict(race_id='2026101005010101', venue='05', start_time='1000', runners=[
        dict(horse_id='2020000001', horse_number='1', horse_name='テスト馬', jockey_25=[.6, 1, 1]),
        dict(horse_id='2020000002', horse_number='2', horse_name='次の馬', jockey_25=[.4, 1, 1])])


def execute(personal, replay, later=None):
    node = shutil.which('node')
    if not node:
        raise unittest.SkipTest('Node unavailable; actual browser check remains required')
    rendered = ui.render(personal, replay)
    script = re.search(r'<script>(.*?)</script>', rendered, re.S).group(1)
    # Only DOM storage and clock are simulated; filtering/rendering executes production JS.
    fixture = r'''
const elements={};
function element(id){return elements[id]||(elements[id]={value:id==='pw-mode'?'personal':'',checked:false,disabled:false,textContent:'',_html:'',set innerHTML(s){this._html=s;if(['pw-day','pw-venue','pw-race'].includes(id)){const matches=[...s.matchAll(/<option value="([^"]*)"/g)].map(m=>m[1]);this.value=matches[0]||'';}},get innerHTML(){return this._html;}});}
global.document={getElementById:element};let tick;global.setInterval=f=>{tick=f;};
Date.now=()=>Date.parse(INITIAL_TIME);
eval(PANEL_SCRIPT);
function snapshot(){return {status:element('pw-status').textContent,table:element('pw-table').innerHTML,day:element('pw-day').value,venue:element('pw-venue').value,race:element('pw-race').value,resultDisabled:element('pw-result').disabled};}
const initial=snapshot();
element('pw-mode').value='replay';element('pw-mode').onchange();element('pw-result').checked=true;element('pw-result').onchange();const replayState=snapshot();
element('pw-mode').value='personal';element('pw-mode').onchange();
if(LATER_TIME){Date.now=()=>Date.parse(LATER_TIME);tick();}
process.stdout.write(JSON.stringify({initial,replay:replayState,later:snapshot()}));
'''
    program = 'const INITIAL_TIME='+json.dumps(NOW)+';const LATER_TIME='+json.dumps(later)+';const PANEL_SCRIPT='+json.dumps(script)+';\n'+fixture
    run = subprocess.run([node, '-'], input=program, text=True, capture_output=True, encoding='utf-8', timeout=10)
    if run.returncode:
        raise AssertionError(run.stderr)
    return json.loads(run.stdout)


class Tests(unittest.TestCase):
    def test_payload_cannot_close_script(self):
        card = race()
        malicious = '</script><script>alert("x")</script><img src=x onerror=alert(1)>'
        card['runners'][0]['horse_name'] = malicious
        personal = dict(captured_at=NOW, predictions=[card])
        rendered = ui.render(personal, dict(predictions=[]))
        class Parser(HTMLParser):
            scripts=0
            images=0
            def handle_starttag(self, tag, attrs):
                if tag == 'script': self.scripts += 1
                if tag == 'img': self.images += 1
        parser=Parser();parser.feed(rendered)
        self.assertEqual(parser.scripts, 1)
        self.assertEqual(parser.images, 0)
        result=execute(personal, dict(predictions=[]))
        self.assertIn('&lt;/script&gt;', result['initial']['table'])
        self.assertNotIn('<img', result['initial']['table'])

    def test_selection_and_result_mode(self):
        old = race();old['race_id']='2026100305010101';old['runners'][0]['finish_order']='1'
        result=execute(dict(captured_at=NOW,predictions=[race()]), dict(predictions=[old]))
        self.assertEqual(result['initial']['day'],'20261010')
        self.assertEqual(result['initial']['venue'],'05')
        self.assertIn('60.0%',result['initial']['table'])
        self.assertTrue(result['initial']['resultDisabled'])
        self.assertEqual(result['replay']['day'],'20261003')
        self.assertFalse(result['replay']['resultDisabled'])
        self.assertIn('確定着順',result['replay']['table'])

    def test_at_start_and_expired_capture_hidden(self):
        personal=dict(captured_at=NOW,predictions=[race()])
        result=execute(personal,dict(predictions=[]),later='2026-10-10T10:00:00+09:00')
        self.assertEqual(result['later']['race'],'')
        self.assertNotIn('60.0%',result['later']['table'])
        card=race();card['race_id']='2026101205010101'
        result=execute(dict(captured_at=NOW,predictions=[card]),dict(predictions=[]),later='2026-10-11T09:00:01+09:00')
        self.assertEqual(result['later']['race'],'')
        self.assertNotIn('60.0%',result['later']['table'])

    def test_invalid_or_future_capture_hidden(self):
        for captured in ('invalid','2026-10-10T09:00:01+09:00'):
            result=execute(dict(captured_at=captured,predictions=[race()]),dict(predictions=[]))
            self.assertEqual(result['initial']['race'],'')

    def test_empty_forecast_has_waiting_message(self):
        result=execute(dict(captured_at=NOW,predictions=[]),dict(predictions=[]))
        self.assertIn('0レース・0頭',result['initial']['status'])
        self.assertIn('確定出馬表の到着待ち',result['initial']['status'])

    def test_cancelled_forecast_remains_empty_in_panel(self):
        rid='2026101005010101'
        payload=dict(races=[dict(race_id=rid,venue='05',distance='1600',track='11',grade='',race_class='005',start_time='1000',registered='02',created='20261009')],
                     runners=[dict(race_id=rid,horse_id=f'202000000{i}',horse_number=str(i),jockey_id='01234',trainer_id='01234',created='20261009') for i in (1,2)],workouts=[])
        metadata=dict(runner_status=[dict(race_id=rid,horse_id=r['horse_id'],abnormal_code='1' if i==0 else '0') for i,r in enumerate(payload['runners'])])
        now=datetime.fromisoformat(NOW)
        with patch.object(forecast.f,'score_race',side_effect=AssertionError('Cancelled race must not score')):
            personal=forecast.predict(payload,now,now,dict(snapshot_through='20261009'),metadata)
        personal['captured_at']=NOW
        self.assertEqual(personal['state'],'input_checks_blocked')
        self.assertEqual(personal['predicted_races'],0)
        result=execute(personal,dict(predictions=[]))
        self.assertNotIn('60.0%',result['initial']['table'])
        self.assertEqual(result['initial']['race'],'')


if __name__=='__main__':
    unittest.main()
