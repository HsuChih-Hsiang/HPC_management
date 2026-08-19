// static/js/profile.ctrl.js

// 取得 app.js 中已定義的 emailApp 主模組（注意：不要加第二個參數 []）
var app = angular.module('emailApp');

// 本頁的插值符號改為 [[ ]]，避免與 Flask Jinja2 的 {{ }} 衝突
app.config(['$interpolateProvider', function($interpolateProvider) {
    $interpolateProvider.startSymbol('[[');
    $interpolateProvider.endSymbol(']]');
}]);

app.controller('ProfileController', ['$scope', '$http', '$timeout', function($scope, $http, $timeout) {

    // ==========================================
    // 1. 初始化狀態
    // ==========================================
    $scope.message = { text: '', type: '', visible: false };
    $scope.loading = true;
    $scope.saving = false;
    $scope.profile = {
        name: '',
        contact_email: '',
        google_email: ''
    };

    function showMessage(text, type) {
        $scope.message.text = text;
        $scope.message.type = type;
        $scope.message.visible = true;
        $timeout(function() {
            $scope.message.visible = false;
        }, 5000);
    }

    // ==========================================
    // 2. API 串接
    // ==========================================
    function loadProfile() {
        return $http.get('/api/profile').then(function(response) {
            var data = (response && response.data) || {};
            var profile = data.profile || {};
            $scope.profile.name = profile.name || '';
            $scope.profile.contact_email = profile.contact_email || '';
            $scope.profile.google_email = profile.google_email || '';
        }, function(error) {
            console.error('載入個人資料失敗:', error);
            var data = (error && error.data) || {};
            showMessage('無法載入個人資料：' + (data.message || '請稍後再試'), 'error');
        }).finally(function() {
            $scope.loading = false;
        });
    }

    $scope.saveProfile = function() {
        var name = ($scope.profile.name || '').trim();
        var contactEmail = ($scope.profile.contact_email || '').trim();

        // 後端 validate_profile() 會再檢查一次，這裡只是讓使用者馬上得到回饋
        if (!name) {
            showMessage('請輸入顯示名稱。', 'error');
            return;
        }

        $scope.saving = true;

        $http.post('/api/profile', {
            name: name,
            contact_email: contactEmail
        }).then(function(response) {
            var result = (response && response.data) || {};
            if (!result.success) {
                showMessage('儲存失敗：' + (result.message || '未知錯誤'), 'error');
                return;
            }

            var profile = result.profile || {};
            $scope.profile.name = profile.name || '';
            $scope.profile.contact_email = profile.contact_email || '';

            // 側邊欄的名字是 sidebar.html 用 ng-init 設在同一個 scope 上的 userName，
            // 這裡一併更新，使用者不必重新整理就能看到新名字。
            $scope.userName = $scope.profile.name;

            showMessage(result.message || '個人資料已更新。', 'success');
        }, function(error) {
            console.error('儲存個人資料失敗:', error);
            var data = (error && error.data) || {};
            showMessage('儲存失敗：' + (data.message || '請檢查網路或稍後再試'), 'error');
        }).finally(function() {
            $scope.saving = false;
        });
    };

    // ==========================================
    // 3. 頁面初始化進入點
    // ==========================================
    loadProfile();
}]);
