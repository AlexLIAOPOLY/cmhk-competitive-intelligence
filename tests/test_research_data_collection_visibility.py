from pathlib import Path
import json
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('node'), 'Node.js required for diagram behavior tests')
class ResearchDataCollectionVisibilityTests(unittest.TestCase):
    def render(self, incremental=True, state='completed', items=None, publication=None, accepted=None):
        items = items if items is not None else [{'metric': 'Revenue', 'status': 'missing'}]
        accepted = sum(item.get('status') == 'verified' for item in items) if accepted is None else accepted
        snapshot = {'date': '2026-09-07', 'plan': [{'key': 'asia', 'title': '亚太运营商研究 Agent', 'companies': ['Singtel'], 'purpose': '任务'}],
                    'run': {'status': state, 'tasks': len(items), 'accepted': accepted, 'publication': publication or {}},
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
        self.assertEqual(node['unit'], '新增数据未统计')
        self.assertEqual(node['health']['label'], '历史记录')
        self.assertIn('不代表原库缺失', result['detail'])
        self.assertNotIn('条数据已收集', result['detail'])

    def test_no_new_disclosures_is_success_and_preserves_database_and_page(self):
        result = self.render(publication={'status': 'completed', 'database_updated': False, 'insights': 0, 'result_status': 'no_new_disclosures'})
        node = next(n for n in result['nodes'] if n['key'] == 'research-asia')
        self.assertEqual(node['value'], 0)
        self.assertEqual(node['health'], {'key': 'warning', 'label': '已完成·含失败项'})
        self.assertIn('执行失败 1 项', node['note'])
        self.assertIn('无新增·沿用页面', str(result['nodes']))
        self.assertNotIn('历史核对通过', result['detail'])

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
        self.assertEqual(node['unit'], '项研究通过·待终审')
        self.assertIn('库内已有 1 项', node['note'])
        self.assertIn('本Agent指标与判断', result['detail'])
        self.assertLess(result['detail'].index('research-decisions'), result['detail'].index('这个节点如何处理'))

    def test_database_update_separates_reviewed_main_table_and_visible_changes(self):
        publication = {
            'status': 'completed',
            'database_updated': True,
            'domains': {'mainland': {'daily_main_database_promotion': {'added_rows': 4, 'upgraded_rows': 0}}},
            'changes': {'baseline_available': True, 'changed': 0, 'added': 0, 'removed': 0},
        }
        result = self.render(items=[{'metric': 'Revenue', 'status': 'verified'}], publication=publication)
        update = next(n for n in result['nodes'] if n['key'] == 'research-update')
        self.assertEqual(update['unit'], '项已入库')
        self.assertEqual(update['value'], '—')
        self.assertNotEqual(update['health']['key'], 'healthy')
        self.assertIn('尚未执行正式表回读', update['note'])
        self.assertIn('本轮提交 1 项', update['note'])
        self.assertNotIn('主表新增 4 行', update['note'])

    def test_final_review_card_leads_with_new_update_count(self):
        result = self.render(items=[{'metric': 'Revenue', 'status': 'verified'}])
        review = next(n for n in result['nodes'] if n['key'] == 'research-merge')
        self.assertEqual(review['value'], 1)
        self.assertEqual(review['unit'], '项可入库')

    def test_research_asset_cache_version_is_bumped(self):
        self.assertIn('/static/research-diagram.js?v=32', (ROOT / 'web/static/index.html').read_text())

    def test_saved_materials_explain_all_destinations_and_tooltip_explains_role(self):
        receipts = [{'readback_verified': True, 'main_table': {'status': state}}
                    for state, count in [('saved', 8), ('existing_preserved', 1), ('source_fact_only', 25)]
                    for _ in range(count)]
        check = {'confirmed': 34, 'accepted': 34, 'missing': 0, 'ok': True, 'items': receipts}
        result = self.render(accepted=34, publication={'status': 'completed', 'storage_readback': check})
        update = next(n for n in result['nodes'] if n['key'] == 'research-update')
        self.assertEqual(update['value'], 8)
        self.assertEqual(update['note'], '本轮提交 34 项：已入库 8 项；未入库 26 项')
        self.assertEqual(update['health']['key'], 'critical')
        for node in result['nodes']:
            self.assertNotEqual(node['purpose'], node['note'])
        self.assertIn('写入正式指标表', update['purpose'])
        self.assertIn('实际表格、字段、数值及原因', update['purpose'])
        self.assertNotIn('34', update['purpose'])

    def test_missing_materials_are_not_counted_as_saved_reference_materials(self):
        check = {'confirmed': 1, 'accepted': 3, 'missing': 2, 'main_missing': 1, 'ok': False,
                 'items': [{'readback_verified': True, 'main_table': {'status': 'missing'}},
                           {'readback_verified': False, 'main_table': {'status': 'source_fact_only'}},
                           {'readback_verified': False, 'main_table': {'status': 'saved'}}]}
        result = self.render(accepted=3, publication={'status': 'completed', 'storage_readback': check})
        update = next(n for n in result['nodes'] if n['key'] == 'research-update')
        self.assertEqual(update['value'], 1)
        self.assertIn('未入库 2 项', update['note'])
        self.assertNotIn('仅保存为资料', update['note'])

    def test_missing_destination_receipts_are_not_inferred_as_reference_materials(self):
        check = {'confirmed': 34, 'accepted': 34, 'missing': 0, 'ok': True, 'items': []}
        result = self.render(accepted=34, publication={'status': 'completed', 'storage_readback': check})
        update = next(n for n in result['nodes'] if n['key'] == 'research-update')
        self.assertIn('未入库 34 项', update['note'])
        self.assertEqual(update['health']['key'], 'critical')
        self.assertNotIn('34 项仅保存为资料', update['note'])

    def test_current_readback_overrides_archived_completion(self):
        for complete in [True, False]:
            check = {'confirmed': 1 if complete else 0, 'accepted': 1, 'missing': 0 if complete else 1, 'ok': complete, 'items': []}
            check['items'] = [{'status': 'written' if complete else 'not_written', 'main_table': {'status': 'written' if complete else 'not_written'}}]
            result = self.render(items=[{'status': 'verified'}], publication={'status': 'completed', 'database_updated': True, 'storage_readback': check})
            update = next(n for n in result['nodes'] if n['key'] == 'research-update')
            self.assertEqual(update['value'], check['confirmed'])
            self.assertEqual(update['health']['key'], 'healthy' if complete else 'critical')


if __name__ == '__main__':
    unittest.main()
