/**
 * 入稿予定表の入力補助（qmate_agent 用）。
 *
 * 実行設定シートに手で入力したときと同じ補助を、入稿予定表でも行う。
 *   - 職種名選択：6重め・7軽めのときだけ、その職種の職種名のプルダウンにする。
 *                 同じ会社で30日以内に使った職種名はプルダウンから外し、選んだときは重複警告を出す。
 *   - スタンバイキーワード：通勤／入寮それぞれの土台にある候補のプルダウンにする。
 *   - 会社・職種・通勤/入寮を変えたら、職種名選択を消して選び直してもらう。
 * 通勤の行は通勤用の土台、入寮の行は入寮用の土台（職種名・候補・使用履歴）を見る。
 *
 * 既存のコード（Code.gs）は変更せず、このファイルを同じ Apps Script プロジェクトに追加する。
 * 【設定方法】
 *   1. 左の「ファイル」の＋ →「スクリプト」で plan_sheet_helper という名前のファイルを作り、この内容を貼り付けて保存
 *   2. 上の関数選択で setupQmatePlanHelper を選んで「実行」→ 権限を許可
 *      （入稿予定表を編集したときに動く設定を作り、今入っている行にもプルダウンを付ける）
 */

const QMATE_PLAN_SHEET_NAME = '入稿予定表';
const QMATE_PLAN_BASE_IDS = {
  '通勤': '1ZfuZBafA0G1WPhpm_-7VnEdTF4mbiZkX0U-EQ09w0zY', // ＜土台＞Q-mate 求人原稿自動生成
  '入寮': '1PDeksvTvzx6LqDC7nCz5fk4IX8Ssi3cKsRDYdVCTbdI', // ＜土台/入寮用＞Q-mate 求人原稿自動生成
};
const QMATE_PLAN_USAGE_SHEET = 'アカウント×職種名_使用履歴';
const QMATE_PLAN_COOLDOWN_DAYS = 30; // 生成側（Code.gs の COOLDOWN_DAYS）と同じ日数

function setupQmatePlanHelper() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  ScriptApp.getProjectTriggers().forEach(t => {
    if (t.getHandlerFunction() === 'qmatePlanOnEdit') ScriptApp.deleteTrigger(t);
  });
  // 土台を開く必要があるため、普通の onEdit ではなく「インストール型」の編集時トリガーにする
  ScriptApp.newTrigger('qmatePlanOnEdit').forSpreadsheet(ss).onEdit().create();

  const sh = ss.getSheetByName(QMATE_PLAN_SHEET_NAME);
  const cols = qmatePlanColumns_(sh);
  for (let r = 2; r <= sh.getLastRow(); r++) qmatePlanRefreshRow_(sh, cols, r, false);
  ss.toast('入稿予定表の入力補助を設定しました', 'Q-mate', 5);
}

function qmatePlanOnEdit(e) {
  try {
    const sh = e.range.getSheet();
    if (sh.getName() !== QMATE_PLAN_SHEET_NAME) return;
    const cols = qmatePlanColumns_(sh);
    const c1 = e.range.getColumn();
    const c2 = c1 + e.range.getNumColumns() - 1;
    const touches = c => !!c && c1 <= c && c <= c2;
    const keyChanged = touches(cols['会社']) || touches(cols['職種']) || touches(cols['通勤/入寮']);
    const titleChanged = touches(cols['職種名選択']);
    if (!keyChanged && !titleChanged) return;

    const r1 = Math.max(e.range.getRow(), 2);
    const r2 = e.range.getRow() + e.range.getNumRows() - 1;
    for (let r = r1; r <= r2; r++) {
      if (keyChanged) qmatePlanRefreshRow_(sh, cols, r, true);
      else qmatePlanWarnIfRecentlyUsed_(sh, cols, r);
    }
  } catch (err) {
    Logger.log('qmatePlanOnEdit: ' + err.message);
  }
}

