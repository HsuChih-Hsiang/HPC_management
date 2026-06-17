document.addEventListener('DOMContentLoaded', () => {
    // 獲取按鈕元素
    const loginBtn = document.querySelector('.google-login-btn');
    
    if (loginBtn) {
        loginBtn.addEventListener('click', function(event) {
            // 變更按鈕樣式與文字，提供視覺回饋
            this.textContent = '準備跳轉至 Google 驗證...';
            
            // 禁用按鈕，避免使用者在跳轉過程中因網路延遲而重複點擊
            this.style.pointerEvents = 'none'; 
            this.style.opacity = '0.7';
            this.style.backgroundColor = '#999';
            this.style.cursor = 'wait';
        });
    }
});