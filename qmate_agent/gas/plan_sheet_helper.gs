/**
 * 入稿予定表の入力補助（qmate_agent 用）。
 *
 * 実行設定シートに手で入力したときと同じ補助を、入稿予定表でも行う。
 *   - 職種名選択：6重め・7軽めのときだけ、その職種の職種名のプルダウンにする。
 *                 同じ会社で30日以内に使った職種名はプルダウンに出さない（候補にない値は入れられない）。
 *   - スタンバイキーワード：通勤／入寮それぞれの土台にある候補のプルダウンにする。
 *   - 会社・職種・通勤/入寮を変えたら、職種名選択を消して選び直してもらう。
 *   - 「職種名の確認」列に、その職種名が使えるかを書く（30日以内に使っていないか、通勤/入寮の一覧にあるか、
 *     同じ会社・職種のまだ実行していない別の行と同じ職種名を選んでいないか）。使えないときはセルを赤くする。
 *   - 毎朝6時と、メニュー「入稿予定表 → 職種名の確認をやり直す」で、プルダウンと確認を全行作り直す
 *     （予定を入れたあとに、ほかの行の入稿で使用済みになることがあるため）。
 * 通勤の行は通勤用の土台、入寮の行は入寮用の土台（職種名・候補・使用履歴）を見る。
 *
 * 既存のコード（Code.gs）は変更せず、このファイルを同じ Apps Script プロジェクトに追加する。
 * 【設定方法】
 *   1. 左の「ファイル」の＋ →「スクリプト」で plan_sheet_helper という名前のファイルを作り、この内容を貼り付けて保存
 *   2. 上の関数選択で setupQmatePlanHelper を選んで「実行」→ 権限を許可
 *      （入稿予定表を編集したときに動く設定・メニュー・毎朝の確認を作り、今入っている行にもプルダウンと確認を付ける）
 *   ※ このファイルを貼り直したときも、もう一度 setupQmatePlanHelper を実行してください
 *
 * 速さのため、候補の一覧は「通勤/入寮・会社・職種」の組み合わせごとに1回だけ隠しシートに書き、
 * 確認の列とセルの色は、行ごとではなくまとめて書く。
 */

const QMATE_PLAN_SHEET_NAME = '入稿予定表';
const QMATE_PLAN_BASE_IDS = {
  '通勤': '1ZfuZBafA0G1WPhpm_-7VnEdTF4mbiZkX0U-EQ09w0zY', // ＜土台＞Q-mate 求人原稿自動生成
  '入寮': '1PDeksvTvzx6LqDC7nCz5fk4IX8Ssi3cKsRDYdVCTbdI', // ＜土台/入寮用＞Q-mate 求人原稿自動生成
};
const QMATE_PLAN_USAGE_SHEET = 'アカウント×職種名_使用履歴';
// プルダウンの候補を書き出しておく隠しシート。候補の数に上限がないよう、プルダウンはこのシートの範囲を参照する
// （候補を直接プルダウンに入れると500件までしか入らず、7軽めの職種名は入りきらない）
const QMATE_PLAN_LIST_SHEET = '_入稿予定表_候補（自動生成・編集不要）';
const QMATE_PLAN_COOLDOWN_DAYS = 30; // 生成側（Code.gs の COOLDOWN_DAYS）と同じ日数
const QMATE_PLAN_CHECK_HEADER = '職種名の確認';
const QMATE_PLAN_NG_COLOR = '#F4CCCC';
const QMATE_PLAN_NONE = '（使える職種名がありません）';

function setupQmatePlanHelper() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const mine = ['qmatePlanOnEdit', 'qmatePlanOnOpen', 'qmatePlanCheckAll'];
  ScriptApp.getProjectTriggers().forEach(t => {
    if (mine.indexOf(t.getHandlerFunction()) >= 0) ScriptApp.deleteTrigger(t);
  });
  // 土台を開く必要があるため、普通の onEdit ではなく「インストール型」の編集時トリガーにする
  ScriptApp.newTrigger('qmatePlanOnEdit').forSpreadsheet(ss).onEdit().create();
  // Code.gs に onOpen があるので、メニューはインストール型の起動時トリガーで足す
  ScriptApp.newTrigger('qmatePlanOnOpen').forSpreadsheet(ss).onOpen().create();
  ScriptApp.newTrigger('qmatePlanCheckAll').timeBased().everyDays(1).atHour(6).create();
  qmatePlanCleanListSheet_();

  const sh = ss.getSheetByName(QMATE_PLAN_SHEET_NAME);
  qmatePlanUpdate_(sh, qmatePlanColumns_(sh), { standby: true });
  qmatePlanOnOpen();
  ss.toast('入稿予定表の入力補助を設定しました', 'Q-mate', 5);
}

