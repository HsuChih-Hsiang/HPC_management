<script src="https://cdnjs.cloudflare.com/ajax/libs/jsencrypt/3.3.2/jsencrypt.min.js"></script>

// 假設這是您的儲存 SMTP 設定的 function
$scope.saveSmtpConfig = function(smtpPassword) {
    // 1. 先向後端拿最新的 RSA 公鑰
    $http.get('/api/auth/public-key').then(function(response) {
        const publicKey = response.data.public_key;

        // 2. 初始化加密器並放入公鑰
        const encryptor = new JSEncrypt();
        encryptor.setPublicKey(publicKey);

        // 3. 對敏感資料（例如密碼或整個 JSON）進行加密
        // 注意：Web Crypto API / JSEncrypt 預設通常使用 SHA1 或 SHA256，需與後端對齊
        // 這裡我們直接加密密碼字串
        const encryptedPassword = encryptor.encrypt(smtpPassword);

        // 4. 把加密後的密文傳給後端
        const payload = {
            smtp_user: $scope.smtpUser,
            encrypted_password: encryptedPassword // 這串在網路上是亂碼
        };

        $http.post('/api/user/save-smtp', payload).then(function(res) {
            alert('儲存成功！');
        });
    });
};