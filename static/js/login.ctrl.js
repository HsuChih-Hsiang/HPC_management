// static/js/login.ctrl.js
app.controller('LoginController', ['$scope', '$timeout', '$window', function($scope, $timeout, $window) {
    $scope.isLoggingIn = false;
    $scope.buttonText = '使用 Google 帳號繼續';

    $scope.login = function() {
        $scope.isLoggingIn = true;
        $scope.buttonText = '準備跳轉至 Google 驗證...';
        
        // 延遲一小段時間模擬給使用者的視覺反饋，然後跳轉路由
        $timeout(function() {
            $window.location.href = '/login';
        }, 100);
    };
}]);