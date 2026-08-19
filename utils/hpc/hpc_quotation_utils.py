"""
繳費單（報價單）的內容組裝、HTML 渲染與 PDF 轉檔。

「寄送繳費單」刻意與「寄送確認信」分成兩條獨立的流程：
  - 確認信 (hpc_quota_routes._build_confirm_email_content)
    寄的是年度用量核對信，沒有附件。
  - 繳費單 (本模組)
    信件本文用 templates/email/bill_notification.html，
    真正的報價單 templates/quotation/hpc_quotation.html 會轉成 PDF 當附件。

報價單上「計算資源」那張表要出現哪幾列，是由「⚙️ 設定 → 繳費單格式設定」
(QuotationItem) 決定的，金額則一律回 Accounting × Serverlist 實算，
不吃設定裡的顯示係數，避免有人改了顯示值就讓帳單金額失真。
"""

import io
import os
import pathlib
import re
import tempfile
from datetime import date

from flask import current_app, render_template, render_template_string
from reportlab.lib.fonts import addMapping
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from xhtml2pdf import pisa
from xhtml2pdf.default import DEFAULT_FONT

from database.hpc_model import PrepaidAmount
from utils.email_utils import get_bill_notification_template_html
from utils.hpc.hpc_bill_utils import build_quotation_rows, build_empty_quotation_rows

# 從自由文字的聯絡資訊裡撈電話：抓連續的數字、-、()、空白、分機字樣。
# 聯絡資訊欄是自由輸入，這裡只做「盡量帶入」，帶錯或帶不到都可在視窗裡手動改。
PHONE_PATTERN = re.compile(r'(?:\+?\d{1,3}[-\s]?)?(?:\(\d{2,4}\)|\d{2,4})[-\s]?\d{3,4}[-\s]?\d{3,4}(?:\s*(?:#|分機)\s*\d{1,6})?')
EMAIL_IN_TEXT_PATTERN = re.compile(r'[\w.+-]+@[\w-]+\.[\w.-]+')

# Jinja 的樣板名稱一律用正斜線，不能用 os.path.join —— 在 Windows 上會變成
# 反斜線，Flask 找不到樣板而丟 TemplateNotFound。
QUOTATION_TEMPLATE_PATH = 'quotation/hpc_quotation.html'

# 報價單的 CSS 用 'GenRyuMin' 與 'TaipeiSans' 兩種字型（Excel 匯出時寫死的），
# 但 xhtml2pdf 不知道去哪裡找，沒註冊的話 PDF 上的中文會整片變成黑方塊。
# source/ 底下已經有對應的字型檔，轉檔前先註冊起來。
#
# ⚠️ 不能用 CSS 的 @font-face：xhtml2pdf 會先把字型寫進 NamedTemporaryFile，
# 再叫 reportlab 用「檔名」重新開啟它。Windows 的 NamedTemporaryFile 是獨佔開啟的，
# 第二次開啟一定失敗（TTFError: Can't open file ...tmpXXXX.ttf）。
# 因此改成直接向 reportlab 註冊，並把字型名稱塞進 xhtml2pdf 的字型對照表，
# 讓它在解析 font-family 時就查得到，完全不需要走 @font-face 那條路。
PDF_FONTS = [
    ('GenRyuMin', 'GenRyuMin2TW-R.ttf'),
    ('TaipeiSans', 'TaipeiSansTCBeta-Regular.ttf'),
]

# 字型註冊只要做一次；每次轉檔都重註冊會拖慢速度，也會讓 reportlab 一直發出警告
_pdf_fonts_registered = False


def _format_amount(value):
    """金額顯示格式：$1,234（報價單上不列小數）。"""
    return '${:,.0f}'.format(round(float(value or 0)))


def _format_core_hours(value):
    """核心小時顯示格式：1,234（與原始報價單一致，不列小數）。"""
    return '{:,.0f}'.format(round(float(value or 0)))


def _format_coefficient(value):
    """
    收費係數顯示格式。

    None 代表這一列涵蓋的 queue 單價不一致、又沒有在設定裡指定顯示值，
    這時印 '-' 比印一個「係數 × 使用量 ≠ 總價」的數字誠實。
    """
    if value is None:
        return '-'
    text = '{:.4f}'.format(float(value)).rstrip('0').rstrip('.')
    return text or '0'


