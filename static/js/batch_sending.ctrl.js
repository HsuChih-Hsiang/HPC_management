// 這一頁的 Angular 樣板一律使用 [[ ]]，避免和 Jinja 的 {{ }} 打架
// （其餘頁面如 contact_manager / mailbox_manager 也是同樣的設定）。
app.config(['$interpolateProvider', function($interpolateProvider) {
    $interpolateProvider.startSymbol('[[');
    $interpolateProvider.endSymbol(']]');
}]);

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
    // 側邊欄狀態統一由 app.js 的 $rootScope 管理（isMenuOpen / toggleMenu / closeMenu），
    // 這裡不可再宣告同名的 $scope 屬性，否則會遮蔽掉 $rootScope 的版本，
    // 導致 sidebar.html 的遮罩點擊（closeMenu）關不掉選單。
    $scope.showBcc = false;
    
    $scope.mailData = {
        to: [],
        cc: [],
        bcc: [],
        // 「帳號新增」進來的收件人：一個元素代表一個 HPC 帳號（= 一封信），
        // 畫面上只顯示帳號名稱，展開才會看到底下的聯絡人 Email。
        accounts: [],
        subject: '',
        body: ''
    };

    $scope.inputs = { to: '', cc: '', bcc: '' };
    $scope.message = { text: '', type: '', visible: false };

    // 模態視窗狀態
    $scope.modals = { template: false, group: false, account: false };
    $scope.templates = [];
    $scope.groups = [];
    $scope.currentGroupTarget = ''; // 紀錄當前開啟群組的目標 (to, cc, bcc)
    $scope.accountResults = [];
    $scope.accountSearch = { keyword: '', loading: false };

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
    // toggleMenu 由 $rootScope 提供，此處不再覆寫
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

        // 帳號收件人：一個帳號打包成一封信送給後端
        let accountPayload = [];
        $scope.mailData.accounts.forEach(function(acc) {
            let split = splitAccountRecipients(acc);
            if (!split.to.length) return;
            accountPayload.push({ label: acc.account, to: split.to, cc: split.cc });
        });

        if ((!$scope.mailData.to.length && !accountPayload.length) || !$scope.mailData.subject || !emptyCheck) {
            $scope.showMessage('請填寫所有必填欄位 (收件人、主旨、郵件內容)。', 'error');
            return;
        }

        let payload = {
            to: $scope.mailData.to.join(', '),
            cc: $scope.mailData.cc.join(', '),
            bcc: $scope.mailData.bcc.join(', '),
            accounts: accountPayload,
            subject: $scope.mailData.subject,
            body: $scope.mailData.body
        };

        $http.post('/send_email', payload).then(function(res) {
            if (res.data.success) {
                $scope.showMessage(res.data.message || '郵件已成功寄送！', 'success');
                // 重置表單
                $scope.mailData = { to: [], cc: [], bcc: [], accounts: [], subject: '', body: '' };
                // 透過雙向綁定觸發 directive 的 $render 自動清空 TinyMCE
            } else {
                $scope.showMessage('郵件寄送失敗: ' + (res.data.message || '未知錯誤'), 'error');
            }
        }).catch(function(err) {
            // 後端在「部分收件人寄送失敗」時會回 500 並附上是哪幾封失敗，優先顯示它
            let detail = err && err.data && err.data.message;
            $scope.showMessage(detail || '郵件寄送失敗，請檢查網路或稍後再試。', 'error');
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

    // === 帳號新增功能 ===
    // 一個帳號 = 一封信，拆法如下：
    //   1. 有主要聯絡人：主要聯絡人放收件人，其餘團隊成員放副本
    //      （畫面上另外填的副本欄位，後端會再併進每一封信）
    //   2. 沒有主要聯絡人：全部放收件人，同一封信寄出即可
    //      （同一個團隊彼此看得到 Email 沒有隱私問題）
    //   3. 被設定「停止寄信」的聯絡人一律排除，且不可勾選
    function splitAccountRecipients(acc) {
        var to = [];
        var cc = [];
        var hasPrimary = false;

        (acc.members || []).forEach(function(m) {
            if (!m.selected || m.email_disabled || !m.email) return;
            if (m.is_primary && !hasPrimary) {
                hasPrimary = true;
                to.push(m.email);
            } else if (cc.indexOf(m.email) === -1 && to.indexOf(m.email) === -1) {
                cc.push(m.email);
            }
        });

        if (!hasPrimary) {
            return { to: cc, cc: [] };
        }
        return { to: to, cc: cc };
    }

    $scope.accountSelectedCount = function(acc) {
        return (acc.members || []).filter(function(m) {
            return m.selected && !m.email_disabled;
        }).length;
    };

    $scope.memberRole = function(acc, member) {
        var split = splitAccountRecipients(acc);
        return split.to.indexOf(member.email) > -1 ? '收件人' : '副本';
    };

    $scope.accountSummary = function(acc) {
        var split = splitAccountRecipients(acc);
        if (!split.to.length) {
            return '⚠ 此帳號目前沒有勾選任何聯絡人，不會寄出。';
        }
        var text = '將寄出 1 封信 → 收件人：' + split.to.join(', ');
        if (split.cc.length) {
            text += '；副本：' + split.cc.join(', ');
        }
        return text;
    };

    $scope.toggleAccountExpand = function(acc) {
        acc.expanded = !acc.expanded;
    };

    $scope.removeAccount = function(index) {
        $scope.mailData.accounts.splice(index, 1);
    };

    // 明細裡把成員勾選狀態改掉後，同步更新「整個帳號」的全選勾勾（搜尋視窗用）
    $scope.onAccountMemberToggle = function(acc) {
        var selectable = (acc.members || []).filter(function(m) { return !m.email_disabled; });
        acc.selected = selectable.length > 0 && selectable.every(function(m) { return m.selected; });
    };

    $scope.toggleAccountSelectAll = function(acc) {
        (acc.members || []).forEach(function(m) {
            m.selected = acc.selected && !m.email_disabled;
        });
    };

    // 搜尋視窗開著的期間，所有「看過／勾過」的帳號都記在這裡（key = contact_id）。
    // 搜尋會重打 API 換掉 accountResults，靠這份紀錄才不會把先前的勾選弄丟。
    var accountSelection = {};

    function rememberedMemberSelection(acc) {
        var map = {};
        (acc.members || []).forEach(function(m) {
            map[m.id] = !!m.selected;
        });
        return map;
    }

    $scope.openAccountModal = function() {
        // 用複本作業，按「取消」就不會動到已經加進收件人的帳號
        accountSelection = {};
        $scope.mailData.accounts.forEach(function(acc) {
            accountSelection[acc.contact_id] = angular.copy(acc);
        });

        $scope.modals.account = true;
        $scope.accountSearch.keyword = '';
        $scope.fetchAccounts();
    };

    var accountSearchTimer = null;
    $scope.onAccountSearchChange = function() {
        if (accountSearchTimer) $timeout.cancel(accountSearchTimer);
        accountSearchTimer = $timeout($scope.fetchAccounts, 300);
    };

    var accountFetchToken = 0;
    $scope.fetchAccounts = function() {
        var keyword = ($scope.accountSearch.keyword || '').trim();
        var token = ++accountFetchToken;   // 連續搜尋時，只認最後一次送出的請求
        $scope.accountSearch.loading = true;
        $http.get('/api/contacts/mail-accounts', {
            params: { search: $scope.accountSearch.keyword || '' }
        }).then(function(res) {
            if (token !== accountFetchToken) return;
            var list = (res.data || []).map(function(acc) {
                // 這個帳號之前勾過（或已經在收件人裡）就把勾選帶回來
                var remembered = accountSelection[acc.contact_id];
                var prev = remembered ? rememberedMemberSelection(remembered) : null;

                acc.members.forEach(function(m) {
                    if (m.email_disabled) {
                        m.selected = false;
                    } else if (prev) {
                        m.selected = !!prev[m.id];
                    } else {
                        m.selected = false;
                    }
                });
                acc.selected = false;
                $scope.onAccountMemberToggle(acc);
                // 存的是畫面上這個物件本身，之後使用者改勾選會直接同步進來
                accountSelection[acc.contact_id] = acc;
                return acc;
            });

            if (!keyword) {
                // 搜尋欄清空時：已勾選的帳號排到最前面，
                // 連同這次結果沒回傳到（例如超過筆數上限）的也一起補在最上面
                var inList = {};
                list.forEach(function(acc) { inList[acc.contact_id] = true; });

                var pinned = [];
                Object.keys(accountSelection).forEach(function(key) {
                    var acc = accountSelection[key];
                    if (!inList[acc.contact_id] && $scope.accountSelectedCount(acc) > 0) {
                        pinned.push(acc);
                    }
                });

                var selected = list.filter(function(acc) { return $scope.accountSelectedCount(acc) > 0; });
                var others = list.filter(function(acc) { return $scope.accountSelectedCount(acc) === 0; });
                list = pinned.concat(selected, others);
            }

            $scope.accountResults = list;
            $scope.accountSearch.loading = false;
        }).catch(function() {
            if (token !== accountFetchToken) return;
            $scope.accountSearch.loading = false;
            $scope.accountResults = [];
            $scope.showMessage('搜尋帳號失敗，請稍後再試。', 'error');
        });
    };

    $scope.confirmAccountSelection = function() {
        var added = 0;

        // 走過這次開窗期間看過的所有帳號，不只是目前搜尋結果，
        // 這樣先勾好、再換關鍵字搜尋的帳號也會被加進去
        Object.keys(accountSelection).map(function(key) {
            return accountSelection[key];
        }).forEach(function(acc) {
            var chosen = (acc.members || []).filter(function(m) {
                return m.selected && !m.email_disabled;
            });

            var existingIndex = -1;
            $scope.mailData.accounts.forEach(function(a, i) {
                if (a.contact_id === acc.contact_id) existingIndex = i;
            });

            if (!chosen.length) {
                // 這次沒勾任何人 → 視為把這個帳號移除
                if (existingIndex > -1) $scope.mailData.accounts.splice(existingIndex, 1);
                return;
            }

            var entry = {
                contact_id: acc.contact_id,
                account: acc.account,
                account_type: acc.account_type,
                team_name: acc.team_name,
                applicant: acc.applicant,
                members: acc.members.map(function(m) {
                    return angular.extend({}, m);
                }),
                expanded: false
            };

            if (existingIndex > -1) {
                entry.expanded = $scope.mailData.accounts[existingIndex].expanded;
                $scope.mailData.accounts[existingIndex] = entry;
            } else {
                $scope.mailData.accounts.push(entry);
                added++;
            }
        });

        $scope.modals.account = false;
        $scope.showMessage('已更新帳號收件人（新增 ' + added + ' 個帳號，目前共 ' +
            $scope.mailData.accounts.length + ' 個）。', 'success');
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