// 見出し「職種名選択\n(6重め/7軽めのみ・必須)」のような補足を除いた名前 → 列番号
function qmatePlanColumns_(sh) {
  const head = sh.getRange(1, 1, 1, sh.getLastColumn()).getValues()[0];
  const cols = {};
  head.forEach((h, i) => {
    const name = String(h).trim().split('\n')[0].split(/[（(]/)[0].trim();
    if (name && !cols[name]) cols[name] = i + 1;
  });
  return cols;
}

function qmatePlanRow_(sh, cols, r) {
  const v = name => cols[name] ? String(sh.getRange(r, cols[name]).getValue() || '').trim() : '';
  return {
    company: v('会社'),
    category: v('職種'),
    commute: v('通勤/入寮') === '入寮' ? '入寮' : '通勤',
    title: v('職種名選択'),
  };
}

// 1行分のプルダウンを付け直す。clearTitle が true なら選んであった職種名を消す（会社・職種・通勤/入寮を変えたとき）
function qmatePlanRefreshRow_(sh, cols, r, clearTitle) {
  const row = qmatePlanRow_(sh, cols, r);
  const titleCell = cols['職種名選択'] ? sh.getRange(r, cols['職種名選択']) : null;
  if (!row.company && !row.category) {
    if (titleCell && clearTitle) titleCell.clearContent().clearDataValidations();
    return;
  }
  const base = SpreadsheetApp.openById(QMATE_PLAN_BASE_IDS[row.commute]);

  if (cols['スタンバイキーワード']) {
    const keywords = qmatePlanStandbyKeywords_(base, row.commute);
    const cell = sh.getRange(r, cols['スタンバイキーワード']);
    if (keywords.length) {
      cell.setDataValidation(SpreadsheetApp.newDataValidation()
        .requireValueInList(keywords, true).setAllowInvalid(true).build());
    }
  }

  if (!titleCell) return;
  const m = row.category.match(/^\d+(重め|軽め)$/);
  if (clearTitle) titleCell.clearContent();
  if (!m) {
    titleCell.clearDataValidations();
    return;
  }
  let titles = qmatePlanPairedTitles_(base, m[1]);
  if (row.company) {
    const used = qmatePlanLastUsed_(base, row.company, row.category);
    const fresh = titles.filter(t => !qmatePlanIsRecent_(used[t]));
    // 全部使用済みのときは、プルダウンが空になるより全件を出す（選ぶと重複警告が出る）
    if (fresh.length) titles = fresh;
  }
  if (!titles.length) {
    titleCell.clearDataValidations();
    return;
  }
  titleCell.setDataValidation(SpreadsheetApp.newDataValidation()
    .requireValueInList(titles, true).setAllowInvalid(true).build());
}

function qmatePlanWarnIfRecentlyUsed_(sh, cols, r) {
  const row = qmatePlanRow_(sh, cols, r);
  if (!row.company || !row.category || !row.title) return;
  const title = row.title.indexOf('｜') >= 0 ? row.title.slice(row.title.indexOf('｜') + 1) : row.title;
  const base = SpreadsheetApp.openById(QMATE_PLAN_BASE_IDS[row.commute]);
  const lastUsed = qmatePlanLastUsed_(base, row.company, row.category)[title];
  if (!qmatePlanIsRecent_(lastUsed)) return;
  const days = Math.floor((new Date() - lastUsed) / 86400000);
  const msg = `${title} は ${row.company} で${days}日前に使っています（${QMATE_PLAN_COOLDOWN_DAYS}日以内）。` +
    'このままだと実行日に生成がエラーになります。別の職種名を選んでください。';
  try {
    SpreadsheetApp.getUi().alert('重複警告', msg, SpreadsheetApp.getUi().ButtonSet.OK);
  } catch (err) {
    SpreadsheetApp.getActiveSpreadsheet().toast(msg, '重複警告', 10);
  }
}

// 6重め・7軽めのシート（A列=職種名）から職種名の一覧を読む
function qmatePlanPairedTitles_(base, kind) {
  const re = new RegExp(`^\\d+${kind}$`);
  const sh = base.getSheets().find(s => re.test(s.getName()));
  if (!sh || sh.getLastRow() < 2) return [];
  const top = sh.getRange(1, 1, Math.min(6, sh.getLastRow()), Math.min(sh.getLastColumn(), 30)).getValues();
  let headerRow = 1;
  for (let i = 0; i < top.length; i++) {
    if (top[i].some(v => String(v).indexOf('職種名') >= 0)) { headerRow = i + 1; break; }
  }
  if (sh.getLastRow() <= headerRow) return [];
  const vals = sh.getRange(headerRow + 1, 1, sh.getLastRow() - headerRow, 1).getValues();
  const seen = {};
  const titles = [];
  vals.forEach(v => {
    const t = String(v[0] || '').trim();
    if (t && !seen[t]) { seen[t] = true; titles.push(t); }
  });
  return titles;
}

// スタンバイキーワードの候補。入寮用は「スタンバイタイトル」シートのA列、通勤用は「タイトル」シートのB列
// （それぞれの GAS が実行設定のプルダウンに使っているのと同じ候補）
function qmatePlanStandbyKeywords_(base, commute) {
  const seen = {};
  const list = [];
  const add = v => {
    const k = String(v || '').replace(/^＜/, '').replace(/＞$/, '').trim();
    if (k && !seen[k]) { seen[k] = true; list.push(k); }
  };
  if (commute === '入寮') {
    const sh = base.getSheetByName('スタンバイタイトル');
    if (sh && sh.getLastRow() >= 1) sh.getRange(1, 1, sh.getLastRow(), 1).getValues().forEach(v => add(v[0]));
    if (list.length) return list;
  }
  const sh = base.getSheetByName('タイトル');
  if (sh && sh.getLastRow() >= 1) {
    sh.getRange(1, 1, sh.getLastRow(), 2).getValues().forEach(v => {
      if (/^\d+$/.test(String(v[0]))) add(v[1]);
    });
  }
  return list;
}

// 使用履歴（会社名・職種番号・職種名・…・直近使用日）から { 職種名: 直近使用日 }
function qmatePlanLastUsed_(base, company, category) {
  const sh = base.getSheetByName(QMATE_PLAN_USAGE_SHEET);
  const map = {};
  if (!sh || sh.getLastRow() < 2) return map;
  sh.getRange(2, 1, sh.getLastRow() - 1, 6).getValues().forEach(r => {
    if (r[0] !== company || r[1] !== category || !r[5]) return;
    const d = r[5] instanceof Date ? r[5] : new Date(String(r[5]).trim().replace(' ', 'T'));
    if (!isNaN(d.getTime())) map[String(r[2])] = d;
  });
  return map;
}

function qmatePlanIsRecent_(lastUsed) {
  return !!lastUsed && (new Date() - lastUsed) / 86400000 < QMATE_PLAN_COOLDOWN_DAYS;
}