def _decorate_rows(rows):
    """
    替每一列與其子項補上畫面／範本要用的顯示字串。

    一列可能有多個子項（entries）：當該列涵蓋的 queue 單價不同時，
    報價單上「計算資源」那格會跨列合併，收費係數則逐項列出並附註 queue。
    只有一個子項時 queue 註記留空，維持原本單純的一行。
    """
    decorated = []
    for row in rows:
        entries = row.get('entries')
        if not entries:
            # 相容只給單一係數的呼叫端（例如預繳帳單自行組出來的列）
            entries = [{
                'coefficient': row.get('coefficient'),
                'queues': row.get('queues') or [],
                'core_hours': row.get('core_hours'),
                'amount': row.get('amount'),
                'core_hours_text': row.get('core_hours_text')
            }]

        decorated_entries = []
        for entry in entries:
            decorated_entries.append({
                'coefficient': entry.get('coefficient'),
                'coefficient_text': _format_coefficient(entry.get('coefficient')),
                'queues': entry.get('queues') or [],
                # 多個子項時才需要標出這個係數對應哪些 queue
                'queue_label': '、'.join(entry.get('queues') or []) if len(entries) > 1 else '',
                'core_hours': entry.get('core_hours') or 0,
                'core_hours_text': (entry.get('core_hours_text')
                                    if entry.get('core_hours_text') is not None
                                    else _format_core_hours(entry.get('core_hours'))),
                'amount': entry.get('amount') or 0,
                'amount_text': _format_amount(entry.get('amount'))
            })

        total_core_hours = row.get('core_hours')
        if total_core_hours is None:
            total_core_hours = sum(e['core_hours'] for e in decorated_entries)
        total_amount = row.get('amount')
        if total_amount is None:
            total_amount = sum(e['amount'] for e in decorated_entries)

        decorated.append({
            'label': row.get('label') or '',
            'entries': decorated_entries,
            'entry_count': len(decorated_entries),
            'core_hours': total_core_hours,
            'core_hours_text': _format_core_hours(total_core_hours),
            'amount': total_amount,
            'amount_text': _format_amount(total_amount)
        })
    return decorated


def get_unpaid_prepaids(username):
    """
    該帳號「已開立但尚未繳款」的預繳紀錄（活躍那一筆，不含 is_history 的存檔）。

    「開立預繳帳單」只有在這裡有東西時才能使用，
    沒有未繳款的預繳紀錄卻開預繳帳單，等於憑空生出一筆不存在的應收款。
    """
    if not username:
        return []

    return PrepaidAmount.query.filter(
        PrepaidAmount.username == username,
        PrepaidAmount.is_paid == False,   # noqa: E712 - SQLAlchemy 需要 == 而非 is
        PrepaidAmount.is_history == False
    ).order_by(PrepaidAmount.year.asc(), PrepaidAmount.id.asc()).all()


def _extract_contact_fields(contact):
    """
    從聯絡人資料推出報價單表頭要帶入的預設值。

    這些只是「盡量自動帶入」，全部都可以在寄送繳費單的視窗裡手動修改，
    因為 secondary_contacts.info 是自由文字欄位，格式不保證。
    """
    primary_name = ''
    primary_email = ''
    primary_phone = ''

    # 主要聯絡人優先，其次才看其他聯絡人；被關閉寄信的一律跳過
    ordered = sorted(
        [sc for sc in contact.secondaries if not sc.email_disabled],
        key=lambda s: (not bool(s.is_primary), s.id or 0)
    )

    for sc in ordered:
        info = sc.info or ''
        if not primary_email:
            match = EMAIL_IN_TEXT_PATTERN.search(info)
            if match:
                primary_email = match.group(0)
                if not primary_name:
                    primary_name = sc.name or ''
        if not primary_phone:
            # 先把 Email 從文字裡拿掉，免得信箱裡的數字被當成電話
            phone_source = EMAIL_IN_TEXT_PATTERN.sub(' ', info)
            match = PHONE_PATTERN.search(phone_source)
            if match:
                primary_phone = match.group(0).strip()
                if not primary_name:
                    primary_name = sc.name or ''

    if not primary_name:
        primary_name = contact.applicant or ''

    # 客戶名稱：一級單位 + 申請人（例如「國立臺灣大學農經系林柏熊教授」），
    # 資料不齊時退回申請團隊名稱
    parts = [p for p in [(contact.dept_level1 or '').strip(), (contact.applicant or '').strip()] if p]
    customer_name = ''.join(parts) or (contact.team_name or '')

    return {
        'customer_name': customer_name,
        'contact_person': primary_name,
        'contact_phone': primary_phone,
        'contact_email': primary_email
    }


