/**
 * ヒトマネ原稿(旧FMT) 自動生成スクリプト(Google Apps Script版)
 * ===================================================
 * 【インストール方法】
 *   1. 「ヒトマネ 求人原稿自動生成」スプレッドシートを開く
 *   2. 拡張機能 > Apps Script
 *   3. デフォルトの Code.gs の中身を全部消して、このファイルの内容を貼り付け
 *   4. 保存 → スプレッドシートに戻って再読み込み → メニューに「ヒトマネ自動生成」が追加される
 *   5. まず「①シート診断」で各データが正しく認識されているか確認
 *
 * 【現時点の対応範囲】
 *   Q-mateと共通のカテゴリー(1クルマ, 2工場, 3軽作業, 4電子部品, 5半導体, 8梱包, 9検査,
 *   10ピッキング, 11仕分け, 12シール貼り)のみ対応。
 *   「6重め」「7軽め」(職種名+お仕事番号+専用仕事内容1〜13のセット構造)は未対応。追って対応予定。
 *
 * 【2026/09/10 更新】
 *   「土台」(職種名・仕事内容・会社情報マスター・勤務地・画像カテゴリー・給与パターン・
 *   勤務時間パターン・6重め/7軽め・タイトル組み立て用・旧FMT/新FMTテンプレ・職種名管理)を
 *   別スプレッドシート(HM_BASE_SPREADSHEET_ID)に切り出した。
 *   運用ファイル(このファイル)側は実行設定・出力シート・使用履歴・検品シートのみを持つ。
 *   これにより運用ファイルの総セル数が減り、⑤検品シート作成などでのスプレッドシート
 *   サービスのタイムアウトが起きにくくなる。
 */

const HITOMANE_HEADERS = ["募集番号","ステータス","開始日","終了日","拠点コード","拠点","お仕事番号","都道府県","市区町村","媒体","費用","メモ","応募フォーム","閲覧数（PC)","閲覧数（MOBILE)","閲覧数（SMARTPHONE)","給与方法","シフト","応募方法","定員","募集職種","一覧用給与","給与","一覧用PR","PR","早朝","朝","昼","夕方","夜","深夜","駅チカ・駅ナカ","オープニングスタッフ","高校生歓迎","大学生歓迎","主婦・主夫歓迎","シフト制勤務","短時間勤務（4時間以内）","時間曜日応相談","即日勤務OK","未経験者歓迎","交通費支給","交通費一部支給","社内割引あり","日祝給料アップ","社員登用あり","寮・社宅あり","まかないあり","食事補助","制服貸与","髪型自由","服装自由","土日のみOK","平日のみOK","週払いOK","日払いOK","土日祝勤務歓迎","車通勤応相談","フリーター歓迎","語学力を活かせる","研修制度あり","経験者歓迎","前払い応相談","早朝・深夜勤務","土日祝・面接可","大量募集","Wワーク歓迎","仕事ブランクOK","画像名一覧用","画像名1","画像名2","画像名3","画像名4","画像名5","画像1キャプション","画像2キャプション","画像3キャプション","画像4キャプション","画像5キャプション","仕事内容","最低給与額","勤務時間","勤務期間","勤務地","交通アクセス","年齢制限","応募資格","待遇","地図用テキスト","地図用タイトル","地図用住所","その他地図用テキスト","その他地図用タイトル","その他地図用住所","応募方法","担当","オンライン面接予約機能","応募時面接予約任意","面接締切時応募続行","優先度","掲載用拠点名","受付電話番号","カスタム検索キーワード","媒体出稿時の名称","ファイル名","コンテントタイプ","雇用形態","案件詳細URL","Indeed広告用参照番号"];

// お仕事番号(メモ相当)組み立て用: 媒体番号(ヒトマネ固定)
const HITOMANE_MEDIA_CODE = 3;

// カテゴリー番号(Q-mateの「職種名」タブの列見出しと同じ表記に対応させる)
const HITOMANE_CATEGORY_NUMBER_LABEL = {
  'クルマ': '1クルマ', '工場': '2工場', '軽作業': '3軽作業', '電子部品': '4電子部品',
  '半導体': '5半導体', '重め': '6重め', '軽め': '7軽め', '梱包': '8梱包', '検査': '9検査', 'ピッキング': '10ピッキング',
  '仕分け': '11仕分け', 'シール貼り': '12シール貼り',
};
const HITOMANE_CATEGORY_NAMES = Object.keys(HITOMANE_CATEGORY_NUMBER_LABEL);

const HITOMANE_CATEGORY_TO_TYPE = {
  'クルマ': '製造・生産工程従事者', '工場': '製造・生産工程従事者', '軽作業': 'その他製造・生産工程従事者',
  '電子部品': '電気・電子機器組立・修理', '半導体': '電気・電子機器組立・修理', '梱包': '梱包',
  '検査': '製品検査・検品', 'ピッキング': 'ピッキング', '仕分け': '仕分け', 'シール貼り': 'その他製造・生産工程従事者',
};

// 固定列(白背景=常に同じ値。会社情報・実行設定に関わらず一律)
const HITOMANE_FIXED_VALUES = {
  '媒体': '自社',
  '応募フォーム': '応募項目パターン１',
  'シフト': '週5日以上',
  '早朝': 'TRUE', '朝': 'TRUE', '昼': 'TRUE', '夕方': 'TRUE', '夜': 'TRUE', '深夜': 'TRUE',
  'シフト制勤務': 'TRUE',
  '即日勤務OK': 'TRUE',
  '未経験者歓迎': 'TRUE',
  '交通費支給': 'TRUE',
  '寮・社宅あり': 'TRUE',
  '制服貸与': 'TRUE',
  '平日のみOK': 'TRUE',
  'フリーター歓迎': 'TRUE',
  '経験者歓迎': 'TRUE',
  '仕事ブランクOK': 'TRUE',
  '地図用テキスト': '勤務地はこの周辺です。',
  '地図用タイトル': '勤務所在地',
  '担当': '採用担当',
  '掲載用拠点名': '非公開',
  '雇用形態': '正社員',
};

const HITOMANE_COMMUTE_CODE = { '通勤': 1, '入寮': 2 };

// ============================================================
// 新FMT用の定数
// ============================================================
const HITOMANE_NEW_HEADERS = ["募集番号", "開始日", "終了日", "ステータス", "案件タイプ", "お仕事番号", "拠点コード", "拠点", "掲載用拠点名", "職種カテゴリ", "募集職種", "雇用形態", "早朝", "朝", "昼", "夕方", "夜", "深夜", "一覧用PR", "PR", "仕事内容", "基本給_給与タイプ", "基本給_定額", "基本給_最低額", "基本給_最高額", "基本給_タスク_単位", "基本給_タスク_時間", "平均所定労働時間", "平均勤務日数", "一律支給される諸手当_定額", "一律支給される諸手当_最低額", "一律支給される諸手当_最高額", "給与", "固定残業代の有無", "固定残業代の支払額_定額", "固定残業代の支払額_最低額", "固定残業代の支払額_最高額", "固定残業時間", "固定残業時間を超えた場合の追加支払い", "試用期間の有無", "試用期間_期間", "試用期間_単位", "試用期間_労働条件の差異", "試用期間_労働条件の差異_給与", "試用期間_労働条件の差異_労働時間", "試用期間_労働条件の差異_その他（雇用形態や手当など）", "試用期間_給与条件_給与タイプ", "試用期間_給与条件_定額", "試用期間_給与条件_最低額", "試用期間_給与条件_最高額", "試用期間_給与条件_タスク_単位", "試用期間_給与条件_タスク_時間", "試用期間_一律支給される諸手当_定額", "試用期間_一律支給される諸手当_最低額", "試用期間_一律支給される諸手当_最高額", "試用期間_給与条件_固定残業代の有無", "試用期間_給与条件_固定残業代の支払額_定額", "試用期間_給与条件_固定残業代の支払額_最低額", "試用期間_給与条件_固定残業代の支払額_最高額", "試用期間_給与条件_固定残業時間", "試用期間_給与条件_固定残業時間を超えた場合の追加支払い", "試用期間_労働時間条件_労働時間", "試用期間_その他", "勤務地_郵便番号", "勤務地_都道府県", "勤務地_市区町村", "勤務地_町域", "勤務地_番地", "勤務地_建物名など", "勤務地_補足", "交通アクセス", "地図用テキスト", "地図用タイトル", "地図用住所", "その他地図用テキスト", "その他地図用タイトル", "その他地図用住所", "勤務期間", "契約期間", "勤務時間_開始_1", "勤務時間_終了_1", "実働時間_固定_1", "実働時間_最小_1", "実働時間_最大_1", "休憩時間_変動_1", "休憩時間_1", "勤務時間_開始_2", "勤務時間_終了_2", "実働時間_固定_2", "実働時間_最小_2", "実働時間_最大_2", "休憩時間_変動_2", "休憩時間_2", "勤務時間_開始_3", "勤務時間_終了_3", "実働時間_固定_3", "実働時間_最小_3", "実働時間_最大_3", "休憩時間_変動_3", "休憩時間_3", "勤務時間_補足", "勤務形態_固定時間制", "勤務形態_シフト制", "勤務形態_変形労働制", "勤務形態_フレックスタイム制度", "勤務形態_専門業務型裁量労働制", "勤務形態_企画業務型裁量労働制", "勤務形態_事業場外みなし労働時間制", "勤務形態_高度プロフェッショナル制", "シフト", "Indeed連携用_シフト", "休日・休暇", "待遇", "社会保険_厚生年金", "社会保険_健康保険", "社会保険_雇用保険", "社会保険_労災保険", "選択できない社会保険がある場合の理由", "受動喫煙対策_屋内禁煙", "受動喫煙対策_屋外喫煙可", "受動喫煙対策_屋内原則禁煙（ただし、適用除外の場所あり）", "受動喫煙対策_屋内喫煙可", "受動喫煙対策_屋内喫煙可（ただし、特定の喫煙可能室または喫煙目的室のみ）", "受動喫煙対策_内定時までに開示", "応募資格", "応募方法", "応募方法_補足", "担当", "受付電話番号", "画像名一覧用", "画像名1", "画像名2", "画像名3", "画像名4", "画像名5", "画像1キャプション", "画像2キャプション", "画像3キャプション", "画像4キャプション", "画像5キャプション", "オンライン面接予約機能", "応募時面接予約任意", "面接締切時応募続行", "応募フォーム", "駅チカ・駅ナカ", "オープニングスタッフ", "高校生歓迎", "大学生歓迎", "主婦・主夫歓迎", "シフト制勤務", "短時間勤務（4時間以内）", "時間曜日応相談", "即日勤務OK", "未経験者歓迎", "交通費支給", "交通費一部支給", "社内割引あり", "日祝給料アップ", "社員登用あり", "寮・社宅あり", "まかないあり", "食事補助", "制服貸与", "髪型自由", "服装自由", "土日のみOK", "平日のみOK", "週払いOK", "日払いOK", "土日祝勤務歓迎", "車通勤応相談", "フリーター歓迎", "語学力を活かせる", "研修制度あり", "経験者歓迎", "前払い応相談", "早朝・深夜勤務", "土日祝・面接可", "大量募集", "Wワーク歓迎", "仕事ブランクOK", "カスタム検索キーワード", "媒体", "費用", "定員", "媒体出稿時の名称", "ファイル名", "メモ", "閲覧数（PC)", "閲覧数（SMARTPHONE)", "案件詳細URL", "Indeed広告用参照番号"];

// 新FMT固定列(白背景)。サンプル行(Grit19522)の実際の値をそのまま採用。
const HITOMANE_NEW_FIXED_VALUES = {"案件タイプ": "有料人材紹介案件", "掲載用拠点名": "非公開", "職種カテゴリ": "製造・生産業務（その他）", "雇用形態": "正社員", "早朝": "あり", "朝": "あり", "昼": "あり", "夕方": "あり", "夜": "あり", "深夜": "あり", "基本給_給与タイプ": "月給", "基本給_定額": "なし", "平均所定労働時間": "160", "平均勤務日数": "20", "一律支給される諸手当_定額": "なし", "固定残業代の有無": "なし", "固定残業代の支払額_定額": "なし", "固定残業代の支払額_最低額": "", "固定残業代の支払額_最高額": "", "固定残業時間": "", "固定残業時間を超えた場合の追加支払い": "なし", "試用期間の有無": "あり", "試用期間_期間": "2", "試用期間_単位": "週間", "試用期間_労働条件の差異": "なし", "試用期間_労働条件の差異_給与": "なし", "試用期間_労働条件の差異_労働時間": "なし", "試用期間_労働条件の差異_その他（雇用形態や手当など）": "なし", "試用期間_給与条件_給与タイプ": "", "試用期間_給与条件_定額": "なし", "試用期間_給与条件_最低額": "", "試用期間_給与条件_最高額": "", "試用期間_給与条件_タスク_単位": "", "試用期間_給与条件_タスク_時間": "", "試用期間_一律支給される諸手当_定額": "なし", "試用期間_一律支給される諸手当_最低額": "", "試用期間_一律支給される諸手当_最高額": "", "試用期間_給与条件_固定残業代の有無": "なし", "試用期間_給与条件_固定残業代の支払額_定額": "なし", "試用期間_給与条件_固定残業代の支払額_最低額": "", "試用期間_給与条件_固定残業代の支払額_最高額": "", "試用期間_給与条件_固定残業時間": "", "試用期間_給与条件_固定残業時間を超えた場合の追加支払い": "なし", "地図用テキスト": "勤務地", "地図用タイトル": "勤務地はこちら", "実働時間_固定_1": "なし", "休憩時間_変動_1": "なし", "実働時間_固定_2": "なし", "休憩時間_変動_2": "なし", "実働時間_固定_3": "なし", "休憩時間_変動_3": "なし", "勤務形態_固定時間制": "なし", "勤務形態_シフト制": "あり", "勤務形態_変形労働制": "なし", "勤務形態_フレックスタイム制度": "なし", "勤務形態_専門業務型裁量労働制": "なし", "勤務形態_企画業務型裁量労働制": "なし", "勤務形態_事業場外みなし労働時間制": "なし", "勤務形態_高度プロフェッショナル制": "なし", "Indeed連携用_シフト": "週4日以上OK", "社会保険_厚生年金": "あり", "社会保険_健康保険": "あり", "社会保険_雇用保険": "あり", "社会保険_労災保険": "あり", "選択できない社会保険がある場合の理由": "", "受動喫煙対策_屋内禁煙": "なし", "受動喫煙対策_屋外喫煙可": "なし", "受動喫煙対策_屋内原則禁煙（ただし、適用除外の場所あり）": "あり", "受動喫煙対策_屋内喫煙可": "なし", "受動喫煙対策_屋内喫煙可（ただし、特定の喫煙可能室または喫煙目的室のみ）": "なし", "受動喫煙対策_内定時までに開示": "なし", "担当": "採用担当", "オンライン面接予約機能": "なし", "応募時面接予約任意": "なし", "面接締切時応募続行": "なし", "応募フォーム": "応募項目パターン１", "駅チカ・駅ナカ": "なし", "オープニングスタッフ": "なし", "高校生歓迎": "なし", "大学生歓迎": "なし", "主婦・主夫歓迎": "なし", "シフト制勤務": "なし", "短時間勤務（4時間以内）": "なし", "時間曜日応相談": "なし", "即日勤務OK": "あり", "未経験者歓迎": "あり", "交通費支給": "あり", "交通費一部支給": "なし", "社内割引あり": "なし", "日祝給料アップ": "なし", "社員登用あり": "なし", "寮・社宅あり": "あり", "まかないあり": "なし", "食事補助": "あり", "制服貸与": "あり", "髪型自由": "なし", "服装自由": "なし", "土日のみOK": "なし", "平日のみOK": "なし", "週払いOK": "あり", "日払いOK": "なし", "土日祝勤務歓迎": "なし", "車通勤応相談": "なし", "フリーター歓迎": "あり", "語学力を活かせる": "なし", "研修制度あり": "あり", "経験者歓迎": "あり", "前払い応相談": "なし", "早朝・深夜勤務": "なし", "土日祝・面接可": "なし", "大量募集": "なし", "Wワーク歓迎": "なし", "仕事ブランクOK": "なし", "カスタム検索キーワード": "", "媒体": "自社"}
;

const HITOMANE_EMPLOYMENT_CODE = { '正社員': 1, '契約社員': 2, 'その他': 3 };

const HM_CONFIG_SHEET_NAME = 'ヒトマネ実行設定';
const HM_LIST_SHEET_NAME = '_ヒトマネ_プルダウン用リスト（自動生成・編集不要）';
const HM_USAGE_SHEET_NAME = 'ヒトマネ_アカウント×職種名_使用履歴';
const HM_INSPECTION_SHEET_NAME = 'ヒトマネ_検品シート';
const HM_COOLDOWN_DAYS = 30;
const HM_CONFIG_HEADER_ROW = 2;
const HM_CONFIG_DATA_START_ROW = 4; // 3行目は注意書き欄として空けておく(手入力用、処理対象外)
const HM_CONFIG_MAX_ROWS = 100;
const HM_MAX_ROWS_PER_SHEET = 10000;
const HM_RUN_TIME_LIMIT_MS = 5 * 60 * 1000; // 5分(6分の実行上限に対して安全マージンを確保)
const HM_WRITE_BATCH_SIZE = 1000; // 1回のsetValues()で書き込む行数
const HM_RESUME_TRIGGER_FUNCTION = 'hmRunFromConfig';
const HM_RUN_STATUS_CELL_ROW = 1;
const HM_RUN_STATUS_CELL_COL = 16; // 実行状況列と同じ列(1行目)に全体の進捗を表示する

// トリガー実行時などUIが無い状況でも安全に呼べるalert(失敗時はログにだけ残す)
function hmSafeAlert_(message) {
  try {
    SpreadsheetApp.getUi().alert(message);
  } catch (e) {
    Logger.log('hmSafeAlert_ (UIなしのため表示できず): ' + message);
  }
}

// この関数(hmRunFromConfig)用に残っている自動再開トリガーがあれば削除する
function hmDeleteResumeTriggers_() {
  ScriptApp.getProjectTriggers().forEach(t => {
    if (t.getHandlerFunction() === HM_RESUME_TRIGGER_FUNCTION && t.getEventType() === ScriptApp.EventType.CLOCK) {
      ScriptApp.deleteTrigger(t);
    }
  });
}

