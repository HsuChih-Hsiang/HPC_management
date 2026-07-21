// === 1. 定義 TinyMCE 的 AngularJS 指令 ===
app.directive('tinymceEditor', ['$timeout', function($timeout) {
    return {
        restrict: 'A',
        require: 'ngModel',
        link: function(scope, element, attrs, ngModelCtrl) {
            // 生成隨機的 ID 給 textarea，避免多個編輯器時衝突
            const id = 'tiny-editor-' + Math.random().toString(36).substr(2, 9);
            element.attr('id', id);

            $timeout(function() {
                tinymce.init({
                    selector: '#' + id,
                    height: 350,
                    menubar: 'edit view insert format tools table help',
                    plugins: 'anchor autolink charmap codesample emoticons image link lists media searchreplace table visualblocks wordcount',
                    toolbar: 'undo redo | blocks fontfamily fontsize | bold italic underline strike | link image table | align lineheight | numlist bullist indent outdent | emoticons charmap | removeformat',
                    branding: false,
                    promotion: false,
                    contextmenu: false,
                    setup: function(editor) {
                        // 當編輯器內容改變時，同步更新 AngularJS 的 ngModel
                        editor.on('change keyup nodechange', function() {
                            scope.$evalAsync(function() {
                                ngModelCtrl.$setViewValue(editor.getContent());
                            });
                        });

                        // 監聽外部 ngModel 的變更（例如：應用模板或清空時），同步回填給 TinyMCE
                        ngModelCtrl.$render = function() {
                            if (tinymce.get(id)) {
                                tinymce.get(id).setContent(ngModelCtrl.$viewValue || '');
                            }
                        };
                    }
                });
            });

            // 當 Scope 銷毀時，記得釋放 TinyMCE 實例記憶體
            scope.$on('$destroy', function() {
                if (tinymce.get(id)) {
                    tinymce.get(id).remove();
                }
            });
        }
    };
}]);

