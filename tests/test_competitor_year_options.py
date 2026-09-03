"""Execute the real JS selection helpers, without a server or AI requests."""
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class CompetitorYearOptionsTests(unittest.TestCase):
    def test_year_filter_and_all_history_gap_semantics(self):
        script = r'''
const fs = require('fs'), vm = require('vm'), assert = require('assert/strict');
const source = fs.readFileSync('web/static/workspace-tabs.js', 'utf8');
const helpers = source.slice(source.indexOf('  function competitorComparableWindow'), source.indexOf('  let competitorOptionsTransitionTimer'));
const ctx = vm.createContext({}); vm.runInContext(helpers, ctx);
const data = {companies:[{id:'A'},{id:'B'}], metrics:[{key:'m'}], cells:[], gaps:[]};
for (const company of ['A','B']) for (let year=2020; year<=2025; year++) {
  const row={company, metric:'m', year, unit:'%'};
  if(company==='B' && year<2023) data.gaps.push(row);
  else data.cells.push({...row,value:year});
}
const sel={companies:['A','B'], metric:'m', years:3};
assert.deepEqual([...ctx.visibleCompetitorYears(data,sel)], [3,99]);
assert.equal(ctx.competitorHasCompleteMetric(data,sel.companies,5,'m'),false);
assert.equal(ctx.competitorHasCompleteMetric(data,sel.companies,99,'m'),true);
const all=ctx.competitorComparableWindow(data,sel.companies,'m',99);
assert.deepEqual([...all.visibleYears],[2020,2021,2022,2023,2024,2025]);
assert.deepEqual([...all.sharedVisibleYears],[2023,2024,2025]);
assert.deepEqual([...ctx.visibleCompetitorYears(data,{companies:[],metric:''})],[3,5,10,99]);
assert.deepEqual([...ctx.visibleCompetitorYears({...data,cells:[]},sel)],[99]);
assert.equal(ctx.competitorHasCompleteMetric({...data,cells:[]},sel.companies,99,'m'),false);
data.cells[0].unit='USD';
assert.equal(ctx.competitorHasCompleteMetric(data,sel.companies,99,'m'),false);
assert.deepEqual([...ctx.visibleCompetitorYears(data,sel)],[99]);
console.log('year filtering, retained All, audited gaps, empty state and unit guard passed');
'''
        result = subprocess.run(["node", "-e", script], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_exit_motion_never_locks_all_controls(self):
        source = (ROOT / "web/static/workspace-tabs.js").read_text()
        self.assertIn('data-competitor-year="${years}"', source)
        self.assertIn('inert aria-hidden="true"', source)
        self.assertIn('window.clearTimeout(competitorOptionsTransitionTimer)', source)
        self.assertNotIn('panel.querySelectorAll("input,select,button").forEach', source)


if __name__ == "__main__":
    unittest.main()