def _build_prepaid_target_options(rows):
    """
    列出預繳金額可以計入的位置。

    每個選項對應報價單上「某一列的某一個係數子項」，用 "列索引:子項索引" 當識別碼。
    直接用列/子項而不是 (server, queue)，是因為一個子項本來就可能涵蓋多個
    同價的 queue，用列/子項才能精準對應到金額最後會落在哪一格。
    沒有費率的子項不列入（算不出可購買的核心小時數）。
    """
    options = []
    for row_index, row in enumerate(rows):
        for entry_index, entry in enumerate(row.get('entries') or []):
            if entry.get('coefficient') in (None, 0):
                continue
            queues = entry.get('queues') or []
            suffix = f" ({'、'.join(queues)})" if queues and len(row.get('entries') or []) > 1 else ''
            options.append({
                'key': f'{row_index}:{entry_index}',
                'label': f"{row.get('label') or ''}{suffix}",
                'coefficient': entry['coefficient'],
                'queues': queues
            })
    return options


def _apply_prepaid_amount(rows, target_key, amount):
    """
    把預繳金額放進指定的那一格，並回推等值的核心小時數。

    回推的用意是讓預繳帳單跟一般帳單在算術上完全一致
    （係數 × 使用量 = 總價），看起來就是「這筆錢買了多少核心小時」，
    而不是一張欄位空空、只有金額的特殊單據。
    """
    row_index, entry_index = (int(part) for part in target_key.split(':'))
    row = rows[row_index]
    entry = row['entries'][entry_index]

    coefficient = float(entry['coefficient'])
    entry['amount'] = round(amount, 2)
    entry['core_hours'] = round(amount / coefficient, 2) if coefficient else 0.0

    row['amount'] = round(sum(e['amount'] for e in row['entries']), 2)
    row['core_hours'] = round(sum(e['core_hours'] for e in row['entries']), 2)


def build_quotation_context(contact, year, kind='normal', overrides=None):
    """
    組出渲染報價單與通知信所需的完整資料。

    Args:
        contact: Contact 物件
        year:    帳務年度（一般帳單為「去年度」，預繳帳單為該筆預繳的年度）
        kind:    'normal' = 依用量計價的一般帳單
                 'prepaid' = 依未繳款預繳紀錄開立的預繳帳單
        overrides: 使用者在視窗裡手動改過的欄位（表頭那幾格），會覆蓋自動帶入值

    Returns:
        (context dict, error message)；error 不為 None 時 context 為 None。
    """
    overrides = overrides or {}
    formal_account = contact.get_formal_account()

    prepaid_targets = []

    if kind == 'prepaid':
        prepaids = get_unpaid_prepaids(formal_account)
        if not prepaids:
            return None, '該帳號沒有尚未繳款的預繳紀錄，無法開立預繳帳單。'

        prepaid_total = round(sum(float(p.amount or 0) for p in prepaids), 2)

        # 預繳帳單的版面要跟一般帳單完全一樣，所以先取同一套「計算資源」骨架，
        # 再把預繳金額放進使用者指定的那一格。
        skeleton = build_empty_quotation_rows(year)
        rows = skeleton['rows']
        prepaid_targets = _build_prepaid_target_options(rows)

        if not prepaid_targets:
            return None, ('目前的「繳費單格式設定」中沒有任何具備費率的計算資源，'
                          '無法決定預繳金額要計入哪一項，請先至「⚙️ 設定 → 繳費單格式設定」完成設定。')

        target_key = str(overrides.get('prepaid_target') or '').strip()
        if target_key not in {t['key'] for t in prepaid_targets}:
            target_key = prepaid_targets[0]['key']

        _apply_prepaid_amount(rows, target_key, prepaid_total)

        subtotal = prepaid_total
        # 預繳賣的是額度、不牽涉既有用量，所以沒有漏算用量的問題
        unmatched, unmatched_amount, unpriced = [], 0.0, []
        default_period_year = prepaids[0].year or year
        defaults_extra = {'prepaid_target': target_key}
    else:
        defaults_extra = {}
        if not formal_account:
            return None, '該聯絡人尚未對應正式帳號，無法計算使用量以開立繳費單。'

        result = build_quotation_rows(formal_account, year)
        rows = result['rows']
        subtotal = result['subtotal']
        unmatched = result['unmatched']
        unmatched_amount = result['unmatched_amount']
        unpriced = result['unpriced']
        default_period_year = year

    decorated_rows = _decorate_rows(rows)
    defaults = _extract_contact_fields(contact)
    defaults.update({
        'quote_date': date.today().strftime('%Y/%m/%d'),
        # 預設帶入整個帳務年度，管理員可在視窗裡改成實際使用區間
        'usage_period': f'{default_period_year}/01/01-{default_period_year}/12/31'
    })
    defaults.update(defaults_extra)

    # 只讓表頭那幾個欄位可以被覆寫；金額相關的一律以資料庫實算為準
    for key in ('customer_name', 'contact_person', 'contact_phone', 'contact_email',
                'quote_date', 'usage_period'):
        value = overrides.get(key)
        if value is not None and str(value).strip() != '':
            defaults[key] = str(value).strip()

    context = dict(defaults)
    context.update({
        'kind': kind,
        'usage_year': year,
        # 預繳帳單刻意不標示「預繳」：對客戶而言它就是一張繳費單，
        # 版面與用字都與一般帳單一致，差別只在金額的來源。
        'prepaid_targets': prepaid_targets,
        'quotation_rows': decorated_rows,
        'subtotal': subtotal,
        'subtotal_text': _format_amount(subtotal),
        # 報價單上稅金標示「內含」，因此總價與小計相同；
        # 未來若要外加稅金，改這裡即可，範本不必動。
        'total': subtotal,
        'total_text': _format_amount(subtotal),
        'unmatched': unmatched,
        'unmatched_amount': unmatched_amount,
        'unpriced': unpriced
    })
    return context, None


