// static/js/hpc_usage.ctrl.js
angular.module('emailApp')
.controller('HpcUsageController', ['$scope', '$http', '$timeout', function($scope, $http, $timeout) {
    
    // ==========================================
    // 1. 初始化狀態與變數
    // ==========================================
    $scope.message = { text: '', type: '', visible: false };
    $scope.settings = {};
    
    // 載入鎖（控制遮罩轉圈圈）
    $scope.isLoadingHistory = false;
    $scope.isLoadingPrepaid = false;
    
    // 前端記憶體快取空間
    const historyCache = {};
    const prepaidCache = {};
    
    // 歷史紀錄分頁與查詢變數
    $scope.historyRecords = [];
    $scope.totalHistoryPages = 1;
    $scope.historyQuery = {
        startDate: '',
        endDate: '',
        page: 1,
        limit: 10
    };

    // 預繳金額監控分頁與查詢變數
    $scope.prepaidRecords = [];
    $scope.totalPrepaidPages = 1;
    $scope.prepaidQuery = {
        filterExceeded: false,
        page: 1,
        limit: 10
    };

    // ==========================================
    // 2. 輔助函式 (訊息提示、日期初始化、平滑捲動)
    // ==========================================
    function showMessage(text, type) {
        $scope.message.text = text;
        $scope.message.type = type;
        $scope.message.visible = true;
        $timeout(() => {
            $scope.message.visible = false;
        }, 5000);
    }

    // 初始化 Flatpickr 與日期設定
    function initDatePicker() {
        const today = new Date();
        const thirtyDaysAgo = new Date(today);
        thirtyDaysAgo.setDate(today.getDate() - 30);
        const formatDate = (date) => date.toISOString().split('T')[0];

        $scope.historyQuery.startDate = formatDate(thirtyDaysAgo);
        $scope.historyQuery.endDate = formatDate(today);

        $timeout(() => {
            flatpickr('#startDate', {
                defaultDate: $scope.historyQuery.startDate,
                onChange: function(selectedDates, dateStr) {
                    $scope.historyQuery.startDate = dateStr;
                    $scope.$apply();
                }
            });
            flatpickr('#endDate', {
                defaultDate: $scope.historyQuery.endDate,
                onChange: function(selectedDates, dateStr) {
                    $scope.historyQuery.endDate = dateStr;
                    $scope.$apply();
                }
            });
        });
    }

    // 當換頁成功時，平滑移動回表格頂端，優化視覺體驗
    function scrollToContainer(containerId) {
        const element = document.getElementById(containerId);
        if (element) {
            element.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
    }

    // ==========================================
    // 3. API 串接與邏輯處理 (含快取機制)
    // ==========================================

    // 載入目前設定
    $scope.loadSettings = function() {
        $http.get('/api/hpc-usage/settings')
            .then(function(response) {
                if (response.data) {
                    $scope.settings = response.data;
                }
            }, function(error) {
                console.error('載入設定時發生錯誤:', error);
                showMessage('無法載入目前設定或連線錯誤。', 'error');
            });
    };

    // 儲存設定
    $scope.saveSettings = function() {
        const s = $scope.settings;
        if (s.price_threshold < 0 || s.check_interval <= 0 || s.check_period <= 0 || s.diff_price_threshold <= 0 || s.notification_cooldown_days <= 0) {
            showMessage('請輸入有效的數值。', 'error');
            return;
        }

        $http.post('/api/hpc-usage/settings', s)
            .then(function(response) {
                if (response.data && response.data.success) {
                    showMessage(response.data.message, 'success');
                } else {
                    showMessage('儲存設定失敗: ' + (response.data.message || '未知錯誤'), 'error');
                }
            }, function(error) {
                console.error('儲存設定時發生錯誤:', error);
                showMessage('儲存設定時發生連線錯誤，請檢查網路。', 'error');
            });
    };

    // 查詢歷史通知紀錄 (加入 Cache 優化)
    $scope.fetchHistory = function(page, isScroll) {
        if ($scope.isLoadingHistory) return;
        $scope.historyQuery.page = page || 1;
        
        // 建立唯一快取鍵值
        const cacheKey = `${$scope.historyQuery.startDate}_${$scope.historyQuery.endDate}_${$scope.historyQuery.page}`;
        
        // 命中快取：若之前有撈過，直接渲染，達成 0 毫秒秒開體感
        if (historyCache[cacheKey]) {
            $scope.historyRecords = historyCache[cacheKey].records;
            $scope.totalHistoryPages = historyCache[cacheKey].totalPages;
            if (isScroll) scrollToContainer('historyTableContainer');
            return;
        }

        $scope.isLoadingHistory = true;
        const params = {
            start_date: $scope.historyQuery.startDate,
            end_date: $scope.historyQuery.endDate,
            page: $scope.historyQuery.page,
            limit: $scope.historyQuery.limit
        };

        $http.get('/api/hpc-usage/history', { params: params })
            .then(function(response) {
                $scope.historyRecords = response.data.records || [];
                const totalRecords = response.data.total_records || 0;
                $scope.totalHistoryPages = Math.ceil(totalRecords / $scope.historyQuery.limit) || 1;
                
                // 寫入快取
                historyCache[cacheKey] = {
                    records: $scope.historyRecords,
                    totalPages: $scope.totalHistoryPages
                };
                
                if (isScroll) scrollToContainer('historyTableContainer');
            }, function(error) {
                console.error('查詢歷史紀錄時發生錯誤:', error);
                showMessage('查詢歷史紀錄時發生連線錯誤。', 'error');
                $scope.historyRecords = [];
            })
            .finally(function() {
                // 稍微延遲釋放狀態，讓 UI 動態更平滑
                $timeout(() => { $scope.isLoadingHistory = false; }, 200);
            });
    };

    $scope.searchHistory = function() {
        // 當點擊手動「查詢」按鈕時，必須清空快取以取得後端最新狀態
        for (let key in historyCache) delete historyCache[key];
        $scope.fetchHistory(1, false);
    };

    $scope.changeHistoryPage = function(delta) {
        const targetPage = $scope.historyQuery.page + delta;
        if (targetPage >= 1 && targetPage <= $scope.totalHistoryPages) {
            $scope.fetchHistory(targetPage, true);
        }
    };

    // 查詢預繳金額與年度用量監控資料 (加入 Cache 優化)
    $scope.fetchPrepaidData = function(page, isScroll) {
        if ($scope.isLoadingPrepaid) return;
        $scope.prepaidQuery.page = page || 1;

        // 建立唯一快取鍵值
        const cacheKey = `${$scope.prepaidQuery.filterExceeded}_${$scope.prepaidQuery.page}`;

        // 命中快取
        if (prepaidCache[cacheKey]) {
            $scope.prepaidRecords = prepaidCache[cacheKey].records;
            $scope.totalPrepaidPages = prepaidCache[cacheKey].totalPages;
            if (isScroll) scrollToContainer('prepaidTableContainer');
            return;
        }

        $scope.isLoadingPrepaid = true;
        const params = {
            filter_exceeded: $scope.prepaidQuery.filterExceeded,
            page: $scope.prepaidQuery.page,
            limit: $scope.prepaidQuery.limit
        };

        $http.get('/api/hpc-usage/prepaid', { params: params })
            .then(function(response) {
                $scope.prepaidRecords = response.data.records || [];
                const totalRecords = response.data.total_records || 0;
                $scope.totalPrepaidPages = Math.ceil(totalRecords / $scope.prepaidQuery.limit) || 1;
                
                // 寫入快取
                prepaidCache[cacheKey] = {
                    records: $scope.prepaidRecords,
                    totalPages: $scope.totalPrepaidPages
                };

                if (isScroll) scrollToContainer('prepaidTableContainer');
            }, function(error) {
                console.error('查詢預繳資料時發生錯誤:', error);
                $scope.prepaidRecords = [];
            })
            .finally(function() {
                $timeout(() => { $scope.isLoadingPrepaid = false; }, 200);
            });
    };

    // 當勾選「僅顯示用量超過預繳金額的帳號」或重新載入時，清空監控快取
    $scope.clearPrepaidCacheAndFetch = function() {
        for (let key in prepaidCache) delete prepaidCache[key];
        $scope.fetchPrepaidData(1, false);
    };

    $scope.changePrepaidPage = function(delta) {
        const targetPage = $scope.prepaidQuery.page + delta;
        if (targetPage >= 1 && targetPage <= $scope.totalPrepaidPages) {
            $scope.fetchPrepaidData(targetPage, true);
        }
    };

    // 一鍵通知與個別通知按鈕實作（觸發後必須清空監控快取以更新通知狀態欄位）
    $scope.notifyAll = function() {
        if (confirm('確定要一鍵通知所有未通知的帳號嗎？')) {
            $http.post('/api/hpc-usage/notify-all')
                .then(function(response) {
                    showMessage(response.data.message || '批次通知已發送', 'success');
                    $scope.clearPrepaidCacheAndFetch();
                }, function(error) {
                    showMessage('發送全體通知失敗。', 'error');
                });
        }
    };

    $scope.notifySingle = function(account) {
        $http.post('/api/hpc-usage/notify-single', { username: account.username })
            .then(function(response) {
                showMessage(response.data.message || '通知已發送', 'success');
                $scope.clearPrepaidCacheAndFetch();
            }, function(error) {
                showMessage('發送個人通知失敗。', 'error');
            });
    };

    // ==========================================
    // 4. 頁面初始化進入點
    // ==========================================
    $scope.loadSettings();
    initDatePicker();
    $scope.fetchHistory(1, false);
    $scope.fetchPrepaidData(1, false);
}]);