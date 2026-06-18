// static/js/edit_templates.ctrl.js
angular.module('emailApp')
.controller('EditTemplatesController', ['$scope', '$http', '$window', '$timeout', function($scope, $http, $window, $timeout) {
    
    // 初始化變數
    $scope.templates = [];
    $scope.templateData = {
        name: '',
        subject: '',
        html: ''
    };
    $scope.currentEditingTemplateId = null;
    $scope.message = { text: '', type: '', visible: false };

    // 側邊欄狀態與邏輯
    $scope.isMenuOpen = false;
    $scope.toggleMenu = function() {
        $scope.isMenuOpen = !$scope.isMenuOpen;
    };
    $scope.isActive = function(path) {
        return $window.location.pathname === path;
    };

    // 顯示訊息提示框
    function showMessage(text, type) {
        $scope.message.text = text;
        $scope.message.type = type;
        $scope.message.visible = true;

        $timeout(function() {
            $scope.message.visible = false;
        }, 5000);
    }

    // 清空編輯器與輸入框狀態
    $scope.clearEditor = function() {
        $scope.templateData = {
            name: '',
            subject: '',
            html: ''
        };
        $scope.currentEditingTemplateId = null;
    };

    // 1. 加載所有已儲存的模板列表
    $scope.loadTemplates = function() {
        $http.get('/api/templates')
            .then(function(response) {
                $scope.templates = response.data;
            }, function(error) {
                console.error('加載模板失敗:', error);
                showMessage('加載模板列表失敗。', 'error');
            });
    };

    // 2. 點擊列表項目：載入模板內容到編輯器進行修改
    $scope.editTemplate = function(tpl) {
        $http.get('/api/templates/' + tpl.id)
            .then(function(response) {
                var data = response.data;
                if (data.success === false) {
                    showMessage(data.message, 'error');
                    return;
                }

                $scope.currentEditingTemplateId = tpl.id;
                $scope.templateData.name = data.name;
                $scope.templateData.subject = data.subject || '';
                $scope.templateData.html = data.html || '';

                showMessage('已載入模板 "' + data.name + '" 進行編輯。', 'info');

                // 畫面平滑捲動到編輯區域
                var editForm = document.getElementById('editForm');
                if (editForm) {
                    editForm.scrollIntoView({ behavior: 'smooth', block: 'start' });
                }
            }, function(error) {
                console.error('載入模板內容失敗:', error);
                showMessage('載入模板內容失敗。', 'error');
            });
    };

    // 3. 刪除模板
    $scope.deleteTemplate = function(tpl, event) {
        if (event) {
            event.stopPropagation(); // 阻止點擊事件穿透到外層容器
        }

        if (!$window.confirm('確定要刪除模板 "' + tpl.name + '" 嗎？此操作不可恢復！')) {
            return;
        }

        $http.delete('/api/templates/' + tpl.id)
            .then(function(response) {
                var result = response.data;
                if (result.success) {
                    showMessage(result.message, 'success');
                    $scope.loadTemplates(); // 重新整理列表

                    // 如果被刪除的正是目前正在編輯的模板，則清空編輯器
                    if ($scope.currentEditingTemplateId === tpl.id) {
                        $scope.clearEditor();
                    }
                } else {
                    showMessage('刪除模板失敗: ' + (result.message || '未知錯誤'), 'error');
                }
            }, function(error) {
                console.error('刪除模板連線錯誤:', error);
                showMessage('刪除模板失敗，請檢查網路或稍後再試。', 'error');
            });
    };

    // 4. 新增或更新儲存模板
    $scope.saveTemplate = function() {
        var name = $scope.templateData.name ? $scope.templateData.name.trim() : '';
        var subject = $scope.templateData.subject ? $scope.templateData.subject.trim() : '';
        var html = $scope.templateData.html ? $scope.templateData.html.trim() : '';

        if (!name) {
            showMessage('模板名稱不能為空。', 'error');
            return;
        }
        if (!html || html === '<p><br></p>') {
            showMessage('模板內容不能為空。', 'error');
            return;
        }

        var dataToSend = { name: name, subject: subject, html: html };
        var url = '/api/templates';
        var method = 'POST';

        // 如果有 ID，切換為更新（PUT）模式
        if ($scope.currentEditingTemplateId) {
            method = 'PUT';
            url = '/api/templates/' + $scope.currentEditingTemplateId;
        }

        $http({
            method: method,
            url: url,
            data: dataToSend
        }).then(function(response) {
            var result = response.data;
            if (result.success) {
                showMessage(result.message, 'success');
                $scope.clearEditor();   // 重置表單
                $scope.loadTemplates(); // 更新左側列表
            } else {
                showMessage('操作失敗: ' + (result.message || '未知錯誤'), 'error');
            }
        }, function(error) {
            console.error('模板操作連線錯誤:', error);
            showMessage('操作失敗，請檢查網路或稍後再試。', 'error');
        });
    };

    // 5. 取消編輯
    $scope.cancelEdit = function() {
        $scope.clearEditor();
        showMessage('編輯已取消。', 'info');
    };

    // 初始化：頁面載入時自動讀取模板列表
    $scope.loadTemplates();
}]);