function hmWriteRunStatus_(configSh, message) {
  try {
    const nowStr = Utilities.formatDate(new Date(), Session.getScriptTimeZone(), 'HH:mm:ss');
    configSh.getRange(HM_RUN_STATUS_CELL_ROW, HM_RUN_STATUS_CELL_COL).setValue(`${message} (${nowStr}時点)`);
    SpreadsheetApp.flush();
  } catch (e) {
    Logger.log('hmWriteRunStatus_ error: ' + e.message);
  }
}

// ここまでの実績(処理済み予約行数・経過時間)から、残り予約行の完了予定時刻を概算する(あくまで目安)
function hmEstimateEta_(startTime, targetsProcessedThisRun, totalTargetsThisRun) {
  if (targetsProcessedThisRun <= 0) return '';
  const remaining = totalTargetsThisRun - targetsProcessedThisRun;
  if (remaining <= 0) return '';
  const elapsedMs = Date.now() - startTime;
  const avgMsPerTarget = elapsedMs / targetsProcessedThisRun;
  const etaMs = avgMsPerTarget * remaining;
  const etaClock = Utilities.formatDate(new Date(Date.now() + etaMs), Session.getScriptTimeZone(), 'HH:mm');
  const etaMinutes = Math.max(1, Math.round(etaMs / 60000));
  return ` ／ 残り${remaining}件・目安あと約${etaMinutes}分(${etaClock}頃完了予定)`;
}

const HM_CONFIG_COLUMNS = [
  'グループ番号(例:1-1)', '作成日', '通勤か入寮か', '雇用形態', '職種番号(カテゴリ)', '会社名',
  'フォーマット(旧FMT/新FMT)', '原稿数(空欄=勤務地数で作成)', '募集番号の先頭',
  'ステータス(掲載/非掲載)', '画像カテゴリー(必須)', '給与パターン', '夜勤の有無',
  '職種名選択(6重め/7軽めのみ・必須)', 'タイトル末尾ワード(空欄=シートの現在値)',
  '実行状況', '進行状況(待機中/作成中/完了)', '原稿URL'
];
const HM_CONFIG_COL_PROGRESS = 17; // 進行状況列(待機中/作成中/完了)。実行状況列(処理済み判定に使う)とは別の列

// ============================================================
// 土台スプレッドシート(職種名・仕事内容・会社情報マスター等)の切り分け設定
// ============================================================
// 土台データを置く別スプレッドシートのID。このIDのファイルに職種名・仕事内容・会社情報マスター・
// 勤務地・NGエリア・給与パターン・画像カテゴリー一覧・勤務時間パターン・タイトル組み立て用・
// 旧FMT/新FMTテンプレ・職種名管理シートを置く。運用ファイル(このファイル)は実行設定・出力シート・
// 使用履歴・検品シートだけを持つことで、運用ファイル自体を軽く保つ。
const HM_BASE_SPREADSHEET_ID = '1fTDLsTOIcf-JONthvU-60rWqUVSF6mkvK2HmYcSb3CI';

// hmClassifySheet_が返すロールのうち、「土台」とみなすものの接頭辞一覧
const HM_BASE_SHEET_ROLE_PREFIXES = [
  '職種名', '仕事内容(', '職種内容ペア(', 'パーツ(PR等・正社員)', '会社情報マスター',
  '勤務地・NGエリア', '給与パターン', '画像カテゴリー一覧', '勤務時間パターン(新FMT用',
  '組み立てタイトル(募集職種用)', '旧FMT(テンプレ)', '新FMT(テンプレ・未対応)',
  '職種名管理(6重め/7軽め使用状況)'
];
function hmIsBaseSheetRole_(role) {
  return HM_BASE_SHEET_ROLE_PREFIXES.some(prefix => role.indexOf(prefix) === 0);
}

// 【1回だけ実行する移行用】今のスプレッドシートから「土台」シートを判定し、
// HM_BASE_SPREADSHEET_ID へコピーする。元シートは削除しない(内容を見比べてから手動で削除してください)。
// 既に土台ファイル側に同名シートがある場合は、入れ替える(再実行しても重複コピーは作らない)。
function hmMoveBaseSheetsToBaseFile_() {
  const srcSs = SpreadsheetApp.getActiveSpreadsheet();
  const destSs = SpreadsheetApp.openById(HM_BASE_SPREADSHEET_ID);
  const moved = [];
  const skipped = [];

  srcSs.getSheets().forEach(sh => {
    const role = hmClassifySheet_(sh);
    if (!hmIsBaseSheetRole_(role)) { skipped.push(`${sh.getName()} [${role}]`); return; }
    const existing = destSs.getSheetByName(sh.getName());
    if (existing) destSs.deleteSheet(existing);
    sh.copyTo(destSs).setName(sh.getName());
    moved.push(`${sh.getName()} [${role}]`);
  });

  // 新規スプレッドシート作成時の初期シート(シート1/Sheet1)が空のまま残っていたら削除
  const initialSheet = destSs.getSheetByName('シート1') || destSs.getSheetByName('Sheet1');
  if (initialSheet && destSs.getSheets().length > 1) destSs.deleteSheet(initialSheet);

  const msg = `コピーしたシート: ${moved.length}件\n${moved.join('\n')}\n\n対象外(運用ファイルに残す)シート: ${skipped.length}件\n${skipped.join('\n')}`;
  Logger.log(msg);
  hmSafeAlert_('土台シートのコピー結果\n\n' + msg);
}

// ============================================================
// メニュー
// ============================================================
function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('ヒトマネ自動生成')
    .addItem('①シート診断', 'hmDiagnoseSheets')
    .addItem('②実行設定を作成/更新', 'hmSetupConfigSheet')
    .addItem('③予約リストを一括実行', 'hmRunFromConfig')
    .addItem('④生成済み原稿シートを一括削除', 'hmDeleteAllOutputSheets')
    .addItem('⑤検品シートを作成', 'hmCreateInspectionSheet')
    .addItem('⑥職種名管理を使用履歴と同期', 'hmSyncPairedTitleUsage_menu')
    .addToUi();
}

// ============================================================
// ①シート診断
// ============================================================
// 運用ファイル(実行設定・出力シート等)と土台ファイル(職種名・仕事内容等)の両方を診断する
function hmDiagnoseSheets() {
  const results = [];
  const scan = (targetSs, label) => {
    targetSs.getSheets().forEach(sh => {
      if (sh.getLastRow() === 0) return;
      const role = hmClassifySheet_(sh);
      results.push(`[${label}] ${sh.getName()} → ${role}`);
    });
  };
  scan(SpreadsheetApp.getActiveSpreadsheet(), '運用');
  scan(SpreadsheetApp.openById(HM_BASE_SPREADSHEET_ID), '土台');
  const msg = results.join('\n');
  Logger.log(msg);
  SpreadsheetApp.getUi().alert('シート診断結果', msg, SpreadsheetApp.getUi().ButtonSet.OK);
}

// ============================================================
// 【サイズ調査用】各シートの「使用範囲」の広さ(行数×列数)を調べて、重そうなシートを見つける。
// 見た目のデータ件数が少なくても、過去の貼り付けや書式設定などで使用範囲だけが広がっている
// シートがあると、それがファイル全体を重くしている原因になっていることが多い。
// 値やセルの中身は読まない(メタ情報だけを見る)ので、これ自体が重くてタイムアウトすることはない。
// ============================================================
function hmReportSheetWeight() {
  const report = (targetSs, label) => targetSs.getSheets().map(sh => {
    const maxRows = sh.getMaxRows();
    const maxCols = sh.getMaxColumns();
    const lastRow = sh.getLastRow();
    const lastCol = sh.getLastColumn();
    let condFmtCount = 0;
    try { condFmtCount = sh.getConditionalFormatRules().length; } catch (e) {}
    return { label, name: sh.getName(), maxRows, maxCols, lastRow, lastCol, cells: maxRows * maxCols, condFmtCount };
  });

  const all = [
    ...report(SpreadsheetApp.getActiveSpreadsheet(), '運用'),
    ...report(SpreadsheetApp.openById(HM_BASE_SPREADSHEET_ID), '土台')
  ];
  all.sort((a, b) => b.cells - a.cells);

  const lines = all.map(s =>
    `[${s.label}] ${s.name} : 使用範囲${s.maxRows}行×${s.maxCols}列(セル数約${s.cells.toLocaleString()}) ／ 実データ${s.lastRow}行×${s.lastCol}列 ／ 条件付き書式${s.condFmtCount}件`
  );
  const msg = lines.join('\n');
  Logger.log(msg);

  // アラートが長すぎると表示できないことがあるので、上位20件だけ表示する(全件は実行ログを参照)
  const topMsg = lines.slice(0, 20).join('\n');
  hmSafeAlert_('シート重さ調査(使用範囲のセル数が多い順・上位20件)\n\n' + topMsg + '\n\n※全件はApps Scriptの「実行数」画面のログで確認できます。');
}

function hmGetHeaderRowGuess_(sh) {
  const maxCheck = Math.min(6, sh.getLastRow());
  let best = 1, bestCount = -1;
  for (let r = 1; r <= maxCheck; r++) {
    const vals = sh.getRange(r, 1, 1, Math.min(sh.getLastColumn(), 30)).getValues()[0];
    const count = vals.filter(v => v !== '' && v !== null).length;
    if (count > bestCount) { bestCount = count; best = r; }
  }
  return best;
}

function hmGetTopBlockText_(sh) {
  const maxRow = Math.min(6, sh.getLastRow());
  const maxCol = Math.min(sh.getLastColumn(), 40);
  if (maxRow < 1 || maxCol < 1) return '';
  const vals = sh.getRange(1, 1, maxRow, maxCol).getValues();
  return vals.map(row => row.join(' ')).join(' ');
}

// 「画像カテゴリー」というラベルが無く、代わりに「軽作業」「製造」「工場」のような
// 職種系の名前が直接列見出しになっているシート用に、見出し行を広い範囲(20行)から探す
// 「勤務時間」シート用: 見出し行が「勤務時間_開始_1」のような文字列ではなく、
// 「CB」「CC」「CW」のような新FMTの列記号そのものになっているケースに対応する
const HM_WORKTIME_COLUMN_LETTERS = ['CW', 'CB', 'CC', 'CE', 'CH', 'CI', 'CJ', 'CL', 'CO', 'CP', 'CQ', 'CS', 'CV'];
function hmFindWorkTimeHeaderRow_(sh) {
  const maxRow = Math.min(sh.getLastRow(), 10);
  const maxCol = Math.min(sh.getLastColumn(), 25);
  for (let r = 1; r <= maxRow; r++) {
    const vals = sh.getRange(r, 1, 1, maxCol).getValues()[0].map(v => String(v).trim());
    const matchCount = vals.filter(v => HM_WORKTIME_COLUMN_LETTERS.indexOf(v) >= 0).length;
    if (matchCount >= 5) return r;
  }
  return -1;
}

function hmFindImageHeaderRow_(sh) {
  const lastColForImg = Math.min(sh.getLastColumn(), 20);
  const maxRowForImg = Math.min(sh.getLastRow(), 20);
  const imageLikeLabels = ['軽作業', '製造', '工場', '入寮', '寮画像', 'クルマ', '梱包', '検査', '電子部品', '半導体', 'ピッキング', '仕分け', 'シール貼り'];
  for (let r = 1; r <= maxRowForImg; r++) {
    const headerVals = sh.getRange(r, 1, 1, lastColForImg).getValues()[0].map(v => String(v).trim());
    const matchCount = headerVals.filter(v => imageLikeLabels.indexOf(v) >= 0).length;
    if (matchCount >= 2) return r;
  }
  return -1;
}

function hmFindSignatureRow_(sh, requiredSubstrings) {
  const maxRow = Math.min(6, sh.getLastRow());
  const maxCol = Math.min(sh.getLastColumn(), 40);
  for (let r = 1; r <= maxRow; r++) {
    const vals = sh.getRange(r, 1, 1, maxCol).getValues()[0].map(v => String(v));
    const joined = vals.join(' ');
    if (requiredSubstrings.every(s => joined.indexOf(s) >= 0)) return r;
  }
  return hmGetHeaderRowGuess_(sh);
}

function hmFindHeaderRowIndex_(sh, headerList, minMatch) {
  const maxCheck = Math.min(6, sh.getLastRow());
  const maxCol = Math.min(sh.getLastColumn(), 260);
  for (let r = 1; r <= maxCheck; r++) {
    const vals = sh.getRange(r, 1, 1, maxCol).getValues()[0];
    const matchCount = vals.filter(v => headerList.indexOf(String(v)) >= 0).length;
    if (matchCount >= minMatch) return r;
  }
  return -1;
}

function hmClassifySheet_(sh) {
  const name = sh.getName();
  if (name === HM_CONFIG_SHEET_NAME) return 'ヒトマネ実行設定シート';
  if (name === HM_LIST_SHEET_NAME) return 'プルダウン用リスト(自動生成・無視してOK)';
  if (name === HM_USAGE_SHEET_NAME) return '使用履歴シート(自動生成)';
  if (name === HM_CONTENT_USAGE_SHEET_NAME) return '仕事内容使用履歴シート(自動生成)';
  if (name === HM_INSPECTION_SHEET_NAME) return '検品シート(自動生成)';
  if (name.indexOf('ヒトマネ出力_') === 0) return '生成済み出力シート(過去分)';

  // 新FMT(テンプレ): まだ生成ロジック未対応。シート名で区別し、誤って旧FMTとして読み込まないようにする
  if (name.indexOf('新FMT') >= 0) return '新FMT(テンプレ・未対応)';
  if (name === '職種名管理') return '職種名管理(6重め/7軽め使用状況)';
  if (name === 'タイトル') return '組み立てタイトル(募集職種用)';
  // 旧FMT(テンプレ): ヒトマネ109列見出しが入っているシート(サンプル行=固定値の元)
  // ※260列分の読み込みは重いため、列数が明らかに少ない(100列未満)シートは最初からスキップする
  if (sh.getLastColumn() >= 100 && hmFindHeaderRowIndex_(sh, HITOMANE_HEADERS, 40) >= 0) return '旧FMT(テンプレ)';

  const text = hmGetTopBlockText_(sh);
  if (text.indexOf('低額') >= 0 && text.indexOf('基本') >= 0 && text.indexOf('高額') >= 0) return '給与パターン';
  if (text.indexOf('画像カテゴリー') >= 0) return '画像カテゴリー一覧';
  // 「画像カテゴリー」という見出しが無くても、「軽作業」「製造」「工場」のような職種系の名前が
  // 複数、列見出しとして横に並んでいる場合は画像一覧とみなす
  {
    if (hmFindImageHeaderRow_(sh) >= 0) return '画像カテゴリー一覧';
  }
  if (text.indexOf('都道府県') >= 0 && text.indexOf('市区町村') >= 0) return '勤務地・NGエリア';
  if (text.indexOf('会社名') >= 0 && (text.indexOf('応募時メール送信先1') >= 0 || text.indexOf('拠点コード') >= 0)) return '会社情報マスター';
  if (text.indexOf('PR') >= 0 && text.indexOf('応募資格') >= 0 && text.indexOf('待遇') >= 0) return 'パーツ(PR等・正社員)';
  if ((text.indexOf('勤務時間_開始_1') >= 0 && text.indexOf('勤務時間_終了_1') >= 0) || hmFindWorkTimeHeaderRow_(sh) >= 0) {
    if (name.indexOf('夜勤あり') >= 0) return '勤務時間パターン(新FMT用・夜勤あり)';
    if (name.indexOf('夜勤なし') >= 0) return '勤務時間パターン(新FMT用・夜勤なし)';
    return '勤務時間パターン(新FMT用)'; // 夜勤の区別がない従来型の単一シート(後方互換用)
  }

  // 重め/軽めシート: A列=職種名, B列=アルファベット, D列以降=お仕事内容 が1シートにまとまっている特殊タイプ
  const heavyLightMatch = name.match(/^\d+(重め|軽め)$/);
  if (heavyLightMatch) return `職種内容ペア(${heavyLightMatch[1]})`;

  const m = name.match(/^\d+(.+)$/);
  if (m && HITOMANE_CATEGORY_NAMES.indexOf(m[1]) >= 0) return `仕事内容(${m[1]})`;
  const matchedCategory = HITOMANE_CATEGORY_NAMES.find(c => name === c || name.indexOf(c) >= 0);
  if (matchedCategory) return `仕事内容(${matchedCategory})`;

  const headerRow = hmGetHeaderRowGuess_(sh);
  const lastCol = Math.min(sh.getLastColumn(), 30);
  const headers = sh.getRange(headerRow, 1, 1, lastCol).getValues()[0].map(v => String(v));
  const numberedCategoryCount = headers.filter(h => /^\d+\S/.test(h)).length;
  if (numberedCategoryCount >= 3) return '職種名';

  return '(未分類 - 手動確認が必要)';
}

