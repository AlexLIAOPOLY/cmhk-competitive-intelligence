from pathlib import Path
import json
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('node'), 'Node.js required for diagram behavior tests')
class ResearchDataCollectionVisibilityTests(unittest.TestCase):
    def render(self, incremental=True, state='completed', items=None, publication=None):
        items = items if items is not None else [{'metric': 'Revenue', 'status': 'missing'}]
        snapshot = {'date': '2026-09-07', 'plan': [{'key': 'asia', 'title': '亚太运营商研究 Agent', 'companies': ['Singtel'], 'purpose': '任务'}],
                    'run': {'status': state, 'tasks': len(items), 'accepted': 0, 'publication': publication or {}},
                    'agents': [{'key': 'asia', 'status': state, 'reports': [{'company': 'Singtel', 'status': state, 'metrics': ['Revenue'], 'items': items}]}]}
        if incremental:
            snapshot['run']['research_policy'] = 'latest_disclosure_incremental_v1'
        script = '''const fs=require('fs');global.window={};eval(fs.readFileSync('web/static/research-diagram.js','utf8'));
const s=JSON.parse(process.argv[1]);const m=window.CmhkResearchDiagram.build({nodes:[],edges:[]},s,s.date);
console.log(JSON.stringify({nodes:m.nodes,detail:window.CmhkResearchDiagram.detail(m.nodes.find(n=>n.key==='research-asia'),s,s.date)}));'''
        return json.loads(subprocess.check_output(['node', '-e', script, json.dumps(snapshot)], cwd=ROOT, text=True))

    def test_historical_zero_coverage_is_not_zero_new_disclosures_or_a_database_gap(self):
        result = self.render(incremental=False)
        node = next(n for n in result['nodes'] if n['key'] == 'research-asia')
        self.assertEqual(node['value'], '—')
        self.assertEqual(node['unit'], '新增披露未统计')
        self.assertEqual(node['health']['label'], '历史记录')
        self.assertIn('不代表原库缺失', result['detail'])
        self.assertNotIn('条数据已收集', result['detail'])

    def test_no_new_disclosures_is_success_and_preserves_database_and_page(self):
        result = self.render(publication={'status': 'completed', 'database_updated': False, 'insights': 0, 'result_status': 'no_new_disclosures'})
        node = next(n for n in result['nodes'] if n['key'] == 'research-asia')
        self.assertEqual(node['value'], 0)
        self.assertEqual(node['health'], {'key': 'healthy', 'label': '最新披露搜索完成'})
        self.assertIn('未发现更新 1 项', node['note'])
        self.assertIn('无新增·沿用页面', str(result['nodes']))
        self.assertNotIn('历史核验通过', result['detail'])

    def test_pending_search_has_no_fake_zero(self):
        result = self.render(state='pending', items=[])
        node = next(n for n in result['nodes'] if n['key'] == 'research-asia')
        self.assertEqual(node['health']['key'], 'unknown')
        # A saved empty pending report is not a completed search.
        self.assertEqual(node['value'], '—')

    def test_error_and_conflict_are_not_silently_no_update(self):
        for status, health in [('error', 'critical'), ('conflict', 'warning')]:
            with self.subTest(status=status):
                result = self.render(items=[{'metric': 'Revenue', 'status': status}])
                node = next(n for n in result['nodes'] if n['key'] == 'research-asia')
                self.assertEqual(node['health']['key'], health)

    def test_new_values_and_existing_values_are_separate(self):
        result = self.render(items=[{'metric': 'Revenue', 'status': 'verified'}, {'metric': 'EBITDA', 'status': 'no_update'}])
        node = next(n for n in result['nodes'] if n['key'] == 'research-asia')
        self.assertEqual(node['value'], 1)
        self.assertEqual(node['unit'], '条可更新新数据')
        self.assertIn('库内已有 1 项', node['note'])
        self.assertIn('最新披露搜索结果', result['detail'])
        self.assertLess(result['detail'].index('本节点逐条明细'), result['detail'].index('这个节点如何处理'))

    def test_research_asset_cache_version_is_bumped(self):
        self.assertIn('/static/research-diagram.js?v=13', (ROOT / 'web/static/index.html').read_text())


if __name__ == '__main__':
    unittest.main()
