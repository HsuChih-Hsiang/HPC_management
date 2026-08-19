import os
from urllib.parse import urlparse

from flask import Blueprint, session, redirect, url_for, request, abort
from flask import render_template, send_from_directory, current_app
from utils.permission_utils import get_user_ordered_features, get_landing_path

routes_bp = Blueprint('routes', __name__)

PROFILE_PATH = '/profile'


def _safe_back_url(raw):
    """
    決定個人資料頁「返回」要回到哪裡。

    來源是側邊欄帶過來的 ?next=<目前頁面>，屬於使用者可控的輸入，
    因此只接受站內的相對路徑：擋掉含網域的絕對網址與 //evil.com
    這類會被瀏覽器當成外部網址的寫法，避免變成開放式轉址。
    指向個人資料頁本身也視為無效，否則返回鍵會原地打轉。
    找不到合法來源時，退回該使用者權限允許的落地頁。
    """
    if raw:
        parsed = urlparse(raw)
        if (not parsed.scheme and not parsed.netloc
                and raw.startswith('/') and not raw.startswith('//')
                and parsed.path != PROFILE_PATH):
            return raw

    return get_landing_path(get_user_ordered_features(session.get('user_id')))

@routes_bp.route('/batch_sending')
def batch_sending():
    return render_template('batch_sending.html')

@routes_bp.route('/edit-templates')
def edit_templates():
    return render_template('edit_templates.html')

@routes_bp.route('/mailbox-manager')
def mailbox_manager():
    return render_template('mailbox_manager.html')

@routes_bp.route('/hpc-usage')
def hpc_usage():
    return render_template('hpc_usage.html')

@routes_bp.route('/hpc-contact')
def hpc_contact():
    return render_template('contact_manager.html')

@routes_bp.route('/hpc-billing-review')
def hpc_billing_review():
    return render_template('billing_review.html')

@routes_bp.route('/space-stats')
def space_stats():
    """Space 統計資料：目前僅先建立頁面與側邊欄連結，功能待後續補上。"""
    return render_template('space_stats.html')


# 報價單 (templates/quotation/*.html) 會在「寄送繳費單」的預覽視窗中以
# iframe 顯示，其 @font-face 需要真的抓得到字型檔。字型放在專案的
# source/ 底下（不在 static/），所以另開這支路由提供。
#
# 只允許這份白名單內的檔名：檔名來自網址，屬於使用者可控輸入，
# 限定清單可杜絕任何路徑穿越或把 source/ 當成任意檔案下載點的可能。
QUOTATION_FONTS = {
    'GenRyuMin2TW-R.ttf',
    'TaipeiSansTCBeta-Regular.ttf',
}


@routes_bp.route('/fonts/<path:filename>')
def quotation_font(filename):
    if filename not in QUOTATION_FONTS:
        abort(404)

    source_dir = os.path.join(current_app.root_path, 'source')
    # 這兩個字型檔各約 20MB，內容也不會變動，
    # 因此給長效快取並開啟條件式請求（ETag/Last-Modified），
    # 讓瀏覽器只在第一次真的下載，之後都走 304。
    return send_from_directory(
        source_dir, filename,
        mimetype='font/ttf',
        conditional=True,
        max_age=60 * 60 * 24 * 30
    )

@routes_bp.route('/setting')
def setting():
    return render_template('setting.html')

@routes_bp.route('/profile')
def profile():
    """
    個人資料設定：修改側邊欄顯示的名稱，以及自己的聯絡信箱。
    這是每位登入者的個人設定，不需要任何功能權限（見 params.PUBLIC_ENDPOINTS），
    與需要 setting 權限的系統「設定」頁面是兩回事。
    """
    return render_template('profile.html', back_url=_safe_back_url(request.args.get('next')))

@routes_bp.route('/permission')
def permission():
    return render_template('permission.html')

@routes_bp.route('/pending-approval')
def pending_approval():
    """尚未被指派權限群組的使用者，登入後會被導向此頁等候管理員開通。"""
    return render_template('pending_approval.html')

@routes_bp.route('/')
@routes_bp.route('/login_page')
def login_page():
    if 'user_id' in session:
        # 同樣依權限決定落地頁，避免導向使用者無權存取的頁面
        return redirect(get_landing_path(get_user_ordered_features(session['user_id'])))
    return render_template('login.html')