// ============================================================
// コンテンツバンクの読み込み
// ============================================================
// 土台データ(職種名・仕事内容・会社情報マスター等)は、運用ファイルではなく
// HM_BASE_SPREADSHEET_ID の土台ファイルから読み込む
function hmBuildContentBank_() {
  const ss = SpreadsheetApp.openById(HM_BASE_SPREADSHEET_ID);
  const sheets = ss.getSheets();

  const bank = {
    jobTitles: {}, jobContents: {}, parts: {}, companies: {}, locations: [], ngByCompany: {},
    fixedTemplateSample: {}, salaryPatterns: {}, imagesByCategory: {}, imageCategoryByJobCategory: {},
    pairedJobData: {}, // { '重め': [{title, letter, contentOptions}, ...], '軽め': [...] }
    titleComponents: { personas: [], appeals: [], dedupWord: '' }, // 「タイトル」シート由来: 募集職種の組み立て用パーツ(ペルソナ句・アピール句・重複対策ワード)
    workTimePatterns: [], // 新FMT用(夜勤の区別がない従来型シートのみ、後方互換用)
    workTimePatternsByShift: { '夜勤あり': [], '夜勤なし': [] }, // 新FMT用: 夜勤あり/なしシートごとに分けて保持
  };

  sheets.forEach(sh => {
    if (sh.getLastRow() < 1) return;
    const role = hmClassifySheet_(sh);
    const lastCol = sh.getLastColumn();
    const lastRow = sh.getLastRow();

    if (role === '職種名') {
      const hRow = hmGetHeaderRowGuess_(sh);
      const headers = sh.getRange(hRow, 1, 1, lastCol).getValues()[0];
      const data = sh.getRange(hRow + 1, 1, lastRow - hRow, lastCol).getValues();
      headers.forEach((h, colIdx) => {
        if (!/^\d+\S/.test(String(h))) return;
        const list = [];
        data.forEach(row => {
          const v = row[colIdx];
          if (v !== '' && v !== null) list.push(String(v));
        });
        bank.jobTitles[String(h)] = list;
      });
    } else if (role === '組み立てタイトル(募集職種用)') {
      // 列構成: 連番|連番2|「|職種名(参考・未使用)|」|ペルソナ句|／|夜勤テキスト|／|アピール句|／|重複対策ワード|完成文|文字数
      // 実際のローテーション職種名と組み合わせるため、ペルソナ句・アピール句・重複対策ワードだけを個別に抽出する
      // (このシートに書かれた職種名の言い回し自体は使わない)
      const scanRows = Math.min(lastRow, 500);
      const allVals = sh.getRange(1, 1, scanRows, lastCol).getValues();

      const personas = new Set();
      const appeals = new Set();
      let dedupWord = '';
      allVals.forEach(row => {
        if (!/^\d+$/.test(String(row[0]).trim())) return; // A列が連番の行だけを実データとみなす
        const persona = row[5];
        const appeal = row[9];
        const dedup = row[11];
        if (persona) personas.add(String(persona));
        if (appeal) appeals.add(String(appeal));
        if (dedup) dedupWord = String(dedup); // 最後に見つかった値(現在値)を採用
      });
      bank.titleComponents.personas = Array.from(personas);
      bank.titleComponents.appeals = Array.from(appeals);
      bank.titleComponents.dedupWord = dedupWord;
    } else if (role.indexOf('職種内容ペア(') === 0) {
      // A列=職種名, B列=アルファベット, D列以降=お仕事内容の候補(1セル=1パターン。生成時にランダムで1つ選ぶ)
      const category = role.slice(7, -1); // '重め' または '軽め'
      const hRow = hmFindSignatureRow_(sh, ['職種名']);
      const dataStartRow = hRow + 1;
      if (!bank.pairedJobData[category]) bank.pairedJobData[category] = [];
      if (lastRow >= dataStartRow) {
        const numDataRows = lastRow - dataStartRow + 1;
        const contentColStart = 4; // D列
        const contentColCount = Math.max(lastCol - contentColStart + 1, 1);
        const titleVals = sh.getRange(dataStartRow, 1, numDataRows, 1).getValues();
        const letterVals = sh.getRange(dataStartRow, 2, numDataRows, 1).getValues();
        const contentVals = sh.getRange(dataStartRow, contentColStart, numDataRows, contentColCount).getValues();
        for (let i = 0; i < numDataRows; i++) {
          const title = titleVals[i][0];
          if (!title) continue;
          const letter = letterVals[i][0] ? String(letterVals[i][0]).trim() : '';
          const contentOptions = contentVals[i].filter(v => v !== '' && v !== null).map(String);
          bank.pairedJobData[category].push({ title: String(title), letter, contentOptions });
        }
      }
    } else if (role.indexOf('仕事内容(') === 0) {
      const category = role.slice(5, -1);
      if (!bank.jobContents[category]) bank.jobContents[category] = [];
      if (lastRow >= 1 && lastCol >= 1) {
        const all = sh.getRange(1, 1, lastRow, lastCol).getValues();
        all.forEach(row => {
          row.forEach(v => {
            if (v !== '' && v !== null) bank.jobContents[category].push(String(v));
          });
        });
      }
    } else if (role === 'パーツ(PR等・正社員)') {
      const hRow = hmFindSignatureRow_(sh, ['PR', '応募資格']);
      const headers = sh.getRange(hRow, 1, 1, lastCol).getValues()[0];
      let dataStartRow = hRow + 1;
      const nextRowVals = sh.getRange(dataStartRow, 1, 1, lastCol).getValues()[0];
      if (nextRowVals.some(v => /文字まで|文字以内/.test(String(v)))) dataStartRow += 1;
      const data = sh.getRange(dataStartRow, 1, lastRow - dataStartRow + 1, lastCol).getValues();
      headers.forEach((h, colIdx) => {
        const key = String(h);
        if (!key) return;
        if (!bank.parts[key]) bank.parts[key] = [];
        data.forEach(row => {
          const v = row[colIdx];
          if (v !== '' && v !== null && !/文字まで|文字以内/.test(String(v))) bank.parts[key].push(String(v));
        });
      });
    } else if (role === '会社情報マスター') {
      const hRow = hmFindSignatureRow_(sh, ['会社名']);
      const headers = sh.getRange(hRow, 1, 1, lastCol).getValues()[0];
      const data = sh.getRange(hRow + 1, 1, lastRow - hRow, lastCol).getValues();
      const colIndex = {};
      headers.forEach((h, i) => colIndex[String(h)] = i);
      data.forEach(row => {
        const name = row[colIndex['会社名']];
        if (!name) return;
        const obj = {};
        // 「応募方法」のように同名列が複数ある場合、1回目=obj['応募方法']、2回目=obj['応募方法#2']として保持する
        const seenNames = {};
        headers.forEach((h, i) => {
          const key = String(h);
          if (!key) return;
          seenNames[key] = (seenNames[key] || 0) + 1;
          const propKey = seenNames[key] >= 2 ? `${key}#${seenNames[key]}` : key;
          obj[propKey] = row[i];
        });
        bank.companies[String(name)] = obj;
      });
    } else if (role === '勤務地・NGエリア') {
      const hRow = hmFindSignatureRow_(sh, ['都道府県', '市区町村']);
      const headers = sh.getRange(hRow, 1, 1, lastCol).getValues()[0];
      const data = sh.getRange(hRow + 1, 1, lastRow - hRow, lastCol).getValues();
      const colIndex = {};
      headers.forEach((h, i) => colIndex[String(h)] = i);
      const prefCol = colIndex['都道府県'];
      const cityCol = colIndex['市区町村'];
      data.forEach(row => {
        const pref = row[prefCol];
        const city = row[cityCol];
        if (pref) bank.locations.push({ pref: String(pref), city: String(city || '') });
      });
      headers.forEach((h, colIdx) => {
        const key = String(h);
        if (!key) return;
        if (['都道府県', '市区町村'].indexOf(key) >= 0 || key.indexOf('合体') >= 0) return;
        const ngs = [];
        data.forEach(row => {
          const v = row[colIdx];
          if (v !== '' && v !== null) ngs.push(String(v));
        });
        if (ngs.length) bank.ngByCompany[key] = ngs;
      });
    } else if (role === '給与パターン') {
      const blocks = [{ name: '低額', startCol: 1 }, { name: '基本', startCol: 8 }, { name: '高額', startCol: 15 }];
      const dataStartRow = 4;
      if (lastRow >= dataStartRow) {
        const numDataRows = lastRow - dataStartRow + 1;
        blocks.forEach(b => {
          const lowerVals = sh.getRange(dataStartRow, b.startCol, numDataRows, 1).getValues();
          const upperVals = sh.getRange(dataStartRow, b.startCol + 3, numDataRows, 1).getValues();
          const detailVals = sh.getRange(dataStartRow, b.startCol + 5, numDataRows, 1).getValues();
          const list = [];
          for (let i = 0; i < numDataRows; i++) {
            const lower = lowerVals[i][0];
            if (lower === '' || lower === null) continue;
            const upper = upperVals[i][0];
            list.push({
              lower: String(Math.round(Number(lower))),
              upper: (upper === '' || upper === null) ? '' : String(Math.round(Number(upper))),
              detail: String(detailVals[i][0] || ''),
            });
          }
          if (list.length) bank.salaryPatterns[b.name] = list;
        });
      }
    } else if (role === '画像カテゴリー一覧') {
      let hRow = hmFindImageHeaderRow_(sh);
      if (hRow < 0) hRow = hmFindSignatureRow_(sh, ['画像カテゴリー']);
      const headers = sh.getRange(hRow, 1, 1, lastCol).getValues()[0];
      const mappingRowVals = sh.getRange(hRow + 1, 1, 1, lastCol).getValues()[0];
      const isMappingRow = String(mappingRowVals[0]).indexOf('職種') >= 0;
      const dataStartOffset = isMappingRow ? 2 : 1;
      const data = sh.getRange(hRow + dataStartOffset, 1, lastRow - hRow - dataStartOffset + 1, lastCol).getValues();
      headers.forEach((h, colIdx) => {
        const key = String(h);
        if (!key || key === '画像カテゴリー') return;
        const list = [];
        data.forEach(row => {
          const v = row[colIdx];
          if (v !== '' && v !== null) list.push(String(v));
        });
        if (list.length) bank.imagesByCategory[key] = list;
        if (isMappingRow) {
          const mappingText = String(mappingRowVals[colIdx] || '');
          const jobCats = mappingText.split(/[・\s]+/).map(s => s.trim()).filter(Boolean);
          jobCats.forEach(jc => {
            if (HITOMANE_CATEGORY_NAMES.indexOf(jc) >= 0) bank.imageCategoryByJobCategory[jc] = key;
          });
        }
      });
    } else if (role.indexOf('勤務時間パターン(新FMT用') === 0) {
      const targetArray = role.indexOf('夜勤あり') >= 0 ? bank.workTimePatternsByShift['夜勤あり']
        : role.indexOf('夜勤なし') >= 0 ? bank.workTimePatternsByShift['夜勤なし']
        : bank.workTimePatterns; // 夜勤の区別が無い従来型シート

      const letterHRow = hmFindWorkTimeHeaderRow_(sh);
      if (letterHRow >= 0) {
        // 見出し行が「CB」「CC」のような列記号そのもの: 記号→実際のシート列番号の対応表を作ってから読む
        const maxCol = Math.min(sh.getLastColumn(), 25);
        const headerVals = sh.getRange(letterHRow, 1, 1, maxCol).getValues()[0].map(v => String(v).trim());
        const colOf = {};
        headerVals.forEach((v, i) => { if (HM_WORKTIME_COLUMN_LETTERS.indexOf(v) >= 0) colOf[v] = i + 1; }); // 1始まりの列番号
        const dataStartRow = letterHRow + 1;
        if (lastRow >= dataStartRow) {
          const numDataRows = lastRow - dataStartRow + 1;
          const data = sh.getRange(dataStartRow, 1, numDataRows, maxCol).getValues();
          const get = (row, letter) => (colOf[letter] ? row[colOf[letter] - 1] : '') || '';
          data.forEach(row => {
            const start1 = get(row, 'CB'), end1 = get(row, 'CC');
            if (!start1 && !end1) return;
            targetArray.push({
              supplement: get(row, 'CW'), start1, end1, min1: get(row, 'CE'), break1: get(row, 'CH'),
              start2: get(row, 'CI'), end2: get(row, 'CJ'), min2: get(row, 'CL'), break2: get(row, 'CO'),
              start3: get(row, 'CP'), end3: get(row, 'CQ'), min3: get(row, 'CS'), break3: get(row, 'CV'),
            });
          });
        }
      } else {
        // 見出しが「勤務時間_補足」等の文字列そのものの通常パターン
        // 見出し: 勤務時間_補足, 開始_1, 終了_1, 実働最小_1, 休憩_1, 開始_2, 終了_2, 実働最小_2, 休憩_2, 開始_3, 終了_3, 実働最小_3, 休憩_3
        const hRow = hmFindSignatureRow_(sh, ['勤務時間_開始_1']);
        let dataStartRow = hRow + 1;
        const nextRowVals = sh.getRange(dataStartRow, 1, 1, 13).getValues()[0];
        const looksLikeColumnLetters = nextRowVals.filter(v => /^[A-Z]{1,3}$/.test(String(v).trim())).length >= 5;
        if (looksLikeColumnLetters) dataStartRow += 1;

        if (lastRow >= dataStartRow) {
          const numDataRows = lastRow - dataStartRow + 1;
          const vals = sh.getRange(dataStartRow, 1, numDataRows, 13).getValues();
          vals.forEach(row => {
            if (!row[1] && !row[2]) return;
            targetArray.push({
              supplement: row[0] || '', start1: row[1] || '', end1: row[2] || '', min1: row[3] || '', break1: row[4] || '',
              start2: row[5] || '', end2: row[6] || '', min2: row[7] || '', break2: row[8] || '',
              start3: row[9] || '', end3: row[10] || '', min3: row[11] || '', break3: row[12] || '',
            });
          });
        }
      }
    } else if (role === '旧FMT(テンプレ)') {
      // サンプル行(固定列の実例)を1行だけ拾っておく(参考表示・検証用)
      const hRow = hmFindHeaderRowIndex_(sh, HITOMANE_HEADERS, 40);
      for (let r = hRow + 1; r <= lastRow; r++) {
        const vals = sh.getRange(r, 1, 1, lastCol).getValues()[0];
        if (vals.some(v => v !== '' && v !== null)) {
          const headers = sh.getRange(hRow, 1, 1, lastCol).getValues()[0];
          headers.forEach((h, i) => { if (h) bank.fixedTemplateSample[String(h)] = vals[i]; });
          break;
        }
      }
    }
  });

  return bank;
}

// ============================================================
// ②実行設定の作成
// ============================================================
function hmSetupConfigSheet() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sh = ss.getSheetByName(HM_CONFIG_SHEET_NAME);
  if (!sh) sh = ss.insertSheet(HM_CONFIG_SHEET_NAME);

  const maxRows = Math.max(sh.getMaxRows(), HM_CONFIG_DATA_START_ROW + HM_CONFIG_MAX_ROWS);
  const maxCols = Math.max(sh.getMaxColumns(), HM_CONFIG_COLUMNS.length + 5);
  sh.getRange(1, 1, maxRows, maxCols).clearDataValidations();
  // 過去のバージョンでA1が現在より広い範囲(P列以降)まで結合されている場合、
  // clear()だけでは結合状態が残ってしまうことがあるため、明示的に結合を解除しておく
  sh.getRange(1, 1, maxRows, maxCols).breakApart();
  sh.clear();

  const bank = hmWithRetry_(() => hmBuildContentBank_()); // 読み取り専用なので、丸ごとリトライしても安全
  const categories = Object.keys(bank.jobTitles).filter(k => bank.jobTitles[k].length > 0);
  // 重め/軽めは「職種名」タブではなく専用シート(6重め/7軽め)からタイトルを取得するため、
  // bank.jobTitlesには入らない。カテゴリ選択肢として表示するため、ここで追加する。
  Object.keys(bank.pairedJobData || {}).forEach(cat => {
    if (bank.pairedJobData[cat] && bank.pairedJobData[cat].length) {
      const label = HITOMANE_CATEGORY_NUMBER_LABEL[cat] || cat;
      if (categories.indexOf(label) < 0) categories.push(label);
    }
  });
  categories.sort((a, b) => (parseInt(a, 10) || 0) - (parseInt(b, 10) || 0));
  const companyNames = Object.keys(bank.companies);

  let listSh = ss.getSheetByName(HM_LIST_SHEET_NAME);
  if (listSh) ss.deleteSheet(listSh);
  listSh = ss.insertSheet(HM_LIST_SHEET_NAME);
  listSh.getRange(1, 1).setValue('職種番号一覧');
  listSh.getRange(1, 2).setValue('会社名一覧');
  if (categories.length) listSh.getRange(2, 1, categories.length, 1).setValues(categories.map(c => [c]));
  if (companyNames.length) listSh.getRange(2, 2, companyNames.length, 1).setValues(companyNames.map(c => [c]));
  // 6重め/7軽めの職種名選択肢: 「6重め｜職種名」の形式で表示し、カテゴリを区別できるようにする
  const pairedTitleOptions = [];
  ['重め', '軽め'].forEach(cat => {
    const label = HITOMANE_CATEGORY_NUMBER_LABEL[cat] || cat;
    (bank.pairedJobData[cat] || []).forEach(e => {
      pairedTitleOptions.push(`${label}｜${e.title}`);
    });
  });
  if (pairedTitleOptions.length) listSh.getRange(2, 6, pairedTitleOptions.length, 1).setValues(pairedTitleOptions.map(c => [c]));
  listSh.hideSheet();

  // タイトルの結合は原稿URL列の手前まで。実行状況列(HM_RUN_STATUS_CELL_COL)の1行目は進捗表示用に空けておく
  const TITLE_MERGE_WIDTH = HM_RUN_STATUS_CELL_COL - 1;
  sh.getRange(1, 1).setValue('ヒトマネ原稿(旧FMT) 自動生成 予約リスト（1行＝1回の生成予約）').setFontWeight('bold').setFontSize(14);
  sh.getRange(1, 1, 1, TITLE_MERGE_WIDTH).merge();

  // ③の進行状況を表示するセル。手動実行・自動再開のどちらでも、ここを見れば今の状況が分かる。
  sh.getRange(HM_RUN_STATUS_CELL_ROW, HM_RUN_STATUS_CELL_COL).setValue('停止中').setFontWeight('bold');

  HM_CONFIG_COLUMNS.forEach((h, i) => {
    sh.getRange(HM_CONFIG_HEADER_ROW, i + 1).setValue(h).setFontWeight('bold').setFontColor('#FFFFFF').setBackground('#4472C4');
  });

  // ---- 3行目: 注意書き欄(自由に手入力してもらう。処理対象外なのでスクリプトからは触らない) ----
  sh.getRange(3, 1).setValue('※このセル(3行目)は自由に注意書きを入力できます。4行目以降が予約データとして処理されます。');
  sh.getRange(3, 1, 1, HM_CONFIG_COLUMNS.length).merge();
  sh.getRange(3, 1).setFontColor('#888888').setFontStyle('italic');

  sh.getRange(HM_CONFIG_DATA_START_ROW, 1, HM_CONFIG_MAX_ROWS, 1).setNumberFormat('@');

  const salaryPatternOptions = ['基本', '高額', '低額'].filter(p => bank.salaryPatterns[p]);
  const imageCategories = Object.keys(bank.imagesByCategory);
  const nightShiftOptions = ['夜勤あり', '夜勤なし'].filter(n => hmFindPartsKeyAll_(bank, ['勤務時間', n]));

  const exampleRow = ['1-1', new Date(), '通勤', '正社員', categories[0] || '', companyNames[0] || '', '旧FMT', 500, 'CB', '掲載', imageCategories[0] || '軽作業', salaryPatternOptions[0] || '', nightShiftOptions[0] || '', '', '', '', '', ''];
  sh.getRange(HM_CONFIG_DATA_START_ROW, 1, 1, exampleRow.length).setValues([exampleRow]);
  sh.getRange(HM_CONFIG_DATA_START_ROW, 1, 1, exampleRow.length).setBackground('#FFF2CC');

  const commuteRule = SpreadsheetApp.newDataValidation().requireValueInList(['通勤', '入寮'], true).build();
  sh.getRange(HM_CONFIG_DATA_START_ROW, 3, HM_CONFIG_MAX_ROWS, 1).setDataValidation(commuteRule);

  const employmentRule = SpreadsheetApp.newDataValidation().requireValueInList(['正社員', '契約社員', 'その他'], true).build();
  sh.getRange(HM_CONFIG_DATA_START_ROW, 4, HM_CONFIG_MAX_ROWS, 1).setDataValidation(employmentRule);

  if (categories.length) {
    const catRange = listSh.getRange(2, 1, categories.length, 1);
    sh.getRange(HM_CONFIG_DATA_START_ROW, 5, HM_CONFIG_MAX_ROWS, 1)
      .setDataValidation(SpreadsheetApp.newDataValidation().requireValueInRange(catRange, true).build());
  }
  if (companyNames.length) {
    const compRange = listSh.getRange(2, 2, companyNames.length, 1);
    sh.getRange(HM_CONFIG_DATA_START_ROW, 6, HM_CONFIG_MAX_ROWS, 1)
      .setDataValidation(SpreadsheetApp.newDataValidation().requireValueInRange(compRange, true).build());
  }

  const formatRule = SpreadsheetApp.newDataValidation().requireValueInList(['旧FMT', '新FMT'], true).build();
  sh.getRange(HM_CONFIG_DATA_START_ROW, 7, HM_CONFIG_MAX_ROWS, 1).setDataValidation(formatRule);

  const statusRule = SpreadsheetApp.newDataValidation().requireValueInList(['掲載', '非掲載'], true).build();
  sh.getRange(HM_CONFIG_DATA_START_ROW, 10, HM_CONFIG_MAX_ROWS, 1).setDataValidation(statusRule);

  if (imageCategories.length) {
    const imgRange = listSh.getRange(2, 3, imageCategories.length, 1);
    listSh.getRange(1, 3).setValue('画像カテゴリー一覧');
    listSh.getRange(2, 3, imageCategories.length, 1).setValues(imageCategories.map(c => [c]));
    sh.getRange(HM_CONFIG_DATA_START_ROW, 11, HM_CONFIG_MAX_ROWS, 1)
      .setDataValidation(SpreadsheetApp.newDataValidation().requireValueInRange(imgRange, true).setAllowInvalid(true).build());
  }

  if (salaryPatternOptions.length) {
    const salaryRule = SpreadsheetApp.newDataValidation().requireValueInList(salaryPatternOptions, true).build();
    sh.getRange(HM_CONFIG_DATA_START_ROW, 12, HM_CONFIG_MAX_ROWS, 1).setDataValidation(salaryRule);
  }

  if (nightShiftOptions.length) {
    const nightRule = SpreadsheetApp.newDataValidation().requireValueInList(nightShiftOptions, true).build();
    sh.getRange(HM_CONFIG_DATA_START_ROW, 13, HM_CONFIG_MAX_ROWS, 1).setDataValidation(nightRule);
  }

  if (pairedTitleOptions.length) {
    const pairedRange = listSh.getRange(2, 6, pairedTitleOptions.length, 1);
    const pairedRule = SpreadsheetApp.newDataValidation().requireValueInRange(pairedRange, true).setAllowInvalid(true).build();
    sh.getRange(HM_CONFIG_DATA_START_ROW, 14, HM_CONFIG_MAX_ROWS, 1).setDataValidation(pairedRule);
  }

  HM_CONFIG_COLUMNS.forEach((h, i) => sh.setColumnWidth(i + 1, i === 0 ? 100 : 170));
  sh.setFrozenRows(3); // 1行目(タイトル)〜3行目(注意書き)まで固定する

  SpreadsheetApp.getUi().alert(
    '「' + HM_CONFIG_SHEET_NAME + '」を作成/更新しました。\n\n' +
    '3行目は注意書き欄として自由に使えます(処理対象外)。\n' +
    '4行目以降に、1行＝1回分の生成条件をプルダウンで入力してください(' + HM_CONFIG_MAX_ROWS + '行まで予約可能)。\n' +
    '※「募集番号の先頭」を空欄にすると、同じ会社名の直前の予約行の続きの番号を自動で引き継ぎます(グループ番号をまたいでも引き継がれます)。'
  );
}

