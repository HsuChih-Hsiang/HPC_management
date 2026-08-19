// static/js/billing_review.ctrl.js
//
// HPC 帳務審核頁面。
//
// 這頁只做一件事：把「錢收到了沒」回寫到資料庫的狀態欄位
//   - 預付額度 PrepaidAmount.is_paid
//   - 繳費單   Bill.status
//
// ⚠️ 一筆預付額度在資料庫中是「活躍 + 歷史」兩筆紀錄（靠 source_id 配對），
//    兩筆一起更新的工作由後端 /api/billing/... 處理，前端只需送出一次請求。
var app = angular.module('emailApp');

app.controller('BillingReviewController', ['$scope', '$http', '$timeout', function($scope, $http, $timeout) {

    // ==========================================
    // 1. 初始化狀態
    // ==========================================
    $scope.message = { text: '', type: '', visible: false };
    $scope.loading = true;
    $scope.saving = false;

    $scope.prepaids = [];
    $scope.bills = [];
    $scope.filteredPrepaids = [];
    $scope.filteredBills = [];
    $scope.summary = {
        pending_prepaid_count: 0, pending_prepaid_amount: 0,
        pending_bill_count: 0, pending_bill_amount: 0
    };
    $scope.counts = { pendingPrepaid: 0, pendingBill: 0, selected: 0 };

    $scope.selectAllPrepaid = false;
    $scope.selectAllBill = false;

    $scope.filter = {
        status: 'pending',
        keyword: '',
        // 預設帶今天，按下「確認繳費」時會寫進 PrepaidAmount.payment_date。
        // AngularJS 的 input[type="date"] 規定 ng-model 必須是 Date 物件，
        // 綁字串會拋 ngModel:datefmt 並讓欄位顯示空白，送出前才用 paymentDateString() 轉成 YYYY-MM-DD。
        paymentDate: new Date()
    };

    // 用本地時間組出 YYYY-MM-DD。不能用 toISOString()，它會先轉成 UTC，
    // 台灣時間的凌晨時段會被推回前一天，繳款日期就會記錯。
    $scope.paymentDateString = function() {
        var d = $scope.filter.paymentDate;
        if (!(d instanceof Date) || isNaN(d.getTime())) return '';

        var month = String(d.getMonth() + 1);
        var day = String(d.getDate());
        return d.getFullYear() + '-'
            + (month.length < 2 ? '0' + month : month) + '-'
            + (day.length < 2 ? '0' + day : day);
    };

    function showMessage(text, type) {
        $scope.message.text = text;
        $scope.message.type = type;
        $scope.message.visible = true;
        $timeout(function() { $scope.message.visible = false; }, 6000);
    }

    function errorMessage(error, fallback) {
        var data = (error && error.data) || {};
        showMessage(data.message || fallback, 'error');
    }

    $scope.formatMoney = function(value) {
        var num = Number(value || 0);
        return num.toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 2 });
    };

    // 已鎖定的項目（獎勵額度以外的限制、0 元紀錄單、已被扣抵過的額度）不開放勾選批次操作
    $scope.canToggle = function(item) {
        return !item.locked;
    };

    // ==========================================
    // 2. 載入與篩選
    // ==========================================
    $scope.reload = function() {
        $scope.loading = true;
        $scope.selectAllPrepaid = false;
        $scope.selectAllBill = false;

        return $http.get('/api/billing/review-items', { params: { status: $scope.filter.status } })
            .then(function(res) {
                var data = res.data || {};
                $scope.prepaids = data.prepaids || [];
                $scope.bills = data.bills || [];
                $scope.summary = data.summary || $scope.summary;

                $scope.counts.pendingPrepaid = $scope.prepaids.filter(function(p) {
                    return !p.is_paid;
                }).length;
                $scope.counts.pendingBill = $scope.bills.filter(function(b) {
                    return b.status === 'unpaid' && !b.locked;
                }).length;

                $scope.applyFilter();
            }, function(error) {
                errorMessage(error, '載入審核清單失敗。');
            }).finally(function() {
                $scope.loading = false;
            });
    };

    function matchKeyword(item, keyword) {
        if (!keyword) return true;
        var haystack = [
            item.team_name, item.applicant, item.dept_level1,
            item.username, item.formal_account, item.notes
        ].join(' ').toLowerCase();
        return haystack.indexOf(keyword) !== -1;
    }

    $scope.applyFilter = function() {
        var keyword = ($scope.filter.keyword || '').trim().toLowerCase();

        $scope.filteredPrepaids = $scope.prepaids.filter(function(p) {
            return matchKeyword(p, keyword);
        });
        $scope.filteredBills = $scope.bills.filter(function(b) {
            return matchKeyword(b, keyword);
        });
    };

    // ==========================================
    // 3. 勾選
    // ==========================================
    function countSelected() {
        var total = 0;
        $scope.filteredPrepaids.forEach(function(p) { if (p._selected) total++; });
        $scope.filteredBills.forEach(function(b) { if (b._selected) total++; });
        return total;
    }

    // 用 $watch 同步勾選數量，這樣模板只讀 scope 屬性，不必在每個 digest 呼叫函式
    $scope.$watch(countSelected, function(newCount) {
        $scope.counts.selected = newCount;
    });

    $scope.toggleAllPrepaid = function() {
        var checked = $scope.selectAllPrepaid;
        $scope.filteredPrepaids.forEach(function(p) {
            if ($scope.canToggle(p)) p._selected = checked;
        });
    };

    $scope.toggleAllBill = function() {
        var checked = $scope.selectAllBill;
        $scope.filteredBills.forEach(function(b) {
            if ($scope.canToggle(b)) b._selected = checked;
        });
    };

    $scope.clearSelection = function() {
        $scope.selectAllPrepaid = false;
        $scope.selectAllBill = false;
        $scope.prepaids.forEach(function(p) { p._selected = false; });
        $scope.bills.forEach(function(b) { b._selected = false; });
    };

    // ==========================================
    // 4. 審核動作
    // ==========================================
    function describePrepaid(p) {
        return (p.team_name || p.username) + ' ' + (p.year || '') + ' 年度 $' + $scope.formatMoney(p.total);
    }

    $scope.reviewPrepaid = function(p, isPaid) {
        // 確認繳費會把日期寫進 payment_date，日期被清空時先擋下來，
        // 避免不知不覺被後端 fallback 成今天。
        if (isPaid && !$scope.paymentDateString()) {
            showMessage('請先於上方工具列選擇繳費日期。', 'error');
            return;
        }

        var confirmText = isPaid
            ? '確認【' + describePrepaid(p) + '】已經收到款項？\n\n'
              + '繳款日期將記為 ' + $scope.paymentDateString() + '，'
              + '確認後這筆額度即可被計費扣款使用。'
            : '確定要把【' + describePrepaid(p) + '】退回「未繳費」嗎？\n\n'
              + '退回後這筆額度將無法用於扣款。';

        if (!confirm(confirmText)) return;

        $scope.saving = true;
        $http.put('/api/billing/prepaids/' + p.id + '/review', {
            is_paid: isPaid,
            payment_date: $scope.paymentDateString()
        }).then(function(res) {
            var result = res.data || {};
            showMessage(result.message, 'success');
            $scope.reload();
        }, function(error) {
            errorMessage(error, '更新預付額度狀態失敗。');
        }).finally(function() {
            $scope.saving = false;
        });
    };

    $scope.reviewBill = function(b, isPaid) {
        var label = '繳費單 #' + b.id + '（' + (b.team_name || '未對應聯絡人') + ' $' + $scope.formatMoney(b.amount) + '）';
        var confirmText = isPaid
            ? '確認【' + label + '】已經收到款項？'
            : '確定要把【' + label + '】退回「未繳費」嗎？';

        if (!confirm(confirmText)) return;

        $scope.saving = true;
        $http.put('/api/billing/bills/' + b.id + '/review', { is_paid: isPaid })
            .then(function(res) {
                var result = res.data || {};
                showMessage(result.message, 'success');
                $scope.reload();
            }, function(error) {
                errorMessage(error, '更新繳費單狀態失敗。');
            }).finally(function() {
                $scope.saving = false;
            });
    };

    $scope.reviewSelected = function(isPaid) {
        var prepaidIds = $scope.filteredPrepaids
            .filter(function(p) { return p._selected; })
            .map(function(p) { return p.id; });
        var billIds = $scope.filteredBills
            .filter(function(b) { return b._selected; })
            .map(function(b) { return b.id; });

        if (!prepaidIds.length && !billIds.length) {
            showMessage('請先勾選要審核的項目。', 'error');
            return;
        }

        if (isPaid && prepaidIds.length && !$scope.paymentDateString()) {
            showMessage('請先於上方工具列選擇繳費日期。', 'error');
            return;
        }

        var action = isPaid ? '確認繳費' : '退回未繳費';
        var confirmText = '即將對 ' + prepaidIds.length + ' 筆預付額度與 '
            + billIds.length + ' 筆繳費單執行「' + action + '」。\n\n'
            + (isPaid ? '繳款日期將統一記為 ' + $scope.paymentDateString() + '。\n\n' : '')
            + '若其中任何一筆不符合條件，整批都不會被更新。是否繼續？';

        if (!confirm(confirmText)) return;

        $scope.saving = true;
        $http.post('/api/billing/review-batch', {
            prepaid_ids: prepaidIds,
            bill_ids: billIds,
            is_paid: isPaid,
            payment_date: $scope.paymentDateString()
        }).then(function(res) {
            var result = res.data || {};
            showMessage(result.message, 'success');
            $scope.clearSelection();
            $scope.reload();
        }, function(error) {
            errorMessage(error, '批次審核失敗。');
        }).finally(function() {
            $scope.saving = false;
        });
    };

    // ==========================================
    // 5. 進入點
    // ==========================================
    $scope.reload();
}]);