function qmatePlanOnOpen() {
  try {
    SpreadsheetApp.getUi().createMenu('入稿予定表')
      .addItem('職種名の確認をやり直す', 'qmatePlanCheckAll')
      .addToUi();
  } catch (err) {
    Logger.log('qmatePlanOnOpen: ' + err.message);
  }
}

// 全部の行のプルダウンと「職種名の確認」を作り直す（毎朝6時・メニューから）
function qmatePlanCheckAll() {
  const sh = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(QMATE_PLAN_SHEET_NAME);
  if (!sh) return;
  qmatePlanUpdate_(sh, qmatePlanColumns_(sh), {});
  try {
    SpreadsheetApp.getActiveSpreadsheet().toast('職種名の確認をやり直しました', '入稿予定表', 5);
  } catch (err) {
    // 毎朝の自動実行では画面がないので何もしない
  }
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
    const edited = [];
    for (let r = r1; r <= r2; r++) edited.push(r);
    // 会社・職種・通勤/入寮を変えた行は職種名を消す。職種名を選んだだけなら、30日以内のときに知らせる
    qmatePlanUpdate_(sh, cols, keyChanged ? { clearRows: edited, standbyRows: edited } : { warnRows: edited });
  } catch (err) {
    Logger.log('qmatePlanOnEdit: ' + err.message);
    SpreadsheetApp.getActiveSpreadsheet().toast(err.message, '入稿予定表の入力補助でエラー', 15);
  }
}

// プルダウンと「職種名の確認」をまとめて作り直す。
// opts.clearRows：職種名を消す行、opts.standbyRows：スタンバイキーワードのプルダウンを付け直す行、
// opts.standby：全行のスタンバイキーワードを付け直す、opts.warnRows：30日以内なら知らせる行
function qmatePlanUpdate_(sh, cols, opts) {
  const titleCol = cols['職種名選択'];
  if (!titleCol || sh.getLastRow() < 2) return;
  const checkCol = qmatePlanCheckColumn_(sh, cols);
  const values = sh.getDataRange().getValues();
  const cache = { plan: values };
  const clear = {};
  (opts.clearRows || []).forEach(r => {
    clear[r] = true;
    if (values[r - 1]) values[r - 1][titleCol - 1] = '';
  });
  (opts.clearRows || []).forEach(r => sh.getRange(r, titleCol).clearContent());

  const rows = [];
  for (let r = 2; r <= values.length; r++) rows.push(qmatePlanRow_(sh, cols, r, cache));
  let last = 1;
  rows.forEach(row => { if (row.company || row.category) last = row.row; });
  if (last < 2) return;
  const live = rows.filter(row => row.row <= last && (row.company || row.category) && !qmatePlanIsDone_(row.result));

  // 同じ会社・職種・通勤/入寮で、まだ実行していない行が選んでいる職種名 → 行番号
  const chosen = {};
  live.forEach(row => {
    if (!row.title) return;
    const k = qmatePlanKey_(row);
    chosen[k] = chosen[k] || {};
    (chosen[k][row.title] = chosen[k][row.title] || []).push(row.row);
  });

  // プルダウン（候補の一覧は組み合わせごとに1回だけ作る）
  const rules = {};
  live.forEach(row => {
    const m = row.category.match(/^\d+(重め|軽め)$/);
    const cell = sh.getRange(row.row, titleCol);
    if (!m) {
      if (clear[row.row]) cell.clearDataValidations();
      return;
    }
    const k = qmatePlanKey_(row);
    if (!rules[k]) {
      const used = qmatePlanUsed_(cache, row);
      let titles = qmatePlanTitles_(cache, row.commute, m[1]).filter(t => !qmatePlanIsRecent_(used[t]));
      if (!titles.length) titles = [QMATE_PLAN_NONE];
      rules[k] = SpreadsheetApp.newDataValidation()
        .requireValueInRange(qmatePlanListRange_(`職種名選択｜${k}`, titles), true)
        .setAllowInvalid(false).setHelpText('30日以内に使った職種名は出ません').build();
    }
    cell.setDataValidation(rules[k]);
  });

  // スタンバイキーワード
  if (cols['スタンバイキーワード']) {
    const want = opts.standby ? live.map(row => row.row) : (opts.standbyRows || []);
    const ranges = {};
    want.forEach(r => {
      const row = rows[r - 2];
      if (!row || (!row.company && !row.category)) return;
      if (!(row.commute in ranges)) {
        const kw = qmatePlanStandbyKeywords_(qmatePlanBase_(cache, row.commute), row.commute);
        ranges[row.commute] = kw.length ? qmatePlanListRange_(`スタンバイキーワード｜${row.commute}`, kw) : null;
      }
      if (ranges[row.commute]) {
        sh.getRange(r, cols['スタンバイキーワード']).setDataValidation(SpreadsheetApp.newDataValidation()
          .requireValueInRange(ranges[row.commute], true).setAllowInvalid(true).build());
      }
    });
  }

  // 「職種名の確認」はまとめて書く
  const now = new Date();
  const texts = [], checkBg = [], titleBg = [];
  rows.filter(row => row.row <= last).forEach(row => {
    const m = row.category.match(/^\d+(重め|軽め)$/);
    let text = '';
    if (!qmatePlanIsDone_(row.result) && (row.company || row.category)) {
      const titles = m && row.title ? qmatePlanTitles_(cache, row.commute, m[1]) : null;
      const used = m && row.title ? qmatePlanUsed_(cache, row) : {};
      const all = (chosen[qmatePlanKey_(row)] || {})[row.title] || [];
      const taken = {};
      if (row.title) taken[row.title] = all.filter(r => r !== row.row);
      text = qmatePlanCheckText_(row, titles, used, now, taken);
    }
    const ng = text.indexOf('❌') === 0;
    texts.push([text]);
    checkBg.push([ng ? QMATE_PLAN_NG_COLOR : null]);
    titleBg.push([ng ? QMATE_PLAN_NG_COLOR : null]);
  });
  sh.getRange(2, checkCol, texts.length, 1).setValues(texts).setBackgrounds(checkBg);
  sh.getRange(2, titleCol, titleBg.length, 1).setBackgrounds(titleBg);

  (opts.warnRows || []).forEach(r => qmatePlanWarnIfRecentlyUsed_(sh, cols, r, cache));
}