// ============================================================
// ③一括実行
// ============================================================
// ============================================================
// 実行設定シート編集時の自動処理(onEditトリガー)
// 「職種番号(カテゴリ)」で6重め/7軽めを選んだ行だけ、「職種名選択」列のプルダウンを
// そのカテゴリの職種名だけに絞り込む
// ============================================================
const HM_CONFIG_CATEGORY_COL = 5;
const HM_CONFIG_PAIRED_TITLE_COL = 14;

function onEdit(e) {
  try {
    if (hmPlanOnEdit_(e)) return; // 入稿予定表（入稿予定表.js）
    const range = e.range;
    const sheet = range.getSheet();
    if (sheet.getName() !== HM_CONFIG_SHEET_NAME) return;

    const editedColStart = range.getColumn();
    const editedColEnd = editedColStart + range.getNumColumns() - 1;
    const touchesCategoryCol = editedColStart <= HM_CONFIG_CATEGORY_COL && editedColEnd >= HM_CONFIG_CATEGORY_COL;
    const touchesTitleCol = editedColStart <= HM_CONFIG_PAIRED_TITLE_COL && editedColEnd >= HM_CONFIG_PAIRED_TITLE_COL;
    if (!touchesCategoryCol && !touchesTitleCol) return;

    const startRow = Math.max(range.getRow(), HM_CONFIG_DATA_START_ROW);
    const endRow = range.getRow() + range.getNumRows() - 1;
    if (endRow < HM_CONFIG_DATA_START_ROW) return;

    for (let r = startRow; r <= endRow; r++) {
      if (touchesCategoryCol) hmUpdatePairedTitleDropdownForRow_(sheet, r);
      if (touchesTitleCol) hmWarnIfTitleRecentlyUsed_(sheet, r);
    }
  } catch (err) {
    Logger.log(`onEdit error: ${err.message}`);
  }
}

// 「職種名選択」列で選んだ職種名が、同じ会社×カテゴリで直近クールダウン期間内に使われていたら選択直後に警告する
function hmWarnIfTitleRecentlyUsed_(sheet, row) {
  const categoryValue = String(sheet.getRange(row, HM_CONFIG_CATEGORY_COL).getValue() || '');
  const companyName = String(sheet.getRange(row, 6).getValue() || ''); // 会社名列
  const titleSelectionRaw = String(sheet.getRange(row, HM_CONFIG_PAIRED_TITLE_COL).getValue() || '');
  if (!categoryValue || !companyName || !titleSelectionRaw) return;

  let titleText = titleSelectionRaw;
  const sep = titleText.indexOf('｜');
  if (sep >= 0) titleText = titleText.slice(sep + 1);

  const everUsed = hmGetEverUsedTitles_(companyName, categoryValue, hmLoadUsageHistoryCache_());
  if (everUsed.has(titleText)) {
    SpreadsheetApp.getUi().alert(`重複警告\n\n${titleText}は使用履歴に存在しています。`);
  }
}

function hmUpdatePairedTitleDropdownForRow_(sheet, row) {
  const categoryValue = String(sheet.getRange(row, HM_CONFIG_CATEGORY_COL).getValue() || '');
  const titleCell = sheet.getRange(row, HM_CONFIG_PAIRED_TITLE_COL);

  const pairedCategory = ['重め', '軽め'].find(cat => HITOMANE_CATEGORY_NUMBER_LABEL[cat] === categoryValue);

  if (!pairedCategory) {
    titleCell.clearDataValidations();
    titleCell.clearContent();
    return;
  }

  const titles = hmGetPairedJobTitlesForCategory_(pairedCategory);
  titleCell.clearContent();
  if (!titles.length) {
    titleCell.clearDataValidations();
    return;
  }
  const options = titles.map(t => `${categoryValue}｜${t}`);
  const rule = SpreadsheetApp.newDataValidation().requireValueInList(options, true).setAllowInvalid(true).build();
  titleCell.setDataValidation(rule);
}

// 6重め/7軽めシートのA列(職種名)だけを軽量に取得する(hmBuildContentBank_全体は重いためonEditでは使わない)
// 6重め/7軽めシートは土台ファイル側にあるため、そちらを開いて探す
function hmGetPairedJobTitlesForCategory_(category) {
  const ss = SpreadsheetApp.openById(HM_BASE_SPREADSHEET_ID);
  const re = new RegExp(`^\\d+${category}$`);
  const targetSheet = ss.getSheets().find(sh => re.test(sh.getName()));
  if (!targetSheet) return [];
  const lastRow = targetSheet.getLastRow();
  if (lastRow < 2) return [];
  const hRow = hmFindSignatureRow_(targetSheet, ['職種名']);
  const dataStartRow = hRow + 1;
  if (lastRow < dataStartRow) return [];
  const numDataRows = lastRow - dataStartRow + 1;
  const titleVals = targetSheet.getRange(dataStartRow, 1, numDataRows, 1).getValues();
  const titles = [];
  titleVals.forEach(r => { if (r[0]) titles.push(String(r[0])); });
  return titles;
}

// カテゴリキーが6重め/7軽めのような「職種名選択」必須の特殊カテゴリかどうかを判定する。
// 通常カテゴリはローテーション+クールダウンで重複管理しているため、
// この判定でtrueになるカテゴリだけ、実行時に全期間の使用履歴チェック(ハードエラー)を行う。
function hmIsPairedCategoryKey_(bank, categoryKey) {
  const contentCategory = HITOMANE_CATEGORY_NAMES.find(c => categoryKey.indexOf(c) >= 0);
  return !!(bank.pairedJobData && bank.pairedJobData[contentCategory] && bank.pairedJobData[contentCategory].length);
}

function hmRunFromConfig() {
  const startTime = Date.now();
  Logger.log('[hmRunFromConfig] 開始');
  hmDeleteResumeTriggers_(); // 前回中断時に残っている自動再開トリガーがあれば削除(重複実行を防ぐ)

  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const configSh = ss.getSheetByName(HM_CONFIG_SHEET_NAME);
  if (!configSh) {
    hmSafeAlert_('「' + HM_CONFIG_SHEET_NAME + '」が見つかりません。先に「②実行設定を作成/更新」を実行してください。');
    return;
  }

  const lastRow = configSh.getLastRow();
  if (lastRow < HM_CONFIG_DATA_START_ROW) {
    hmSafeAlert_('予約リストにデータがありません。');
    return;
  }

  const numRows = lastRow - HM_CONFIG_DATA_START_ROW + 1;
  const data = configSh.getRange(HM_CONFIG_DATA_START_ROW, 1, numRows, HM_CONFIG_COLUMNS.length).getValues();

  const targets = [];
  data.forEach((row, i) => {
    const [groupNumberRaw, creationDate, commuteOrDorm, employmentType, categoryKey, companyName, formatType, targetCountRaw, entryNoPrefix, status, imageCategory, salaryPattern, nightShift, pairedTitleSelection, titleDedupWord, execStatus] = row;
    const sheetRow = HM_CONFIG_DATA_START_ROW + i;
    const isBlankRow = !categoryKey && !companyName && !targetCountRaw && !groupNumberRaw;
    if (isBlankRow) return;
    if (execStatus) return;

    const groupNumber = String(groupNumberRaw || '').trim();
    const m = groupNumber.match(/^(.+)-(\d+)$/);
    const groupId = m ? m[1] : `_単独_${sheetRow}`;
    const seq = m ? Number(m[2]) : 0;

    targets.push({
      sheetRow, groupId, seq, creationDate, commuteOrDorm, employmentType, categoryKey, companyName,
      formatType: formatType || '旧FMT',
      targetCountRaw: targetCountRaw === '' ? null : Number(targetCountRaw),
      entryNoPrefix, status, imageCategory, salaryPattern, nightShift, pairedTitleSelection, titleDedupWord,
    });
  });

  if (!targets.length) {
    hmSafeAlert_('実行対象の予約行がありません。');
    return;
  }

  // 実行対象の行に、まず「待機中」を表示してから処理を始める(進捗が見えるように)
  targets.forEach(t => configSh.getRange(t.sheetRow, HM_CONFIG_COL_PROGRESS).setValue('待機中'));
  SpreadsheetApp.flush();

  hmWriteRunStatus_(configSh, `⏳処理中… (残り${targets.length}件の予約行)`);

  Logger.log(`[hmRunFromConfig] hmBuildContentBank_ 呼び出し前。経過=${((Date.now() - startTime) / 1000).toFixed(1)}秒`);
  const bank = hmWithRetry_(() => hmBuildContentBank_()); // 読み取り専用なので、丸ごとリトライしても安全
  Logger.log(`[hmRunFromConfig] hmBuildContentBank_ 完了。経過=${((Date.now() - startTime) / 1000).toFixed(1)}秒`);
  const usageCache = hmWithRetry_(() => hmLoadUsageHistoryCache_()); // 使用履歴は1回だけ読み込み、以降はメモリ上のキャッシュを使う
  const contentUsageCache = hmWithRetry_(() => hmLoadContentUsageCache_()); // 仕事内容の使用履歴も同様に1回だけ読み込む
  const results = [];

  const groups = {};
  targets.forEach(t => { if (!groups[t.groupId]) groups[t.groupId] = []; groups[t.groupId].push(t); });
  const entryContinuationByCompany = {}; // 会社名ごとの募集番号引き継ぎ状態(グループ番号をまたいで共有する)

  let stoppedEarly = false;
  const groupIds = Object.keys(groups);
  const totalTargetsThisRun = targets.length;
  let targetsProcessedThisRun = 0;
  const pendingUsageUpdates = []; // まとめて最後にキャッシュへ反映する使用履歴更新

  try {
    for (let gi = 0; gi < groupIds.length; gi++) {
      if (Date.now() - startTime > HM_RUN_TIME_LIMIT_MS) { stoppedEarly = true; break; }

      const groupId = groupIds[gi];
      const groupTargets = groups[groupId].slice().sort((a, b) => a.seq - b.seq);
      Logger.log(`[hmRunFromConfig] グループ「${groupId}」処理開始(予約行${groupTargets.length}件)。経過=${((Date.now() - startTime) / 1000).toFixed(1)}秒`);
      const allRows = [];
      const contributions = [];
      const boundaries = [];
      const usageUpdates = [];
      const titleIndexByKey = {};

      let groupStoppedEarly = false;
      for (let ti = 0; ti < groupTargets.length; ti++) {
        if (Date.now() - startTime > HM_RUN_TIME_LIMIT_MS) { groupStoppedEarly = true; break; }
        const t = groupTargets[ti];
        hmWithRetry_(() => { configSh.getRange(t.sheetRow, HM_CONFIG_COL_PROGRESS).setValue('作成中'); SpreadsheetApp.flush(); });
        try {
          if (!t.categoryKey) throw new Error('職種番号(カテゴリ)が空です');
          if (!t.entryNoPrefix && !entryContinuationByCompany[t.companyName]) throw new Error('募集番号の先頭が空です(この会社で最初の予約行は必須入力です)');
          if (!t.imageCategory) throw new Error('画像カテゴリーが空です(必須入力です)');
          if (!t.companyName) throw new Error('会社名が空です');
          if (t.targetCountRaw !== null && (isNaN(t.targetCountRaw) || t.targetCountRaw <= 0)) {
            throw new Error('原稿数が数値になっていません');
          }

          const titleIndexKey = `${t.categoryKey}||${t.companyName}`;
          const titleStartIndex = titleIndexByKey[titleIndexKey] || 0;
          const entryNoInput = t.entryNoPrefix || entryContinuationByCompany[t.companyName];

          const genResult = t.formatType === '新FMT'
            ? hmGenerateBatchNewFmt_(bank, t.categoryKey, t.companyName, t.employmentType, t.commuteOrDorm, t.targetCountRaw, t.creationDate, t.status, t.imageCategory, t.salaryPattern, entryNoInput, t.pairedTitleSelection, titleStartIndex, t.nightShift, t.titleDedupWord, usageCache, contentUsageCache)
            : hmGenerateBatch_(bank, t.categoryKey, t.companyName, t.employmentType, t.commuteOrDorm, t.targetCountRaw, t.creationDate, t.status, t.imageCategory, t.salaryPattern, entryNoInput, t.pairedTitleSelection, titleStartIndex, t.nightShift, t.titleDedupWord, usageCache, contentUsageCache);
          titleIndexByKey[titleIndexKey] = genResult.titleEndIndex;
          entryContinuationByCompany[t.companyName] = genResult.entryNoEnd;
          targetsProcessedThisRun++;

          // 全期間の使用履歴との重複チェックは、職種名を1つに固定選択する6重め/7軽めのみ行う。
          // 通常カテゴリはローテーション側でクールダウン(HM_COOLDOWN_DAYS)を見て自動的に避けているため、
          // ここで全期間チェックまでしてしまうと、期間経過後の正当な再利用まで誤ってエラーになる。
          if (hmIsPairedCategoryKey_(bank, t.categoryKey)) {
            const everUsed = hmGetEverUsedTitles_(t.companyName, t.categoryKey, usageCache);
            const alreadyUsedTitles = Object.keys(genResult.titleCounts).filter(title => everUsed.has(title));
            if (alreadyUsedTitles.length) {
              throw new Error(`重複警告: ${alreadyUsedTitles.join('、')}は使用履歴に存在しています。`);
            }
          }

          configSh.getRange(t.sheetRow, 1, 1, HM_CONFIG_COLUMNS.length).setBackground(null);

          boundaries.push(allRows.length);
          allRows.push(...genResult.rows);
          contributions.push({ sheetRow: t.sheetRow, count: genResult.rows.length });
          usageUpdates.push({ companyName: t.companyName, categoryKey: t.categoryKey, titleCounts: genResult.titleCounts, contentCounts: genResult.contentCounts });

          if (t.targetCountRaw === null) configSh.getRange(t.sheetRow, 8).setValue(genResult.rows.length);
        } catch (e) {
          configSh.getRange(t.sheetRow, 1, 1, HM_CONFIG_COLUMNS.length).setBackground('#FF0000');
          configSh.getRange(t.sheetRow, 16).setValue(`❌エラー: ${e.message}`);
          configSh.getRange(t.sheetRow, HM_CONFIG_COL_PROGRESS).setValue('❌エラー');
          SpreadsheetApp.flush();
          throw new Error(`行${t.sheetRow}: ${e.message}`);
        }
      }

      if (groupStoppedEarly) { stoppedEarly = true; break; }
      if (!allRows.length) continue;

      const first = groupTargets[0];
      const dateStr = Utilities.formatDate(new Date(first.creationDate || new Date()), Session.getScriptTimeZone(), 'yyyyMMdd');
      const groupLabel = groupId.indexOf('_単独_') === 0 ? '' : `G${groupId}_`;
      const isNewFmt = first.formatType === '新FMT';
      const outHeaders = isNewFmt ? HITOMANE_NEW_HEADERS : HITOMANE_HEADERS;
      const baseNamePrefix = `ヒトマネ出力_${isNewFmt ? '新_' : ''}${groupLabel}${first.companyName}_${first.categoryKey}_${dateStr}`;

      const chunks = [];
      for (let i = 0; i < allRows.length; i += HM_MAX_ROWS_PER_SHEET) chunks.push(allRows.slice(i, i + HM_MAX_ROWS_PER_SHEET));

      const outSheetNames = [];
      let writeStoppedEarly = false;
      for (let idx = 0; idx < chunks.length && !writeStoppedEarly; idx++) {
        const chunkRows = chunks[idx];
        let outName = (chunks.length > 1 ? `${baseNamePrefix}_part${idx + 1}` : baseNamePrefix).slice(0, 95);
        let outSh = ss.getSheetByName(outName);
        if (outSh) ss.deleteSheet(outSh);
        outSh = ss.insertSheet(outName);
        outSh.getRange(1, 1, 1, outHeaders.length).setValues([outHeaders]);
        // 1万行を一度に書き込むと重くなるため、HM_WRITE_BATCH_SIZE行ずつに分けて書き込む
        for (let w = 0; w < chunkRows.length; w += HM_WRITE_BATCH_SIZE) {
          if (Date.now() - startTime > HM_RUN_TIME_LIMIT_MS) { writeStoppedEarly = true; break; }
          const batchRows = chunkRows.slice(w, w + HM_WRITE_BATCH_SIZE).map(r => hmRowToArray_(r, outHeaders));
          outSh.getRange(2 + w, 1, batchRows.length, outHeaders.length).setValues(batchRows);
        }
        if (writeStoppedEarly) break;
        outSheetNames.push(outName);
      }

      if (writeStoppedEarly) {
        // 途中まで書き込んだシート(このグループの分)を削除してクリーンな状態に戻す
        ss.getSheets().forEach(sh => {
          const name = sh.getName();
          if (name === baseNamePrefix || name.indexOf(`${baseNamePrefix}_part`) === 0) ss.deleteSheet(sh);
        });
        groupTargets.forEach(t => configSh.getRange(t.sheetRow, HM_CONFIG_COL_PROGRESS).setValue('待機中'));
        stoppedEarly = true;
        break;
      }

      // グループ内で2件以上の予約行が連結されている場合、セグメントごとに交互の色で塗り分ける
      if (groupTargets.length > 1 && boundaries.length > 1) {
        const bandColors = ['#FFFFFF', '#FFE58F'];
        const segmentEnds = boundaries.slice(1).concat([allRows.length]);
        boundaries.forEach((startIdx, segIdx) => {
          const endIdx = segmentEnds[segIdx];
          const color = bandColors[segIdx % 2];
          if (color === '#FFFFFF') return;
          let rowCursor = startIdx;
          while (rowCursor < endIdx) {
            const chunkIdx = Math.floor(rowCursor / HM_MAX_ROWS_PER_SHEET);
            const chunkStart = chunkIdx * HM_MAX_ROWS_PER_SHEET;
            const chunkEnd = Math.min(chunkStart + HM_MAX_ROWS_PER_SHEET, endIdx);
            const targetSheetName = outSheetNames[chunkIdx];
            if (targetSheetName) {
              const targetSh = ss.getSheetByName(targetSheetName);
              const rowInChunkStart = rowCursor - chunkStart;
              const rowCount = chunkEnd - rowCursor;
              const sheetRowStart = rowInChunkStart + 2;
              targetSh.getRange(sheetRowStart, 1, rowCount, outHeaders.length).setBackground(color);
            }
            rowCursor = chunkEnd;
          }
        });
      }

      const doneStr = Utilities.formatDate(new Date(), Session.getScriptTimeZone(), 'yyyy-MM-dd HH:mm');
      const sheetUrls = outSheetNames.map(name => {
        const s = ss.getSheetByName(name);
        return `${ss.getUrl()}#gid=${s.getSheetId()}`;
      });

      usageUpdates.forEach(u => hmUpdateUsageCache_(usageCache, u.companyName, u.categoryKey, u.titleCounts));
      usageUpdates.forEach(u => hmUpdateContentUsageCache_(contentUsageCache, u.companyName, u.categoryKey, u.contentCounts));
      pendingUsageUpdates.push(...usageUpdates);

      contributions.forEach(c => {
        configSh.getRange(c.sheetRow, 16).setValue(`✅完了(${doneStr}) ${c.count}件 → ${outSheetNames.join(', ')}`);
        configSh.getRange(c.sheetRow, HM_CONFIG_COL_PROGRESS).setValue('完了');
        configSh.getRange(c.sheetRow, 18).setFormula(`=HYPERLINK("${sheetUrls[0]}","${outSheetNames[0]}")`);
      });
      SpreadsheetApp.flush();

      results.push(`グループ「${groupId}」: 合計${allRows.length}件生成 → ${outSheetNames.join(', ')}`);
      hmWriteRunStatus_(configSh, `⏳処理中…${hmEstimateEta_(startTime, targetsProcessedThisRun, totalTargetsThisRun)}`);
    }
  } catch (e) {
    // 使用履歴の保存自体がタイムアウトで失敗しても、本来のエラー内容(e.message)は必ず表示したいので、
    // ここでの保存失敗は握りつぶす(ログにだけ残す)。
    try { hmWithRetry_(() => hmFlushUsageCache_(usageCache)); } catch (e2) { Logger.log('使用履歴の保存に失敗(エラー停止時): ' + e2.message); }
    try { hmWithRetry_(() => hmFlushContentUsageCache_(contentUsageCache)); } catch (e2) { Logger.log('仕事内容使用履歴の保存に失敗(エラー停止時): ' + e2.message); }
    hmWriteRunStatus_(configSh, '❌エラーで停止');
    hmSafeAlert_(`重複または入力エラーが検出されたため、処理を中断しました。\n\n${e.message}\n\n該当行は実行設定シート上で赤く表示されています。`);
    return;
  }

  hmWithRetry_(() => hmFlushUsageCache_(usageCache)); // メモリ上の使用履歴をまとめて1回で書き込む(タイムアウト対策でリトライ付き)
  hmWithRetry_(() => hmFlushContentUsageCache_(contentUsageCache)); // 仕事内容の使用履歴も同様にまとめて1回で書き込む

  if (stoppedEarly) {
    // 実行時間の上限に近づいたため、ここで一旦区切り、1分後に自動で続きを再開するトリガーを仕掛ける
    // ※自動再開はこのポップアップの有無に関わらず裏側で進むため、ここでは確認ポップアップを出さない(P1の表示のみで十分)
    ScriptApp.newTrigger(HM_RESUME_TRIGGER_FUNCTION).timeBased().after(60 * 1000).create();
    hmWriteRunStatus_(configSh, '⏸ 一時停止中(1分後に自動再開予定)');
    return;
  }

  const syncMsg = hmWithRetry_(() => hmSyncPairedTitleUsage_());
  hmWriteRunStatus_(configSh, '✅全件完了');
  hmSafeAlert_('予約リストを処理しました\n\n' + results.join('\n') + '\n\n' + syncMsg);
}