// === 2. 舊有的控制器內容 ===
app.controller('BatchSendingController', ['$scope', '$http', '$timeout', function($scope, $http, $timeout) {
    // === 狀態模型 ===
    $scope.isMenuOpen = false;
    $scope.showBcc = false;
    
    $scope.mailData = {
        to: [],
        cc: [],
        bcc: [],
        subject: '',
        body: ''
    };
    
    $scope.inputs = { to: '', cc: '', bcc: '' };
    $scope.message = { text: '', type: '', visible: false };
    
    // 模態視窗狀態
    $scope.modals = { template: false, group: false };
    $scope.templates = [];
    $scope.groups = [];
    $scope.currentGroupTarget = ''; // 紀錄當前開啟群組的目標 (to, cc, bcc)

    // === 訊息提示系統 ===
    $scope.showMessage = function(text, type) {
        $scope.message.text = text;
        $scope.message.type = type;
        $scope.message.visible = true;
        $timeout(function() {
            $scope.message.visible = false;
        }, 5000);
    };

    // === UI 互動 ===
    $scope.toggleMenu = function() { $scope.isMenuOpen = !$scope.isMenuOpen; };
    $scope.toggleBcc = function() {
        $scope.showBcc = !$scope.showBcc;
        if (!$scope.showBcc) {
            $scope.mailData.bcc = [];
            $scope.inputs.bcc = '';
        }
    };

    // === 標籤 (Tag) 邏輯 ===
    $scope.isValidEmail = function(email) {
        return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
    };

    $scope.addTag = function(event, type) {
        if (event && event.key !== 'Enter' && event.key !== ',') return;
        if (event) event.preventDefault();

        let email = $scope.inputs[type].trim().replace(',', '');
        if (!email) return;

        if (!$scope.isValidEmail(email)) {
            $scope.showMessage('請輸入有效的電子郵件地址。', 'error');
            return;
        }
        if ($scope.mailData[type].includes(email)) {
            $scope.showMessage('此電子郵件已存在。', 'error');
            return;
        }

        $scope.mailData[type].push(email);
        $scope.inputs[type] = ''; 
    };

    $scope.removeTag = function(type, index) {
        $scope.mailData[type].splice(index, 1);
    };

    $scope.moveTag = function(email, fromType, toType) {
        if ($scope.mailData[toType].includes(email)) {
            $scope.showMessage('目標容器已存在此電子郵件。', 'error');
            return;
        }
        let index = $scope.mailData[fromType].indexOf(email);
        if (index > -1) {
            $scope.mailData[fromType].splice(index, 1);
            $scope.mailData[toType].push(email);
        }
    };

    $scope.handlePaste = function(event, type) {
        event.preventDefault();
        let pastedText = (event.originalEvent || event).clipboardData.getData('text');
        let emails = pastedText.split(/[\s,]+/).filter(e => e.trim() !== '');
        
        let addedCount = 0;
        emails.forEach(email => {
            if ($scope.isValidEmail(email) && !$scope.mailData[type].includes(email)) {
                $scope.mailData[type].push(email);
                addedCount++;
            }
        });

        if (addedCount > 0) {
            $scope.showMessage(`已成功新增 ${addedCount} 個電子郵件地址。`, 'success');
        } else if (emails.length > 0) {
            $scope.showMessage('所有貼上的郵件地址均無效或已存在。', 'error');
        }
    };

    $scope.editTag = function(email, type, index) {
        let newEmail = prompt('編輯電子郵件:', email);
        if (newEmail !== null) {
            newEmail = newEmail.trim();
            if (!newEmail) {
                $scope.removeTag(type, index);
            } else if ($scope.isValidEmail(newEmail)) {
                if (!$scope.mailData[type].includes(newEmail) || newEmail === email) {
                    $scope.mailData[type][index] = newEmail;
                } else {
                    $scope.showMessage('此電子郵件已重複。', 'error');
                }
            } else {
                $scope.showMessage('請輸入有效的電子郵件地址。', 'error');
            }
        }
    };

    // === 寄信 API ===
    $scope.sendEmail = function() {
        // TinyMCE 空白時通常會帶有預設的段落標籤，這裡加入清除判斷
        let emptyCheck = $scope.mailData.body ? $scope.mailData.body.replace(/<[^>]*>/g, '').trim() : '';

        if (!$scope.mailData.to.length || !$scope.mailData.subject || !emptyCheck) {
            $scope.showMessage('請填寫所有必填欄位 (收件人、主旨、郵件內容)。', 'error');
            return;
        }

        let payload = {
            to: $scope.mailData.to.join(', '),
            cc: $scope.mailData.cc.join(', '),
            bcc: $scope.mailData.bcc.join(', '),
            subject: $scope.mailData.subject,
            body: $scope.mailData.body
        };

        $http.post('/send_email', payload).then(function(res) {
            if (res.data.success) {
                $scope.showMessage('郵件已成功寄送！', 'success');
                // 重置表單
                $scope.mailData = { to: [], cc: [], bcc: [], subject: '', body: '' };
                // 透過雙向綁定觸發 directive 的 $render 自動清空 TinyMCE
            } else {
                $scope.showMessage('郵件寄送失敗: ' + (res.data.message || '未知錯誤'), 'error');
            }
        }).catch(function(err) {
            $scope.showMessage('郵件寄送失敗，請檢查網路或稍後再試。', 'error');
        });
    };

    // === 模板功能 ===
    $scope.openTemplateModal = function() {
        $scope.modals.template = true;
        $http.get('/api/templates').then(function(res) {
            $scope.templates = res.data;
        }).catch(function() {
            $scope.showMessage('加載模板列表失敗。', 'error');
        });
    };

    $scope.applyTemplate = function(tpl) {
        $scope.mailData.body = tpl.html;
        $scope.mailData.subject = tpl.subject || '';
        // 已移除舊有的 Quill 剪貼簿轉換邏輯，因為 ngModel 會自動藉由 $render 同步至 TinyMCE
        $scope.modals.template = false;
        $scope.showMessage('模板已成功應用。', 'info');
    };

    $scope.saveTemplate = function() {
        let emptyCheck = $scope.mailData.body ? $scope.mailData.body.replace(/<[^>]*>/g, '').trim() : '';
        if (!emptyCheck) {
            $scope.showMessage('請先輸入郵件內容再儲存為模板。', 'error');
            return;
        }
        let templateName = prompt('請輸入模板名稱：');
        if (!templateName || templateName.trim() === '') {
            $scope.showMessage('模板名稱不能為空。', 'error');
            return;
        }

        $http.post('/api/templates', {
            name: templateName.trim(),
            subject: $scope.mailData.subject,
            html: $scope.mailData.body
        }).then(function(res) {
            if (res.data.success) {
                $scope.showMessage('模板已成功儲存！', 'success');
            } else {
                $scope.showMessage('儲存模板失敗: ' + (res.data.message || '未知錯誤'), 'error');
            }
        }).catch(function() {
            $scope.showMessage('儲存模板失敗，請檢查網路或稍後再試。', 'error');
        });
    };

    $scope.clearTemplate = function() {
        if (confirm('確定要清空當前郵件內容和主旨嗎？')) {
            $scope.mailData.body = '';
            $scope.mailData.subject = '';
            // 已移除舊有的 Quill setContents，透過雙向綁定驅動更新
            $scope.modals.template = false;
            $scope.showMessage('郵件內容和主旨已清空。', 'info');
        }
    };

    // === 群組功能 ===
    $scope.openGroupModal = function(target) {
        $scope.currentGroupTarget = target;
        $scope.modals.group = true;
        $scope.selectAllStatus = false;
        
        $http.get('/api/mailboxes').then(function(res) {
            $scope.groups = res.data.map(function(group) {
                group.emailsObj = group.emails.filter(e => e && e.trim() !== '' && e.trim().toLowerCase() !== 'on').map(e => ({
                    email: e,
                    selected: $scope.mailData[target].includes(e)
                }));
                group.selectAll = group.emailsObj.length > 0 && group.emailsObj.every(e => e.selected);
                return group;
            });
        }).catch(function() {
            $scope.showMessage('加載群組列表失敗。', 'error');
        });
    };

    $scope.toggleGroupSelectAll = function(group) {
        group.emailsObj.forEach(e => e.selected = group.selectAll);
    };

    $scope.updateGroupSelectAllStatus = function(group) {
        group.selectAll = group.emailsObj.every(e => e.selected);
    };

    $scope.toggleAllGroups = function() {
        $scope.selectAllStatus = !$scope.selectAllStatus;
        $scope.groups.forEach(group => {
            group.selectAll = $scope.selectAllStatus;
            group.emailsObj.forEach(e => e.selected = $scope.selectAllStatus);
        });
    };

    $scope.confirmGroupSelection = function() {
        let selectedEmails = [];
        $scope.groups.forEach(group => {
            group.emailsObj.forEach(e => {
                if (e.selected && !selectedEmails.includes(e.email)) {
                    selectedEmails.push(e.email);
                }
            });
        });
        
        $scope.mailData[$scope.currentGroupTarget] = selectedEmails;
        $scope.modals.group = false;
        $scope.showMessage(`已成功更新 ${selectedEmails.length} 個電子郵件。`, 'success');
    };
}]);