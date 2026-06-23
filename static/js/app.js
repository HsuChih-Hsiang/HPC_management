// static/js/app.js
var app = angular.module('emailApp', []);

// Quill Editor 封裝指令
app.directive('quillEditor', function() {
    return {
        require: 'ngModel',
        link: function(scope, element, attrs, ngModel) {
            var quill = new Quill(element[0], {
                theme: 'snow',
                modules: {
                    toolbar: [
                        [{ 'header': [1, 2, 3, 4, 5, 6, false] }],
                        ['bold', 'italic', 'underline', 'strike'],
                        ['blockquote', 'code-block'],
                        [{ 'list': 'ordered'}, { 'list': 'bullet' }],
                        [{ 'script': 'sub'}, { 'script': 'super' }],
                        [{ 'indent': '-1'}, { 'indent': '+1' }],
                        [{ 'direction': 'rtl' }],
                        [{ 'color': [] }, { 'background': [] }],
                        [{ 'font': [] }],
                        [{ 'align': [] }],
                        ['link', 'image'],
                        ['clean']
                    ]
                },
                placeholder: '在這裡輸入你的郵件內容...',
            });

            // 當 Quill 內容改變時，更新 Angular 的 ngModel
            quill.on('text-change', function() {
                scope.$applyAsync(function() {
                    ngModel.$setViewValue(quill.root.innerHTML);
                });
            });

            // 當 Angular 的 ngModel 改變時，更新 Quill
            ngModel.$render = function() {
                if (ngModel.$viewValue !== undefined) {
                    quill.root.innerHTML = ngModel.$viewValue;
                }
            };
            
            // 將 quill 實例暴露給 scope 以便其他功能使用 (如清空、套用模板)
            scope.quillInstance = quill;
        }
    };
});

// HTML5 拖曳指令 (Draggable)
app.directive('draggableTag', function() {
    return function(scope, element, attrs) {
        element[0].draggable = true;
        element.on('dragstart', function(e) {
            // 由於 scope.email 在不同上下文可能不同，安全起見可以用 attrs 傳入或確保 scope 存在該變數
            var emailVal = scope.email || element.text().trim().replace('×', ''); 
            e.dataTransfer.setData('text/plain', emailVal);
            e.dataTransfer.setData('sourceType', attrs.draggableTag);
        });
    };
});

// HTML5 放置指令 (Droppable)
app.directive('droppableArea', function() {
    return function(scope, element, attrs) {
        element.on('dragover', function(e) {
            e.preventDefault();
        });
        element.on('drop', function(e) {
            e.preventDefault();
            var draggedEmail = e.dataTransfer.getData('text/plain');
            var sourceType = e.dataTransfer.getData('sourceType');
            var targetType = attrs.droppableArea;
            
            // 安全檢查：確保兩個類型不同，且目前頁面的 scope 確實有 moveTag 函式
            if (sourceType !== targetType && typeof scope.moveTag === 'function') {
                scope.$apply(function() {
                    scope.moveTag(draggedEmail, sourceType, targetType);
                });
            }
        });
    };
});


// 2. 使用 .run() 定義全域（所有頁面通用）的側邊欄與導航邏輯
app.run(['$rootScope', function($rootScope) {
    
    // 狀態：側邊欄是否開啟
    $rootScope.isMenuOpen = false;

    // 功能：切換側邊欄開關
    $rootScope.toggleMenu = function() {
        $rootScope.isMenuOpen = !$rootScope.isMenuOpen;
    };

    // 功能：自動判斷當前瀏覽器網址路徑，決定哪個選單要變高亮 (active)
    // 這裡加上了移除尾隨斜線的處理，避免 /setting 與 /setting/ 造成判斷失敗
    $rootScope.isActive = function(path) {
        var currentPath = window.location.pathname;
        if (currentPath > 1 && currentPath.endsWith('/')) {
            currentPath = currentPath.slice(0, -1);
        }
        return currentPath === path;
    };
    
}]);

app.run(['$rootScope', '$interval', '$http', '$window', function($rootScope, $interval, $http, $window) {
    
    // 定義檢查 Function
    function checkSessionAlive() {
        $http.get('/check-session')
            .then(function(response) {
                // Session 依然有效，正常不作動作
                console.log('Session is valid.');
            }, function(error) {
                // 後端回傳 401 (或其他非 200 狀態)
                if (error.status === 401) {
                    stopHeartbeat();
                    alert('您的登入時效已過期，請重新登入！');
                    $window.location.href = '/login_page'; // 跳轉至登入頁
                }
            });
    }

    // 每 60,000 毫秒（1分鐘）執行一次
    const heartbeatTimer = $interval(checkSessionAlive, 300000);

    // 安全機制：當頁面銷毀或切換時關閉計時器，避免記憶體洩漏
    function stopHeartbeat() {
        if (angular.isDefined(heartbeatTimer)) {
            $interval.cancel(heartbeatTimer);
        }
    }

    $rootScope.$on('$destroy', function() {
        stopHeartbeat();
    });
    
    // 網頁一載入就先檢查一次
    checkSessionAlive();
}]);

app.config(['$httpProvider', function($httpProvider) {
    $httpProvider.interceptors.push(['$q', '$window', function($q, $window) {
        return {
            'responseError': function(rejection) {
                // 如果後端任何一個 API 回傳 401，代表工作階段已結束
                if (rejection.status === 401) {
                    // 為了避免重複 alert，可以確認當前網址是不是已經在登入頁了
                    if ($window.location.pathname !== '/login_page') {
                        alert('登入已過期，請重新登入。');
                        $window.location.href = '/login_page';
                    }
                }
                return $q.reject(rejection);
            }
        };
    }]);
}]);