// ============================================================
// 生成ロジック本体
// ============================================================
function hmPick_(arr) { return arr[Math.floor(Math.random() * arr.length)]; }

// 実際にローテーション(または6重め/7軽めで選択)された職種名に、「タイトル」シート由来のペルソナ句・アピール句を
// ランダムに組み合わせて募集職種を組み立てる。「「職種名」ペルソナ句／夜勤テキスト／アピール句／重複対策ワード」の形。
// 重複対策ワードは、実行設定で指定があればそちらを優先。文字数制限はかけない。
function hmBuildComposedTitle_(bank, actualTitle, nightShift, titleDedupWord) {
  const tc = bank.titleComponents;
  if (!tc || !tc.personas.length || !tc.appeals.length) return actualTitle;
  const persona = hmPick_(tc.personas);
  const appeal = hmPick_(tc.appeals);
  const shiftText = nightShift === '夜勤あり' ? '二交代・夜勤あり' : '二交代・夜勤なし';
  const dedup = titleDedupWord || tc.dedupWord || '';
  return `「${actualTitle}」${persona}／${shiftText}／${appeal}${dedup ? '／' + dedup : ''}`;
}

function hmShuffle_(arr) {
  const a = arr.slice();
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}
function hmFindPartsKey_(bank, substring) { return Object.keys(bank.parts).find(k => k.indexOf(substring) >= 0); }
function hmFindPartsKeyAll_(bank, substrings) { return Object.keys(bank.parts).find(k => substrings.every(s => k.indexOf(s) >= 0)); }

// バッチ処理中は同じキーが何度も必要になるため、行ごとに再検索せず、バッチ開始時に1回だけ解決しておく(高速化)
function hmResolvePartKeys_(bank, nightShift) {
  return {
    qualKey: hmFindPartsKey_(bank, '応募資格'),
    workTimeKey: nightShift ? hmFindPartsKeyAll_(bank, ['勤務時間', nightShift]) : hmFindPartsKey_(bank, '勤務時間'),
    workPeriodKey: hmFindPartsKey_(bank, '勤務期間'),
    benefitKey: hmFindPartsKey_(bank, '待遇'),
    holidayKey: hmFindPartsKey_(bank, '休日'),
    applyMethodKey: hmFindPartsKey_(bank, '応募方法'),
    prKey: hmFindPartsKey_(bank, 'PR'),
    salaryTextKey: hmFindPartsKey_(bank, '給与'),
  };
}

// 使用履歴シートの全件を1回だけ読み込む(呼び出しごとに読み直すと予約行数が多い時に非常に遅くなるため)
// 使用履歴は土台ファイル側に一本化しているため、そちらを読む(複数の運用ファイル間で重複を避けるため)
function hmLoadUsageHistoryCache_() {
  const ss = SpreadsheetApp.openById(HM_BASE_SPREADSHEET_ID);
  const sh = ss.getSheetByName(HM_USAGE_SHEET_NAME);
  const lastRow = sh ? sh.getLastRow() : 0;
  const rows = (sh && lastRow >= 2) ? sh.getRange(2, 1, lastRow - 1, 6).getValues() : [];
  const indexMap = {};
  rows.forEach((row, i) => { indexMap[`${row[0]}||${row[1]}||${row[2]}`] = i; });
  return { rows, indexMap };
}

function hmGetRecentlyUsedTitles_(companyName, categoryKey, usageCache) {
  const recentlyUsed = new Set();
  const lastUsed = {};
  const today = new Date();
  ((usageCache && usageCache.rows) || []).forEach(row => {
    const [comp, cat, title, , , lastDateRaw] = row;
    if (comp !== companyName || cat !== categoryKey || !lastDateRaw) return;
    const lastDate = new Date(String(lastDateRaw).replace(' ', 'T'));
    lastUsed[title] = lastDate;
    if ((today - lastDate) / 86400000 < HM_COOLDOWN_DAYS) recentlyUsed.add(title);
  });
  return { recentlyUsed, lastUsed };
}

// 使用履歴シートに「過去に一度でも使ったことがある」職種名の集合を返す(クールダウン期間に関係なく、全期間対象)。
// 6重め/7軽め(通常のクールダウン管理をしないカテゴリ)で警告・エラー判定に使う。
function hmGetEverUsedTitles_(companyName, categoryKey, usageCache) {
  const everUsed = new Set();
  ((usageCache && usageCache.rows) || []).forEach(row => {
    const [comp, cat, title] = row;
    if (comp === companyName && cat === categoryKey && title) everUsed.add(String(title));
  });
  return everUsed;
}

// ============================================================
// 「職種名管理」シートを使用履歴シートと同期する(6重め/7軽めの会社別使用状況)
// 使用履歴にある組み合わせをTRUEにする(追記のみ)。既存のチェック(TRUE)は理由を問わず一切消さない。
// 間違ってチェックが入っている場合は、職種名管理シート側のそのセルを直接手動でFALSEに戻してください
// (使用履歴を削除しても、このセルは自動では戻りません)。
// ============================================================
const HM_TITLE_MANAGEMENT_SHEET_NAME = '職種名管理';

function hmSyncPairedTitleUsage_menu() {
  const result = hmSyncPairedTitleUsage_();
  SpreadsheetApp.getUi().alert(result);
}

// 職種名管理シート・使用履歴シートは両方とも土台ファイル側に一本化しているため、土台ファイルだけを開いて同期する
function hmSyncPairedTitleUsage_() {
  const baseSs = SpreadsheetApp.openById(HM_BASE_SPREADSHEET_ID); // 職種名管理・使用履歴はどちらもこちら(土台ファイル)
  const sh = baseSs.getSheetByName(HM_TITLE_MANAGEMENT_SHEET_NAME);
  if (!sh) return `「${HM_TITLE_MANAGEMENT_SHEET_NAME}」シートが見つかりませんでした。`;

  // 使用履歴から「会社名||職種名」の組み合わせを、6重め/7軽めそれぞれのSetとして作る
  const usageSh = baseSs.getSheetByName(HM_USAGE_SHEET_NAME);
  const usedSets = { '6重め': new Set(), '7軽め': new Set() };
  if (usageSh && usageSh.getLastRow() >= 2) {
    const data = usageSh.getRange(2, 1, usageSh.getLastRow() - 1, 3).getValues();
    data.forEach(row => {
      const [comp, cat, title] = row;
      if (usedSets[cat] && title) usedSets[cat].add(`${comp}||${title}`);
    });
  }

  const lastCol = sh.getLastColumn();
  const lastRow = sh.getLastRow();
  const headerVals = sh.getRange(1, 1, 1, lastCol).getValues()[0].map(v => String(v).trim());

  // ヘッダー行の中から「6重め」「7軽め」というラベルのセルを探し、そのブロックの開始列とする
  const blockStarts = [];
  headerVals.forEach((v, i) => {
    if (v === '6重め' || v === '7軽め') blockStarts.push({ category: v, col: i + 1 });
  });
  if (!blockStarts.length) return `「${HM_TITLE_MANAGEMENT_SHEET_NAME}」シートに「6重め」「7軽め」の見出しが見つかりませんでした。`;

  let updatedCount = 0;
  blockStarts.forEach((block, idx) => {
    // このブロックの会社名は、同じ行で次のブロック開始列(または表の終端)までの間に並んでいる
    const blockEndCol = (idx + 1 < blockStarts.length) ? blockStarts[idx + 1].col - 1 : lastCol;
    const blockWidth = blockEndCol - block.col; // タイトル列を除いた会社列の数
    if (blockWidth <= 0 || lastRow < 2) return;

    const companyNamesRow = sh.getRange(1, block.col + 1, 1, blockWidth).getValues()[0].map(v => String(v).trim());
    const titleCol = block.col;
    const numDataRows = lastRow - 1;
    const titleVals = sh.getRange(2, titleCol, numDataRows, 1).getValues();
    // TRUE/FALSEの現在値もまとめて1回で読み込み、更新が必要な箇所だけメモリ上で書き換えてから一括で書き戻す
    const checkVals = sh.getRange(2, block.col + 1, numDataRows, blockWidth).getValues();

    let blockChanged = false;
    for (let r = 0; r < numDataRows; r++) {
      const title = String(titleVals[r][0] || '').trim();
      if (!title) continue;
      for (let c = 0; c < blockWidth; c++) {
        const companyName = companyNamesRow[c];
        if (!companyName) continue;
        const isUsed = usedSets[block.category].has(`${companyName}||${title}`);
        if (!isUsed) continue; // 使用履歴に無いものはそのまま(既存のチェックは絶対に消さない)
        const current = checkVals[r][c];
        const currentBool = current === true || String(current).toUpperCase() === 'TRUE';
        if (!currentBool) {
          checkVals[r][c] = true;
          blockChanged = true;
          updatedCount++;
        }
      }
    }
    if (blockChanged) {
      sh.getRange(2, block.col + 1, numDataRows, blockWidth).setValues(checkVals);
    }
  });

  return `「${HM_TITLE_MANAGEMENT_SHEET_NAME}」を使用履歴シートと同期しました(${updatedCount}セル更新)。`;
}