def render_quotation_html(context):
    """把 templates/quotation/hpc_quotation.html 渲染成完整的報價單 HTML。"""
    return render_template(QUOTATION_TEMPLATE_PATH, **context)


def render_bill_notification_html(context):
    """
    渲染繳費單通知信的信件本文。

    範本可能來自資料庫的自訂版本，所以用 render_template_string 而不是
    render_template（後者只吃 templates/ 底下的實體檔案）。
    """
    template_html = get_bill_notification_template_html()
    return render_template_string(template_html, **context)


def _ensure_pdf_fonts():
    """
    向 reportlab 註冊報價單需要的中文字型，並讓 xhtml2pdf 查得到它們。

    xhtml2pdf 解析 font-family 時是查 pisaContext.fontList，而該表是在
    建立文件時從 xhtml2pdf.default.DEFAULT_FONT 複製過去的。因此只要在
    轉檔前把字型名稱補進 DEFAULT_FONT，CSS 裡的 'GenRyuMin' / 'TaipeiSans'
    就會直接對到我們註冊好的字型，不必經過會在 Windows 上失敗的 @font-face。

    順便把 serif / sans-serif 也指向中文字型：報價單的 CSS 寫的是
    font-family:'GenRyuMin', serif，萬一哪天字型檔不在，退到 serif 至少
    還是中文字型而不是印出黑方塊。
    """
    global _pdf_fonts_registered
    if _pdf_fonts_registered:
        return

    registered = []
    for font_name, filename in PDF_FONTS:
        path = os.path.join(current_app.root_path, 'source', filename)
        if not os.path.exists(path):
            current_app.logger.warning(f'找不到 PDF 字型檔 {path}，報價單 PDF 的中文可能顯示為方塊。')
            continue
        try:
            pdfmetrics.registerFont(TTFont(font_name, path))
            # 這兩個字型檔只有一種字重，粗體／斜體都對應到同一個實體字型，
            # 沒有 addMapping 的話 reportlab 遇到 font-weight:700 會找不到而報錯
            for bold in (0, 1):
                for italic in (0, 1):
                    addMapping(font_name, bold, italic, font_name)
            DEFAULT_FONT[font_name.lower()] = font_name
            registered.append(font_name)
        except Exception as e:
            current_app.logger.warning(f'註冊 PDF 字型 {font_name} 失敗：{e}')

    if registered:
        fallback = registered[0]
        for generic in ('serif', 'sans-serif', 'sans serif'):
            DEFAULT_FONT[generic] = fallback

    _pdf_fonts_registered = True


