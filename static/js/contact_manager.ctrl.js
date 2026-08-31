/* =========================================================================
 * HPC 帳號管理 —— AngularJS 版本
 *
 * 對照原生版 contact_manager.js 逐一改寫，功能完全保留，
 * 所有 API 的網址、HTTP method、payload 結構、回應處理方式
 * 都與原版一致（連查詢字串的組法都刻意保持相同）。
 *
 * 依賴（請放本機檔案，不要用 CDN，內網通常連不出去）：
 *   static/js/angular.min.js
 *   static/js/angular-sanitize.min.js
 * ========================================================================= */
(function () {
    'use strict';

    /* -------------------------------------------------------------------
     * 依賴 'emailApp'（static/js/app.js）
     *
     * 側邊欄（sidebar.html）用的 toggleMenu() / isMenuOpen / isActive()
     * 是定義在 app.js 的 emailApp 模組的 $rootScope 上。
     * 這一頁是用 ng-app="contactManagerApp" 啟動，
     * 如果沒有把 emailApp 列為依賴，emailApp 的 .run() 永遠不會執行，
     * side menu 就打不開（連帶 session 心跳與 401 自動導回登入頁也會失效）。
     * ------------------------------------------------------------------- */
    var app = angular.module('contactManagerApp', ['ngSanitize', 'emailApp']);

    /* -------------------------------------------------------------------
     * 這個頁面是 Flask/Jinja2 樣板，Jinja 也用 {{ }}。
     * 若沿用 Angular 預設符號，表達式會先被伺服器端的 Jinja 吃掉，
     * 送到瀏覽器時已經變成空字串。因此改用 [[ ]]。
     * ------------------------------------------------------------------- */
    app.config(['$interpolateProvider', function ($interpolateProvider) {
        $interpolateProvider.startSymbol('[[').endSymbol(']]');
    }]);

    /* -------------------------------------------------------------------
     * raw-date / raw-number 指令
     *
     * Angular 的 input[type=date] 規定 ngModel 必須是 Date 物件，
     * input[type=number] 必須是 Number。
     * 但後端收發的是 "YYYY-MM-DD" 字串與可能為字串的金額，
     * 直接綁定會讓欄位靜默變空白（console 會出現 ngModel:datefmt / numfmt）。
     * 這兩個指令把 formatter/parser 換掉，讓 ngModel 直接吃原始字串，
     * 行為與原生 JS 的 element.value 完全一致。
     * ------------------------------------------------------------------- */
    function rawValueDirective(validatorKey) {
        return function () {
            return {
                restrict: 'A',
                require: 'ngModel',
                priority: 10, // post-link 依 priority 反序執行，確保晚於內建 input 指令
                link: function (scope, element, attrs, ngModel) {
                    ngModel.$formatters.length = 0;
                    ngModel.$parsers.length = 0;
                    if (ngModel.$validators[validatorKey]) {
                        delete ngModel.$validators[validatorKey];
                    }
                    ngModel.$render = function () {
                        element.val(ngModel.$viewValue == null ? '' : ngModel.$viewValue);
                    };
                    element.on('input change blur', function () {
                        var val = element.val();
                        if (val === ngModel.$viewValue) return;
                        scope.$applyAsync(function () { ngModel.$setViewValue(val); });
                    });
                }
            };
        };
    }
    app.directive('rawDate', rawValueDirective('date'));
    app.directive('rawNumber', rawValueDirective('number'));

    /* -------------------------------------------------------------------
     * tinymce-editor 指令（與 edit_templates.ctrl.js / batch_sending.ctrl.js 同款）
     *
     * 若 textarea 本身已經有 id（例如本頁的 emailTemplateEditor）就沿用，
     * 沒有的話才隨機生成，避免與頁面上其他潛在的 TinyMCE 實例衝突；
     * 用 init_instance_callback 確保編輯器初始化完成後，
     * 一定會把當下的 ngModel 值渲染進去（不受 tinymce.init 非同步時機影響）。
     * ------------------------------------------------------------------- */
    app.directive('tinymceEditor', ['$timeout', function ($timeout) {
        return {
            restrict: 'A',
            require: 'ngModel',
            link: function (scope, element, attrs, ngModel) {
                var id = attrs.id;
                if (!id) {
                    id = 'tiny-editor-' + Math.random().toString(36).substr(2, 9);
                    element.attr('id', id);
                }

                $timeout(function () {
                    tinymce.init({
                        selector: '#' + id,
                        height: 400,
                        menubar: 'edit view insert format tools table help',
                        plugins: 'advlist autolink lists link image charmap preview anchor searchreplace visualblocks code fullscreen insertdatetime media table code help wordcount',
                        toolbar: 'undo redo | blocks | bold italic backcolor | alignleft aligncenter alignright alignjustify | bullist numlist outdent indent | removeformat | code help',
                        branding: false,
                        promotion: false,
                        setup: function (editor) {
                            editor.on('change keyup undo redo', function () {
                                var content = editor.getContent();
                                scope.$apply(function () {
                                    ngModel.$setViewValue(content);
                                });
                            });
                        },
                        init_instance_callback: function (editor) {
                            ngModel.$render = function () {
                                editor.setContent(ngModel.$viewValue || '');
                            };
                            if (ngModel.$viewValue) {
                                editor.setContent(ngModel.$viewValue);
                            }
                        }
                    });
                });

                scope.$on('$destroy', function () {
                    if (window.tinymce && tinymce.get(id)) {
                        tinymce.get(id).remove();
                    }
                });
            }
        };
    }]);

    /* -------------------------------------------------------------------
     * bill-preview-srcdoc 指令
     *
     * 繳費單 (hpc_quotation.html) 是一份完整的 HTML 文件：有自己的 <head>、
     * 大量 Excel 匯出的 CSS（.x30 ~ .x87 這種類名），還有一張內嵌的
     * base64 圖章。直接用 ng-bind-html 塞進頁面，那些樣式會外洩污染整個
     * 額度視窗，而 ngSanitize 也會把大部分 inline style 洗掉，
     * 預覽就跟實際寄出的 PDF 長得不一樣了。
     *
     * 因此改放進 iframe 用 srcdoc 隔離：樣式互不干擾，看到的排版
     * 也才是報價單真正的樣子。
     * ------------------------------------------------------------------- */
    app.directive('billPreviewSrcdoc', function () {
        return {
            restrict: 'A',
            link: function (scope, element, attrs) {
                scope.$watch(attrs.billPreviewSrcdoc, function (html) {
                    element.attr('srcdoc', html || '');
                });
            }
        };
    });

    /* -------------------------------------------------------------------
     * pagination-render 指令
     *
     * contact.css 對分頁有「結構型」選擇器：
     *   .pagination-container { display: flex; gap: 15px }
     *   #pagination button:first-child,
     *   #pagination button:last-child { min-width: 80px }
     *
     * 只要用 ng-repeat 在 #pagination 底下多包一層元素，
     * 每顆頁碼都會變成各自容器的 :first-child，全部被套上
     * 「上一頁/下一頁」的加寬樣式，flex 間距也會失效。
     * 而 ng-repeat 又無法在同一個 range 內同時輸出 <button> 與 <span>
     * 且維持正確的 first/last-child。
     *
     * 因此這裡改用指令，直接產生與原版 renderPagination() 完全相同的
     * HTML 結構（button + span.ellipsis 都是 #pagination 的直接子元素），
     * 只把 onclick 換成 data-page + 事件委派。
     * ------------------------------------------------------------------- */
    app.directive('paginationRender', function () {
        return {
            restrict: 'A',
            link: function (scope, element, attrs) {
                function render() {
                    var totalPages = parseInt(scope.$eval(attrs.totalPages), 10) || 0;
                    var currentPage = parseInt(scope.$eval(attrs.currentPage), 10) || 0;

                    // 如果沒有資料 (totalPages 為 0)，顯示特定訊息
                    if (totalPages <= 0) {
                        element.html('<span style="color: #999; font-size: 14px;">暫無資料</span>');
                        return;
                    }

                    var html = '';

                    // 上一頁：如果是第 1 頁則禁用
                    var isFirstPage = currentPage === 1;
                    html += '<button data-page="' + (currentPage - 1) + '"' +
                            (isFirstPage ? ' disabled' : '') + '>上一頁</button>';

                    // --- 核心邏輯：計算顯示的頁碼範圍 ---
                    var range = 2; // 目前頁面配置前後各顯示 2 頁
                    var startPage = Math.max(1, currentPage - range);
                    var endPage = Math.min(totalPages, currentPage + range);

                    // 1. 處理開頭的「第一頁」與「...」
                    if (startPage > 1) {
                        html += '<button data-page="1">1</button>';
                        if (startPage > 2) {
                            html += '<span class="ellipsis" style="padding: 0 8px; color: #999;">...</span>';
                        }
                    }

                    // 2. 渲染中間的頁碼（目前頁面的前後兩頁）
                    for (var i = startPage; i <= endPage; i++) {
                        html += '<button data-page="' + i + '" class="' +
                                (i === currentPage ? 'active' : '') + '">' + i + '</button>';
                    }

                    // 3. 處理結尾的「...」與「最後一頁」
                    if (endPage < totalPages) {
                        if (endPage < totalPages - 1) {
                            html += '<span class="ellipsis" style="padding: 0 8px; color: #999;">...</span>';
                        }
                        html += '<button data-page="' + totalPages + '">' + totalPages + '</button>';
                    }

                    // 下一頁：如果是最後一頁 OR 總頁數為 0 則禁用
                    var isLastPage = currentPage >= totalPages;
                    html += '<button data-page="' + (currentPage + 1) + '"' +
                            (isLastPage ? ' disabled' : '') + '>下一頁</button>';

                    element.html(html);
                }

                scope.$watch(attrs.totalPages, render);
                scope.$watch(attrs.currentPage, render);

                // 事件委派：取代原版每顆按鈕上的 onclick="loadData(n)"
                element.on('click', function (e) {
                    var btn = e.target;
                    while (btn && btn !== element[0] && btn.tagName !== 'BUTTON') {
                        btn = btn.parentNode;
                    }
                    if (!btn || btn.tagName !== 'BUTTON' || btn.disabled) return;
                    var page = parseInt(btn.getAttribute('data-page'), 10);
                    if (isNaN(page)) return;
                    scope.$apply(function () {
                        scope.$eval(attrs.paginationRender, { $page: page });
                    });
                });
            }
        };
    });

    app.controller('ContactManagerController', [
        '$scope', '$http', '$document', '$timeout', '$sce',
        function ($scope, $http, $document, $timeout, $sce) {

            // ============================================================
            // 全域變數（對應原版 let currentPage = 1;）
            // ============================================================
            $scope.currentPage = 1;
            $scope.totalPages = 0;
            $scope.records = [];
            $scope.paginationItems = [];

            $scope.search = '';
            $scope.year = '';
            $scope.years = [];

            // 篩選下拉的四個 checkbox
            $scope.filters = {
                course: false,
                formal: false,
                trial: false,
                payment: false
            };
            $scope.filterMenuOpen = false;

            // 「使用主機」篩選的彈出清單
            $scope.hostFilter = {
                list: [],
                selected: {},
                loaded: false,
                loadError: false,
                popoverOpen: false
            };

            function trim(v) { return v == null ? '' : String(v).trim(); }

            // ============================================================
            // 切換篩選選單顯示/隱藏（原 toggleFilterMenu）
            // ============================================================
            $scope.toggleFilterMenu = function ($event) {
                if ($event) $event.stopPropagation();  // 防止事件冒泡觸發其他點擊事件
                $scope.filterMenuOpen = !$scope.filterMenuOpen;
            };

            // ============================================================
            // 核心功能：載入列表資料（原 loadData）
            // 查詢字串刻意用與原版完全相同的組法
            // ============================================================
            $scope.loadData = loadData;
            function loadData(page) {
                page = page || 1;
                $scope.currentPage = page;

                var search = $scope.search || '';
                var year = $scope.year || '';
                var isCourse = $scope.filters.course;
                var isFormal = $scope.filters.formal;
                var isTrial = $scope.filters.trial;
                var isPayment = $scope.filters.payment;
                var selectedHosts = getFilterHosts().join(',');

                var url = '/api/contacts?page=' + page +
                    '&search=' + encodeURIComponent(search) +
                    '&year=' + year +
                    '&is_course=' + isCourse +
                    '&is_formal=' + isFormal +
                    '&is_trial=' + isTrial +
                    '&is_payment=' + isPayment +
                    '&hosts=' + encodeURIComponent(selectedHosts);

                $http.get(url).then(function (res) {
                    var data = res.data || {};
                    $scope.records = (data.records || []).map(decorateRecord);
                    renderPagination(data.total_pages, data.current_page);
                }, function (err) {
                    console.error('載入資料失敗:', err);
                });
            }

            // Enter 觸發搜尋（對應原本 input 的 onkeyup）
            $scope.onSearchKeyup = function ($event) {
                if ($event.key === 'Enter') loadData(1);
            };

            // 對應原版 String.replace(',', ',<br>')：只取代第一個逗號
            function replaceFirstComma(str) {
                if (!str) return '';
                str = String(str);
                var idx = str.indexOf(',');
                if (idx === -1) return str;
                return str.slice(0, idx) + ',<br>' + str.slice(idx + 1);
            }

            function decorateRecord(r) {
                // 1. 判斷是否為試用帳號：沒有正式帳號且有試用帳號
                var isTrialAccount = !r.formal_account && (r.trial_account || !r.trial_account);
                // 2. 判斷是否為課程帳號
                var isCourseAccount = r.is_course_account === true;
                // 3. 課程或試用帳號皆不允許操作額度
                r._isTrialAccount = !!isTrialAccount;
                r._isCourseAccount = isCourseAccount;
                r._isQuotaDisabled = isCourseAccount || !!isTrialAccount;

                r._applicantHtml = $sce.trustAsHtml(replaceFirstComma(r.applicant));
                r._trailPasswordHtml = $sce.trustAsHtml(replaceFirstComma(r.trail_account_password));
                return r;
            }

            /* ------------------------------------------------------------
             * 渲染分頁按鈕（原 renderPagination）
             *
             * 注意 contact.css 有這兩條規則：
             *   .pagination-container { display: flex; gap: 15px }
             *   #pagination button:first-child,
             *   #pagination button:last-child { min-width: 80px }
             *
             * 只要在 #pagination 底下多包一層元素，每顆頁碼都會變成
             * 各自容器的 :first-child，全部被套上「上一頁/下一頁」的加寬
             * 樣式，flex 間距也會亂掉。
             * 所以這裡壓成一個扁平陣列，用單一 ng-repeat 直接產生 <button>，
             * 確保每顆按鈕都是 #pagination 的直接子元素。
             * ---------------------------------------------------------- */
            // 實際的 DOM 由 pagination-render 指令產生（結構與原版完全相同），
            // 這裡只負責把頁數狀態寫回 scope 讓指令重繪。
            function renderPagination(totalPages, currentPage) {
                $scope.totalPages = totalPages || 0;
                $scope.currentPage = currentPage || $scope.currentPage;
            }

            // ============================================================
            // 使用主機篩選（原 DOMContentLoaded 內的那整段）
            // ============================================================
            // <label> 內包著 <input id="filterHost">，瀏覽器會把 label 的點擊
            // 再轉送一次給裡面的 checkbox，該事件又會冒泡回 label，
            // 導致同一次點擊觸發兩次 toggle（開了又立刻關）。
            // 這裡用時間戳去重，確保一次實體點擊只切換一次。
            var lastHostToggleTs = 0;

            $scope.toggleHostFilterPopover = function ($event) {
                // 阻止點擊 label 導致 checkbox 狀態亂跳的預設行為
                if ($event) {
                    $event.preventDefault();
                    $event.stopPropagation();

                    var ts = $event.timeStamp || Date.now();
                    if (ts >= lastHostToggleTs && (ts - lastHostToggleTs) < 50) {
                        return; // 同一次點擊被 label 轉送而重複觸發，忽略
                    }
                    lastHostToggleTs = ts;
                }
                var isHidden = !$scope.hostFilter.popoverOpen;
                $scope.hostFilter.popoverOpen = isHidden;

                // 如果是打開清單，且尚未載入過資料，就去戳 API
                if (isHidden && !$scope.hostFilter.loaded) {
                    loadHostsFromAPI();
                }
            };

            function loadHostsFromAPI() {
                $http.get('/api/contacts/hosts').then(function (res) {
                    $scope.hostFilter.list = res.data || [];
                    $scope.hostFilter.loaded = true;
                }, function (err) {
                    console.error(err);
                    $scope.hostFilter.list = [];
                    $scope.hostFilter.loaded = true;
                    $scope.hostFilter.loadError = true;
                });
            }

            // 供發送 API 搜尋時，取得當前勾選的主機陣列（原 window.getFilterHosts）
            function getFilterHosts() {
                var result = [];
                angular.forEach($scope.hostFilter.selected, function (v, k) {
                    if (v) result.push(k);
                });
                return result;
            }
            $scope.getFilterHosts = getFilterHosts;
            window.getFilterHosts = getFilterHosts; // 保留原版的全域介面

            // 連動：根據子主機的勾選狀況，決定外層大 Checkbox 與筆數顯示
            $scope.hostFilterChecked = function () {
                return getFilterHosts().length > 0;
            };
            $scope.hostFilterCountLabel = function () {
                var n = getFilterHosts().length;
                return n > 0 ? '(' + n + ')' : '';
            };

            // 全選 / 全取消
            $scope.popoverSelectAll = function () {
                $scope.hostFilter.list.forEach(function (h) { $scope.hostFilter.selected[h] = true; });
            };
            $scope.popoverClearAll = function () {
                $scope.hostFilter.list.forEach(function (h) { $scope.hostFilter.selected[h] = false; });
            };

            // ============================================================
            // 全域點擊事件（原 window.onclick + 兩個 window/document click）
            // ============================================================
            function onDocumentClick(event) {
                var target = event.target;
                var changed = false;

                // 點擊頁面其他地方時，自動關閉篩選選單
                var menu = document.getElementById('filterDropdown');
                var btn = document.querySelector('.btn-filter-dropdown');
                if ($scope.filterMenuOpen && menu && !menu.contains(target) && target !== btn) {
                    $scope.filterMenuOpen = false;
                    changed = true;
                }

                // 點擊外面時自動收起主機選單
                var triggerHostLabel = document.getElementById('triggerHostLabel');
                var hostContainer = document.getElementById('hostDropdownContainer');
                if ($scope.hostFilter.popoverOpen && triggerHostLabel && hostContainer &&
                    !triggerHostLabel.contains(target) && !hostContainer.contains(target)) {
                    $scope.hostFilter.popoverOpen = false;
                    changed = true;
                }

                // 點擊搜尋清單以外區域則隱藏搜尋建議
                var resultsDiv = document.getElementById('search-results');
                var accountInput = document.getElementById('account_search');
                if ($scope.accountSearchOpen && resultsDiv &&
                    target !== accountInput && !resultsDiv.contains(target)) {
                    $scope.accountSearchOpen = false;
                    changed = true;
                }

                if (changed) $scope.$applyAsync();
            }

            $document.on('click', onDocumentClick);
            $scope.$on('$destroy', function () {
                $document.off('click', onDocumentClick);
                if (window.getFilterHosts === getFilterHosts) { delete window.getFilterHosts; }
            });

            // 點擊彈窗外部背景關閉介面（原 window.onclick 的 event.target === modal 判斷）
            $scope.onContactModalBackdrop = function ($event) {
                if ($event.target && $event.target.id === 'contactModal') { $scope.closeModal(); }
            };
            $scope.onDetailModalBackdrop = function ($event) {
                if ($event.target && $event.target.id === 'detailViewModal') { $scope.closeDetailModal(); }
            };
            $scope.onQuotaModalBackdrop = function ($event) {
                if ($event.target && $event.target.id === 'quotaEditorModal') { $scope.closeQuotaModal(); }
            };
            $scope.onStatisticsBackdrop = function ($event) {
                if ($event.target && $event.target.id === 'statisticsModal') { $scope.closeStatisticsModal(); }
            };
            $scope.onRewardModalBackdrop = function ($event) {
                if ($event.target && $event.target.id === 'rewardQuotaModal') { $scope.closeRewardModal(); }
            };
            $scope.onSettingModalBackdrop = function ($event) {
                if ($event.target && $event.target.id === 'settingModal') { $scope.closeSettingModal(); }
            };

            // ============================================================
            // 年份下拉選單（原 initYearFilter）
            // 維持原行為：只負責填選項，不會自動重新查詢
            // ============================================================
            function initYearFilter() {
                $http.get('/api/contacts/years').then(function (res) {
                    $scope.years = res.data || [];
                }, function (error) {
                    console.error('初始化年份失敗:', error);
                    $scope.years = [new Date().getFullYear()];
                });
            }

            // ============================================================
            // 新增 / 修改聯絡人 Modal
            // ============================================================
            $scope.contactModalOpen = false;
            $scope.modalTitle = '新增聯絡人';
            $scope.editId = '';
            $scope.form = emptyForm();

            $scope.accountSearch = '';
            $scope.formalAccountId = '';
            $scope.accountSearchResults = [];
            $scope.accountSearchOpen = false;

            $scope.contactRows = [];   // 其他聯絡人
            $scope.courseRows = [];    // 課程學生帳號

            var standardServers = [];  // 儲存從 API 抓到的標準清單
            $scope.hostOptions = [];
            $scope.hostLoaded = false;
            $scope.hostLoadError = false;
            $scope.customHostName = '';

            function emptyForm() {
                return {
                    team_name: '', dept_level1: '', applicant: '', apply_date: '',
                    trial_account: '', trail_account_password: '', test_deadline: '',
                    research_content: '', used_software: '', calc_resource: '', notes: '',
                    is_course_account: false
                };
            }

            // 原 openModal
            $scope.openModal = function () {
                // 1. 重置表單與清空隱藏的 ID
                $scope.form = emptyForm();
                $scope.editId = '';

                // 2. 恢復標題
                $scope.modalTitle = '新增聯絡人';

                // 3. 重置所有隱藏與細項欄位
                $scope.accountSearch = '';
                $scope.formalAccountId = '';
                $scope.accountSearchResults = [];
                $scope.accountSearchOpen = false;

                // 4. [關鍵] 重置主機選擇區：傳入兩個空陣列，確保「全不勾選」
                renderHostInterface([], []);
                $scope.customHostName = '';

                // 5. 重置動態聯絡人
                $scope.contactRows = [];

                // 6. 重置課程帳號區塊
                $scope.courseRows = [];

                // 7. 顯示彈窗
                $scope.contactModalOpen = true;
                $timeout(function () {
                    var modal = document.getElementById('contactModal');
                    if (modal) modal.scrollTop = 0;
                });
            };

            // 原 closeModal
            $scope.closeModal = function () {
                if (confirm('確定要關閉視窗嗎？未儲存的變更將會遺失。')) {
                    $scope.contactModalOpen = false;
                }
            };

            // 原 editItem
            $scope.editItem = function (id) {
                // 1. 從 API 取得資料
                $http.get('/api/contacts/' + id).then(function (res) {
                    var data = res.data || {};

                    // 2. 只有資料成功取得後，才呼叫 openModal() 重置並打開介面
                    $scope.openModal();

                    // 3. 修改介面標題與暗中存下 ID
                    $scope.modalTitle = '修改聯絡人資料';
                    $scope.editId = data.id;

                    // 4. 回填基本欄位
                    [
                        'team_name', 'dept_level1', 'applicant', 'apply_date',
                        'trial_account', 'trail_account_password', 'test_deadline',
                        'research_content', 'used_software', 'calc_resource', 'notes'
                    ].forEach(function (field) {
                        $scope.form[field] = data[field] || '';
                    });

                    // 5. 回填正式帳號搜尋框與隱藏 ID
                    $scope.accountSearch = data.formal_account || '';
                    $scope.formalAccountId = data.user_id || '';

                    // 6. 回填主機勾選（含自定義主機）
                    renderHostInterface(data.hosts || [], []);

                    // 7. 回填動態聯絡人區塊
                    $scope.contactRows = [];
                    console.log('收到的次要聯絡人資料:', data.secondary_contacts);
                    if (data.secondary_contacts && data.secondary_contacts.length > 0) {
                        data.secondary_contacts.forEach(function (sc) {
                            addContactRow(!!sc.is_primary, sc.name || '', sc.info || '', sc.id, !!sc.email_disabled, sc.email_toggled_at || null);
                        });
                    } else {
                        console.warn('沒有次要聯絡人資料或格式錯誤');
                    }

                    // 8. 處理「是否為課程帳號」勾選框與區塊顯示
                    var isCourse = data.is_course_account || false;
                    $scope.form.is_course_account = isCourse;

                    // 9. 回填學生帳號清單表格
                    $scope.courseRows = [];
                    if (isCourse && data.course_students && data.course_students.length > 0) {
                        data.course_students.forEach(function (cs) {
                            addCourseRow(cs.account || '', cs.password || '');
                        });
                    }

                    // 供「寄送繳費單」取用的聯絡人 Email
                    $scope.currentContactEmail = data.email || '';
                }, function (err) {
                    console.error('讀取編輯資料失敗:', err);
                    alert('讀取資料失敗，請檢查網路或後端服務');
                });
            };

            // ---- 正式帳號自動完成搜尋（原 initAutocomplete）----
            $scope.onAccountSearchInput = function () {
                var val = trim($scope.accountSearch);

                // 重要：一旦使用者開始打字，先清空隱藏的 ID
                // 這樣如果使用者最後沒點選建議清單，後端就會收到這串「純文字」
                $scope.formalAccountId = '';

                if (val.length < 1) {
                    $scope.accountSearchOpen = false;
                    return;
                }

                $http.get('/api/hpc-usage/search_users?q=' + encodeURIComponent(val))
                    .then(function (res) {
                        var users = res.data || [];
                        $scope.accountSearchResults = users;
                        $scope.accountSearchOpen = users.length > 0;
                    }, function (err) {
                        console.error('搜尋失敗:', err);
                    });
            };

            // 原 selectUser(id, username)
            $scope.selectUser = function (id, username) {
                // 1. 將帳號名稱顯示在搜尋框
                $scope.accountSearch = username;
                // 2. 將真正的使用者 ID 存入隱藏欄位，供儲存 API 使用
                $scope.formalAccountId = id;
                console.log('選取的使用者 ID:', id);
                // 3. 隱藏搜尋結果清單
                $scope.accountSearchOpen = false;
            };

            // ---- 開通主機（原 fetchAndRenderHosts / renderHostInterface）----
            function fetchAndRenderHosts() {
                $http.get('/api/hpc-usage/serverlist').then(function (res) {
                    // 防呆：萬一 API 回傳的不是陣列，不要讓整個主機清單直接爆掉
                    var servers = angular.isArray(res.data) ? res.data : [];
                    // 取得標準清單（去重）
                    var seen = {};
                    standardServers = [];
                    servers.forEach(function (s) {
                        if (s.server && !seen[s.server]) {
                            seen[s.server] = true;
                            standardServers.push(s.server);
                        }
                    });
                    $scope.hostLoaded = true;
                    // 初始渲染傳入空陣列，這樣就不會預設打勾
                    renderHostInterface([], []);
                }, function (err) {
                    console.error('主機載入失敗', err);
                    $scope.hostLoaded = true;
                    $scope.hostLoadError = true;
                });
            }

            function renderHostInterface(savedHosts, optionsToInclude) {
                savedHosts = savedHosts || [];
                optionsToInclude = optionsToInclude || [];

                // 1. 取得目前畫面上的勾選狀態
                // 如果兩個陣列都是空的（代表 openModal 觸發的初始重置），
                // 則強制不抓取現有狀態，避免抓到舊資料。
                var currentChecked = [];
                if (savedHosts.length > 0 || optionsToInclude.length > 0) {
                    $scope.hostOptions.forEach(function (opt) {
                        if (opt.checked) currentChecked.push(opt.name);
                    });
                }

                // 2. 建立勾選白名單
                var mustBeChecked = {};
                savedHosts.concat(optionsToInclude, currentChecked).forEach(function (h) {
                    if (h) mustBeChecked[h] = true;
                });

                // 3. 顯示清單：標準清單 + 目前被勾選的自定義項目
                var seen = {};
                var displayList = [];
                standardServers.concat(Object.keys(mustBeChecked)).forEach(function (s) {
                    if (s && !seen[s]) { seen[s] = true; displayList.push(s); }
                });

                // 4. 產生 Checkbox 清單
                $scope.hostOptions = displayList.map(function (s) {
                    return { name: s, checked: !!mustBeChecked[s] };
                });
            }
            $scope.renderHostInterface = renderHostInterface;

            // 原 handleAddCustomHost
            $scope.handleAddCustomHost = function () {
                var value = trim($scope.customHostName);
                if (!value) return;
                renderHostInterface([], [value]);
                $scope.customHostName = '';
            };

            // ---- 其他聯絡人（原 addContactRow）----
            // id / emailDisabled / emailToggledAt 只有從編輯既有聯絡人回填時才會帶值；
            // 「＋ 新增聯絡人欄位」按鈕呼叫時不帶參數，代表這是還沒存檔的新聯絡人，
            // 沒有 id 就沒辦法呼叫關閉寄信 API，畫面上會把該按鈕停用。
            function addContactRow(isPrimary, name, info, id, emailDisabled, emailToggledAt) {
                $scope.contactRows.push({
                    id: id || null,
                    is_primary: Boolean(isPrimary),
                    name: name || '',
                    info: info || '',
                    email_disabled: Boolean(emailDisabled),
                    email_toggled_at: emailToggledAt || null
                });
            }
            $scope.addContactRow = addContactRow;

            $scope.removeContactRow = function (index) {
                $scope.contactRows.splice(index, 1);
            };

            // 主要聯絡人勾選框（可取消勾選）
            //
            // 原本用 <input type="radio"> + ng-checked + ng-click(preventDefault) 手動控制勾選/取消，
            // 但瀏覽器對 radio 的原生行為是：click 事件結束後，若呼叫了 preventDefault()，
            // 會把 checked 狀態「還原成點擊前的樣子」（canceled activation steps），
            // 這一步發生在 Angular 的 digest 之後，會把我們剛設好的 checked=false 蓋回 true。
            // 結果是 Angular 的資料模型正確變成 false，畫面上的圓圈卻仍顯示勾選、看起來完全沒反應。
            // radio 天生就不支援「點自己取消勾選」，因此改用 checkbox（原生就支援取消勾選），
            // 再用 ng-change 手動確保「同時最多只有一個勾選」即可，不需要跟瀏覽器的原生行為搏鬥。
            $scope.onPrimaryContactChange = function (row) {
                if (row.is_primary) {
                    $scope.contactRows.forEach(function (r) {
                        if (r !== row) r.is_primary = false;
                    });
                }
            };

            // 關閉/開啟寄信給這個聯絡人（即時呼叫 API，不用等整份聯絡人表單存檔）。
            // 只有已經存過檔、有 id 的聯絡人才能呼叫；還沒存檔的新增列請先按「儲存提交」。
            $scope.toggleContactEmail = function (row) {
                if (!row.id) {
                    alert('請先儲存聯絡人資料後，才能設定是否寄信給這位聯絡人。');
                    return;
                }
                $http.post('/api/contacts/secondary-contacts/' + row.id + '/toggle-email').then(function (res) {
                    var data = res.data || {};
                    row.email_disabled = !!data.email_disabled;
                    row.email_toggled_at = data.email_toggled_at || null;
                }, function (err) {
                    var data = (err && err.data) || {};
                    alert('設定失敗：' + (data.message || ('HTTP ' + (err && err.status))));
                });
            };

            // ---- 課程帳號（原 is_course_account change / addCourseRow / getCourseData）----
            $scope.onCourseAccountToggle = function () {
                // 只有在「真的沒資料」且「勾選」時才自動補一行
                if ($scope.form.is_course_account && $scope.courseRows.length === 0) {
                    addCourseRow();
                }
            };

            function addCourseRow(account, password) {
                $scope.courseRows.push({ account: account || '', password: password || '' });
            }
            $scope.addCourseRow = addCourseRow;

            $scope.removeCourseRow = function (index) {
                $scope.courseRows.splice(index, 1);
            };

            function getCourseData() {
                var data = [];
                $scope.courseRows.forEach(function (row) {
                    var acc = trim(row.account);
                    var pwd = trim(row.password);
                    if (acc || pwd) data.push({ account: acc, password: pwd });
                });
                return data;
            }
            $scope.getCourseData = getCourseData;

            // ---- 儲存表單：新增或修改（原 contactForm.onsubmit）----
            $scope.submitContactForm = function () {
                var editId = $scope.editId;
                var method = editId ? 'PUT' : 'POST';
                var url = editId ? '/api/contacts/' + editId : '/api/contacts';

                try {
                    // --- 帳號邏輯處理 ---
                    var formalId = $scope.formalAccountId;
                    var formalText = trim($scope.accountSearch);

                    // 優先傳 ID，若無 ID 則傳手動輸入的文字
                    var finalFormalAccount = formalId ? formalId : formalText;

                    var payload = {
                        team_name: trim($scope.form.team_name),
                        dept_level1: trim($scope.form.dept_level1),
                        applicant: trim($scope.form.applicant),
                        apply_date: trim($scope.form.apply_date),

                        // 這裡發送給後端：可能是 ID (int) 或 帳號名稱 (string)
                        formal_account: finalFormalAccount || null,

                        trial_account: trim($scope.form.trial_account),
                        trail_account_password: trim($scope.form.trail_account_password),
                        test_deadline: trim($scope.form.test_deadline),
                        research_content: trim($scope.form.research_content),
                        used_software: trim($scope.form.used_software),
                        calc_resource: trim($scope.form.calc_resource),
                        notes: trim($scope.form.notes),
                        hosts: $scope.hostOptions
                            .filter(function (h) { return h.checked; })
                            .map(function (h) { return h.name; }),
                        secondary_contacts: $scope.contactRows.map(function (row) {
                            // 強制用 Boolean 轉型，確保存入的是明確的 true / false
                            // 後端存整份聯絡人時會整批刪除重建，email_disabled/email_toggled_at
                            // 一定要跟著送回去，不然「關閉寄信」的設定會在下次儲存時被重置掉
                            return {
                                name: trim(row.name),
                                info: trim(row.info),
                                is_primary: Boolean(row.is_primary),
                                email_disabled: Boolean(row.email_disabled),
                                email_toggled_at: row.email_toggled_at || null
                            };
                        }),
                        is_course_account: Boolean($scope.form.is_course_account),
                        course_students: getCourseData()
                    };

                    $http({
                        method: method,
                        url: url,
                        headers: { 'Content-Type': 'application/json' },
                        data: payload
                    }).then(function () {
                        alert(editId ? '修改成功！' : '新增成功！');
                        // 繞過 confirm，直接強制隱藏彈窗
                        $scope.contactModalOpen = false;
                        loadData($scope.currentPage);
                    }, function () {
                        alert('儲存失敗');
                    });
                } catch (err) {
                    console.error('執行出錯:', err);
                    alert('前端程式錯誤');
                }
            };

            // ============================================================
            // 刪除（原 deleteItem）
            // ============================================================
            $scope.deleteItem = function (id) {
                if (!confirm('確定要刪除這筆資料嗎？')) return;
                $http({ method: 'DELETE', url: '/api/contacts/' + id })['finally'](function () {
                    loadData($scope.currentPage);
                });
            };

            // ============================================================
            // 其他資訊 Modal（原 showInfoFromData / showInfoModal / closeDetailModal）
            // ============================================================
            $scope.detailModalOpen = false;
            $scope.detailInfo = { content: '', software: '', resource: '', note: '' };

            function formatToHtml(text) {
                if (!text) return $sce.trustAsHtml('未填寫');
                var out = String(text)
                    .replace(/<br\s*\/?>/gi, '\n')  // 1. 先把 <br> 轉回換行符號
                    .replace(/，/g, ',')            // 2. 統一逗號
                    .split(/[,\n]/)                 // 3. 依逗號或換行分割
                    .map(function (item) { return item.trim(); })
                    .filter(function (item) { return item !== ''; })
                    .join('<br>');
                return $sce.trustAsHtml(out || '未填寫');
            }

            // 原 showInfoFromData(btn)：從 data-* 取值後轉呼叫 showInfoModal
            $scope.showInfoFromData = function (record) {
                showInfoModal(
                    record.research_content || '',
                    record.used_software || '',
                    record.calc_resource || '',
                    record.notes || ''
                );
            };

            function showInfoModal(content, software, resource, note) {
                // 填入資料，若無資料顯示「未填寫」
                $scope.detailInfo = {
                    content: formatToHtml(content),
                    software: formatToHtml(software),
                    resource: formatToHtml(resource),
                    note: formatToHtml(note)
                };
                $scope.detailModalOpen = true;
            }
            $scope.showInfoModal = showInfoModal;

            $scope.closeDetailModal = function () {
                $scope.detailModalOpen = false;
            };

            // ============================================================
            // 餘額明細懸浮窗（原 toggleQuotaDetail）
            // 原版 HTML 未掛任何呼叫點，此處同樣保留函式備用
            // ============================================================
            $scope.quotaPopoverOpenId = null;
            $scope.toggleQuotaDetail = function (id) {
                // 先關閉所有其他的 popover，再切換自己
                $scope.quotaPopoverOpenId = ($scope.quotaPopoverOpenId === id) ? null : id;
            };

            // ============================================================
            // 共用小工具（原 getTodayDateString / formatCurrency）
            // ============================================================
            function getTodayDateString() {
                var today = new Date();
                var yyyy = today.getFullYear();
                var mm = String(today.getMonth() + 1).padStart(2, '0');
                var dd = String(today.getDate()).padStart(2, '0');
                return yyyy + '-' + mm + '-' + dd;
            }
            $scope.getTodayDateString = getTodayDateString;

            function formatCurrency(value) {
                var num = parseFloat(value);
                return isNaN(num) ? '0.00' : num.toFixed(2);
            }
            $scope.formatCurrency = formatCurrency;
            $scope.absCurrency = function (v) {
                return formatCurrency(Math.abs(Number(v) || 0));
            };
            $scope.toLocale = function (v) {
                return Number(v || 0).toLocaleString();
            };

            // ============================================================
            // 額度管理 Modal（原 openQuotaModal / closeQuotaModal）
            // ============================================================
            $scope.quotaModalOpen = false;
            $scope.quotaTargetId = null;
            $scope.quotaTargetName = '';
            $scope.currentContactEmail = '';

            $scope.quota = {
                totalRemainingText: '0.00',
                discountDetails: null,
                rechargeHistory: null,
                consumptionHistory: null,
                // 兩份歷史紀錄各自的年份篩選（空字串 = 所有年份）
                rechargeYear: '',
                consumptionYear: '',
                bills: null,
                billsLoading: false
            };

            $scope.pendingBill = {
                amount: '', date: '', notes: '',
                placeholder: '請輸入核對後的金額',
                notesColor: '', notesBold: false,
                // 開啟視窗時後端試算出來的建議金額與自動帶入的備註，
                // 用來判斷「金額被改過但備註還是系統自動產生的那句」
                suggestedAmount: null,
                autoNotes: ''
            };
            $scope.addQuota = { amount: '0', purchaseDate: '' };

            // ---- 儲值紀錄 / 消費紀錄的年份篩選 ----
            // 儲值紀錄本身就有 year 欄位；消費紀錄只有 created_at，取前四碼當年份。
            function collectYears(list, getYear) {
                var seen = {};
                var years = [];
                (list || []).forEach(function (item) {
                    var y = getYear(item);
                    if (y && !seen[y]) {
                        seen[y] = true;
                        years.push(y);
                    }
                });
                // 新的年份排前面
                years.sort(function (a, b) { return Number(b) - Number(a); });
                return years;
            }

            function rechargeYearOf(item) {
                return item && item.year ? String(item.year) : '';
            }

            function consumptionYearOf(tx) {
                return tx && tx.created_at ? String(tx.created_at).substring(0, 4) : '';
            }

            $scope.rechargeYearOptions = function () {
                return collectYears($scope.quota.rechargeHistory, rechargeYearOf);
            };

            $scope.consumptionYearOptions = function () {
                return collectYears($scope.quota.consumptionHistory, consumptionYearOf);
            };

            $scope.filteredRechargeHistory = function () {
                var list = $scope.quota.rechargeHistory || [];
                if (!$scope.quota.rechargeYear) return list;
                return list.filter(function (item) {
                    return rechargeYearOf(item) === String($scope.quota.rechargeYear);
                });
            };

            $scope.filteredConsumptionHistory = function () {
                var list = $scope.quota.consumptionHistory || [];
                if (!$scope.quota.consumptionYear) return list;
                return list.filter(function (tx) {
                    return consumptionYearOf(tx) === String($scope.quota.consumptionYear);
                });
            };

            /* ------------------------------------------------------------
             * 金額被人工調整過時，強制要求備註也要自己寫過。
             *
             * 不能用「備註有沒有文字」判斷：視窗一開啟備註就會自動帶入系統
             * 產生的說明（例如「2025 年度合計 123 筆作業，系統自動統計費用。」），
             * 所以「有文字」永遠成立。真正要擋的是「金額被改了，備註卻還是
             * 系統自動帶入的那一句」——那張單日後沒人說得出金額為什麼不一樣。
             *
             * 後端 validate_amount_and_notes() 會用同一套規則再擋一次，
             * 這裡只是先在前端給出即時提示。
             * ------------------------------------------------------------ */
            function checkNotesEditedWhenAmountChanged(amount) {
                var suggested = $scope.pendingBill.suggestedAmount;
                if (suggested === null || suggested === undefined) return null;

                var submitted = parseFloat(amount);
                if (isNaN(submitted)) return '金額格式不正確。';
                if (submitted.toFixed(2) === Number(suggested).toFixed(2)) return null;

                var notes = ($scope.pendingBill.notes || '').trim();
                if (!notes) {
                    return '本期應收總金額已與系統試算金額不同，請於「核對備註說明」填寫調整原因後再送出。';
                }
                if (notes === ($scope.pendingBill.autoNotes || '').trim()) {
                    return '本期應收總金額已由系統試算的 $' + Number(suggested).toLocaleString() +
                           ' 調整為 $' + submitted.toLocaleString() +
                           '，請一併修改「核對備註說明」寫出調整原因（目前仍是系統自動帶入的文字）。';
                }
                return null;
            }

            // 原 handleQuotaButtonClick
            $scope.handleQuotaButtonClick = function ($event, id, applicant, isCourse, isTrial) {
                if (isCourse || isTrial) {
                    if ($event) $event.preventDefault();
                    alert('課程帳號與試用帳號不適用此功能，無法開啟額度管理。');
                    return;
                }
                // 驗證通過，才允許呼叫原本的開啟彈窗功能
                openQuotaModal(id, applicant);
            };

            function openQuotaModal(id, name) {
                // 強制轉換為整數，確保符合後端 Flask <int:id> 的嚴格規範
                var targetId = parseInt(id, 10);
                if (isNaN(targetId)) {
                    console.error('致命錯誤：無法解析聯絡人 ID');
                    alert('無法讀取該聯絡人的識別 ID，請重新整理網頁再試。');
                    return;
                }

                // 1. 立即將確認無誤的 ID 與姓名更新至 Modal 欄位上
                $scope.quotaTargetId = targetId;
                $scope.quotaTargetName = name || '選擇的帳號';

                // 核心：在發送任何請求前，先把所有顯示區塊強制清空/重設
                $scope.quota = {
                    totalRemainingText: '載入中...',
                    discountDetails: null,      // null = 顯示「資料載入中...」
                    rechargeHistory: null,      // null = 顯示「歷史紀錄載入中...」
                    consumptionHistory: null,   // null = 顯示「消費與扣款明細載入中...」
                    rechargeYear: '',
                    consumptionYear: '',
                    bills: null,
                    billsLoading: true
                };

                // 強制清空舊資料，顯示 placeholder
                $scope.pendingBill = {
                    amount: '', date: '', notes: '',
                    placeholder: '計算建議金額中...',
                    notesColor: '', notesBold: false,
                    suggestedAmount: null,
                    autoNotes: ''
                };

                // 四顆按鈕在流程狀態回來之前一律停用，避免搶在狀態載入前按下去
                loadBillingWorkflow(targetId);

                // 將新增購買額度區塊也同步重設
                $scope.addQuota = { amount: '0', purchaseDate: getTodayDateString() };

                // 立即顯示 Modal 框架
                $scope.quotaModalOpen = true;

                // 2. 平行發送非同步請求，避免其中一個卡死導致另一個不更新

                // 請求 A：聯絡人基本額度與完整歷史軌跡
                $http.get('/api/contacts/' + targetId).then(function (res) {
                    var data = res.data || {};
                    // 呈現經後端歸戶統計、且格式化後的金額
                    $scope.quota.totalRemainingText = formatCurrency(data.total_remaining);
                    // 【A-1】年度可用餘額明細
                    $scope.quota.discountDetails = data.discount_details || [];
                    // 【A-2】儲值紀錄明細
                    $scope.quota.rechargeHistory = data.recharge_history || [];
                    // 【A-3】歷史消費與扣款日期明細
                    $scope.quota.consumptionHistory = data.consumption_history || [];
                    // 【A-4】繳費單紀錄明細與銷帳
                    $scope.quota.bills = data.bills || [];
                    $scope.quota.billsLoading = false;

                    if (data.email) $scope.currentContactEmail = data.email;
                }, function (err) {
                    console.error('基本額度與流水帳明細載入失敗:', err);
                    $scope.quota.discountDetails = [];
                    $scope.quota.rechargeHistory = [];
                    $scope.quota.consumptionHistory = [];
                    $scope.quota.bills = [];
                    $scope.quota.billsLoading = false;
                });

                // 請求 B：動態試算建議扣款金額
                $http.get('/api/contacts/' + targetId + '/calculate_pending_bill').then(function (res) {
                    var billData = res.data || {};
                    $scope.pendingBill.amount = billData.suggested_amount !== undefined
                        ? String(billData.suggested_amount) : '0';
                    $scope.pendingBill.placeholder = '';
                    $scope.pendingBill.date = billData.bill_date || getTodayDateString();
                    $scope.pendingBill.notes = billData.notes || '';

                    // 留存後端的試算結果，供「金額改了、備註沒改」的檢查比對
                    $scope.pendingBill.suggestedAmount = billData.suggested_amount !== undefined
                        ? billData.suggested_amount : null;
                    $scope.pendingBill.autoNotes = billData.notes || '';

                    // 若備註包含警告標籤(⚠️)或成功標籤(✅)，調整輸入框提示顏色
                    var notes = billData.notes || '';
                    if (notes.indexOf('⚠️') !== -1 || notes.indexOf('✅') !== -1) {
                        $scope.pendingBill.notesColor = notes.indexOf('⚠️') !== -1 ? '#e53e3e' : '#38a169';
                        $scope.pendingBill.notesBold = true;
                    }

                    console.log('成功載入 ID: ' + targetId + ' 的新建議扣款金額: ' + billData.suggested_amount);
                }, function (billErr) {
                    console.error('無法取得待確認帳單數據:', billErr);
                    $scope.pendingBill.amount = '0';
                    $scope.pendingBill.placeholder = '無法取得建議金額';
                    $scope.pendingBill.date = getTodayDateString();
                });
            }
            $scope.openQuotaModal = openQuotaModal;

            $scope.closeQuotaModal = function () {
                $scope.quotaModalOpen = false;
            };

            // 原版程式中沒有定義 reloadQuotaPanel，會走 else 分支重開 Modal
            function reloadQuotaPanel(contactId) {
                openQuotaModal(parseInt(contactId, 10), $scope.quotaTargetName);
            }

            // ---- 主表單：新增購買額度（原 quotaForm.onsubmit）----
            $scope.submitAddQuota = function () {
                var id = $scope.quotaTargetId;
                var addAmount = parseFloat($scope.addQuota.amount);

                // 取得購買日期，如果使用者手動清空了，就預設帶入今天
                var purchaseDate = $scope.addQuota.purchaseDate;
                if (!purchaseDate) purchaseDate = getTodayDateString();

                // 前端防呆
                if (isNaN(addAmount) || addAmount <= 0) {
                    alert('請輸入大於 0 的購買額度');
                    return;
                }

                // Payload 包含新增額度與購買日期
                var payload = {
                    amount: addAmount,
                    purchase_date: purchaseDate // 格式為 "YYYY-MM-DD"
                };

                $http({
                    method: 'POST',
                    url: '/api/contacts/' + id + '/quota',
                    headers: { 'Content-Type': 'application/json' },
                    data: payload
                }).then(function () {
                    alert('額度新增成功');
                    $scope.closeQuotaModal();
                    loadData($scope.currentPage);
                }, function (err) {
                    if (err && err.status <= 0) {
                        // 對應原版 catch：網路層失敗
                        alert('更新失敗，網路或連線異常');
                        return;
                    }
                    var data = (err && err.data) || {};
                    alert('新增失敗：' + (data.message || '請檢查輸入或伺服器狀態'));
                });
            };

            // ============================================================
            // 學術獎勵額度 Modal（原 DOMContentLoaded 內的複選結構那段）
            // ============================================================
            $scope.rewardModalOpen = false;
            $scope.reward = { free: false, academic: false, quantity: '1' };

            $scope.openRewardModal = function () {
                $scope.rewardModalOpen = true;
            };

            // 關閉時重置複選框狀態與行內輸入框
            $scope.closeRewardModal = function () {
                $scope.rewardModalOpen = false;
                $scope.reward = { free: false, academic: false, quantity: '1' };
            };

            // 監聽學術額度勾選狀態：勾選才顯示行內的數量輸入框
            $scope.onRewardAcademicChange = function () {
                if ($scope.reward.academic) {
                    $timeout(function () {
                        var el = document.getElementById('reward_quantity');
                        if (el) el.focus();
                    });
                }
            };

            // 分流一：確認發放獎勵額度（單次 API 批量送出）
            $scope.confirmRewardQuota = function () {
                var id = $scope.quotaTargetId; // 取得當前對象 ID

                // 蒐集被勾選的任務與確認訊息
                var selectedItems = [];
                var confirmDetails = [];

                // 額度金額改用「⚙️ 學術獎勵額度與優惠區間」設定裡即時載入的數字，
                // 不要寫死 10000 / 1000，避免確認視窗顯示的金額跟後端實際發放的金額對不上。
                var freeQuotaAmount = $scope.quotaSettings.freeQuota || 10000;
                var academicQuotaAmount = $scope.quotaSettings.academicQuota || 1000;

                if ($scope.reward.free) {
                    selectedItems.push({ type: 'free', quantity: 1 });
                    confirmDetails.push('・免費額度 $' + freeQuotaAmount.toLocaleString() + ' 元 (限今年度帳單折抵)');
                }

                if ($scope.reward.academic) {
                    var qty = parseInt($scope.reward.quantity, 10) || 1;
                    if (qty <= 0) {
                        alert('學術額度數量必須大於 0');
                        return;
                    }
                    selectedItems.push({ type: 'academic', quantity: qty });
                    confirmDetails.push('・學術額度 $' + academicQuotaAmount.toLocaleString() + ' × ' + qty + ' 份 = $' + (academicQuotaAmount * qty).toLocaleString() + ' 元');
                }

                // 防呆：什麼都沒勾選
                if (selectedItems.length === 0) {
                    alert('請至少選擇一種額度類型');
                    return;
                }

                // 組裝統一的確認提示視窗
                var confirmMsg = '【確認發放以下研究獎勵？】\n\n' + confirmDetails.join('\n');
                if (!confirm(confirmMsg)) return;

                // 整包 items 一次打包送過去
                $http({
                    method: 'POST',
                    url: '/api/contacts/' + id + '/research_bonus',
                    headers: { 'Content-Type': 'application/json' },
                    data: { items: selectedItems }
                }).then(function (res) {
                    var data = res.data || {};
                    // 顯示後端組合好、帶有換行與千分位的成功訊息
                    alert(data.message);
                    $scope.closeRewardModal();      // 關閉小視窗
                    $scope.closeQuotaModal();       // 關閉原本的分配額度大彈窗
                    loadData($scope.currentPage);
                }, function (err) {
                    var data = (err && err.data) || {};
                    if (err && err.status <= 0) {
                        alert('連線失敗，無法完成獎勵額度發放');
                    } else {
                        alert('發放失敗：' + (data.message || '伺服器錯誤'));
                    }
                });
            };

            // ============================================================
            // 直接開立繳費單（原 submitDirectBill）
            // ============================================================
            $scope.submitDirectBill = function () {
                console.log('🚀 submitDirectBill 被點擊了！');

                var contactId = $scope.quotaTargetId;
                var amount = $scope.pendingBill.amount;
                var notes = $scope.pendingBill.notes || '管理員手動直接開單';

                // 安全防護：避免找不到元素時程式直接當掉
                if (!contactId) {
                    alert('🛑 前端錯誤：找不到必要的網頁元素！請確認 HTML 欄位是否完整。');
                    return;
                }

                if (!amount || parseFloat(amount) <= 0) {
                    alert('請輸入要開立的繳費單金額');
                    return;
                }

                if (!$scope.billingWorkflow.can_direct_bill) {
                    alert($scope.billingWorkflow.direct_blocked_reason || '目前無法執行此步驟。');
                    return;
                }

                var notesError = checkNotesEditedWhenAmountChanged(amount);
                if (notesError) {
                    alert('🛑 ' + notesError);
                    return;
                }

                if (!confirm('【確認直接開立繳費單？】\n\n系統將跳過預付額度扣款，直接建立一筆 $' + amount + ' 元的未繳帳單。')) {
                    return;
                }

                $http({
                    method: 'POST',
                    url: '/api/contacts/' + contactId + '/direct_create_bill',
                    headers: { 'Content-Type': 'application/json' },
                    data: { amount: parseFloat(amount), notes: notes }
                }).then(function (res) {
                    var data = res.data || {};
                    alert(data.message || '繳費單直接開立成功！');
                    $scope.pendingBill.amount = '';
                    $scope.pendingBill.notes = '';

                    // 成功開單後，重新載入面板與外圍表格
                    reloadQuotaPanel(contactId);
                    loadData($scope.currentPage);
                }, function (err) {
                    alert('直接開單失敗: ' + ((err && err.data && err.data.message) || ('HTTP ' + (err && err.status))));
                });
            };

            // ============================================================
            // 額度扣款後開立繳費單（原 handleConfirmDeduct）
            // ============================================================
            $scope.handleConfirmDeduct = function () {
                console.log('🚀 handleConfirmDeduct 被點擊了！');

                var contactId = $scope.quotaTargetId;
                var amount = $scope.pendingBill.amount;
                var billDate = $scope.pendingBill.date || '';
                var notes = $scope.pendingBill.notes || '管理員核定扣款';

                if (!contactId) {
                    alert('🛑 前端錯誤：找不到必要的網頁元素！');
                    return;
                }

                // 1. 前端基本驗證
                if (!amount || parseFloat(amount) <= 0) {
                    alert('請輸入有效的扣款金額');
                    return;
                }

                // 使用折扣與額度扣款互斥（後端 confirm_deduct 也會擋，這裡只是提早講清楚）
                if ($scope.billingWorkflow.discount_applied) {
                    alert('本期已設定為「使用帳單折扣」，折扣與額度扣款只能擇一；若要改用額度扣款，請先關閉折扣。');
                    return;
                }

                if (!$scope.billingWorkflow.can_deduct) {
                    alert($scope.billingWorkflow.deduct_blocked_reason || '目前無法執行此步驟。');
                    return;
                }

                var deductNotesError = checkNotesEditedWhenAmountChanged(amount);
                if (deductNotesError) {
                    alert('🛑 ' + deductNotesError);
                    return;
                }

                // 2. 執行前二次確認
                if (!confirm('【確認執行額度扣款？】\n系統將優先扣除該帳號的預付優惠額度。\n若額度不足，將自動就剩餘差額生成未繳繳費單。 \n學術獎勵要先點選才折抵。')) {
                    return;
                }

                // 3. 發送請求至後端 confirm_deduct 路由
                $http({
                    method: 'POST',
                    url: '/api/contacts/' + contactId + '/confirm_deduct',
                    headers: { 'Content-Type': 'application/json' },
                    data: {
                        final_amount: parseFloat(amount),
                        bill_date: billDate, // 若留空，後端會自動預設為今天
                        notes: notes
                    }
                }).then(function (res) {
                    var data = res.data || {};
                    // 4. 根據後端回傳的 status 狀態進行客製化提示
                    if (data.status === 'need_bill') {
                        alert('⚠️ 提示：' + data.message + '\n\n執行明細：\n' + (data.detail || []).join('\n'));
                    } else {
                        alert('✅ 成功：' + data.message);
                    }

                    // 5. 清空輸入表單
                    $scope.pendingBill.amount = '';
                    $scope.pendingBill.notes = '';
                    $scope.pendingBill.date = '';

                    // 6. 重新載入 UI 面板與外圍表格資料
                    reloadQuotaPanel(contactId);
                    loadData($scope.currentPage);
                }, function (err) {
                    // 後端回傳 400（防呆阻擋）時把訊息顯示出來
                    var data = (err && err.data) || {};
                    alert(data.message || '計費扣款程序異常');
                });
            };

            /* ============================================================
             * 開單流程狀態
             *
             * 四顆按鈕（寄送確認信 → 額度扣款後開單／開立繳費單 → 寄送繳費單）
             * 的啟用狀態完全由後端 billing-workflow API 決定，進度存在
             * billing_workflows 表，所以重新整理網頁後仍記得走到哪一步。
             *
             * 每次開啟額度視窗、以及每次流程往前一步之後都要重新載入，
             * 按鈕狀態才會即時反映。
             * ============================================================ */
            $scope.billingWorkflowLoading = false;
            $scope.billingWorkflow = {
                can_send_confirm_email: false,
                can_deduct: false,
                can_direct_bill: false,
                can_send_quotation: false,
                can_send_prepaid_quotation: false,
                discount_applied: false,
                can_toggle_discount: false
            };

            function loadBillingWorkflow(contactId) {
                $scope.billingWorkflowLoading = true;
                return $http.get('/api/contacts/' + contactId + '/billing-workflow').then(function (res) {
                    $scope.billingWorkflow = res.data || {};
                    $scope.billingWorkflowLoading = false;
                }, function (err) {
                    console.error('載入開單流程狀態失敗:', err);
                    // 讀不到狀態時一律當成「不能操作」，寧可擋住也不要讓人跳過步驟
                    $scope.billingWorkflow = {
                        can_send_confirm_email: true,
                        can_deduct: false,
                        can_direct_bill: false,
                        can_send_quotation: false,
                        can_send_prepaid_quotation: false,
                        discount_applied: false,
                        can_toggle_discount: false,
                        discount_toggle_blocked_reason: '無法讀取開單流程狀態，請重新整理後再試。',
                        deduct_blocked_reason: '無法讀取開單流程狀態，請重新整理後再試。',
                        direct_blocked_reason: '無法讀取開單流程狀態，請重新整理後再試。',
                        quotation_blocked_reason: '無法讀取開單流程狀態，請重新整理後再試。'
                    };
                    $scope.billingWorkflowLoading = false;
                });
            }

            // 繳費單種類的顯示名稱（後端存的是 normal / prepaid）
            var BILL_KIND_LABELS = { normal: '一般帳單', prepaid: '預繳帳單' };

            /**
             * 「寄送繳費單」的已寄送標記文字。
             *
             * 繳費單本來就允許重寄（上次寄錯人、對方說沒收到），所以寄過之後
             * 按鈕不會被鎖住；但正因為不會鎖，畫面上若沒有任何標記，管理員
             * 分不出「還沒寄」與「已經寄過」，很容易重複寄給客戶。
             * 這行文字同時用在按鈕上的徽章、按鈕的 title 與重寄前的確認視窗。
             *
             * 時間來源是 billing_workflows.quotation_sent_at（重寄會更新成最後一次），
             * 所以重新整理網頁後仍看得到。
             */
            $scope.quotationSentLabel = function () {
                var w = $scope.billingWorkflow || {};
                if (!w.quotation_sent) return '';
                var kind = BILL_KIND_LABELS[w.quotation_kind] || '';
                return '已於 ' + (w.quotation_sent_at || '—') + ' 寄送' + (kind ? '（' + kind + '）' : '');
            };

            // 按鈕底下那行提示：告訴使用者現在該按哪一顆
            $scope.billingWorkflowHint = function () {
                var w = $scope.billingWorkflow || {};
                if (!w.confirm_email_sent) return '流程第一步：請先「寄送確認信」，寄出後才能開立繳費單。';
                if (!w.bill_issued) return '確認信已寄出，請擇一執行「額度扣款後,開立繳費單」或「開立繳費單」（兩者只能選一個）。';
                if (!w.quotation_sent) return '繳費單已開立，可以「寄送繳費單」了。';
                return '本年度流程已全部完成（繳費單' + $scope.quotationSentLabel() + '），仍可視需要重寄繳費單。';
            };

            /* ============================================================
             * 寄送繳費單 —— 步驟一：選擇帳單種類
             *
             * 有「尚未繳款的預繳紀錄」時才能選「開立預繳帳單」；
             * 沒有的話那個選項會是停用狀態（後端也會再擋一次）。
             * ============================================================ */
            $scope.billKindChooserOpen = false;

            $scope.openBillSendChooser = function () {
                if (!$scope.billingWorkflow.can_send_quotation) {
                    alert($scope.billingWorkflow.quotation_blocked_reason || '目前無法寄送繳費單。');
                    return;
                }
                // 寄過之後仍然可以再寄（上次寄錯人／對方沒收到），只是先問一次，
                // 避免同一張繳費單在管理員沒察覺的情況下重複寄給客戶。
                if ($scope.billingWorkflow.quotation_sent &&
                    !confirm('【本年度繳費單已經寄過了】\n\n' + $scope.quotationSentLabel() +
                             '\n\n確定要再寄一次嗎？')) {
                    return;
                }
                $scope.billKindChooserOpen = true;
            };

            $scope.closeBillKindChooser = function () {
                $scope.billKindChooserOpen = false;
            };

            $scope.onBillKindChooserBackdrop = function ($event) {
                if ($event.target && $event.target.id === 'billKindChooserModal') { $scope.closeBillKindChooser(); }
            };

            /* ============================================================
             * 寄送繳費單 —— 步驟二：確認信件內容後寄出
             *
             * 這是與「寄送確認信」完全獨立的一條流程：
             *   - 信件本文＝繳費單通知信範本渲染的 HTML
             *   - 附件    ＝繳費單 (hpc_quotation.html) 轉成的 PDF
             *
             * 表頭那幾格不讓人直接改 HTML，而是用視窗裡的表格逐格填寫，
             * 開啟時自動帶入聯絡人資料；改完按「重新產生預覽」重新渲染，
             * 送出時再把同一份欄位交給後端，確保看到的就是寄出的。
             * ============================================================ */
            $scope.billEmailModalOpen = false;
            $scope.billEmailLoading = false;
            $scope.billEmailRefreshing = false;
            $scope.billEmailSending = false;
            $scope.billEmail = { kind: 'normal', to: [], cc: [], subject: '', fields: {} };

            // 繳費單原尺寸是 880pt 寬，塞進彈窗會看不清楚，所以提供縮放。
            var QUOTATION_ZOOM_STEPS = [0.4, 0.5, 0.6, 0.75, 0.9, 1.0, 1.25, 1.5];
            var QUOTATION_ZOOM_DEFAULT = 0.6;

            function applyBillEmailPreview(data) {
                // 縮放比例是使用者的檢視偏好，重新產生預覽時不該被重設
                var zoom = ($scope.billEmail && $scope.billEmail.zoom) || QUOTATION_ZOOM_DEFAULT;

                $scope.billEmail = {
                    kind: data.kind || 'normal',
                    to: data.to || [],
                    cc: data.cc || [],
                    subject: data.subject || '',
                    fields: data.fields || {},
                    prepaid_targets: data.prepaid_targets || [],
                    rows: data.rows || [],
                    total_text: data.total_text || '',
                    unmatched: data.unmatched || [],
                    unmatched_amount: data.unmatched_amount || 0,
                    // Serverlist 查無費率的用量：算不出金額，但一定要讓開單的人知道
                    unpriced: data.unpriced || [],
                    // 兩份預覽都是完整的 HTML 文件，一律放進 iframe 隔離：
                    // 直接塞進頁面的話，它們 <style> 裡的 table / td 裸選擇器
                    // 會外洩到整個管理頁面，把外面的清單表格一起改掉。
                    notificationHtml: data.notification_html || '',
                    quotationHtml: data.quotation_html || '',
                    zoom: zoom
                };
            }

            $scope.zoomQuotationPreview = function (direction) {
                var current = $scope.billEmail.zoom || QUOTATION_ZOOM_DEFAULT;
                var index = QUOTATION_ZOOM_STEPS.indexOf(current);
                if (index === -1) index = QUOTATION_ZOOM_STEPS.indexOf(QUOTATION_ZOOM_DEFAULT);
                index = Math.min(QUOTATION_ZOOM_STEPS.length - 1, Math.max(0, index + direction));
                $scope.billEmail.zoom = QUOTATION_ZOOM_STEPS[index];
            };

            $scope.resetQuotationZoom = function () {
                $scope.billEmail.zoom = QUOTATION_ZOOM_DEFAULT;
            };

            function fetchBillEmailPreview(contactId, kind, fields) {
                var params = angular.extend({ kind: kind }, fields || {});
                return $http.get('/api/contacts/' + contactId + '/bill-email-preview', { params: params });
            }

            $scope.openBillEmailModal = function (kind) {
                var contactId = $scope.quotaTargetId;
                if (!contactId) {
                    alert('🛑 前端錯誤：找不到必要的網頁元素！');
                    return;
                }

                if (kind === 'prepaid' && !$scope.billingWorkflow.can_send_prepaid_quotation) {
                    alert('該帳號沒有尚未繳款的預繳紀錄，無法開立預繳帳單。');
                    return;
                }
                if (kind === 'normal' && !$scope.billingWorkflow.can_send_normal_quotation) {
                    alert('尚未開立本年度繳費單，請先完成「額度扣款後,開立繳費單」或「開立繳費單」。');
                    return;
                }

                $scope.closeBillKindChooser();
                $scope.billEmail = {
                    kind: kind, to: [], cc: [], subject: '', fields: {},
                    prepaid_targets: [], zoom: QUOTATION_ZOOM_DEFAULT
                };
                $scope.billEmailLoading = true;
                $scope.billEmailModalOpen = true;

                // 第一次開啟不帶 overrides，讓後端自動帶入聯絡人資料當預設值
                fetchBillEmailPreview(contactId, kind, null).then(function (res) {
                    applyBillEmailPreview(res.data || {});
                    $scope.billEmailLoading = false;
                }, function (err) {
                    $scope.billEmailLoading = false;
                    $scope.billEmailModalOpen = false;
                    var data = (err && err.data) || {};
                    alert('❌ 無法產生繳費單預覽：' + (data.message || ('HTTP ' + (err && err.status))));
                });
            };

            $scope.refreshBillEmailPreview = function () {
                var contactId = $scope.quotaTargetId;
                if (!contactId) return;

                $scope.billEmailRefreshing = true;
                fetchBillEmailPreview(contactId, $scope.billEmail.kind, $scope.billEmail.fields).then(function (res) {
                    applyBillEmailPreview(res.data || {});
                    $scope.billEmailRefreshing = false;
                }, function (err) {
                    $scope.billEmailRefreshing = false;
                    var data = (err && err.data) || {};
                    alert('❌ 重新產生預覽失敗：' + (data.message || ('HTTP ' + (err && err.status))));
                });
            };

            $scope.closeBillEmailModal = function () {
                $scope.billEmailModalOpen = false;
            };

            $scope.onBillEmailModalBackdrop = function ($event) {
                if ($event.target && $event.target.id === 'billEmailModal') { $scope.closeBillEmailModal(); }
            };

            $scope.confirmSendBillEmail = function () {
                var contactId = $scope.quotaTargetId;
                if (!contactId) {
                    alert('🛑 前端錯誤：找不到必要的網頁元素！');
                    return;
                }

                var recipients = ($scope.billEmail.to || []).concat($scope.billEmail.cc || []);
                // 已經寄過就在確認視窗裡講明這是重寄，不要讓人以為是第一次寄
                var resendNote = $scope.billingWorkflow.quotation_sent
                    ? '\n⚠️ 本年度繳費單' + $scope.quotationSentLabel() + '，這是重寄。'
                    : '';
                if (!confirm('【確認寄出繳費單？】\n\n收件人：' + recipients.join('、') +
                             '\n金額：' + ($scope.billEmail.total_text || '') + resendNote +
                             '\n\n繳費單會轉成 PDF 附件一併寄出。')) {
                    return;
                }

                $scope.billEmailSending = true;
                $http({
                    method: 'POST',
                    url: '/api/contacts/' + contactId + '/send-bill-email',
                    headers: { 'Content-Type': 'application/json' },
                    data: { kind: $scope.billEmail.kind, fields: $scope.billEmail.fields }
                }).then(function (res) {
                    $scope.billEmailSending = false;
                    var data = res.data || {};
                    if (data.success) {
                        alert('✅ ' + data.message);
                        $scope.closeBillEmailModal();
                        loadBillingWorkflow(contactId);
                    } else {
                        alert('❌ 寄送失敗：' + (data.message || '未知錯誤'));
                    }
                }, function (err) {
                    $scope.billEmailSending = false;
                    var data = (err && err.data) || {};
                    alert('❌ 寄送失敗：' + (data.message || ('HTTP ' + (err && err.status))));
                });
            };

            // ============================================================
            // 寄送確認信（跟寄送繳費單無關，寄的是「確認信範本設定」編輯好的內容，
            // 後端會自動帶入該聯絡人去年度的 HPC 使用量表格）
            //
            // 點擊按鈕不會直接送出，而是先開一個 modal 顯示收件人/副本/主旨與
            // 渲染好的實際內容，管理員確認無誤後才按「確認寄送」真正寄出。
            // ============================================================
            $scope.confirmEmailPreviewModalOpen = false;
            $scope.confirmEmailPreviewLoading = false;
            $scope.confirmEmailSending = false;
            $scope.confirmEmailPreview = { to: [], cc: [], subject: '', html: '' };

            $scope.sendQuotationCheckEmail = function () {
                var contactId = $scope.quotaTargetId;

                if (!contactId) {
                    alert('🛑 前端錯誤：找不到必要的網頁元素！');
                    return;
                }

                $scope.confirmEmailPreview = { to: [], cc: [], subject: '', trustedHtml: '' };
                $scope.confirmEmailPreviewLoading = true;
                $scope.confirmEmailPreviewModalOpen = true;

                $http.get('/api/contacts/' + contactId + '/confirm-email-preview').then(function (res) {
                    var data = res.data || {};
                    $scope.confirmEmailPreview = {
                        to: data.to || [],
                        cc: data.cc || [],
                        subject: data.subject || '',
                        // 用 trustAsHtml 讓信件原本的 inline style 不會被 ngSanitize 洗掉，
                        // 預覽才會跟實際寄出的長相一致
                        trustedHtml: $sce.trustAsHtml(data.html || '')
                    };
                    $scope.confirmEmailPreviewLoading = false;
                }, function (err) {
                    $scope.confirmEmailPreviewLoading = false;
                    $scope.confirmEmailPreviewModalOpen = false;
                    var data = (err && err.data) || {};
                    alert('❌ 無法產生預覽：' + (data.message || ('HTTP ' + (err && err.status))));
                });
            };

            $scope.closeConfirmEmailPreviewModal = function () {
                $scope.confirmEmailPreviewModalOpen = false;
            };

            $scope.onConfirmEmailPreviewBackdrop = function ($event) {
                if ($event.target && $event.target.id === 'confirmEmailPreviewModal') { $scope.closeConfirmEmailPreviewModal(); }
            };

            $scope.confirmSendQuotationCheckEmail = function () {
                var contactId = $scope.quotaTargetId;
                if (!contactId) {
                    alert('🛑 前端錯誤：找不到必要的網頁元素！');
                    return;
                }

                $scope.confirmEmailSending = true;
                $http({
                    method: 'POST',
                    url: '/api/contacts/' + contactId + '/send-confirm-email',
                    headers: { 'Content-Type': 'application/json' }
                }).then(function (res) {
                    $scope.confirmEmailSending = false;
                    var data = res.data || {};
                    if (data.success) {
                        alert('✅ ' + data.message);
                        $scope.closeConfirmEmailPreviewModal();
                        // 確認信是流程第一步，寄出後要立刻刷新狀態才會解鎖後面兩顆開單按鈕
                        loadBillingWorkflow(contactId);
                    } else {
                        alert('❌ 寄送失敗：' + (data.message || '未知錯誤'));
                    }
                }, function (err) {
                    $scope.confirmEmailSending = false;
                    var data = (err && err.data) || {};
                    alert('❌ 寄送失敗：' + (data.message || ('HTTP ' + (err && err.status))));
                });
            };

            // ============================================================
            // 額度設定（原 loadQuotaSettings）
            // ============================================================
            $scope.quotaSettings = { freeQuotaText: '加載中...', academicQuotaText: '加載中...', billDiscount: null };

            function loadQuotaSettings() {
                $http.get('/api/hpc-usage/settings_free_quota').then(function (res) {
                    var data = res.data;
                    // 預設值，防止 API 沒抓到數字時畫面空白
                    var freeQuota = 0;
                    var academicQuota = 0;
                    // 帳單折扣（⚙️ 系統設定 → 帳單折扣設定）與額度設定同屬 classification 2，
                    // 跟著這支 API 一起回來，額度視窗不必再多打一次請求。
                    var billDiscount = null;

                    // 支援 API 回傳清單 Array 或 字典 Object 結構
                    if (angular.isArray(data)) {
                        data.forEach(function (item) {
                            if (item.key === 'free_quota') freeQuota = item.value;
                            if (item.key === 'academic_quota') academicQuota = item.value;
                            if (item.key === 'bill_discount') billDiscount = item.value;
                        });
                    } else if (angular.isObject(data)) {
                        freeQuota = data.free_quota || 0;
                        academicQuota = data.academic_quota || 0;
                        billDiscount = data.bill_discount || null;
                    }

                    $scope.quotaSettings.billDiscount = normalizeBillDiscount(billDiscount);

                    // 格式化數字 (例如 10000 轉為 10,000) 供畫面顯示，同時保留原始數字供計算用
                    $scope.quotaSettings.freeQuota = Number(freeQuota) || 0;
                    $scope.quotaSettings.academicQuota = Number(academicQuota) || 0;
                    $scope.quotaSettings.freeQuotaText = $scope.quotaSettings.freeQuota.toLocaleString();
                    $scope.quotaSettings.academicQuotaText = $scope.quotaSettings.academicQuota.toLocaleString();
                }, function (error) {
                    console.error('載入額度設定失敗:', error);
                    $scope.quotaSettings.freeQuota = 0;
                    $scope.quotaSettings.academicQuota = 0;
                    $scope.quotaSettings.freeQuotaText = '0';
                    $scope.quotaSettings.academicQuotaText = '0';
                    $scope.quotaSettings.billDiscount = null;
                });
            }

            /* ------------------------------------------------------------
             * 帳單折扣（唯讀顯示用）
             *
             * 額度視窗「本期費用核對與帳務管理」的本期應收總金額旁邊會顯示
             * 折扣規則與結算價格，兩者都只是顯示：實際送出的金額仍是使用者
             * 在欄位裡核對過的「本期應收總金額」，這裡不會自動改寫它。
             * 沒有設定折扣時 normalizeBillDiscount() 回 null，畫面上兩項都不出現。
             * ------------------------------------------------------------ */
            function normalizeBillDiscount(raw) {
                if (!raw || !angular.isObject(raw)) return null;

                var minAmount = Number(raw.min_amount);
                var discount = Number(raw.discount);
                if (raw.min_amount === null || raw.min_amount === '' || isNaN(minAmount) || minAmount < 0) return null;
                if (raw.discount === null || raw.discount === '' || isNaN(discount)) return null;
                if (!(discount > 0 && discount <= 10)) return null;

                return { min_amount: minAmount, discount: discount };
            }

            function applyBillDiscount(amount, rule) {
                var value = parseFloat(amount);
                if (isNaN(value) || !rule) return null;
                if (value <= rule.min_amount) return value;
                return rule.min_amount + (value - rule.min_amount) * rule.discount / 10;
            }

            $scope.billDiscountRuleText = function () {
                var rule = $scope.quotaSettings.billDiscount;
                if (!rule) return '';

                var threshold = '超過 $' + rule.min_amount.toLocaleString() + ' 的部分';
                // 10 折等於原價，寫「打 10 折」容易被誤讀成有折扣
                if (rule.discount === 10) return threshold + '不打折 (10 折)';
                return threshold + '打 ' + (Math.round(rule.discount * 100) / 100) + ' 折';
            };

            $scope.billDiscountedAmount = function () {
                return applyBillDiscount($scope.pendingBill.amount, $scope.quotaSettings.billDiscount);
            };

            /* ------------------------------------------------------------
             * 「使用折扣」開關
             *
             * 狀態存在後端 billing_workflows.discount_applied，重新整理後仍記得。
             * 使用折扣與「額度扣款後開立繳費單」互斥：開啟後 can_deduct 會變成
             * false，扣款按鈕跟著停用；後端 confirm_deduct 也會再擋一次。
             * ------------------------------------------------------------ */
            $scope.billDiscountToggling = false;

            $scope.toggleBillDiscountApplied = function () {
                var contactId = $scope.quotaTargetId;
                if (!contactId || $scope.billDiscountToggling) return;

                if (!$scope.billingWorkflow.can_toggle_discount) {
                    alert($scope.billingWorkflow.discount_toggle_blocked_reason || '目前無法變更折扣的使用狀態。');
                    return;
                }

                var next = !$scope.billingWorkflow.discount_applied;
                if (next) {
                    var confirmMsg = '【確認使用帳單折扣？】\n\n' + $scope.billDiscountRuleText() +
                        '。\n使用折扣後，本年度將無法再使用「額度扣款後,開立繳費單」。';
                    if (!confirm(confirmMsg)) return;
                }

                $scope.billDiscountToggling = true;
                $http.post('/api/contacts/' + contactId + '/billing-discount', { applied: next })
                    .then(function (res) {
                        var data = res.data || {};
                        $scope.billDiscountToggling = false;
                        if (data.workflow) {
                            $scope.billingWorkflow = data.workflow;
                        } else {
                            loadBillingWorkflow(contactId);
                        }
                    }, function (err) {
                        $scope.billDiscountToggling = false;
                        var data = (err && err.data) || {};
                        alert('折扣狀態變更失敗：' + (data.message || ('HTTP ' + (err && err.status))));
                        // 後端狀態可能與畫面不一致，重新拉一次以免按鈕停在錯的樣子
                        loadBillingWorkflow(contactId);
                    });
            };

            // ============================================================
            // HPC 統計資料（原 statisticsExport / closeStatisticsModal）
            // ============================================================
            $scope.statisticsModalOpen = false;
            $scope.statsRows = [];
            $scope.statsLoading = false;
            $scope.statsError = '';

            $scope.statisticsExport = function () {
                console.log('開始執行 statisticsExport');

                // 打開視窗並顯示載入中
                $scope.statisticsModalOpen = true;
                $scope.statsLoading = true;
                $scope.statsError = '';
                $scope.statsRows = [];

                // 發送 API 請求
                $http.get('/api/contacts/hpc-statistics').then(function (res) {
                    var resData = res.data || {};
                    console.log('API 回傳資料：', resData);
                    $scope.statsLoading = false;

                    if (resData.status === 'success') {
                        $scope.statsRows = resData.data || [];
                    } else {
                        $scope.statsError = '無法取得統計資料';
                    }
                }, function (error) {
                    console.error('Fetch 錯誤:', error);
                    $scope.statsLoading = false;
                    $scope.statsError = '載入失敗：HTTP 錯誤！狀態碼: ' + (error && error.status);
                });
            };

            $scope.closeStatisticsModal = function () {
                $scope.statisticsModalOpen = false;
            };

            // 註：「繳費單紀錄明細」原本有一欄「操作」放銷帳按鈕，但該功能從未實作
            //     （點下去是 ReferenceError）。銷帳實際上是在「HPC 帳務審核」頁面
            //     進行的，因此該欄位與 triggerManualWriteOff 一併移除。

            // ============================================================
            // ⚙️ 系統設定 Modal（原 setting-button）
            //
            // 這顆按鈕底下之後會陸續掛更多功能，所以做成「選單 + 子畫面」的
            // 小型導覽結構：settingView 記錄目前在哪一頁（'menu' 或功能代號），
            // 進入子畫面時載入該功能的資料，標題列的返回箭頭會回到 'menu'。
            // ============================================================
            var SETTING_VIEWS = {
                menu: { title: '系統設定', icon: 'fa-cog' },
                emailTemplate: { title: '確認信範本設定', icon: 'fa-envelope-open-text' },
                quotaSettings: { title: '學術獎勵額度與優惠區間設定', icon: 'fa-graduation-cap' },
                billDiscount: { title: '帳單折扣設定', icon: 'fa-percent' },
                quotationItems: { title: '繳費單格式設定', icon: 'fa-file-invoice-dollar' },
                defaultCc: { title: '確認信預設副本人員', icon: 'fa-users' }
            };

            $scope.settingModalOpen = false;
            $scope.settingView = 'menu';
            $scope.settingViewTitle = SETTING_VIEWS.menu.title;
            $scope.settingViewIcon = SETTING_VIEWS.menu.icon;

            function setSettingView(view) {
                $scope.settingView = view;
                $scope.settingViewTitle = SETTING_VIEWS[view].title;
                $scope.settingViewIcon = SETTING_VIEWS[view].icon;
            }

            $scope.openSettingModal = function () {
                $scope.settingModalOpen = true;
                setSettingView('menu');
            };

            $scope.closeSettingModal = function () {
                $scope.settingModalOpen = false;
            };

            $scope.backToSettingMenu = function () {
                setSettingView('menu');
            };

            $scope.openSettingView = function (view) {
                setSettingView(view);
                if (view === 'emailTemplate') {
                    loadEmailTemplateView();
                } else if (view === 'quotaSettings') {
                    loadQuotaSettingsView();
                } else if (view === 'billDiscount') {
                    loadBillDiscountView();
                } else if (view === 'quotationItems') {
                    loadQuotationItemsView();
                } else if (view === 'defaultCc') {
                    loadDefaultCcView();
                }
            };

            // ------------------------------------------------------------
            // 子功能 1：確認信範本設定
            //
            // 內容預設抓 templates/email/quotation_check_email.html，
            // 之後若已儲存過自訂範本則改抓資料庫版本（後端已處理 fallback）。
            // 範本內會有 {{ 變數 }} 供後端 Python 端渲染真實資料，
            // 因此存檔前會比對「開啟當下」與「準備存檔」兩份內容的變數清單，
            // 一旦發現使用者刪掉了既有變數就擋下存檔並提示，避免誤刪。
            // ------------------------------------------------------------
            $scope.emailTemplateLoading = false;
            $scope.emailTemplateSaving = false;
            $scope.emailTemplate = { html: '' };
            $scope.emailTemplateHintText = '';

            var emailTemplateBasePlaceholders = [];

            function extractPlaceholders(html) {
                // 同時保護 {{ 變數 }} 輸出標籤，以及 {% for %}/{% endfor %} 這類控制區塊標籤
                // （範本裡的使用量表格需要 {% for %} 迴圈才能運作，少了它 {{ row.xxx }} 會渲染失敗）。
                var matches = String(html || '').match(/\{\{[^{}]*\}\}|\{%[^{}]*%\}/g) || [];
                var seen = {};
                var result = [];
                matches.forEach(function (m) {
                    var key = m.replace(/\s+/g, ' ').trim();
                    if (!seen[key]) {
                        seen[key] = true;
                        result.push(key);
                    }
                });
                return result;
            }

            function buildEmailTemplateHint(placeholders) {
                if (placeholders.length) {
                    return '內容中的 ' + placeholders.join('、') + ' 為系統標籤（含變數與表格迴圈），將由程式自動帶入實際資料，請勿刪除或修改；如需新增變數請維持相同的 {{ 變數名 }} 格式。';
                }
                return '內容若包含 {{ 變數名 }} 或 {% %} 格式的文字，將由系統自動帶入實際資料；請勿刪除既有的標籤，如需新增請維持相同格式。';
            }

            function applyEmailTemplateHtml(html) {
                emailTemplateBasePlaceholders = extractPlaceholders(html);
                $scope.emailTemplateHintText = buildEmailTemplateHint(emailTemplateBasePlaceholders);
                $scope.emailTemplate.html = html;
            }

            function loadEmailTemplateView() {
                $scope.emailTemplateLoading = true;
                $scope.emailTemplateSaving = false;
                $scope.emailTemplate = { html: '' };
                emailTemplateBasePlaceholders = [];

                $http.get('/api/contacts/confirm-email-template').then(function (res) {
                    applyEmailTemplateHtml((res.data && res.data.html) || '');
                    $scope.emailTemplateLoading = false;
                }, function (error) {
                    console.error('載入確認信範本失敗:', error);
                    $scope.emailTemplateLoading = false;
                    $scope.backToSettingMenu();
                    alert('載入確認信範本失敗，請稍後再試。');
                });
            }

            // 還原成預設範本內容（例如自訂版本被編輯器改壞、動態使用量表格失效時使用）。
            // 只是把內容載回編輯器讓管理員確認，還是要按「儲存範本」才會真的覆蓋資料庫版本。
            $scope.restoreDefaultEmailTemplate = function () {
                if (!confirm('確定要用預設範本內容覆蓋目前編輯器裡的內容嗎？（尚未按下「儲存範本」前不會影響已儲存的版本）')) {
                    return;
                }
                $scope.emailTemplateLoading = true;
                $http.get('/api/contacts/confirm-email-template', { params: { default: '1' } }).then(function (res) {
                    applyEmailTemplateHtml((res.data && res.data.html) || '');
                    $scope.emailTemplateLoading = false;
                }, function (error) {
                    console.error('載入預設範本失敗:', error);
                    $scope.emailTemplateLoading = false;
                    alert('載入預設範本失敗，請稍後再試。');
                });
            };

            $scope.saveEmailTemplate = function () {
                var html = $scope.emailTemplate.html || '';

                if (!html.trim()) {
                    alert('範本內容不能為空。');
                    return;
                }

                // 擋下使用者刪除既有 {{ 變數 }} 的存檔動作
                var currentPlaceholders = extractPlaceholders(html);
                var missing = emailTemplateBasePlaceholders.filter(function (p) {
                    return currentPlaceholders.indexOf(p) === -1;
                });
                if (missing.length) {
                    alert('以下系統變數已被移除，請保留供程式渲染使用，否則無法儲存：\n' + missing.join('\n'));
                    return;
                }

                $scope.emailTemplateSaving = true;
                $http.post('/api/contacts/confirm-email-template', { html: html }).then(function (res) {
                    $scope.emailTemplateSaving = false;
                    var result = res.data || {};
                    if (result.success) {
                        alert(result.message || '確認信範本已成功儲存。');
                        emailTemplateBasePlaceholders = extractPlaceholders(html);
                        $scope.backToSettingMenu();
                    } else {
                        alert('儲存失敗: ' + (result.message || '未知錯誤'));
                    }
                }, function (error) {
                    console.error('儲存確認信範本失敗:', error);
                    $scope.emailTemplateSaving = false;
                    alert('儲存失敗，請檢查網路或稍後再試。');
                });
            };

            // ------------------------------------------------------------
            // 子功能 2：學術獎勵額度與優惠區間設定
            //
            // 對應 HPCSetting 表 classification=2 的三筆設定：
            //   free_quota / academic_quota / discount（預繳優惠級距，list）
            // 沿用既有的 GET/POST /api/hpc-usage/settings_free_quota。
            // ------------------------------------------------------------
            $scope.quotaSettingsLoading = false;
            $scope.quotaSettingsSaving = false;
            $scope.quotaSettingsForm = { free_quota: null, academic_quota: null, discounts: [] };

            function loadQuotaSettingsView() {
                $scope.quotaSettingsLoading = true;
                $scope.quotaSettingsSaving = false;

                $http.get('/api/hpc-usage/settings_free_quota').then(function (res) {
                    var data = res.data;
                    var freeQuota = null, academicQuota = null, discounts = [];

                    if (angular.isArray(data)) {
                        data.forEach(function (item) {
                            if (item.key === 'free_quota') freeQuota = item.value;
                            if (item.key === 'academic_quota') academicQuota = item.value;
                            if (item.key === 'discount') discounts = angular.isArray(item.value) ? item.value : [];
                        });
                    }

                    $scope.quotaSettingsForm = {
                        free_quota: freeQuota,
                        academic_quota: academicQuota,
                        discounts: discounts.map(function (d) {
                            return { min_amount: d.min_amount, divisor: d.divisor };
                        })
                    };
                    $scope.quotaSettingsLoading = false;
                }, function (error) {
                    console.error('載入額度設定失敗:', error);
                    $scope.quotaSettingsLoading = false;
                    $scope.backToSettingMenu();
                    alert('載入額度設定失敗，請稍後再試。');
                });
            }

            $scope.addDiscountRow = function () {
                $scope.quotaSettingsForm.discounts.push({ min_amount: null, divisor: null });
            };

            $scope.removeDiscountRow = function (index) {
                $scope.quotaSettingsForm.discounts.splice(index, 1);
            };

            $scope.saveQuotaSettings = function () {
                var form = $scope.quotaSettingsForm;

                if (form.free_quota === null || form.free_quota === '' ||
                    form.academic_quota === null || form.academic_quota === '') {
                    alert('請填寫免費額度與學術獎勵額度。');
                    return;
                }

                var hasInvalidRow = form.discounts.some(function (d) {
                    return d.min_amount === null || d.min_amount === '' ||
                           d.divisor === null || d.divisor === '' || Number(d.divisor) === 0;
                });
                if (hasInvalidRow) {
                    alert('優惠區間的門檻金額與除數皆為必填，且除數不可為 0。');
                    return;
                }

                $scope.quotaSettingsSaving = true;
                $http.post('/api/hpc-usage/settings_free_quota', {
                    free_quota: form.free_quota,
                    academic_quota: form.academic_quota,
                    prepay_discounts: form.discounts.map(function (d) {
                        return { min_amount: Number(d.min_amount), divisor: Number(d.divisor) };
                    })
                }).then(function (res) {
                    $scope.quotaSettingsSaving = false;
                    var result = res.data || {};
                    if (result.success) {
                        alert(result.message || '設定已成功儲存。');
                        loadQuotaSettings(); // 同步刷新學術獎勵彈窗顯示用的唯讀額度文字
                        $scope.backToSettingMenu();
                    } else {
                        alert('儲存失敗: ' + (result.message || '未知錯誤'));
                    }
                }, function (error) {
                    console.error('儲存額度設定失敗:', error);
                    $scope.quotaSettingsSaving = false;
                    alert('儲存失敗，請檢查網路或稍後再試。');
                });
            };

            /* ------------------------------------------------------------
             * 子功能 2-1：帳單折扣設定
             *
             * 對應 HPCSetting 表 classification=2 的 bill_discount，內容是
             *   { min_amount: 門檻金額, discount: 折數(8.5 = 8.5 折) }
             * 空字典代表沒設定，額度視窗上的折扣說明與結算價格就不顯示。
             *
             * 只有「超出門檻的部分」打折，門檻以內照原價：
             *   結算價格 = 門檻 + (應收總金額 - 門檻) × 折數 ÷ 10
             * ------------------------------------------------------------ */
            $scope.billDiscountLoading = false;
            $scope.billDiscountSaving = false;
            $scope.billDiscountForm = { min_amount: null, discount: null };

            function loadBillDiscountView() {
                $scope.billDiscountLoading = true;
                $scope.billDiscountSaving = false;

                $http.get('/api/hpc-usage/settings_bill_discount').then(function (res) {
                    var data = res.data || {};
                    $scope.billDiscountForm = {
                        min_amount: data.min_amount === undefined ? null : data.min_amount,
                        discount: data.discount === undefined ? null : data.discount
                    };
                    $scope.billDiscountLoading = false;
                }, function (error) {
                    console.error('載入帳單折扣設定失敗:', error);
                    $scope.billDiscountLoading = false;
                    $scope.backToSettingMenu();
                    alert('載入帳單折扣設定失敗，請稍後再試。');
                });
            }

            // 設定畫面上的即時試算範例，讓人確認自己填的數字是不是想要的效果
            $scope.billDiscountExample = function () {
                var rule = normalizeBillDiscount($scope.billDiscountForm);
                if (!rule) return '';

                var sample = rule.min_amount + 10000;
                return '例如本期應收 $' + sample.toLocaleString() + ' → 結算價格 $' +
                       formatCurrency(applyBillDiscount(sample, rule)) + '。';
            };

            $scope.saveBillDiscount = function () {
                var form = $scope.billDiscountForm;
                var minBlank = form.min_amount === null || form.min_amount === '' || form.min_amount === undefined;
                var discountBlank = form.discount === null || form.discount === '' || form.discount === undefined;

                if (minBlank !== discountBlank) {
                    alert('門檻金額與折數必須一起填寫；若要清除設定，請兩欄都留空。');
                    return;
                }
                if (!minBlank) {
                    if (Number(form.min_amount) < 0) {
                        alert('門檻金額不可為負數。');
                        return;
                    }
                    if (!(Number(form.discount) > 0 && Number(form.discount) <= 10)) {
                        alert('折數必須大於 0 且不超過 10（10 折 = 不打折）。');
                        return;
                    }
                }

                $scope.billDiscountSaving = true;
                $http.post('/api/hpc-usage/settings_bill_discount', {
                    min_amount: minBlank ? null : Number(form.min_amount),
                    discount: discountBlank ? null : Number(form.discount)
                }).then(function (res) {
                    $scope.billDiscountSaving = false;
                    var result = res.data || {};
                    if (result.success) {
                        alert(result.message || '設定已成功儲存。');
                        loadQuotaSettings(); // 同步刷新額度視窗上的唯讀折扣顯示
                        $scope.backToSettingMenu();
                    } else {
                        alert('儲存失敗: ' + (result.message || '未知錯誤'));
                    }
                }, function (error) {
                    console.error('儲存帳單折扣設定失敗:', error);
                    $scope.billDiscountSaving = false;
                    var data = (error && error.data) || {};
                    alert('儲存失敗：' + (data.message || '請檢查網路或稍後再試。'));
                });
            };

            /* ------------------------------------------------------------
             * 子功能 3：繳費單格式設定 (QuotationItem)
             *
             * 對應繳費單 (hpc_quotation.html) 上「計算資源 / 收費係數 /
             * 使用量（核心小時）/ 總價」那張表的每一列。機器會汰換也會新增，
             * 所以列的內容不寫死在 HTML 裡。
             *
             * 一台主機底下可能有多個 queue、不同 queue 單價也不同：
             *   - 想分開列 → 建兩列，各自勾選不同的 queue
             *   - 想合併成一列 → 建一列，把兩個 queue 都勾起來
             * 未勾選任何 queue = 涵蓋該主機的全部 queue。
             *
             * 儲存採整批覆蓋：畫面上所有列一次送回後端，由後端比對 id
             * 做新增／更新／刪除。
             * ------------------------------------------------------------ */
            $scope.quotationItemsLoading = false;
            $scope.quotationItemsSaving = false;
            $scope.quotationItemsForm = { items: [] };
            $scope.serverOptions = [];

            function loadQuotationItemsView() {
                $scope.quotationItemsLoading = true;
                $scope.quotationItemsSaving = false;

                // 主機/queue 清單與設定內容要一起到齊，畫面才有辦法把已勾選的 queue 標出來
                var serversPromise = $http.get('/api/contacts/quotation-items/servers').then(function (res) {
                    $scope.serverOptions = res.data || [];
                }, function (error) {
                    console.error('載入主機清單失敗:', error);
                    $scope.serverOptions = [];
                });

                var itemsPromise = $http.get('/api/contacts/quotation-items').then(function (res) {
                    var data = res.data || {};
                    $scope.quotationItemsForm = {
                        items: (data.items || []).map(function (item) {
                            return {
                                id: item.id,
                                label: item.label,
                                coefficient: item.coefficient,
                                is_active: item.is_active !== false,
                                targets: (item.targets || []).map(function (t) {
                                    return { server: t.server, queues: (t.queues || []).slice() };
                                })
                            };
                        })
                    };
                }, function (error) {
                    console.error('載入繳費單格式設定失敗:', error);
                    $scope.quotationItemsForm = { items: [] };
                    throw error;
                });

                serversPromise.then(function () {
                    return itemsPromise;
                }).then(function () {
                    $scope.quotationItemsLoading = false;
                }, function () {
                    $scope.quotationItemsLoading = false;
                    $scope.backToSettingMenu();
                    alert('載入繳費單格式設定失敗，請稍後再試。');
                });
            }

            // 某台主機底下有哪些 queue（含單價，讓管理員判斷要不要合併成同一列）
            $scope.queuesOf = function (server) {
                if (!server) return [];
                var found = $scope.serverOptions.filter(function (s) { return s.server === server; })[0];
                return (found && found.queues) || [];
            };

            $scope.addQuotationItem = function () {
                $scope.quotationItemsForm.items.push({
                    id: null, label: '', coefficient: null, is_active: true,
                    targets: [{ server: '', queues: [] }]
                });
            };

            $scope.removeQuotationItem = function (index) {
                $scope.quotationItemsForm.items.splice(index, 1);
            };

            $scope.addQuotationTarget = function (item) {
                item.targets.push({ server: '', queues: [] });
            };

            $scope.removeQuotationTarget = function (item, index) {
                item.targets.splice(index, 1);
            };

            // 換主機時要清掉已勾選的 queue，否則會留下不屬於新主機的 queue 名稱
            $scope.onQuotationTargetServerChange = function (target) {
                target.queues = [];
            };

            $scope.toggleQuotationQueue = function (target, queue) {
                var index = target.queues.indexOf(queue);
                if (index === -1) {
                    target.queues.push(queue);
                } else {
                    target.queues.splice(index, 1);
                }
            };

            $scope.saveQuotationItems = function () {
                var items = $scope.quotationItemsForm.items || [];

                for (var i = 0; i < items.length; i++) {
                    var item = items[i];
                    if (!(item.label || '').trim()) {
                        alert('第 ' + (i + 1) + ' 列缺少「顯示名稱」。');
                        return;
                    }
                    var validTargets = (item.targets || []).filter(function (t) { return !!t.server; });
                    if (validTargets.length === 0) {
                        alert('「' + item.label + '」至少要指定一台主機，否則這一列在繳費單上永遠是 0 元。');
                        return;
                    }
                }

                $scope.quotationItemsSaving = true;
                $http.post('/api/contacts/quotation-items', {
                    items: items.map(function (item) {
                        return {
                            id: item.id,
                            label: (item.label || '').trim(),
                            coefficient: (item.coefficient === '' ? null : item.coefficient),
                            is_active: item.is_active !== false,
                            targets: (item.targets || []).filter(function (t) { return !!t.server; })
                                .map(function (t) { return { server: t.server, queues: t.queues || [] }; })
                        };
                    })
                }).then(function (res) {
                    $scope.quotationItemsSaving = false;
                    var result = res.data || {};
                    if (result.success) {
                        alert(result.message || '繳費單格式設定已成功儲存。');
                        $scope.backToSettingMenu();
                    } else {
                        alert('儲存失敗: ' + (result.message || '未知錯誤'));
                    }
                }, function (error) {
                    console.error('儲存繳費單格式設定失敗:', error);
                    $scope.quotationItemsSaving = false;
                    var data = (error && error.data) || {};
                    alert('儲存失敗：' + (data.message || '請檢查網路或稍後再試'));
                });
            };

            // ------------------------------------------------------------
            // 子功能 4：確認信預設副本人員
            //
            // 對應 HPCSetting key='confirm_email_default_cc'（一個 Email 字串陣列）。
            // 寄送確認信時，後端會自動把這份清單併入 Cc。
            // ------------------------------------------------------------
            $scope.defaultCcLoading = false;
            $scope.defaultCcSaving = false;
            $scope.defaultCcForm = { emails: [] };

            function loadDefaultCcView() {
                $scope.defaultCcLoading = true;

                $http.get('/api/contacts/confirm-email-default-cc').then(function (res) {
                    var emails = (res.data && res.data.emails) || [];
                    $scope.defaultCcForm = { emails: angular.isArray(emails) ? emails.slice() : [] };
                    $scope.defaultCcLoading = false;
                }, function (error) {
                    console.error('載入預設副本人員失敗:', error);
                    $scope.defaultCcLoading = false;
                    $scope.backToSettingMenu();
                    alert('載入預設副本人員失敗，請稍後再試。');
                });
            }

            $scope.addDefaultCcRow = function () {
                $scope.defaultCcForm.emails.push('');
            };

            $scope.removeDefaultCcRow = function (index) {
                $scope.defaultCcForm.emails.splice(index, 1);
            };

            $scope.saveDefaultCc = function () {
                var emails = $scope.defaultCcForm.emails
                    .map(function (e) { return (e || '').trim(); })
                    .filter(function (e) { return e !== ''; });

                $scope.defaultCcSaving = true;
                $http.post('/api/contacts/confirm-email-default-cc', { emails: emails }).then(function (res) {
                    $scope.defaultCcSaving = false;
                    var result = res.data || {};
                    if (result.success) {
                        alert(result.message || '預設副本人員已成功儲存。');
                        $scope.backToSettingMenu();
                    } else {
                        alert('儲存失敗: ' + (result.message || '未知錯誤'));
                    }
                }, function (error) {
                    console.error('儲存預設副本人員失敗:', error);
                    $scope.defaultCcSaving = false;
                    var data = (error && error.data) || {};
                    alert('儲存失敗：' + (data.message || '請檢查網路或稍後再試'));
                });
            };

            // ============================================================
            // 初始化：對應原版三個 DOMContentLoaded 的內容
            // ============================================================
            initYearFilter();       // 初始化年份下拉選單
            fetchAndRenderHosts();  // 動態載入主機清單
            loadData(1);            // 初始載入表格資料
            loadQuotaSettings();    // 載入免費/學術額度設定
        }
    ]);
})();