function hmGenerateBatch_(bank, categoryKey, companyName, employmentType, commuteOrDorm, targetCount, creationDate, status, imageCategoryOverride, salaryPattern, entryNoPrefix, pairedTitleSelection, titleStartIndex, nightShift, titleDedupWord, usageCache, contentUsageCache) {
  const contentCategory = HITOMANE_CATEGORY_NAMES.find(c => categoryKey.indexOf(c) >= 0);

  // 6重め/7軽め: 職種名・アルファベット・仕事内容が1シートの1行にまとまっている特殊カテゴリ。
  // 「職種名選択」列で指定された行を1つに固定して使う(ランダム選択やクールダウンは行わない)。
  const isPairedCategory = !!(bank.pairedJobData && bank.pairedJobData[contentCategory] && bank.pairedJobData[contentCategory].length);

  let titles, contentsPool, fixedLetter = '';

  if (isPairedCategory) {
    if (!pairedTitleSelection) {
      throw new Error(`カテゴリ「${categoryKey}」は「職種名選択(6重め/7軽めのみ・必須)」列で職種名を選択してください`);
    }
    let selectionText = String(pairedTitleSelection);
    const sep = selectionText.indexOf('｜');
    if (sep >= 0) selectionText = selectionText.slice(sep + 1);
    const pairedEntry = bank.pairedJobData[contentCategory].find(e => e.title === selectionText);
    if (!pairedEntry) {
      throw new Error(`「${selectionText}」が${contentCategory}シートの職種名一覧に見つかりません`);
    }
    titles = [pairedEntry.title];
    contentsPool = pairedEntry.contentOptions;
    if (!contentsPool || !contentsPool.length) {
      throw new Error(`「${pairedEntry.title}」のお仕事内容(D列以降)が見つかりません`);
    }
    fixedLetter = pairedEntry.letter;
  } else {
    const allTitles = bank.jobTitles[categoryKey];
    if (!allTitles || !allTitles.length) throw new Error(`カテゴリ「${categoryKey}」の職種名が見つかりません`);
    contentsPool = bank.jobContents[contentCategory] || [];
    if (!contentsPool.length) throw new Error(`カテゴリ「${contentCategory}」の仕事内容が見つかりません`);

    const { recentlyUsed, lastUsed } = hmGetRecentlyUsedTitles_(companyName, categoryKey, usageCache);
    const everUsedTitles = hmGetEverUsedTitles_(companyName, categoryKey, usageCache);
    // 用意されている職種名を全て使い切っていたら、黙って使い回さずエラーにして気づけるようにする
    if (allTitles.every(t => everUsedTitles.has(t))) {
      throw new Error(`「${companyName}」の「${categoryKey}」職種名(全${allTitles.length}件)を全て使い切りました。職種名シートに新しい職種名を追加してください。`);
    }
    titles = allTitles.filter(t => !recentlyUsed.has(t));
    if (!titles.length) {
      // 全職種名がクールダウン期間中(直近使用)の場合は、いったん全職種名を対象に戻す
      titles = allTitles.slice();
    }
    // 一度も使ったことがない職種名を優先し、そのあとは直近使用日が古い順(未使用は最優先)に並べる
    titles.sort((a, b) => {
      const aEver = everUsedTitles.has(a), bEver = everUsedTitles.has(b);
      if (aEver !== bEver) return aEver ? 1 : -1;
      return (lastUsed[a] ? lastUsed[a].getTime() : 0) - (lastUsed[b] ? lastUsed[b].getTime() : 0);
    });
  }

  const company = bank.companies[companyName];
  if (!company) throw new Error(`会社「${companyName}」が会社情報マスターに見つかりません`);

  let ngList = bank.ngByCompany[companyName];
  if (!ngList) {
    const shortKey = Object.keys(bank.ngByCompany).find(k => companyName.indexOf(k) >= 0);
    ngList = shortKey ? bank.ngByCompany[shortKey] : [];
  }
  const locations = bank.locations.filter(loc => {
    const full = loc.pref + loc.city;
    return !(ngList || []).some(ng => ng === loc.pref || ng === full || full.indexOf(ng) >= 0);
  });
  if (!locations.length) throw new Error('使用できる勤務地がありません(NGエリアで全件除外された可能性があります)');

  // 勤務地はランダムな順序で使う(ただしシャッフルするだけなので、1つの職種名の中で同じ勤務地が2回出ることはない)
  const shuffledLocations = hmShuffle_(locations);

  if (targetCount === null || targetCount === undefined) targetCount = locations.length;

  const imageCategoryKey = imageCategoryOverride || bank.imageCategoryByJobCategory[contentCategory]
    || Object.keys(bank.imagesByCategory).find(k => k.indexOf(contentCategory) >= 0) || Object.keys(bank.imagesByCategory)[0];
  const imagesPool = bank.imagesByCategory[imageCategoryKey] || [];

  const salaryPool = bank.salaryPatterns[salaryPattern] || bank.salaryPatterns['基本'] || [];
  const partKeys = hmResolvePartKeys_(bank, nightShift); // 行ごとの再検索を避けるため、バッチ開始時に1回だけ解決する

  const rows = [];
  const titleCounts = {};
  const contentCounts = {};
  let remaining = targetCount;
  let titleIdx = titleStartIndex || 0; // グループ全体を1原稿とみなし、呼び出し元から引き継ぐ
  let loopGuard = 0;
  // 固定回数だと勤務地数が少ない時に目標件数へ届かず静かに打ち切られてしまうため、
  // 「目標件数 ÷ 勤務地数」を基準に必要な周回数を確保しつつ、異常な無限ループだけは防ぐ
  const loopGuardMax = Math.max(1000, Math.ceil(targetCount / Math.max(shuffledLocations.length, 1)) + 10);

  // 募集番号:「CB97595」のように末尾に数字を含む先頭指定なら、その数字自体を起点に連番で増やす
  // (「CB97595」→1件目=CB97595, 2件目=CB97596, ...)。数字を含まない場合は単純に連番を後ろに付ける
  const prefixMatch = String(entryNoPrefix || '').match(/^(.*?)(\d+)$/);
  const entryLetterPart = prefixMatch ? prefixMatch[1] : String(entryNoPrefix || '');
  const entryStartNum = prefixMatch ? parseInt(prefixMatch[2], 10) : null;
  const entryNumDigits = prefixMatch ? prefixMatch[2].length : 0;
  let entryOffset = 0;

  while (remaining > 0 && loopGuard < loopGuardMax) {
    const title = titles[titleIdx % titles.length];
    for (let i = 0; i < shuffledLocations.length && remaining > 0; i++) {
      const content = hmPickUnusedContent_(contentsPool, companyName, categoryKey, contentUsageCache);
      const image = imagesPool.length ? hmPick_(imagesPool) : '';
      const salary = salaryPool.length ? hmPick_(salaryPool) : null;
      let entryNumber;
      if (entryStartNum !== null) {
        const num = entryStartNum + entryOffset;
        const numStr = entryNumDigits > 1 ? String(num).padStart(entryNumDigits, '0') : String(num);
        entryNumber = entryLetterPart + numStr;
      } else {
        entryNumber = entryLetterPart + (entryOffset + 1);
      }
      rows.push(hmBuildRow_(bank, title, content, contentCategory, categoryKey, company, employmentType, commuteOrDorm, shuffledLocations[i], image, salary, creationDate, status, entryNumber, fixedLetter, nightShift, titleDedupWord, partKeys));
      titleCounts[title] = (titleCounts[title] || 0) + 1;
      contentCounts[content] = (contentCounts[content] || 0) + 1;
      remaining--;
      entryOffset++;
    }
    titleIdx++;
    loopGuard++;
  }

  // 次の予約行(募集番号の先頭が空欄の場合)へ引き継ぐための、続きの番号
  const entryNoEnd = entryStartNum !== null
    ? entryLetterPart + (entryNumDigits > 1 ? String(entryStartNum + entryOffset).padStart(entryNumDigits, '0') : String(entryStartNum + entryOffset))
    : entryLetterPart + (entryOffset + 1);

  return { rows, titleCounts, contentCounts, titleEndIndex: titleIdx, entryNoEnd };
}

// ============================================================
// 新FMT用の生成ロジック(旧FMTと同じ職種名/仕事内容/会社/勤務地/給与/画像/パーツを再利用)
// ============================================================
function hmGenerateBatchNewFmt_(bank, categoryKey, companyName, employmentType, commuteOrDorm, targetCount, creationDate, status, imageCategoryOverride, salaryPattern, entryNoPrefix, pairedTitleSelection, titleStartIndex, nightShift, titleDedupWord, usageCache, contentUsageCache) {
  const contentCategory = HITOMANE_CATEGORY_NAMES.find(c => categoryKey.indexOf(c) >= 0);
  const isPairedCategory = !!(bank.pairedJobData && bank.pairedJobData[contentCategory] && bank.pairedJobData[contentCategory].length);

  let titles, contentsPool, fixedLetter = '';

  if (isPairedCategory) {
    if (!pairedTitleSelection) throw new Error(`カテゴリ「${categoryKey}」は「職種名選択(6重め/7軽めのみ・必須)」列で職種名を選択してください`);
    let selectionText = String(pairedTitleSelection);
    const sep = selectionText.indexOf('｜');
    if (sep >= 0) selectionText = selectionText.slice(sep + 1);
    const pairedEntry = bank.pairedJobData[contentCategory].find(e => e.title === selectionText);
    if (!pairedEntry) throw new Error(`「${selectionText}」が${contentCategory}シートの職種名一覧に見つかりません`);
    titles = [pairedEntry.title];
    contentsPool = pairedEntry.contentOptions;
    if (!contentsPool || !contentsPool.length) throw new Error(`「${pairedEntry.title}」のお仕事内容(D列以降)が見つかりません`);
    fixedLetter = pairedEntry.letter;
  } else {
    const allTitles = bank.jobTitles[categoryKey];
    if (!allTitles || !allTitles.length) throw new Error(`カテゴリ「${categoryKey}」の職種名が見つかりません`);
    contentsPool = bank.jobContents[contentCategory] || [];
    if (!contentsPool.length) throw new Error(`カテゴリ「${contentCategory}」の仕事内容が見つかりません`);

    const { recentlyUsed, lastUsed } = hmGetRecentlyUsedTitles_(companyName, categoryKey, usageCache);
    const everUsedTitles = hmGetEverUsedTitles_(companyName, categoryKey, usageCache);
    // 用意されている職種名を全て使い切っていたら、黙って使い回さずエラーにして気づけるようにする
    if (allTitles.every(t => everUsedTitles.has(t))) {
      throw new Error(`「${companyName}」の「${categoryKey}」職種名(全${allTitles.length}件)を全て使い切りました。職種名シートに新しい職種名を追加してください。`);
    }
    titles = allTitles.filter(t => !recentlyUsed.has(t));
    if (!titles.length) {
      // 全職種名がクールダウン期間中(直近使用)の場合は、いったん全職種名を対象に戻す
      titles = allTitles.slice();
    }
    // 一度も使ったことがない職種名を優先し、そのあとは直近使用日が古い順(未使用は最優先)に並べる
    titles.sort((a, b) => {
      const aEver = everUsedTitles.has(a), bEver = everUsedTitles.has(b);
      if (aEver !== bEver) return aEver ? 1 : -1;
      return (lastUsed[a] ? lastUsed[a].getTime() : 0) - (lastUsed[b] ? lastUsed[b].getTime() : 0);
    });
  }

  const company = bank.companies[companyName];
  if (!company) throw new Error(`会社「${companyName}」が会社情報マスターに見つかりません`);

  let ngList = bank.ngByCompany[companyName];
  if (!ngList) {
    const shortKey = Object.keys(bank.ngByCompany).find(k => companyName.indexOf(k) >= 0);
    ngList = shortKey ? bank.ngByCompany[shortKey] : [];
  }
  const locations = bank.locations.filter(loc => {
    const full = loc.pref + loc.city;
    return !(ngList || []).some(ng => ng === loc.pref || ng === full || full.indexOf(ng) >= 0);
  });
  if (!locations.length) throw new Error('使用できる勤務地がありません(NGエリアで全件除外された可能性があります)');

  const shuffledLocations = hmShuffle_(locations);
  if (targetCount === null || targetCount === undefined) targetCount = locations.length;

  const imageCategoryKey = imageCategoryOverride || bank.imageCategoryByJobCategory[contentCategory]
    || Object.keys(bank.imagesByCategory).find(k => k.indexOf(contentCategory) >= 0) || Object.keys(bank.imagesByCategory)[0];
  const imagesPool = bank.imagesByCategory[imageCategoryKey] || [];

  const salaryPool = bank.salaryPatterns[salaryPattern] || bank.salaryPatterns['基本'] || [];
  const partKeys = hmResolvePartKeys_(bank, nightShift); // 行ごとの再検索を避けるため、バッチ開始時に1回だけ解決する

  // 夜勤の有無に応じて勤務時間シートを切り替える。指定が無い/該当シートが無い場合は、
  // 夜勤の区別が無い従来型シート(bank.workTimePatterns)にフォールバックする
  const workTimePool = (nightShift && bank.workTimePatternsByShift[nightShift] && bank.workTimePatternsByShift[nightShift].length)
    ? bank.workTimePatternsByShift[nightShift]
    : bank.workTimePatterns;

  if (!workTimePool || !workTimePool.length) {
    throw new Error('「勤務時間」シート(新FMT用の勤務時間パターン。夜勤あり/なし別、または従来型)が見つかりません');
  }

  const rows = [];
  const titleCounts = {};
  const contentCounts = {};
  let remaining = targetCount;
  let titleIdx = titleStartIndex || 0;
  let loopGuard = 0;
  const loopGuardMax = Math.max(1000, Math.ceil(targetCount / Math.max(shuffledLocations.length, 1)) + 10);

  const prefixMatch = String(entryNoPrefix || '').match(/^(.*?)(\d+)$/);
  const entryLetterPart = prefixMatch ? prefixMatch[1] : String(entryNoPrefix || '');
  const entryStartNum = prefixMatch ? parseInt(prefixMatch[2], 10) : null;
  const entryNumDigits = prefixMatch ? prefixMatch[2].length : 0;
  let entryOffset = 0;

  while (remaining > 0 && loopGuard < loopGuardMax) {
    const title = titles[titleIdx % titles.length];
    for (let i = 0; i < shuffledLocations.length && remaining > 0; i++) {
      const content = hmPickUnusedContent_(contentsPool, companyName, categoryKey, contentUsageCache);
      const image = imagesPool.length ? hmPick_(imagesPool) : '';
      const salary = salaryPool.length ? hmPick_(salaryPool) : null;
      const workTime = hmPick_(workTimePool);
      let entryNumber;
      if (entryStartNum !== null) {
        const num = entryStartNum + entryOffset;
        const numStr = entryNumDigits > 1 ? String(num).padStart(entryNumDigits, '0') : String(num);
        entryNumber = entryLetterPart + numStr;
      } else {
        entryNumber = entryLetterPart + (entryOffset + 1);
      }
      rows.push(hmBuildRowNewFmt_(bank, title, content, contentCategory, categoryKey, company, employmentType, commuteOrDorm, shuffledLocations[i], image, salary, creationDate, status, entryNumber, fixedLetter, workTime, nightShift, titleDedupWord, partKeys));
      titleCounts[title] = (titleCounts[title] || 0) + 1;
      contentCounts[content] = (contentCounts[content] || 0) + 1;
      remaining--;
      entryOffset++;
    }
    titleIdx++;
    loopGuard++;
  }

  return { rows, titleCounts, contentCounts, titleEndIndex: titleIdx, entryNoEnd: entryStartNum !== null
    ? entryLetterPart + (entryNumDigits > 1 ? String(entryStartNum + entryOffset).padStart(entryNumDigits, '0') : String(entryStartNum + entryOffset))
    : entryLetterPart + (entryOffset + 1) };
}

function hmBuildRowNewFmt_(bank, title, content, contentCategory, categoryKey, company, employmentType, commuteOrDorm, location, image, salary, creationDate, status, entryNumber, letter, workTime, nightShift, titleDedupWord, partKeys) {
  const row = {};
  HITOMANE_NEW_HEADERS.forEach(h => row[h] = HITOMANE_NEW_FIXED_VALUES[h] !== undefined ? HITOMANE_NEW_FIXED_VALUES[h] : '');

  row['募集番号'] = entryNumber || '';
  row['ステータス'] = status || '掲載';
  const startDate = new Date(creationDate || new Date());
  const endDate = new Date(startDate);
  endDate.setFullYear(endDate.getFullYear() + 1);
  row['開始日'] = Utilities.formatDate(startDate, Session.getScriptTimeZone(), 'yyyy/MM/dd');
  row['終了日'] = Utilities.formatDate(endDate, Session.getScriptTimeZone(), 'yyyy/MM/dd');

  row['勤務地_都道府県'] = location.pref;
  row['勤務地_市区町村'] = location.city;
  row['雇用形態'] = employmentType || HITOMANE_NEW_FIXED_VALUES['雇用形態'];
  row['募集職種'] = hmBuildComposedTitle_(bank, title, nightShift, titleDedupWord);

  const { qualKey, workPeriodKey, benefitKey, holidayKey, applyMethodKey, prKey } = partKeys;

  if (prKey) row['PR'] = hmPick_(bank.parts[prKey]);
  if (workPeriodKey) row['勤務期間'] = hmPick_(bank.parts[workPeriodKey]);
  if (qualKey) row['応募資格'] = hmPick_(bank.parts[qualKey]);
  if (benefitKey) row['待遇'] = hmPick_(bank.parts[benefitKey]);
  if (holidayKey) row['休日・休暇'] = hmPick_(bank.parts[holidayKey]);

  // DV列(応募方法): 会社情報の「応募方法」(1つ目)をそのまま使用
  row['応募方法'] = company['応募方法'] || '';
  // DW列(応募方法_補足): パーツシートの応募方法_補足からランダム選択 + 会社情報の「応募方法#2」(2つ目)を下につける
  const applyMethodText = applyMethodKey ? hmPick_(bank.parts[applyMethodKey]) : '';
  const secondApplyMethod = company['応募方法#2'] || '';
  row['応募方法_補足'] = [applyMethodText, secondApplyMethod].filter(Boolean).join('\n');

  // 仕事内容: 重複応募の注記 + 受動喫煙対策(サンプル行に倣った固定文言)を付与
  row['仕事内容'] = `${content}\n\n【受動喫煙対策】受動喫煙対策あり（屋内禁煙）`;

  if (salary) {
    row['基本給_最低額'] = salary.lower;
    row['基本給_最高額'] = salary.upper;
    row['給与'] = salary.detail;
  }

  // 勤務時間パターン(「勤務時間」シートから1件ランダムに選んだセット)
  row['勤務時間_開始_1'] = workTime.start1;
  row['勤務時間_終了_1'] = workTime.end1;
  row['実働時間_最小_1'] = workTime.min1;
  row['休憩時間_1'] = workTime.break1;
  row['勤務時間_開始_2'] = workTime.start2;
  row['勤務時間_終了_2'] = workTime.end2;
  row['実働時間_最小_2'] = workTime.min2;
  row['休憩時間_2'] = workTime.break2;
  row['勤務時間_開始_3'] = workTime.start3;
  row['勤務時間_終了_3'] = workTime.end3;
  row['実働時間_最小_3'] = workTime.min3;
  row['休憩時間_3'] = workTime.break3;
  row['勤務時間_補足'] = workTime.supplement;

  const locationStr = `${location.pref}${location.city}`;
  row['地図用住所'] = locationStr;
  row['勤務地_補足'] = locationStr;

  if (image) {
    row['画像名一覧用'] = image;
    row['画像名1'] = image;
  }

  row['拠点コード'] = company['拠点コード'] || '';
  row['拠点'] = company['拠点'] || '';

  if (String(company['応募方法'] || '').indexOf('電話') >= 0) {
    row['受付電話番号'] = company['電話応募番号'] || '';
  }

  // お仕事番号(メモ相当): 媒体番号-作成日-通勤入寮-雇用形態-カテゴリ番号-給与下限-給与上限-画像番号-勤務地-会社名
  const dateStr = Utilities.formatDate(new Date(creationDate || new Date()), Session.getScriptTimeZone(), 'yyMMdd');
  const commuteCode = HITOMANE_COMMUTE_CODE[commuteOrDorm] || '';
  const employmentCode = HITOMANE_EMPLOYMENT_CODE[employmentType] || HITOMANE_EMPLOYMENT_CODE['正社員'];
  const catLabel = HITOMANE_CATEGORY_NUMBER_LABEL[contentCategory] || '';
  const catCodeBase = (catLabel.match(/^\d+/) || [''])[0];
  const catCode = letter ? `${catCodeBase}${letter}` : catCodeBase;
  const companyMemoName = company['求人メモ用会社名'] || company['会社名'] || '';
  row['お仕事番号'] = [
    HITOMANE_MEDIA_CODE, dateStr, commuteCode, employmentCode, catCode,
    salary ? salary.lower : '', salary ? salary.upper : '',
    (image || ''), locationStr, companyMemoName
  ].join('-');

  return row;
}