# 退路（xhtml2pdf）用的紙張設定，與主要途徑一樣是 A4 直式。
#
# ⚠️ 提醒：xhtml2pdf 不會像瀏覽器那樣把過寬的內容縮到符合紙張，
# 報價單本體 880pt 寬硬塞進 A4 直式（595pt）一定會換行、版面會很醜。
# 但這條路只有在 Chromium 不可用時才會走到（屬於待修的部署問題），
# 紙張大小仍與正常情況一致，避免同一種單據卻印出不同開數。
PDF_PAGE_CSS = '@page { size: A4 portrait; margin: 12pt; }'

# Chromium 列印時的縮放比例（A4 直式）。
#
# 實測整份內容渲染出來約 1175px 寬、1031px 高（高度含右下角那張絕對定位的
# 關防圖，它落在 y=710~1031，正是最後那個 181.5pt 空白列預留給它的位置 ——
# 那一列不是純裝飾，不能為了排版把它拿掉）。
# A4 直式扣掉邊界後可用約 748x1062px，取兩軸較嚴格者：
#     min(748/1175, 1062/1031) = min(0.637, 1.03) ≈ 0.637
# 這份文件橫向較寬，改直式後變成「寬度」受限。
#
# 取 0.63（略低於 0.637）而不是更大的值，是為了讓行為是我們決定的：
# 內容比紙張寬時 Chromium 會自己縮到符合寬度，實測 0.64~0.70 產出完全相同，
# 等於這個參數失效、真正的比例由瀏覽器版本決定。明確給一個略小的值，
# 換來跨版本一致、且看得出縮放依據的結果。
#
# 這裡刻意不加任何列印專用 CSS：只要 PDF 有一條瀏覽器看不到的規則，
# 「預覽跟寄出的長得一樣」就不再成立。單純等比縮放不會改變版面關係。
PDF_PRINT_SCALE = 0.63


def _inline_font_faces(html):
    """
    把 @font-face 裡指向 /fonts/... 的網址換成本機字型檔的 file:// 絕對路徑。

    Chromium 是用 set_content() 載入這份 HTML 的，沒有 base URL，
    相對網址（/fonts/GenRyuMin2TW-R.ttf）解析不出來，字型會抓不到，
    中文就會掉成預設字型、跟預覽畫面長得不一樣。

    這裡不用 base64 內嵌是有原因的：兩個字型檔各約 20MB，
    轉成 base64 會膨脹成約 27MB 再塞進 HTML 字串，
    每開一次預覽就要多搬幾十 MB；改用 file:// 讓 Chromium 直接讀檔即可。
    """
    font_dir = os.path.join(current_app.root_path, 'source')

    def replace(match):
        filename = match.group(1)
        path = os.path.join(font_dir, filename)
        if not os.path.exists(path):
            return match.group(0)
        return "url('%s')" % pathlib.Path(path).as_uri()

    return re.sub(r"url\('(?:[^']*/)?([^'/]+\.ttf)'\)", replace, html)


def _prepare_for_pdf(html):
    """
    轉 PDF 前對 HTML 做兩件事。

    1) 拿掉 @font-face。
       報價單的 @font-face 是給「瀏覽器預覽」用的，src 指向 /fonts/... 這支
       Flask 路由；xhtml2pdf 沒有 request context，抓不到那個網址，
       而且它處理 @font-face 的方式在 Windows 上本來就必定失敗
       （會把字型寫進 NamedTemporaryFile 再叫 reportlab 用檔名重開，
       但 Windows 的 NamedTemporaryFile 是獨佔開啟的）。
       PDF 的中文字型一律由 _ensure_pdf_fonts() 直接向 reportlab 註冊。

    2) 指定紙張大小。
       沒有 @page 時 xhtml2pdf 預設 A4 直式，880pt 寬的表格會被硬擠進 595pt，
       標題與各欄位全部換行，跟預覽畫面對不起來。
    """
    html = re.sub(r'@font-face\s*\{[^}]*\}', '', html, flags=re.IGNORECASE)
    return html.replace('<style>', '<style>\n' + PDF_PAGE_CSS + '\n', 1)


