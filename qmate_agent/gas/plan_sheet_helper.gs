/**
 * 入稿予定表の入力補助（qmate_agent 用）。
 *
 * 実行設定シートに手で入力したときと同じ補助を、入稿予定表でも行う。
 *   - 職種名選択：6重め・7軽めのときだけ、その職種の職種名のプルダウンにする。
 *                 次の職種名はプルダウンに出さない（候補にない値は入れられない）。
 *                   ・同じ会社で30日以内に使った職種名
 *                   ・同じ会社・職種の、まだ実行していない別の行で選んでいる職種名
 *   - スタンバイキーワード：通勤／入寮それぞれの土台にある候補のプルダウンにする。
 *   - 会社・職種・通勤/入寮を変えたら、職種名選択を消して選び直してもらう。
 *   - 「職種名の確認」列に、その職種名が使えるか（30日以内に使っていないか、通勤/入寮の一覧にあるか）を書く。
 *     使えないときはセルを赤くする。毎朝6時と、メニュー「入稿予定表 → 職種名の確認をやり直す」で全行を確かめ直す
 *     （予定を入れたあとに、ほかの行の入稿で使用済みになることがあるため）。
 * 通勤の行は通勤用の土台、入寮の行は入寮用の土台（職種名・候補・使用履歴）を見る。
 *
 * 既存のコード（Code.gs）は変更せず、このファイルを同じ Apps Script プロジェクトに追加する。
 * 【設定方法】
 *   1. 左の「ファイル」の＋ →「スクリプト」で plan_sheet_helper という名前のファイルを作り、この内容を貼り付けて保存
 *   2. 上の関数選択で setupQmatePlanHelper を選んで「実行」→ 権限を許可
 *      （入稿予定表を編集したときに動く設定・メニュー・毎朝の確認を作り、今入っている行にもプルダウンと確認を付ける）
 *   ※ このファイルを貼り直したときも、もう一度 setupQmatePlanHelper を実行してください
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

  qmatePlanCheckAll();
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

// 全部の行のプルダウンと「職種名の確認」を作り直す（毎朝6時・メニューから）。
// 30日ルールで外れる職種名は日ごとに変わるので、プルダウンの候補も作り直す
function qmatePlanCheckAll() {
  const sh = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(QMATE_PLAN_SHEET_NAME);
  if (!sh || sh.getLastRow() < 2) return;
  const cols = qmatePlanColumns_(sh);
  const cache = {};
  for (let r = 2; r <= sh.getLastRow(); r++) {
    qmatePlanRefreshRow_(sh, cols, r, false, cache);
    qmatePlanCheckRow_(sh, cols, r, cache);
  }
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
    const cache = {};
    for (let r = r1; r <= r2; r++) {
      if (keyChanged) qmatePlanRefreshRow_(sh, cols, r, true, cache);
      else qmatePlanWarnIfRecentlyUsed_(sh, cols, r, cache);
    }
    // ある行で職種名を選ぶ・変えると、同じ会社・職種のほかの行で選べる職種名も変わるので、
    // まだ実行していない行のプルダウンと確認を全部作り直す
    for (let r = 2; r <= sh.getLastRow(); r++) {
      if (!(keyChanged && r1 <= r && r <= r2)) qmatePlanRefreshRow_(sh, cols, r, false, cache);
      qmatePlanCheckRow_(sh, cols, r, cache);
    }
  } catch (err) {
    Logger.log('qmatePlanOnEdit: ' + err.message);
    SpreadsheetApp.getActiveSpreadsheet().toast(err.message, '入稿予定表の入力補助でエラー', 15);
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

// 同じ会社・職種・通勤/入寮の、まだ実行していない別の行で選んでいる職種名 → その行番号
function qmatePlanTakenByOthers_(sh, cols, row, cache) {
  const taken = {};
  for (let r = 2; r <= sh.getLastRow(); r++) {
    if (r === row.row) continue;
    const o = qmatePlanRow_(sh, cols, r, cache);
    if (o.title && !qmatePlanIsDone_(o.result) && qmatePlanKey_(o) === qmatePlanKey_(row)) {
      (taken[o.title] = taken[o.title] || []).push(r);
    }
  }
  return taken;
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
  if (!cache.used[k]) cache.used[k] = row.company ? qmatePlanLastUsed_(qmatePlanBase_(cache, row.commute), row.company, row.category) : {};
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

// 1行分の「職種名の確認」を書く
function qmatePlanCheckRow_(sh, cols, r, cache) {
  const col = qmatePlanCheckColumn_(sh, cols);
  const row = qmatePlanRow_(sh, cols, r, cache);
  const m = row.category.match(/^\d+(重め|軽め)$/);
  let titles = null, used = {}, taken = {};
  if (m && row.title && !qmatePlanIsDone_(row.result)) {
    titles = qmatePlanTitles_(cache, row.commute, m[1]);
    used = qmatePlanUsed_(cache, row);
    taken = qmatePlanTakenByOthers_(sh, cols, row, cache);
  }
  const text = qmatePlanCheckText_(row, titles, used, new Date(), taken);
  const titleCol = cols['職種名選択'];
  sh.getRange(r, col).setValue(text);
  const ng = text.indexOf('❌') === 0;
  sh.getRange(r, col).setBackground(ng ? QMATE_PLAN_NG_COLOR : null);
  if (titleCol) sh.getRange(r, titleCol).setBackground(ng ? QMATE_PLAN_NG_COLOR : null);
}

// 実行結果が入っていて失敗ではない行（入稿済み・CSV作成まで）は、もう確かめない
function qmatePlanIsDone_(result) {
  return !!result && result.indexOf('失敗') !== 0;
}

// 確認の文言（画面を触らない部分。Node でもテストできるように分けてある）
// titles：その通勤/入寮・職種の職種名一覧（6重め・7軽め以外は null）、used：{ 職種名: 直近使用日 }
function qmatePlanCheckText_(row, titles, used, now, taken) {
  if (!row.company && !row.category) return '';
  if (qmatePlanIsDone_(row.result)) return '';
  const m = row.category.match(/^\d+(重め|軽め)$/);
  if (!m) return row.category ? '✅ 職種名は自動で選びます（30日以内に使ったものは選びません）' : '';
  if (!row.title) return '❌ 職種名選択を選んでください';
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

// 1行分のプルダウンを付け直す。clearTitle が true なら選んであった職種名を消す（会社・職種・通勤/入寮を変えたとき）
function qmatePlanRefreshRow_(sh, cols, r, clearTitle, cache) {
  cache = cache || {};
  const row = qmatePlanRow_(sh, cols, r, cache);
  const titleCell = cols['職種名選択'] ? sh.getRange(r, cols['職種名選択']) : null;
  if (!row.company && !row.category) {
    if (titleCell && clearTitle) titleCell.clearContent().clearDataValidations();
    return;
  }
  if (qmatePlanIsDone_(row.result)) return; // 実行済みの行はそのままにする

  if (cols['スタンバイキーワード']) {
    cache.keywords = cache.keywords || {};
    if (!cache.keywords[row.commute]) {
      const keywords = qmatePlanStandbyKeywords_(qmatePlanBase_(cache, row.commute), row.commute);
      cache.keywords[row.commute] = keywords.length
        ? qmatePlanListRange_(`スタンバイキーワード｜${row.commute}`, keywords) : null;
    }
    if (cache.keywords[row.commute]) {
      sh.getRange(r, cols['スタンバイキーワード']).setDataValidation(SpreadsheetApp.newDataValidation()
        .requireValueInRange(cache.keywords[row.commute], true).setAllowInvalid(true).build());
    }
  }

  if (!titleCell) return;
  const m = row.category.match(/^\d+(重め|軽め)$/);
  if (clearTitle) {
    titleCell.clearContent();
    if (cache.plan && cols['職種名選択']) cache.plan[r - 1][cols['職種名選択'] - 1] = '';
    row.title = '';
  }
  if (!m) {
    titleCell.clearDataValidations();
    return;
  }
  const used = qmatePlanUsed_(cache, row);
  const taken = qmatePlanTakenByOthers_(sh, cols, row, cache);
  let titles = qmatePlanTitles_(cache, row.commute, m[1])
    .filter(t => !qmatePlanIsRecent_(used[t]) && !taken[t]);
  if (!titles.length) titles = ['（使える職種名がありません）'];
  // 行ごとに候補が違う（ほかの行で選んだ職種名を外す）ので、候補の列は行ごとに作る
  titleCell.setDataValidation(SpreadsheetApp.newDataValidation()
    .requireValueInRange(qmatePlanListRange_(`職種名選択｜${r}行目`, titles), true)
    .setAllowInvalid(false).setHelpText('30日以内に使った職種名と、ほかの行で選んでいる職種名は出ません').build());
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
