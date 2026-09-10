import unittest
from unittest.mock import patch
from data_curation.six_agent_research import page_mentions_metric, run_assignment, NO_METRIC_EVIDENCE


class PageScreeningTests(unittest.TestCase):
    def test_disclosure_after_navigation_is_not_skipped(self):
        pages = {'official': {'opened': True, 'official': True, 'text': 'Navigation ' * 300 + 'Total revenue 2026 $30 billion.'}}
        self.assertTrue(page_mentions_metric('收入', pages))
        self.assertFalse(page_mentions_metric('ARPU', pages))
        pages['official']['official'] = False
        self.assertFalse(page_mentions_metric('收入', pages))

    def test_resume_recovers_only_program_skipped_metrics_without_recrawl(self):
        task = {'key': 'test', 'title': 'test', 'purpose': 'test', 'companies': ['Verizon']}
        pages = {'official': {'opened': True, 'official': True, 'text': 'Navigation ' * 300 + 'revenue net income ARPU'}}
        checkpoint = {'reports': [{'company': 'Verizon', 'status': 'completed', 'metrics': ['收入', '净利润', 'ARPU'], 'pages': pages, 'items': [
            {'metric': '收入', 'status': 'missing', 'reason': NO_METRIC_EVIDENCE},
            {'metric': '净利润', 'status': 'missing', 'reason': 'Model found no applicable period'},
            {'metric': 'ARPU', 'status': 'no_update', 'reason': 'Already in baseline'},
        ]}]}
        def extract(company, metric, pages, save, **kwargs):
            save({'company': company, 'metric': metric, 'status': 'no_update', 'value': '', 'reason': 'Checked full disclosure'})
        with patch('data_curation.research_harness.ResearchHarness') as harness, patch('data_curation.research_plan.frontend_metric_plan', return_value={"international": ["收入", "净利润", "ARPU"]}), patch('data_curation.six_agent_research.collect_sources') as collect:
            harness.return_value.extract.side_effect = extract
            result = run_assignment(task, lambda *args: None, checkpoint=checkpoint, model_factory=lambda: object(), baseline={})
            self.assertEqual(harness.return_value.extract.call_count, 1)
            self.assertEqual(harness.return_value.extract.call_args.args[1], '收入')
            collect.assert_not_called()
            self.assertEqual(result['status'], 'completed')
            self.assertEqual(len(result['reports'][0]['items']), 3)