function hmBuildRow_(bank, title, content, contentCategory, categoryKey, company, employmentType, commuteOrDorm, location, image, salary, creationDate, status, entryNumber, letter, nightShift, titleDedupWord, partKeys) {
  const row = {};
  HITOMANE_HEADERS.forEach(h => row[h] = HITOMANE_FIXED_VALUES[h] !== undefined ? HITOMANE_FIXED_VALUES[h] : '');

  row['募集番号'] = entryNumber || '';
  row['ステータス'] = status || '掲載';
  const startDate = new Date(creationDate || new Date());
  const endDate = new Date(startDate);
  endDate.setFullYear(endDate.getFullYear() + 1);
  // C列・D列の日付はスラッシュ区切り
  row['開始日'] = Utilities.formatDate(startDate, Session.getScriptTimeZone(), 'yyyy/MM/dd');
  row['終了日'] = Utilities.formatDate(endDate, Session.getScriptTimeZone(), 'yyyy/MM/dd');
  row['都道府県'] = location.pref;
  row['市区町村'] = location.city;
  row['雇用形態'] = employmentType || HITOMANE_FIXED_VALUES['雇用形態'];
  row['募集職種'] = hmBuildComposedTitle_(bank, title, nightShift, titleDedupWord);

  const { qualKey, workTimeKey, workPeriodKey, benefitKey, holidayKey, applyMethodKey, prKey, salaryTextKey } = partKeys;

  if (prKey) row['PR'] = hmPick_(bank.parts[prKey]);
  if (salaryTextKey) row['給与'] = hmPick_(bank.parts[salaryTextKey]);
  if (workTimeKey) row['勤務時間'] = hmPick_(bank.parts[workTimeKey]);
  if (workPeriodKey) row['勤務期間'] = hmPick_(bank.parts[workPeriodKey]);
  if (qualKey) row['応募資格'] = hmPick_(bank.parts[qualKey]);
  if (benefitKey) row['待遇'] = hmPick_(bank.parts[benefitKey]);
  if (holidayKey) row['勤務期間'] = row['勤務期間'] || hmPick_(bank.parts[holidayKey]);

  // S列(応募方法): 会社情報の「1つ目の応募方法」列(現在のG列)を使用
  row['応募方法'] = company['応募方法'] || '';

  // CQ列(応募方法2): パーツシートH列(応募方法)からランダム選択 + 会社情報の「2つ目の応募方法」列(現在のI列)を下につける
  const applyMethodText = applyMethodKey ? hmPick_(bank.parts[applyMethodKey]) : '';
  const secondApplyMethod = company['応募方法#2'] || '';
  const applyMethod2 = [applyMethodText, secondApplyMethod].filter(Boolean).join('\n');
  hmSetSecondColumn_(row, HITOMANE_HEADERS, '応募方法', applyMethod2);

  // CB列(仕事内容)の下に受動喫煙対策の定型文を固定で追加
  row['仕事内容'] = `${content}\n\n【受動喫煙対策】受動喫煙対策あり（屋内禁煙）`;

  // CC列(最低給与額)は常に空欄にする
  row['最低給与額'] = '';

  if (salary) {
    // V列(一覧用給与)とW列(給与)は同じ値を使う
    const salaryText = salary.detail;
    row['一覧用給与'] = salaryText;
    row['給与'] = salaryText;
  }

  // CF列(勤務地)・CM列(地図用住所)にも勤務地情報を入れる
  const locationStr = `${location.pref}${location.city}`;
  row['勤務地'] = locationStr;
  row['地図用住所'] = locationStr;

  if (image) {
    row['画像名一覧用'] = image;
    row['画像名1'] = image;
  }

  row['拠点コード'] = company['拠点コード'] || '';
  row['拠点'] = company['拠点'] || '';

  // CX列(受付電話番号): 会社情報の「応募方法」(G列)が「電話」の場合のみ、「電話応募番号」(H列)を反映する
  if (String(company['応募方法'] || '').indexOf('電話') >= 0) {
    row['受付電話番号'] = company['電話応募番号'] || '';
  }

  // お仕事番号(メモ相当): 媒体番号-作成日-通勤入寮-雇用形態-カテゴリ番号-給与下限-給与上限-職種名(画像番号)-勤務地-会社名
  const dateStr = Utilities.formatDate(new Date(creationDate || new Date()), Session.getScriptTimeZone(), 'yyMMdd');
  const commuteCode = HITOMANE_COMMUTE_CODE[commuteOrDorm] || '';
  const employmentCode = HITOMANE_EMPLOYMENT_CODE[employmentType] || HITOMANE_EMPLOYMENT_CODE['正社員'];
  const catLabel = HITOMANE_CATEGORY_NUMBER_LABEL[contentCategory] || '';
  const catCodeBase = (catLabel.match(/^\d+/) || [''])[0];
  // 6重め/7軽めは、選択した職種名のB列アルファベットを職種番号の直後に付与する(例: 6H)
  const catCode = letter ? `${catCodeBase}${letter}` : catCodeBase;
  const companyMemoName = company['求人メモ用会社名'] || company['会社名'] || '';
  row['お仕事番号'] = [
    HITOMANE_MEDIA_CODE, dateStr, commuteCode, employmentCode, catCode,
    salary ? salary.lower : '', salary ? salary.upper : '',
    (image || ''), locationStr, companyMemoName
  ].join('-');

  return row;
}

// HITOMANE_HEADERSの中に同名列が複数ある場合(「応募方法」がS列・CQ列の2箇所にある等)、
// 「2番目に出てくる方」だけにこの値をセットする(row はオブジェクトなのでキー1つに1値しか持てないため、
// 出力配列を組み立てる段階で2番目の出現位置に上書きする専用の仕組みを使う)
function hmSetSecondColumn_(row, headerList, headerName, value) {
  if (!row.__secondColumnOverrides) row.__secondColumnOverrides = {};
  row.__secondColumnOverrides[headerName] = value;
}

// 出力配列を組み立てる際、同名列の1回目はrow[見出し名]、2回目以降はrow.__secondColumnOverridesの値を使う
function hmRowToArray_(row, headers) {
  headers = headers || HITOMANE_HEADERS;
  const seen = {};
  return headers.map(h => {
    seen[h] = (seen[h] || 0) + 1;
    if (seen[h] >= 2 && row.__secondColumnOverrides && row.__secondColumnOverrides[h] !== undefined) {
      return row.__secondColumnOverrides[h];
    }
    return row[h] !== undefined ? row[h] : '';
  });
}

// ============================================================
// 使用履歴
// ============================================================
// 使用履歴シートは、複数の運用ファイル間で職種名の重複を避けるため、土台ファイル側に一本化している。
// 呼び出し元の引数(ss)は使わず、常に土台ファイルを見る(後方互換のため引数自体は残す)。
function hmGetUsageSheet_(ss) {
  const baseSs = SpreadsheetApp.openById(HM_BASE_SPREADSHEET_ID);
  let sh = baseSs.getSheetByName(HM_USAGE_SHEET_NAME);
  if (!sh) {
    sh = baseSs.insertSheet(HM_USAGE_SHEET_NAME);
    sh.getRange(1, 1, 1, 6).setValues([['会社名(アカウント)', '職種番号(カテゴリ)', '職種名', '累計使用回数', '累計原稿数', '直近使用日']]);
  }
  return sh;
}

// キャッシュ(メモリ上)だけを更新する。実際のシートへの書き込みはhmFlushUsageCache_()でまとめて行う。
function hmUpdateUsageCache_(usageCache, companyName, categoryKey, counts) {
  const nowStr = Utilities.formatDate(new Date(), Session.getScriptTimeZone(), 'yyyy-MM-dd HH:mm');
  Object.keys(counts).forEach(title => {
    const key = `${companyName}||${categoryKey}||${title}`;
    const count = counts[title];
    const idx = usageCache.indexMap[key];
    if (idx !== undefined) {
      const row = usageCache.rows[idx];
      row[3] = (row[3] || 0) + 1;
      row[4] = (row[4] || 0) + count;
      row[5] = nowStr;
    } else {
      usageCache.rows.push([companyName, categoryKey, title, 1, count, nowStr]);
      usageCache.indexMap[key] = usageCache.rows.length - 1;
    }
  });
}

// キャッシュの内容を、1回のsetValues()でまとめてシートに書き込む(1件ずつ書くと非常に遅いため)
function hmFlushUsageCache_(usageCache) {
  if (!usageCache || !usageCache.rows.length) return;
  const sh = hmGetUsageSheet_(); // 使用履歴は常に土台ファイル側(引数は使わない)
  sh.getRange(2, 1, usageCache.rows.length, 6).setValues(usageCache.rows);
  sh.getRange(2, 6, usageCache.rows.length, 1).setNumberFormat('@'); // 文字列として表示(日付+時刻)
}

// ============================================================
// 仕事内容(お仕事内容の本文)の使用履歴。
// 「梱包」「シール貼り」のような通常カテゴリで、会社名×職種番号(カテゴリ)ごとに
// 「まだ使ったことがない仕事内容」を優先してランダムに選ぶために使う。
// 職種名の使用履歴(HM_USAGE_SHEET_NAME)とは別に、土台ファイル側の専用シートに記録する。
// 候補を全部使い切ったら(そのカテゴリの全パターンを使用済みになったら)、また候補全体からランダムに選び直す。
// ============================================================
const HM_CONTENT_USAGE_SHEET_NAME = 'ヒトマネ_アカウント×職種_仕事内容使用履歴';

function hmLoadContentUsageCache_() {
  const ss = SpreadsheetApp.openById(HM_BASE_SPREADSHEET_ID);
  const sh = ss.getSheetByName(HM_CONTENT_USAGE_SHEET_NAME);
  const lastRow = sh ? sh.getLastRow() : 0;
  const rows = (sh && lastRow >= 2) ? sh.getRange(2, 1, lastRow - 1, 5).getValues() : [];
  const indexMap = {};
  const usedSetByCompanyCategory = {}; // `${会社名}||${職種番号}` -> Set(使用済みの仕事内容)
  rows.forEach((row, i) => {
    const [comp, cat, content] = row;
    indexMap[`${comp}||${cat}||${content}`] = i;
    const groupKey = `${comp}||${cat}`;
    if (!usedSetByCompanyCategory[groupKey]) usedSetByCompanyCategory[groupKey] = new Set();
    usedSetByCompanyCategory[groupKey].add(String(content));
  });
  return { rows, indexMap, usedSetByCompanyCategory };
}

// 使用履歴に無い(会社名×職種番号でまだ使ったことがない)仕事内容を優先してランダムに選ぶ。
// 未使用の候補が無ければ(全部使い切っていたら)、通常どおり候補全体からランダムに選び直す。
function hmPickUnusedContent_(contentsPool, companyName, categoryKey, contentUsageCache) {
  const usedSet = (contentUsageCache && contentUsageCache.usedSetByCompanyCategory[`${companyName}||${categoryKey}`]) || new Set();
  const unused = contentsPool.filter(c => !usedSet.has(c));
  return hmPick_(unused.length ? unused : contentsPool);
}

function hmGetContentUsageSheet_() {
  const baseSs = SpreadsheetApp.openById(HM_BASE_SPREADSHEET_ID);
  let sh = baseSs.getSheetByName(HM_CONTENT_USAGE_SHEET_NAME);
  if (!sh) {
    sh = baseSs.insertSheet(HM_CONTENT_USAGE_SHEET_NAME);
    sh.getRange(1, 1, 1, 5).setValues([['会社名(アカウント)', '職種番号(カテゴリ)', '仕事内容', '累計使用回数', '直近使用日']]);
  }
  return sh;
}

// キャッシュ(メモリ上)だけを更新する。実際のシートへの書き込みはhmFlushContentUsageCache_()でまとめて行う。
function hmUpdateContentUsageCache_(contentUsageCache, companyName, categoryKey, counts) {
  if (!contentUsageCache || !counts) return;
  const nowStr = Utilities.formatDate(new Date(), Session.getScriptTimeZone(), 'yyyy-MM-dd HH:mm');
  Object.keys(counts).forEach(content => {
    const key = `${companyName}||${categoryKey}||${content}`;
    const count = counts[content];
    const idx = contentUsageCache.indexMap[key];
    if (idx !== undefined) {
      const row = contentUsageCache.rows[idx];
      row[3] = (row[3] || 0) + count;
      row[4] = nowStr;
    } else {
      contentUsageCache.rows.push([companyName, categoryKey, content, count, nowStr]);
      contentUsageCache.indexMap[key] = contentUsageCache.rows.length - 1;
    }
    const groupKey = `${companyName}||${categoryKey}`;
    if (!contentUsageCache.usedSetByCompanyCategory[groupKey]) contentUsageCache.usedSetByCompanyCategory[groupKey] = new Set();
    contentUsageCache.usedSetByCompanyCategory[groupKey].add(content);
  });
}

// キャッシュの内容を、1回のsetValues()でまとめてシートに書き込む(1件ずつ書くと非常に遅いため)
function hmFlushContentUsageCache_(contentUsageCache) {
  if (!contentUsageCache || !contentUsageCache.rows.length) return;
  const sh = hmGetContentUsageSheet_();
  sh.getRange(2, 1, contentUsageCache.rows.length, 5).setValues(contentUsageCache.rows);
  sh.getRange(2, 5, contentUsageCache.rows.length, 1).setNumberFormat('@'); // 文字列として表示(日付+時刻)
}

// ============================================================
// 【一時的な統合用】もう1つの運用ファイル(のコピー)の使用履歴を、今のメイン運用ファイルの
// 使用履歴と合算して、土台ファイル側の使用履歴シートにまとめて書き込む。
// company||category||title が一致する行は、累計使用回数・累計原稿数を合算し、直近使用日は新しい方を採用する。
// 実行前後で元の2つのファイルの使用履歴シートには一切手を加えない(読み取り専用)。
// 実行し終わったら、この定数と関数は削除してOK。
// ============================================================
const HM_OTHER_OPERATIONAL_SPREADSHEET_ID = '1TPXjtePxF9a5_b19MZqJbQTBhZUqDPuk84tNBcsNrgs'; // 「ヒトマネ 求人原稿自動生成 のコピー」

function runMergeUsageHistoryOnce() {
  const mainSs = SpreadsheetApp.getActiveSpreadsheet(); // 今動かしているメイン運用ファイル
  const otherSs = SpreadsheetApp.openById(HM_OTHER_OPERATIONAL_SPREADSHEET_ID); // もう1つの運用ファイル(のコピー)
  const baseSs = SpreadsheetApp.openById(HM_BASE_SPREADSHEET_ID); // 統合先(土台ファイル)

  const readHistory = (ss) => {
    const sh = ss.getSheetByName(HM_USAGE_SHEET_NAME);
    if (!sh || sh.getLastRow() < 2) return [];
    return sh.getRange(2, 1, sh.getLastRow() - 1, 6).getValues();
  };

  const mainRows = readHistory(mainSs);
  const otherRows = readHistory(otherSs);

  // company||category||title をキーに合算する。累計使用回数・累計原稿数は合計、直近使用日は新しい方を採用
  const merged = {};
  [...mainRows, ...otherRows].forEach(row => {
    const [comp, cat, title, count, docCount, lastDateRaw] = row;
    if (!comp || !cat || !title) return;
    const key = `${comp}||${cat}||${title}`;
    const lastDate = lastDateRaw ? new Date(String(lastDateRaw).replace(' ', 'T')) : null;
    if (!merged[key]) {
      merged[key] = { comp, cat, title, count: Number(count) || 0, docCount: Number(docCount) || 0, lastDate };
    } else {
      merged[key].count += Number(count) || 0;
      merged[key].docCount += Number(docCount) || 0;
      if (lastDate && (!merged[key].lastDate || lastDate > merged[key].lastDate)) merged[key].lastDate = lastDate;
    }
  });

  const mergedRows = Object.values(merged).map(m => [
    m.comp, m.cat, m.title, m.count, m.docCount,
    m.lastDate ? Utilities.formatDate(m.lastDate, Session.getScriptTimeZone(), 'yyyy-MM-dd HH:mm') : ''
  ]);

  let baseSh = baseSs.getSheetByName(HM_USAGE_SHEET_NAME);
  if (baseSh) baseSs.deleteSheet(baseSh);
  baseSh = baseSs.insertSheet(HM_USAGE_SHEET_NAME);
  baseSh.getRange(1, 1, 1, 6).setValues([['会社名(アカウント)', '職種番号(カテゴリ)', '職種名', '累計使用回数', '累計原稿数', '直近使用日']]);
  if (mergedRows.length) {
    baseSh.getRange(2, 1, mergedRows.length, 6).setValues(mergedRows);
    baseSh.getRange(2, 6, mergedRows.length, 1).setNumberFormat('@');
  }

  hmSafeAlert_(
    '使用履歴を統合しました\n\n' +
    `メイン運用ファイル: ${mainRows.length}行\n` +
    `もう1つのファイル(のコピー): ${otherRows.length}行\n` +
    `統合後(重複合算後): ${mergedRows.length}行\n\n` +
    `土台ファイルの「${HM_USAGE_SHEET_NAME}」シートに保存しました。\n` +
    '元の2ファイルの使用履歴シートはそのまま残っています(今後は不要なので、確認後に手動で削除してください)。'
  );
}

