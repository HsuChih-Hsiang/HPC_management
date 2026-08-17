// static/js/setting.ctrl.js

// 獲取在 app.js 中已經定義好的 emailApp 主模組（注意：不要加第二個參數 []）
var app = angular.module('emailApp');

// 配置該頁面的插值符號為 [[ ]]，防止與 Flask Jinja2 的 {{ }} 衝突
app.config(['$interpolateProvider', function($interpolateProvider) {
    $interpolateProvider.startSymbol('[[');
    $interpolateProvider.endSymbol(']]');
}]);

app.controller('SettingController', ['$scope', '$http', '$timeout', function($scope, $http, $timeout) {

    // ==========================================
    // 1. 初始化狀態
    // ==========================================
    $scope.message = { text: '', type: '', visible: false };
    $scope.saving = false;
    $scope.smtp = {
        smtp_server: '',
        smtp_port: null,
        sender_email: '',
        password: '',
        has_password: false
    };

    var publicKeyPem = null;

    function showMessage(text, type) {
        $scope.message.text = text;
        $scope.message.type = type;
        $scope.message.visible = true;
        $timeout(function() {
            $scope.message.visible = false;
        }, 5000);
    }

    // ==========================================
    // 2. RSA 加密（使用瀏覽器內建的 Web Crypto API）
    //
    // 後端 decrypt_frontend_data() 使用的是
    //   padding.OAEP(mgf=MGF1(SHA256), algorithm=SHA256)
    // 因此這裡必須對應 RSA-OAEP + SHA-256，兩邊參數不一致會解不開。
    //
    // 注意：window.crypto.subtle 只在安全環境 (https 或 localhost) 下可用，
    // 若正式機以純 http 對外提供服務，此處會取不到而無法加密。
    // ==========================================
    function pemToArrayBuffer(pem) {
        var base64 = pem
            .replace(/-----BEGIN PUBLIC KEY-----/, '')
            .replace(/-----END PUBLIC KEY-----/, '')
            .replace(/\s+/g, '');
        var binary = window.atob(base64);
        var bytes = new Uint8Array(binary.length);
        for (var i = 0; i < binary.length; i++) {
            bytes[i] = binary.charCodeAt(i);
        }
        return bytes.buffer;
    }

    function arrayBufferToBase64(buffer) {
        var bytes = new Uint8Array(buffer);
        var binary = '';
        for (var i = 0; i < bytes.length; i++) {
            binary += String.fromCharCode(bytes[i]);
        }
        return window.btoa(binary);
    }

    function encryptPassword(plainPassword) {
        if (!window.crypto || !window.crypto.subtle) {
            return Promise.reject(new Error('瀏覽器不支援加密功能，或目前並非透過 https / localhost 連線。'));
        }

        return window.crypto.subtle.importKey(
            'spki',
            pemToArrayBuffer(publicKeyPem),
            { name: 'RSA-OAEP', hash: 'SHA-256' },
            false,
            ['encrypt']
        ).then(function(key) {
            return window.crypto.subtle.encrypt(
                { name: 'RSA-OAEP' },
                key,
                new TextEncoder().encode(plainPassword)
            );
        }).then(arrayBufferToBase64);
    }

    // ==========================================
    // 3. API 串接
    // ==========================================
    function loadPublicKey() {
        return $http.get('/api/auth/public-key').then(function(response) {
            publicKeyPem = response.data && response.data.public_key;
        }, function(error) {
            console.error('取得公鑰失敗:', error);
            showMessage('無法取得加密金鑰，將無法儲存密碼。', 'error');
        });
    }

    function loadSmtpSetting() {
        return $http.get('/api/setting/smtp').then(function(response) {
            var data = response.data || {};
            $scope.smtp.smtp_server = data.smtp_server || '';
            // 後端可能回傳字串，轉成數字 input 才會正確帶值
            $scope.smtp.smtp_port = data.smtp_port ? parseInt(data.smtp_port, 10) : null;
            $scope.smtp.sender_email = data.sender_email || '';
            $scope.smtp.has_password = !!data.has_password;
        }, function(error) {
            console.error('載入發信設定失敗:', error);
            showMessage('無法載入目前的發信設定。', 'error');
        });
    }

    $scope.saveSmtp = function() {
        var smtpServer = ($scope.smtp.smtp_server || '').trim();
        var smtpPort = $scope.smtp.smtp_port;
        var senderEmail = ($scope.smtp.sender_email || '').trim();
        var password = $scope.smtp.password || '';

        if (!smtpServer) {
            showMessage('請輸入郵件主機位址。', 'error');
            return;
        }

        if (!smtpPort) {
            showMessage('請輸入連接埠。', 'error');
            return;
        }

        if (smtpPort < 1 || smtpPort > 65535) {
            showMessage('連接埠必須介於 1 到 65535 之間。', 'error');
            return;
        }

        if (!senderEmail) {
            showMessage('請輸入發信帳號。', 'error');
            return;
        }

        // 從未設定過密碼時，第一次儲存一定要填密碼
        if (!password && !$scope.smtp.has_password) {
            showMessage('請輸入發信密碼。', 'error');
            return;
        }

        $scope.saving = true;

        var basePayload = {
            smtp_server: smtpServer,
            smtp_port: smtpPort,
            sender_email: senderEmail
        };

        // 密碼留空 = 沿用原本已儲存的密碼，不需要重新加密送出
        var payloadPromise = password
            ? encryptPassword(password).then(function(encrypted) {
                  return angular.extend({}, basePayload, { encrypted_password: encrypted });
              })
            : Promise.resolve(basePayload);

        payloadPromise.then(function(payload) {
            return $http.post('/api/setting/smtp', payload);
        }).then(function(response) {
            var result = (response && response.data) || {};
            if (result.success) {
                showMessage(result.message || '發信設定已儲存。', 'success');
                $scope.smtp.password = '';
                $scope.smtp.has_password = true;
            } else {
                showMessage('儲存失敗: ' + (result.message || '未知錯誤'), 'error');
            }
        }).catch(function(error) {
            console.error('儲存發信設定失敗:', error);
            var data = (error && error.data) || {};
            showMessage('儲存失敗：' + (data.message || error.message || '請檢查網路或稍後再試'), 'error');
        }).finally(function() {
            $scope.saving = false;
            // Web Crypto 的 Promise 不在 Angular 的 digest 週期內，需手動觸發畫面更新
            $scope.$applyAsync();
        });
    };

    // ==========================================
    // 4. 頁面初始化進入點
    // ==========================================
    loadPublicKey();
    loadSmtpSetting();
}]);
