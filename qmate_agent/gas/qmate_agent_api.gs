/**
 * qmate_agent（Q-mate 入稿ツール）から原稿の生成を呼び出すための入口。
 *
 * 既存のコード（Code.gs）は変更せず、このファイルを同じ Apps Script プロジェクトに追加する。
 * 【設定方法】
 *   1. Apps Script の左側「ファイル」の＋ →「スクリプト」で qmate_agent_api という名前のファイルを作り、この内容を貼り付けて保存
 *   2. 上の関数選択で setupQmateAgentToken を選んで「実行」→ 権限を許可 → 実行ログに出た文字列（合言葉）を控える
 *   3. 右上「デプロイ」→「新しいデプロイ」→ 種類「ウェブアプリ」
 *        次のユーザーとして実行: 自分 ／ アクセスできるユーザー: 全員 → デプロイ
 *   4. 表示されたウェブアプリの URL を控える
 *   合言葉を知らない人が URL を開いても何も実行されない。
 */

function doPost(e) {
  let body = {};
  try {
    body = JSON.parse((e && e.postData && e.postData.contents) || '{}');
  } catch (err) {
    return qmateAgentJson_({ ok: false, error: '送られてきた内容が読めません' });
  }
  const token = PropertiesService.getScriptProperties().getProperty('QMATE_AGENT_TOKEN');
  if (!token || body.token !== token) {
    return qmateAgentJson_({ ok: false, error: '合言葉が違います' });
  }

  if (body.action === 'run') {
    // 実行設定の「実行状況」が空欄の行を生成する（メニューの③と同じ処理）。
    // 6分を超えそうなときは、③と同じく1分後に自動で続きから再開する。
    const lock = LockService.getScriptLock();
    if (!lock.tryLock(1000)) return qmateAgentJson_({ ok: true, message: 'すでに生成中です' });
    try {
      runFromConfig();
    } finally {
      lock.releaseLock();
    }
    return qmateAgentJson_({ ok: true });
  }
  return qmateAgentJson_({ ok: false, error: '知らない操作です: ' + body.action });
}

function qmateAgentJson_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}

// 合言葉を作り直す。実行ログに出た文字列を、ツール側の環境変数 QMATE_GAS_TOKEN に入れる。
function setupQmateAgentToken() {
  const token = Utilities.getUuid();
  PropertiesService.getScriptProperties().setProperty('QMATE_AGENT_TOKEN', token);
  Logger.log('合言葉: ' + token);
}