// ============================================================
// 【一時的な統合用】もう1つの運用ファイル(のコピー)の「職種名管理」チェック状態を、
// 土台ファイル側の「職種名管理」に合算する(OR合成: どちらか一方でもTRUEならTRUEにする)。
// 既存のTRUEは理由を問わず一切消さない(hmSyncPairedTitleUsage_と同じ方針)。
// 会社名・職種名のラベルで突き合わせるため、行や列の並び順が2ファイルで多少違っていても問題ない。
// 実行し終わったら、この関数は削除してOK。
// ============================================================
function runMergeTitleManagementOnce() {
  const otherSs = SpreadsheetApp.openById(HM_OTHER_OPERATIONAL_SPREADSHEET_ID);
  const baseSs = SpreadsheetApp.openById(HM_BASE_SPREADSHEET_ID);

  const otherSh = otherSs.getSheetByName(HM_TITLE_MANAGEMENT_SHEET_NAME);
  const baseSh = baseSs.getSheetByName(HM_TITLE_MANAGEMENT_SHEET_NAME);
  if (!otherSh) { hmSafeAlert_(`もう1つのファイルに「${HM_TITLE_MANAGEMENT_SHEET_NAME}」シートが見つかりませんでした。`); return; }
  if (!baseSh) { hmSafeAlert_(`土台ファイルに「${HM_TITLE_MANAGEMENT_SHEET_NAME}」シートが見つかりませんでした。`); return; }

  // シートから {カテゴリ||会社名||職種名 -> true} のSetを作る(「6重め」「7軽め」ブロックをラベルで検出)
  const readTrueSet = (sh) => {
    const lastCol = sh.getLastColumn();
    const lastRow = sh.getLastRow();
    const headerVals = sh.getRange(1, 1, 1, lastCol).getValues()[0].map(v => String(v).trim());
    const blockStarts = [];
    headerVals.forEach((v, i) => { if (v === '6重め' || v === '7軽め') blockStarts.push({ category: v, col: i + 1 }); });
    const result = new Set();
    blockStarts.forEach((block, idx) => {
      const blockEndCol = (idx + 1 < blockStarts.length) ? blockStarts[idx + 1].col - 1 : lastCol;
      const blockWidth = blockEndCol - block.col;
      if (blockWidth <= 0 || lastRow < 2) return;
      const companyNamesRow = sh.getRange(1, block.col + 1, 1, blockWidth).getValues()[0].map(v => String(v).trim());
      const numDataRows = lastRow - 1;
      const titleVals = sh.getRange(2, block.col, numDataRows, 1).getValues();
      const checkVals = sh.getRange(2, block.col + 1, numDataRows, blockWidth).getValues();
      for (let r = 0; r < numDataRows; r++) {
        const title = String(titleVals[r][0] || '').trim();
        if (!title) continue;
        for (let c = 0; c < blockWidth; c++) {
          const companyName = companyNamesRow[c];
          if (!companyName) continue;
          const v = checkVals[r][c];
          const isTrue = v === true || String(v).toUpperCase() === 'TRUE';
          if (isTrue) result.add(`${block.category}||${companyName}||${title}`);
        }
      }
    });
    return result;
  };

  const otherTrueSet = readTrueSet(otherSh);

  // 土台ファイル側に、もう1つのファイルでTRUEだった組み合わせを反映する(FALSE→TRUEへの追記のみ、既存のTRUEはそのまま)
  const lastCol = baseSh.getLastColumn();
  const lastRow = baseSh.getLastRow();
  const headerVals = baseSh.getRange(1, 1, 1, lastCol).getValues()[0].map(v => String(v).trim());
  const blockStarts = [];
  headerVals.forEach((v, i) => { if (v === '6重め' || v === '7軽め') blockStarts.push({ category: v, col: i + 1 }); });

  let updatedCount = 0;
  blockStarts.forEach((block, idx) => {
    const blockEndCol = (idx + 1 < blockStarts.length) ? blockStarts[idx + 1].col - 1 : lastCol;
    const blockWidth = blockEndCol - block.col;
    if (blockWidth <= 0 || lastRow < 2) return;
    const companyNamesRow = baseSh.getRange(1, block.col + 1, 1, blockWidth).getValues()[0].map(v => String(v).trim());
    const numDataRows = lastRow - 1;
    const titleVals = baseSh.getRange(2, block.col, numDataRows, 1).getValues();
    const checkVals = baseSh.getRange(2, block.col + 1, numDataRows, blockWidth).getValues();

    let blockChanged = false;
    for (let r = 0; r < numDataRows; r++) {
      const title = String(titleVals[r][0] || '').trim();
      if (!title) continue;
      for (let c = 0; c < blockWidth; c++) {
        const companyName = companyNamesRow[c];
        if (!companyName) continue;
        if (!otherTrueSet.has(`${block.category}||${companyName}||${title}`)) continue;
        const current = checkVals[r][c];
        const currentBool = current === true || String(current).toUpperCase() === 'TRUE';
        if (!currentBool) { checkVals[r][c] = true; blockChanged = true; updatedCount++; }
      }
    }
    if (blockChanged) baseSh.getRange(2, block.col + 1, numDataRows, blockWidth).setValues(checkVals);
  });

  hmSafeAlert_(
    `「${HM_TITLE_MANAGEMENT_SHEET_NAME}」を統合しました\n\n` +
    `もう1つのファイル由来で新たにTRUEにしたセル: ${updatedCount}件\n\n` +
    '土台ファイル側に反映済みです。もう1つのファイル側の元のシートはそのまま残っています(今後は不要なので、確認後に手動で削除してください)。'
  );
}

// ============================================================
// 【一時的なクリーンアップ用】土台ファイルへのコピーが完了した「土台」シートを、
// 今開いているスプレッドシート(運用ファイル)側から削除する。
// 安全のため、土台ファイル側に「同じ名前のシート」が実在することを確認できたものだけを削除する。
// 土台ファイル側にまだ無い名前のシートは、コピー漏れの可能性があるので絶対に削除しない(対象外として報告する)。
// 「ヒトマネ実行設定」「_ヒトマネ_プルダウン用リスト」「使用履歴」「検品シート」「ヒトマネ出力_」等の
// 運用データは、そもそも土台ロール判定(hmIsBaseSheetRole_)に該当しないため対象にならない。
// 運用ファイル自体が軽くなることで、⑤検品シート作成などのタイムアウトが解消するはず。
// 実行し終わったら、この関数は削除してOK。
// ============================================================
function runDeleteMigratedBaseSheetsFromMainOnce() {
  const srcSs = SpreadsheetApp.getActiveSpreadsheet();
  const baseSs = SpreadsheetApp.openById(HM_BASE_SPREADSHEET_ID);
  const baseNames = new Set(baseSs.getSheets().map(sh => sh.getName()));

  const targets = [];      // 削除するシート名
  const skipped = [];      // 土台ファイル側に同名シートが無いため対象外にしたもの(安全のため削除しない)

  srcSs.getSheets().forEach(sh => {
    const role = hmClassifySheet_(sh);
    if (!hmIsBaseSheetRole_(role)) return; // 土台ロールではない(実行設定・出力シート等)→対象外
    if (baseNames.has(sh.getName())) {
      targets.push(sh.getName());
    } else {
      skipped.push(`${sh.getName()} [${role}]`);
    }
  });

  if (!targets.length) {
    hmSafeAlert_(
      '削除対象の土台シートが見つかりませんでした(既に削除済みかもしれません)。\n\n' +
      (skipped.length ? `※コピー漏れの疑いで対象外にしたシート: ${skipped.length}件\n${skipped.join('\n')}` : '')
    );
    return;
  }

  const deleted = [];
  targets.forEach(name => {
    const sh = srcSs.getSheetByName(name);
    if (sh) { srcSs.deleteSheet(sh); deleted.push(name); }
  });

  let msg = `このファイルから削除しました: ${deleted.length}件\n${deleted.join('\n')}`;
  if (skipped.length) {
    msg += `\n\n※土台ファイル側に同名シートが無いため削除しなかったシート: ${skipped.length}件\n${skipped.join('\n')}`;
  }
  Logger.log(msg);
  hmSafeAlert_(msg);
}

// ============================================================
// ④生成済み原稿シート一括削除
// ============================================================
function hmDeleteAllOutputSheets() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const ui = SpreadsheetApp.getUi();
  const outputSheets = ss.getSheets().filter(sh => sh.getName().indexOf('ヒトマネ出力_') === 0);
  if (!outputSheets.length) { ui.alert('削除対象の「ヒトマネ出力_」シートが見つかりませんでした。'); return; }
  const names = outputSheets.map(sh => sh.getName());
  const response = ui.alert('生成済み原稿シートの一括削除', `以下の${names.length}件を削除します。よろしいですか?\n\n` + names.join('\n'), ui.ButtonSet.YES_NO);
  if (response !== ui.Button.YES) return;
  outputSheets.forEach(sh => ss.deleteSheet(sh));

  const configSh = ss.getSheetByName(HM_CONFIG_SHEET_NAME);
  let resetCount = 0;
  if (configSh && configSh.getLastRow() >= HM_CONFIG_DATA_START_ROW) {
    const numRows = configSh.getLastRow() - HM_CONFIG_DATA_START_ROW + 1;
    const statusValues = configSh.getRange(HM_CONFIG_DATA_START_ROW, 16, numRows, 1).getValues();
    statusValues.forEach((row, i) => {
      if (names.some(n => String(row[0] || '').indexOf(n) >= 0)) {
        configSh.getRange(HM_CONFIG_DATA_START_ROW + i, 16).clearContent();
        configSh.getRange(HM_CONFIG_DATA_START_ROW + i, HM_CONFIG_COL_PROGRESS).clearContent();
        configSh.getRange(HM_CONFIG_DATA_START_ROW + i, 18).clearContent();
        resetCount++;
      }
    });
  }
  if (configSh) configSh.setFrozenRows(3); // シート削除で表示が崩れることがあるため念のため再設定する
  ui.alert(`${names.length}件削除しました。実行状況を${resetCount}件リセットしたので再実行できます。`);
}

// ============================================================
// タイムアウト対策ユーティリティ(⑤検品シート作成で使用)
// ============================================================
// スプレッドシートのサービスタイムアウトなど、一時的なエラーが出たときに間隔を空けて再試行する
function hmWithRetry_(fn, maxRetries) {
  // このファイルは一時的にGoogle側でアクセスが詰まる(タイムアウトする)ことがあるため、
  // 3回程度の再試行では足りないケースがあった。回数と待機時間を増やし、粘り強く再試行する。
  maxRetries = maxRetries || 6;
  for (let attempt = 1; attempt <= maxRetries; attempt++) {
    try {
      return fn();
    } catch (e) {
      const isTransient = /タイムアウト|timeout|Service (Spreadsheets|invoked too many times)/i.test(e.message);
      if (!isTransient || attempt === maxRetries) throw e;
      Logger.log(`一時的なエラーのためリトライします (${attempt}/${maxRetries}): ${e.message}`);
      Utilities.sleep(3000 * attempt); // 3秒→6秒→9秒→12秒→15秒と間隔を広げてリトライ(最大約48秒待つ)
    }
  }
}

// 大きい範囲を一度に読まず、行を分割しながら読み込む(getValues/getBackgroundsどちらにも使う)
function hmReadInChunks_(sheet, startRow, numRows, numCols, chunkSize, readerFn) {
  const result = [];
  for (let offset = 0; offset < numRows; offset += chunkSize) {
    const rows = Math.min(chunkSize, numRows - offset);
    const chunk = hmWithRetry_(() => readerFn(sheet.getRange(startRow + offset, 1, rows, numCols)));
    chunk.forEach(r => result.push(r));
  }
  return result;
}

// ============================================================
// ============================================================
// ⑤検品(結果はスプシに書かず、画面中央の確認画面に表示する)
// ============================================================
function hmCreateInspectionSheet() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const ui = SpreadsheetApp.getUi();
  const outputSheets = hmWithRetry_(() => ss.getSheets().filter(sh => sh.getName().indexOf('ヒトマネ出力_') === 0));
  if (!outputSheets.length) { ui.alert('検品対象の「ヒトマネ出力_」シートが見つかりませんでした。'); return; }

  const colOld = {};
  HITOMANE_HEADERS.forEach((h, i) => { colOld[h] = i; });
  const colNew = {};
  HITOMANE_NEW_HEADERS.forEach((h, i) => { colNew[h] = i; });

  const READ_CHUNK = 2000; // 一度に読む行数。タイムアウトが続くようなら1000などさらに小さくしてください
  const results = [];

  outputSheets.forEach(outSh => {
    const name = outSh.getName();
    const lastRow = hmWithRetry_(() => outSh.getLastRow());
    const count = Math.max(lastRow - 1, 0);
    const isNewFmt = name.indexOf('ヒトマネ出力_新_') === 0;
    if (count === 0) { results.push({ name, fmt: isNewFmt ? '新FMT' : '旧FMT', count: 0, problems: [], ok: true }); return; }

    const headersForSheet = isNewFmt ? HITOMANE_NEW_HEADERS : HITOMANE_HEADERS;
    const col = isNewFmt ? colNew : colOld;
    const fields = isNewFmt
      ? { job: '募集職種', content: '仕事内容', qual: '応募資格', benefit: '待遇', pr: 'PR', salary: '基本給_最低額', pref: '勤務地_都道府県', city: '勤務地_市区町村' }
      : { job: '募集職種', content: '仕事内容', qual: '応募資格', benefit: '待遇', pr: 'PR', salary: '最低給与額', pref: '都道府県', city: '市区町村' };

    const data = hmReadInChunks_(outSh, 2, count, headersForSheet.length, READ_CHUNK, range => range.getValues());

    let blankJob = 0, blankContent = 0, blankQual = 0, blankBenefit = 0, blankPR = 0, badSalary = 0, blankLoc = 0;
    data.forEach(row => {
      if (!row[col[fields.job]]) blankJob++;
      if (!row[col[fields.content]]) blankContent++;
      if (!row[col[fields.qual]]) blankQual++;
      if (!row[col[fields.benefit]]) blankBenefit++;
      if (!row[col[fields.pr]]) blankPR++;
      if (row[col[fields.salary]] === '' || isNaN(Number(row[col[fields.salary]]))) badSalary++;
      if (!row[col[fields.pref]]) blankLoc++;
    });

    // 予約行ごとの区切り(背景色の切り替わり)ごとに、勤務地の重複を数える
    const bgRows = hmReadInChunks_(outSh, 2, count, 1, READ_CHUNK, range => range.getBackgrounds());
    const bgColors = bgRows.map(row => row[0].toLowerCase());
    const segmentBoundaries = [0];
    for (let i = 1; i < count; i++) {
      if (bgColors[i] !== bgColors[i - 1]) segmentBoundaries.push(i);
    }
    segmentBoundaries.push(count);

    let locDup = 0;
    for (let s = 0; s < segmentBoundaries.length - 1; s++) {
      const locCounter = {};
      for (let ri = segmentBoundaries[s]; ri < segmentBoundaries[s + 1]; ri++) {
        const key = `${data[ri][col[fields.pref]]}|${data[ri][col[fields.city]]}`;
        locCounter[key] = (locCounter[key] || 0) + 1;
      }
      locDup += Object.values(locCounter).filter(c => c > 1).reduce((sum, c) => sum + (c - 1), 0);
    }

    const problems = [];
    if (blankJob) problems.push(`募集職種空欄 ${blankJob}件`);
    if (blankContent) problems.push(`仕事内容空欄 ${blankContent}件`);
    if (blankQual) problems.push(`応募資格空欄 ${blankQual}件`);
    if (blankBenefit) problems.push(`待遇空欄 ${blankBenefit}件`);
    if (blankPR) problems.push(`PR空欄 ${blankPR}件`);
    if (badSalary) problems.push(`最低給与額が数値でない ${badSalary}件`);
    if (blankLoc) problems.push(`勤務地空欄 ${blankLoc}件`);
    if (locDup) problems.push(`勤務地の重複 ${locDup}件`);
    results.push({ name, fmt: isNewFmt ? '新FMT' : '旧FMT', count, problems, ok: !problems.length });
  });

  hmShowInspectionDialog_(results);
}

// 検品結果を画面中央に表示する。「確認」ボタンを押すまで閉じない
function hmShowInspectionDialog_(results) {
  const esc = s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  const okCount = results.filter(r => r.ok).length;
  const rows = results.map(r => `
    <div class="item ${r.ok ? 'ok' : 'ng'}">
      <div class="judge">${r.ok ? '✅OK' : '⚠️要確認'}</div>
      <div class="name">${esc(r.name)}</div>
      <div class="meta">${r.fmt}／${r.count}件</div>
      ${r.ok ? '' : `<div class="prob">${r.problems.map(esc).join('<br>')}</div>`}
    </div>`).join('');

  const html = `
    <style>
      body { font-family: sans-serif; font-size: 13px; margin: 0; padding: 12px 16px; color: #222; }
      .sum { font-weight: bold; margin-bottom: 10px; }
      .list { max-height: 330px; overflow-y: auto; }
      .item { border-left: 4px solid #15803D; background: #F3FAF5; padding: 8px 10px; margin-bottom: 8px; }
      .item.ng { border-left-color: #B45309; background: #FFF7ED; }
      .judge { font-weight: bold; }
      .name { word-break: break-all; margin: 2px 0; }
      .meta { color: #666; font-size: 12px; }
      .prob { color: #B45309; margin-top: 4px; }
      .btn { display: block; margin: 12px auto 0; padding: 8px 40px; font-size: 14px; font-weight: bold;
             background: #4472C4; color: #fff; border: none; border-radius: 4px; cursor: pointer; }
    </style>
    <div class="sum">検品結果：${results.length}シート中 ${okCount}シートがOK</div>
    <div class="list">${rows}</div>
    <button class="btn" onclick="google.script.host.close()">確認</button>`;

  const output = HtmlService.createHtmlOutput(html).setWidth(460).setHeight(480);
  SpreadsheetApp.getUi().showModalDialog(output, '検品結果');
}