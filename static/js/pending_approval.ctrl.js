// static/js/pending_approval.ctrl.js
var app = angular.module('emailApp');

app.controller('PendingApprovalController', ['$scope', '$http', '$interval', '$window',
function($scope, $http, $interval, $window) {

    $scope.checking = false;
    $scope.statusText = '';
    $scope.userName = '';

    // 向後端確認自己是否已被開通；已開通就直接進入系統。
    // 這支 API 不需任何功能權限，否則尚未開通的使用者根本查不到自己的狀態。
    function checkApproval(isManual) {
        if ($scope.checking) return;
        $scope.checking = true;

        $http.get('/api/permission/my-permissions')
            .then(function(response) {
                var data = response.data || {};
                if (data.approved) {
                    $scope.statusText = '權限已開通，正在進入系統...';
                    stopPolling();
                    $window.location.href = '/';
                } else if (isManual) {
                    $scope.statusText = '目前仍在等待管理員開通，請稍後再試。';
                }
            }, function(error) {
                if (error && error.status === 401) {
                    $window.location.href = '/login_page';
                    return;
                }
                $scope.statusText = '檢查狀態時發生錯誤，請稍後再試。';
            })
            .finally(function() {
                $scope.checking = false;
            });
    }

    // 每 30 秒自動偵測一次，管理員開通後使用者不必手動重整
    var poller = $interval(function() { checkApproval(false); }, 30000);

    function stopPolling() {
        if (angular.isDefined(poller)) {
            $interval.cancel(poller);
            poller = undefined;
        }
    }

    $scope.checkNow = function() {
        $scope.statusText = '';
        checkApproval(true);
    };

    $scope.$on('$destroy', stopPolling);

    checkApproval(false);
}]);
