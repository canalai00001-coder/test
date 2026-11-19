// ============================================================
// 入稿予定表（hitomane_agent が使うシート）のプルダウンを、その行で選んだ値に合わせて付け直す。
// ＜ヒトマネ/施策用＞の土台の onEdit と同じ動き：
//   職種・分類を選ぶ → 「職種名指定」をその職種（6重め/7軽めは分類。空欄なら4つ全部）の職種名にする
//   職種を選ぶ → 「職種名選択」（通常の作り方）をその職種の職種名にする
//   勤務地_都道府県を選ぶ → 「勤務地_市区町村」をその県の市区町村にする
// 候補は hitomane_agent が作る隠しシートの「<列名>｜<キー>」の列にある（plan.py の list_key と同じ決め方）。
// 選び直して候補から外れた値は消す（候補に残っている値はそのまま）。
// ============================================================
const HM_PLAN_SHEET_NAME = '入稿予定表';
const HM_PLAN_LIST_SHEET_NAME = '_入稿予定表_プルダウン（自動生成・編集不要）';
const HM_PLAN_HEAVY_LIGHT = ['6重め', '7軽め'];

function hmPlanHeaderName_(h) {
  return String(h || '').trim().split(/[\n(（]/)[0].trim();
}

function hmPlanListKey_(kind, cat, bunrui, pref) {
  const heavy = HM_PLAN_HEAVY_LIGHT.indexOf(cat) >= 0;
  if (kind === '職種名指定' && cat) return heavy ? `${kind}｜${cat}｜${bunrui || '4つ全部'}` : `${kind}｜${cat}`;
  if (kind === '職種名選択' && cat) return `${kind}｜${cat}`;
  if (kind === '勤務地_市区町村' && pref) return `${kind}｜${pref}`;
  return '';
}

// 入稿予定表の編集なら処理して true を返す（onEdit から最初に呼ぶ）
function hmPlanOnEdit_(e) {
  const range = e.range;
  const sheet = range.getSheet();
  if (sheet.getName() !== HM_PLAN_SHEET_NAME) return false;

  const head = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0].map(hmPlanHeaderName_);
  const col = name => head.indexOf(name) + 1;  // 無ければ 0
  const c = { cat: col('職種'), bunrui: col('分類'), pref: col('勤務地_都道府県'),
              spec: col('職種名指定'), choice: col('職種名選択'), city: col('勤務地_市区町村') };
  const c0 = range.getColumn();
  const c1 = c0 + range.getNumColumns() - 1;
  const touches = x => x > 0 && c0 <= x && x <= c1;
  const targets = [];
  if (touches(c.cat) || touches(c.bunrui)) targets.push(['職種名指定', c.spec]);
  if (touches(c.cat)) targets.push(['職種名選択', c.choice]);
  if (touches(c.pref)) targets.push(['勤務地_市区町村', c.city]);
  const work = targets.filter(t => t[1] > 0);
  if (!work.length) return true;

  const r0 = Math.max(range.getRow(), 2);
  const r1 = range.getRow() + range.getNumRows() - 1;
  if (r1 < r0) return true;

  const list = e.source.getSheetByName(HM_PLAN_LIST_SHEET_NAME);
  const listHead = list ? list.getRange(1, 1, 1, list.getLastColumn()).getValues()[0].map(String) : [];
  const listRows = list ? Math.max(list.getLastRow() - 1, 1) : 0;
  const cache = {};
  const options = key => {  // [範囲, 値の一覧] か null
    if (!key || !list) return null;
    if (key in cache) return cache[key];
    const i = listHead.indexOf(key);
    let found = null;
    if (i >= 0) {
      const vals = list.getRange(2, i + 1, listRows, 1).getValues().map(r => String(r[0]));
      let n = 0;
      while (n < vals.length && vals[n] !== '') n++;
      if (n) found = [list.getRange(2, i + 1, n, 1), vals.slice(0, n)];
    }
    cache[key] = found;
    return found;
  };
  const value = (r, cc) => (cc > 0 ? String(sheet.getRange(r, cc).getValue() || '').trim() : '');

  for (let r = r0; r <= r1; r++) {
    const cat = value(r, c.cat), bunrui = value(r, c.bunrui), pref = value(r, c.pref);
    work.forEach(([kind, cc]) => {
      const cell = sheet.getRange(r, cc);
      const opt = options(hmPlanListKey_(kind, cat, bunrui, pref));
      const now = String(cell.getValue() || '').trim();
      if (now && (!opt || opt[1].indexOf(now) < 0)) cell.clearContent();
      if (!opt) { cell.clearDataValidations(); return; }
      cell.setDataValidation(SpreadsheetApp.newDataValidation().requireValueInRange(opt[0], true).build());
    });
  }
  return true;
}
