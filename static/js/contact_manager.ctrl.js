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
                            addContactRow(!!sc.is_primary, sc.name || '', sc.info || '');
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
            function addContactRow(isPrimary, name, info) {
                $scope.contactRows.push({
                    is_primary: Boolean(isPrimary),
                    name: name || '',
                    info: info || ''
                });
            }
            $scope.addContactRow = addContactRow;

            $scope.removeContactRow = function (index) {
                $scope.contactRows.splice(index, 1);
            };

            // 原版用 pointerdown + click 兩段式判斷，讓已勾選的 radio 可以再點一次取消
            $scope.togglePrimaryContact = function (row, $event) {
                if ($event) $event.preventDefault();
                if (row.is_primary) {
                    // 點擊前已是勾選狀態 → 這次點擊是要取消勾選
                    row.is_primary = false;
                } else {
                    // 點擊前未勾選 → 設為唯一的主要聯絡人
                    $scope.contactRows.forEach(function (r) { r.is_primary = false; });
                    row.is_primary = true;
                }
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
                            return {
                                name: trim(row.name),
                                info: trim(row.info),
                                is_primary: Boolean(row.is_primary)
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
                bills: null,
                billsLoading: false
            };

            $scope.pendingBill = {
                amount: '', date: '', notes: '',
                placeholder: '請輸入核對後的金額',
                notesColor: '', notesBold: false
            };
            $scope.addQuota = { amount: '0', purchaseDate: '' };

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
                    bills: null,
                    billsLoading: true
                };

                // 強制清空舊資料，顯示 placeholder
                $scope.pendingBill = {
                    amount: '', date: '', notes: '',
                    placeholder: '計算建議金額中...',
                    notesColor: '', notesBold: false
                };

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

                if ($scope.reward.free) {
                    selectedItems.push({ type: 'free', quantity: 1 });
                    confirmDetails.push('・免費額度 $10,000 元 (限今年度帳單折抵)');
                }

                if ($scope.reward.academic) {
                    var qty = parseInt($scope.reward.quantity, 10) || 1;
                    if (qty <= 0) {
                        alert('學術額度數量必須大於 0');
                        return;
                    }
                    selectedItems.push({ type: 'academic', quantity: qty });
                    confirmDetails.push('・學術額度 $1,000 × ' + qty + ' 份 = $' + (1000 * qty) + ' 元');
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

            // ============================================================
            // 兩階段驗證：先檢視 PDF 繳費單，確認無誤後再寄送（原 handlePreviewAndSend）
            // ============================================================
            $scope.handlePreviewAndSend = function () {
                console.log('🚀 handlePreviewAndSend 被點擊了！');

                var contactId = $scope.quotaTargetId;
                var amount = $scope.pendingBill.amount;
                var billDate = $scope.pendingBill.date || '';
                var notes = $scope.pendingBill.notes || '管理員手動直接開單';
                var recipientEmail = $scope.currentContactEmail || '';

                if (!contactId) {
                    alert('🛑 前端錯誤：找不到必要的網頁元素！');
                    return;
                }

                if (!amount || parseFloat(amount) <= 0) {
                    alert('請輸入有效的繳費單金額以產生帳單項目');
                    return;
                }

                if (!recipientEmail) {
                    alert('無法取得客戶電子郵件，請確認外圍畫面的 Email 欄位設定正確');
                    return;
                }

                var payloadData = {
                    recipient: recipientEmail,
                    title: 'HPC 運算服務繳費通知單',
                    executor: '系統管理員',
                    date: billDate,
                    items: [{ name: notes, amount: parseFloat(amount) }]
                };

                alert('系統即將產生繳費單 PDF 預覽，請在即將開啟的新分頁中進行核對。');

                // 階段一：發送預覽請求並開啟新分頁檢視
                $http({
                    method: 'POST',
                    url: '/api/contacts/send-quotation',
                    headers: { 'Content-Type': 'application/json' },
                    data: angular.extend({}, payloadData, { preview: true }),
                    responseType: 'blob'
                }).then(function (res) {
                    var blob = new Blob([res.data], { type: 'application/pdf' });
                    var pdfUrl = URL.createObjectURL(blob);
                    var previewWindow = window.open(pdfUrl, '_blank');

                    if (!previewWindow) {
                        alert('偵測到瀏覽器封鎖了彈出視窗，請允許彈出視窗以檢視 PDF 帳單！');
                    }

                    // 階段二：留在原分頁等待管理員核對
                    $timeout(function () {
                        var isConfirmed = confirm('【繳費單檢視確認】\n\n請確認新分頁中的 PDF 帳單明細。\n\n金額：$' +
                            amount + ' 元\n收件人：' + recipientEmail +
                            '\n\n確認內容完全無誤並現在寄出信件嗎？');

                        if (!isConfirmed) return;

                        $http({
                            method: 'POST',
                            url: '/api/contacts/send-quotation',
                            headers: { 'Content-Type': 'application/json' },
                            data: angular.extend({}, payloadData, { preview: false })
                        }).then(function (res2) {
                            var result = res2.data || {};
                            if (result.status === 'success') {
                                alert('✅ 信件發送成功：' + result.message);
                                $scope.pendingBill.amount = '';
                                $scope.pendingBill.notes = '';
                            } else {
                                alert('❌ 寄送失敗：' + result.message);
                            }
                        }, function (err) {
                            alert('系統發生異常: ' + ((err && err.data && err.data.message) || ('HTTP ' + (err && err.status))));
                        });
                    }, 800);
                }, function (err) {
                    // 統一捕捉階段一的所有連線與系統異常
                    var msg = (err && err.data && err.data.message) ? err.data.message : '無法生成預覽檔';
                    alert('系統發生異常: ' + msg);
                });
            };

            // ============================================================
            // 額度設定（原 loadQuotaSettings）
            // ============================================================
            $scope.quotaSettings = { freeQuotaText: '加載中...', academicQuotaText: '加載中...' };

            function loadQuotaSettings() {
                $http.get('/api/hpc-usage/settings_free_quota').then(function (res) {
                    var data = res.data;
                    // 預設值，防止 API 沒抓到數字時畫面空白
                    var freeQuota = 0;
                    var academicQuota = 0;

                    // 支援 API 回傳清單 Array 或 字典 Object 結構
                    if (angular.isArray(data)) {
                        data.forEach(function (item) {
                            if (item.key === 'free_quota') freeQuota = item.value;
                            if (item.key === 'academic_quota') academicQuota = item.value;
                        });
                    } else if (angular.isObject(data)) {
                        freeQuota = data.free_quota || 0;
                        academicQuota = data.academic_quota || 0;
                    }

                    // 格式化數字 (例如 10000 轉為 10,000)
                    $scope.quotaSettings.freeQuotaText = Number(freeQuota).toLocaleString();
                    $scope.quotaSettings.academicQuotaText = Number(academicQuota).toLocaleString();
                }, function (error) {
                    console.error('載入額度設定失敗:', error);
                    $scope.quotaSettings.freeQuotaText = '0';
                    $scope.quotaSettings.academicQuotaText = '0';
                });
            }

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

            // ============================================================
            // 銷帳按鈕
            // 註：原版 contact_manager.js 從未定義 triggerManualWriteOff，
            //     點下去會是 ReferenceError（既有缺陷）。
            //     這裡保留呼叫點，若他處（例如 index.js）有定義就轉呼叫。
            // ============================================================
            $scope.triggerManualWriteOff = function (billId, amount) {
                if (typeof window.triggerManualWriteOff === 'function') {
                    window.triggerManualWriteOff(billId, amount);
                    return;
                }
                console.warn('triggerManualWriteOff 尚未實作（沿用原始程式行為）', billId, amount);
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
