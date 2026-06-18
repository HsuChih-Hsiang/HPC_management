// static/js/mailbox_manager.js

// 獲取在 app.js 中已經定義好的 emailApp 主模組（注意：不要加第二個參數 []）
var app = angular.module('emailApp');

// 配置該頁面的插值符號為 [[ ]]，防止與 Flask Jinja2 的 {{ }} 衝突
app.config(['$interpolateProvider', function($interpolateProvider) {
    $interpolateProvider.startSymbol('[[');
    $interpolateProvider.endSymbol(']]');
}]);

// 註冊 MailboxController
app.controller('MailboxController', ['$scope', '$http', function($scope, $http) {
    $scope.groups = [];
    $scope.unassignedEmails = [];
    $scope.newGroupName = '';
    
    // 用一個專門的物件來存放各分組的輸入框內容，避免 ng-repeat 作用域污染
    $scope.emailInputs = {}; 

    // 取得所有分組與信箱資料
    $scope.fetchGroups = function() {
        $http.get('/api/mailboxes')
            .then(function(response) {
                const data = response.data;
                
                // 篩選出待分組信箱
                const unassigned = data.find(g => g.name === "待分組信箱");
                $scope.unassignedEmails = unassigned ? unassigned.emails : [];
                $scope.unassignedGroupId = unassigned ? unassigned.id : 0;

                // 其他一般分組
                $scope.groups = data.filter(g => g.name !== "待分組信箱");
            })
            .catch(function(error) {
                console.error('讀取分組失敗:', error);
            });
    };

    // 新增分組
    $scope.addGroup = function() {
        const name = $scope.newGroupName.trim();
        if (!name) return;

        $http.post('/api/mailboxes', { name: name })
            .then(function() {
                $scope.newGroupName = '';
                $scope.fetchGroups();
            })
            .catch(function(error) {
                console.error('新增分組失敗:', error);
            });
    };

    // 刪除分組
    $scope.deleteGroup = function(id) {
        if (!confirm('確定要刪除此分組？')) return;

        $http.delete('/api/mailboxes/' + id)
            .then(function() {
                $scope.fetchGroups();
            })
            .catch(function(error) {
                console.error('刪除分組失敗:', error);
            });
    };

    // 新增信箱到指定分組
    $scope.addEmail = function(groupId) {
        const email = $scope.emailInputs[groupId] ? $scope.emailInputs[groupId].trim() : '';
        if (!email) return;

        $http.post('/api/mailboxes/' + groupId + '/add_email', { email: email })
            .then(function() {
                $scope.emailInputs[groupId] = ''; // 清空該組輸入框
                $scope.fetchGroups();
            })
            .catch(function(error) {
                console.error('新增信箱失敗:', error);
            });
    };

    // 從指定分組刪除信箱
    $scope.deleteEmail = function(groupId, email) {
        if (!confirm('確定要從此分組中刪除郵箱 ' + email + ' 嗎？')) return;

        $http({
            url: '/api/mailboxes/' + groupId + '/delete_email',
            method: 'DELETE',
            data: { email: email },
            headers: { 'Content-Type': 'application/json' }
        }).then(function() {
            $scope.fetchGroups();
        }).catch(function(error) {
            console.error('刪除信箱失敗:', error);
        });
    };

    // --- 拖曳事件（與原先 HTML5 Drag & Drop 相容） ---
    $scope.onDragStart = function(event, email) {
        event.dataTransfer.setData('text/plain', email);
    };

    $scope.onDragOver = function(event) {
        event.preventDefault();
    };

    $scope.onDrop = function(event, groupId) {
        event.preventDefault();
        const email = event.dataTransfer.getData('text/plain');
        if (email) {
            $scope.$apply(function() {
                // 直接寫入物件欄位，100% 觸發雙向綁定更新畫面
                $scope.emailInputs[groupId] = email;
            });
        }
    };

    // 初始化讀取資料
    $scope.fetchGroups();
}]);

// 擴充 H5 拖曳指令至 emailApp 模組中
app.directive('ngOndragstart', function() {
    return function(scope, element, attrs) {
        element[0].addEventListener('dragstart', function(event) {
            scope.$apply(function() {
                scope.$eval(attrs.ngOndragstart, {'$event': event});
            });
        });
    };
}).directive('ngOndragover', function() {
    return function(scope, element, attrs) {
        element[0].addEventListener('dragover', function(event) {
            scope.$apply(function() {
                scope.$eval(attrs.ngOndragover, {'$event': event});
            });
        });
    };
}).directive('ngOndrop', function() {
    return function(scope, element, attrs) {
        element[0].addEventListener('drop', function(event) {
            scope.$apply(function() {
                scope.$eval(attrs.ngOndrop, {'$event': event});
            });
        });
    };
});