// static/js/permission.ctrl.js
var app = angular.module('emailApp');

app.controller('PermissionController', ['$scope', '$http', '$timeout', function($scope, $http, $timeout) {

    // ==========================================
    // 1. 初始化狀態
    // ==========================================
    $scope.message = { text: '', type: '', visible: false };
    $scope.loading = true;
    $scope.saving = false;

    $scope.features = [];
    $scope.groups = [];
    $scope.users = [];
    $scope.pendingUsers = [];

    $scope.groupModalOpen = false;
    $scope.groupForm = { id: null, name: '', description: '', is_system: false, features: [] };

    // 群組卡片顯示用：由功能代碼取得「圖示 + 名稱」
    $scope.featureLabel = function(key) {
        for (var i = 0; i < $scope.features.length; i++) {
            if ($scope.features[i].key === key) {
                return $scope.features[i].icon + ' ' + $scope.features[i].label;
            }
        }
        return key;
    };

    function showMessage(text, type) {
        $scope.message.text = text;
        $scope.message.type = type;
        $scope.message.visible = true;
        $timeout(function() { $scope.message.visible = false; }, 5000);
    }

    function errorMessage(error, fallback) {
        var data = (error && error.data) || {};
        showMessage(data.message || fallback, 'error');
    }

    // ==========================================
    // 2. 載入資料
    // ==========================================
    function loadFeatures() {
        return $http.get('/api/permission/features').then(function(res) {
            $scope.features = (res.data && res.data.features) || [];
        });
    }

    function loadGroups() {
        return $http.get('/api/permission/groups').then(function(res) {
            $scope.groups = (res.data && res.data.groups) || [];
        });
    }

    function loadUsers() {
        return $http.get('/api/permission/users').then(function(res) {
            var data = res.data || {};
            $scope.users = data.users || [];
            $scope.pendingUsers = data.pending_users || [];

            // 下拉選單的初始值：目前所屬群組
            $scope.users.forEach(function(u) { u._selectedGroupId = u.group_id; });
            // 待開通清單預設帶入第一個群組，讓管理員可以直接按「開通」
            $scope.pendingUsers.forEach(function(u) {
                u._selectedGroupId = $scope.groups.length ? $scope.groups[0].id : null;
            });
        });
    }

    function reloadAll() {
        $scope.loading = true;
        return loadGroups()
            .then(loadUsers)
            .catch(function(error) { errorMessage(error, '載入資料失敗。'); })
            .finally(function() { $scope.loading = false; });
    }

    // ==========================================
    // 3. 帳號群組指派
    // ==========================================
    $scope.assignGroup = function(user) {
        var groupId = user._selectedGroupId;

        $http.put('/api/permission/users/' + user.id + '/group', { group_id: groupId || null })
            .then(function(res) {
                var result = res.data || {};
                if (result.success) {
                    showMessage(result.message, 'success');
                    reloadAll();
                } else {
                    showMessage(result.message || '指派失敗。', 'error');
                }
            }, function(error) {
                errorMessage(error, '指派群組失敗。');
                // 失敗時把下拉選單復原成實際值，避免畫面與後端不一致
                user._selectedGroupId = user.group_id;
            });
    };

    // ==========================================
    // 4. 群組維護
    // ==========================================
    /**
     * 組出 modal 內的功能清單。
     * 已授權的功能依群組儲存的順序排在前面，未授權的接在後面，
     * 這樣使用者勾選新功能時它會出現在清單末端，順序直觀可預期。
     */
    function buildFeatureRows(selectedKeys) {
        var rows = [];
        var used = {};

        (selectedKeys || []).forEach(function(key) {
            for (var i = 0; i < $scope.features.length; i++) {
                if ($scope.features[i].key === key) {
                    rows.push(angular.extend({}, $scope.features[i], { checked: true }));
                    used[key] = true;
                    break;
                }
            }
        });

        $scope.features.forEach(function(f) {
            if (!used[f.key]) {
                rows.push(angular.extend({}, f, { checked: false }));
            }
        });

        return rows;
    }

    $scope.openGroupModal = function(group) {
        $scope.groupModalOpen = true;

        if (group) {
            $scope.groupForm = {
                id: group.id,
                name: group.name,
                description: group.description,
                is_system: group.is_system,
                features: buildFeatureRows(group.features)
            };
        } else {
            $scope.groupForm = {
                id: null, name: '', description: '', is_system: false,
                features: buildFeatureRows([])
            };
        }
    };

    // 以 ▲▼ 調整順序；陣列順序即側邊欄順序
    $scope.moveFeature = function(index, delta) {
        var list = $scope.groupForm.features;
        var target = index + delta;
        if (target < 0 || target >= list.length) return;

        var moved = list.splice(index, 1)[0];
        list.splice(target, 0, moved);
    };

    $scope.closeGroupModal = function() {
        $scope.groupModalOpen = false;
    };

    $scope.onGroupModalBackdrop = function($event) {
        if ($event.target && $event.target.id === 'groupModal') {
            $scope.closeGroupModal();
        }
    };

    // 依畫面上的排列順序回傳已勾選的功能代碼（順序即 sort_order）
    function collectSelectedFeatures() {
        return ($scope.groupForm.features || [])
            .filter(function(f) { return f.checked; })
            .map(function(f) { return f.key; });
    }

    $scope.saveGroup = function() {
        var name = ($scope.groupForm.name || '').trim();
        if (!name) {
            showMessage('請輸入群組名稱。', 'error');
            return;
        }

        var payload = {
            name: name,
            description: ($scope.groupForm.description || '').trim(),
            features: collectSelectedFeatures()
        };

        $scope.saving = true;

        var request = $scope.groupForm.id
            ? $http.put('/api/permission/groups/' + $scope.groupForm.id, payload)
            : $http.post('/api/permission/groups', payload);

        request.then(function(res) {
            var result = res.data || {};
            if (result.success) {
                showMessage(result.message, 'success');
                $scope.closeGroupModal();
                reloadAll();
            } else {
                showMessage(result.message || '儲存失敗。', 'error');
            }
        }, function(error) {
            errorMessage(error, '儲存群組失敗。');
        }).finally(function() {
            $scope.saving = false;
        });
    };

    $scope.deleteGroup = function(group) {
        if (!confirm('確定要刪除群組「' + group.name + '」嗎？')) return;

        $http.delete('/api/permission/groups/' + group.id)
            .then(function(res) {
                var result = res.data || {};
                if (result.success) {
                    showMessage(result.message, 'success');
                    reloadAll();
                } else {
                    showMessage(result.message || '刪除失敗。', 'error');
                }
            }, function(error) {
                errorMessage(error, '刪除群組失敗。');
            });
    };

    // ==========================================
    // 5. 頁面初始化進入點
    // ==========================================
    loadFeatures()
        .then(reloadAll)
        .catch(function(error) {
            errorMessage(error, '初始化失敗。');
            $scope.loading = false;
        });
}]);