// 前の版が行ごとに作っていた候補の列（「職種名選択｜12行目」など）を消す
function qmatePlanCleanListSheet_() {
  const sh = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(QMATE_PLAN_LIST_SHEET);
  if (!sh || sh.getLastColumn() < 1) return;
  const head = sh.getRange(1, 1, 1, sh.getLastColumn()).getValues()[0].map(String);
  for (let c = head.length; c >= 1; c--) {
    if (/｜\d+行目$/.test(head[c - 1])) sh.deleteColumn(c);
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

// 入稿予定表の1行。cache.plan に表全体を読んでおき、行ごとにシートを読みに行かない
function qmatePlanRow_(sh, cols, r, cache) {
  cache = cache || {};
  if (!cache.plan) cache.plan = sh.getDataRange().getValues();
  const vals = cache.plan[r - 1] || [];
  const v = name => cols[name] ? String(vals[cols[name] - 1] || '').trim() : '';
  return {
    row: r,
    company: v('会社'),
    category: v('職種'),
    commute: v('通勤/入寮') === '入寮' ? '入寮' : '通勤',
    title: qmatePlanBareTitle_(v('職種名選択')),
    result: v('実行結果'),
  };
}

// 「7軽め｜職種名」→「職種名」
function qmatePlanBareTitle_(t) {
  return t.indexOf('｜') >= 0 ? t.slice(t.indexOf('｜') + 1) : t;
}

function qmatePlanKey_(row) {
  return `${row.commute}|${row.company}|${row.category}`;
}

// 土台・職種名一覧・使用履歴を、同じ実行のあいだ使い回す
function qmatePlanBase_(cache, commute) {
  cache.bases = cache.bases || {};
  if (!cache.bases[commute]) cache.bases[commute] = SpreadsheetApp.openById(QMATE_PLAN_BASE_IDS[commute]);
  return cache.bases[commute];
}

function qmatePlanTitles_(cache, commute, kind) {
  cache.titles = cache.titles || {};
  const k = `${commute}|${kind}`;
  if (!cache.titles[k]) cache.titles[k] = qmatePlanPairedTitles_(qmatePlanBase_(cache, commute), kind);
  return cache.titles[k];
}

function qmatePlanUsed_(cache, row) {
  cache.used = cache.used || {};
  const k = qmatePlanKey_(row);
  if (!cache.used[k]) {
    cache.used[k] = row.company ? qmatePlanLastUsed_(qmatePlanBase_(cache, row.commute), row.company, row.category) : {};
  }
  return cache.used[k];
}

// 「職種名の確認」列の番号。無ければ見出しの右端に作る
function qmatePlanCheckColumn_(sh, cols) {
  if (cols[QMATE_PLAN_CHECK_HEADER]) return cols[QMATE_PLAN_CHECK_HEADER];
  const col = sh.getLastColumn() + 1;
  if (col > sh.getMaxColumns()) sh.insertColumnsAfter(sh.getMaxColumns(), 1);
  sh.getRange(1, col).setValue(QMATE_PLAN_CHECK_HEADER).setFontWeight('bold');
  cols[QMATE_PLAN_CHECK_HEADER] = col;
  return col;
}

// 入稿済みの行は、もう確かめない（「テスト：CSV作成まで」や「失敗」の行は、まだ入稿していないので確かめる）
function qmatePlanIsDone_(result) {
  return !!result && result.indexOf('入稿済み') === 0;
}

// 確認の文言（画面を触らない部分。Node でもテストできるように分けてある）
// titles：その通勤/入寮・職種の職種名一覧（6重め・7軽め以外は null）、used：{ 職種名: 直近使用日 }、
// taken：{ 職種名: [同じ職種名を選んでいるほかの行] }
function qmatePlanCheckText_(row, titles, used, now, taken) {
  if (!row.company && !row.category) return '';
  if (qmatePlanIsDone_(row.result)) return '';
  const m = row.category.match(/^\d+(重め|軽め)$/);
  if (!m) return row.category ? '✅ 職種名は自動で選びます（30日以内に使ったものは選びません）' : '';
  if (!row.title || row.title === QMATE_PLAN_NONE) return '❌ 職種名選択を選んでください';
  const title = qmatePlanBareTitle_(row.title);
  if (titles && titles.indexOf(title) < 0) {
    return `❌ ${row.commute}用の${row.category}にない職種名です。職種名選択を選び直してください`;
  }
  const last = used[title];
  const fmt = d => `${d.getMonth() + 1}/${d.getDate()}`;
  if (last && (now - last) / 86400000 < QMATE_PLAN_COOLDOWN_DAYS) {
    const ok = new Date(last.getTime() + QMATE_PLAN_COOLDOWN_DAYS * 86400000);
    return `❌ ${fmt(last)}に使用済み。${fmt(ok)}から使えます。別の職種名を選んでください`;
  }
  const others = (taken || {})[title];
  if (others && others.length) {
    return `❌ ${others.join('・')}行目でも同じ職種名を選んでいます。どちらかを別の職種名にしてください`;
  }
  return last ? `✅ 使えます（前回 ${fmt(last)}）` : '✅ 使えます';
}

// 候補の一覧を隠しシートの1列に書き、その範囲を返す。1行目は「職種名選択｜通勤｜会社｜7軽め」のような見出しで、
// 同じ見出しの列があれば中身を書き直す（30日ルールで外れる職種名が日ごとに変わるため）
function qmatePlanListRange_(key, values) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sh = ss.getSheetByName(QMATE_PLAN_LIST_SHEET);
  if (!sh) {
    sh = ss.insertSheet(QMATE_PLAN_LIST_SHEET);
    sh.hideSheet();
  }
  const lastCol = sh.getLastColumn();
  const head = lastCol ? sh.getRange(1, 1, 1, lastCol).getValues()[0].map(String) : [];
  let col = head.indexOf(key) + 1;
  if (!col) {
    col = lastCol + 1;
    if (col > sh.getMaxColumns()) sh.insertColumnsAfter(sh.getMaxColumns(), col - sh.getMaxColumns());
    sh.getRange(1, col).setValue(key);
  }
  const need = values.length + 1;
  if (need > sh.getMaxRows()) sh.insertRowsAfter(sh.getMaxRows(), need - sh.getMaxRows());
  if (sh.getLastRow() > 1) sh.getRange(2, col, sh.getLastRow() - 1, 1).clearContent();
  sh.getRange(2, col, values.length, 1).setValues(values.map(v => [v]));
  return sh.getRange(2, col, values.length, 1);
}

function qmatePlanWarnIfRecentlyUsed_(sh, cols, r, cache) {
  const row = qmatePlanRow_(sh, cols, r, cache);
  if (!row.company || !row.category || !row.title) return;
  const title = row.title;
  const lastUsed = qmatePlanUsed_(cache, row)[title];
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