def _render_pdf_with_chromium(html):
    """
    用 Chromium 把報價單列印成 PDF。

    為什麼要用瀏覽器而不是 xhtml2pdf：
      xhtml2pdf 只實作了 CSS 的一小部分。這份報價單是 Excel 匯出的，
      仰賴 <col> 欄寬、colspan/rowspan、windowtext 邊框、絕對定位的印章圖，
      它算出來的版面跟瀏覽器差很多 —— 也就是「預覽跟寄出的 PDF 不一樣」的根因。
      Chromium 正好就是預覽視窗 iframe 用的同一套排版引擎，
      交給它列印，PDF 才會跟畫面上看到的一致。

    幾個關鍵設定：
      print_background=True  少了它，所有底色（表頭的粉色欄位）都會不見
      prefer_css_page_size   讓 @page 的 A4 橫式生效，而不是 Chromium 的預設值
      wait_until='networkidle'  等字型與內嵌圖片載完再列印，
                                否則中文可能還沒套用字型就先被印出去
    """
    from playwright.sync_api import sync_playwright

    # 一定要寫成暫存檔並以 file:// 開啟，不能用 set_content()：
    # set_content() 的頁面來源是 about:blank，Chromium 會擋掉它對 file:// 的請求，
    # 字型載不到就會默默掉成系統預設字型（實測會變成 PMingLiU），
    # 版面與字形都跟預覽對不起來。從 file:// 開啟則與字型同源，才抓得到。
    with tempfile.TemporaryDirectory() as tmpdir:
        html_path = os.path.join(tmpdir, 'quotation.html')
        with io.open(html_path, 'w', encoding='utf-8') as f:
            f.write(html)

        with sync_playwright() as p:
            browser = p.chromium.launch(args=['--no-sandbox'])
            try:
                page = browser.new_page()
                page.goto(pathlib.Path(html_path).as_uri(), wait_until='networkidle')
                # networkidle 只保證請求結束，不保證字型已經套用；
                # 等 document.fonts.ready 才不會印出還沒換上中文字型的畫面
                page.evaluate('() => document.fonts.ready')
                return page.pdf(
                    format='A4',
                    landscape=False,
                    print_background=True,   # 少了它表頭的粉色底色會整片不見
                    prefer_css_page_size=False,
                    # 報價單比 A4 直式寬得多，不縮會被切到第二頁；
                    # scale 讓它整份剛好落在一頁內（比例的算法見上方常數說明）。
                    scale=PDF_PRINT_SCALE,
                    margin={'top': '8mm', 'bottom': '8mm', 'left': '6mm', 'right': '6mm'}
                )
            finally:
                browser.close()


def _render_pdf_with_xhtml2pdf(html):
    """
    退路：Chromium 不可用時改用 xhtml2pdf。

    版面會比較差（見 _render_pdf_with_chromium 的說明），但至少開得出繳費單，
    不會因為部署機器還沒裝好瀏覽器就整個功能停擺。
    """
    _ensure_pdf_fonts()
    buffer = io.BytesIO()
    status = pisa.pisaDocument(
        src=io.BytesIO(_prepare_for_pdf(html).encode('utf-8')),
        dest=buffer,
        encoding='utf-8'
    )
    if status.err:
        raise RuntimeError('xhtml2pdf 轉檔失敗')
    buffer.seek(0)
    return buffer.getvalue()


def quotation_html_to_pdf(html):
    """
    把報價單 HTML 轉成 PDF bytes。

    優先用 Chromium（與預覽畫面同一套排版引擎，版面才會一致），
    失敗時退回 xhtml2pdf 並在 log 留下原因。

    Returns:
        (pdf_bytes, error message)；失敗時 pdf_bytes 為 None。
    """
    # @font-face 指向 /fonts/... 這支 Flask 路由，Chromium 是用 set_content
    # 載入的、沒有 base URL，相對網址抓不到；直接換成內嵌字型檔的絕對路徑。
    chromium_html = _inline_font_faces(html)

    try:
        return _render_pdf_with_chromium(chromium_html), None
    except Exception as e:
        current_app.logger.warning(
            f'Chromium 轉 PDF 失敗，改用 xhtml2pdf（版面會與預覽有落差）：{e}'
        )

    try:
        return _render_pdf_with_xhtml2pdf(html), None
    except Exception as e:
        current_app.logger.error(f'報價單 PDF 轉檔失敗: {e}')
        return None, f'報價單 PDF 轉檔失敗：{e}'


def build_quotation_filename(contact, context):
    """附件檔名：HPC繳費單_<帳號或申請人>_<年度>.pdf。"""
    account = contact.get_formal_account() or contact.applicant or f'contact{contact.id}'
    safe_account = re.sub(r'[^\w\-.]', '_', str(account))
    suffix = 'prepaid' if context.get('kind') == 'prepaid' else 'bill'
    return f"HPC_{suffix}_{safe_account}_{context.get('usage_year')}.pdf"
