// static/js/hpc_usage.js
document.addEventListener('DOMContentLoaded', async function() {
    // 獲取 DOM 元素
    const settingsForm = document.getElementById('settingsForm');
    const priceThresholdInput = document.getElementById('priceThreshold');
    const checkIntervalInput = document.getElementById('checkInterval');
    const checkPeriodInput = document.getElementById('checkPeriod');
    const diffPriceThresholdInput = document.getElementById('diffPriceThreshold');
    const notifyPeriodInput = document.getElementById('notifyPeriod');
    const saveSettingsButton = document.getElementById('saveSettingsButton');
    
    const searchButton = document.getElementById('searchButton');
    const startDateInput = document.getElementById('startDate');
    const endDateInput = document.getElementById('endDate');
    const historyTableBody = document.getElementById('historyTableBody');
    const noRecordsMessage = document.getElementById('noRecordsMessage');
    const messageBox = document.getElementById('messageBox');

    // 新增分頁相關的 DOM 元素
    const paginationContainer = document.getElementById('pagination');
    const prevPageButton = document.getElementById('prevPageButton');
    const nextPageButton = document.getElementById('nextPageButton');
    const pageInfoSpan = document.getElementById('pageInfo');

    // 分頁狀態變數，讓它們能在全域範圍內被存取
    let currentPage = 1;
    const recordsPerPage = 10;
    let totalRecords = 0; // 新增：用來儲存總紀錄數

    // 初始化日期選擇器
    flatpickr(startDateInput, {});
    flatpickr(endDateInput, {});

    // 輔助函式：顯示訊息框
    function showMessage(message, type) {
        messageBox.textContent = message;
        messageBox.className = `message-box ${type}`;
        messageBox.style.display = 'block';
        setTimeout(() => {
            messageBox.style.display = 'none';
        }, 5000);
    }

    // 1. 載入並顯示目前的設定
    async function loadSettings() {
        try {
            const response = await fetch('/api/hpc-usage/settings');
            const settings = await response.json();
            if (response.ok) {
                if (settings) {
                    priceThresholdInput.value = settings.price_threshold;
                    checkIntervalInput.value = settings.check_interval;
                    diffPriceThresholdInput.value = settings.diff_price_threshold;
                    checkPeriodInput.value = settings.check_period;
                    notifyPeriodInput.value = settings.notification_cooldown_days;
                }
            } else {
                showMessage('無法載入目前設定。', 'error');
            }
        } catch (error) {
            console.error('載入設定時發生錯誤:', error);
            showMessage('載入設定時發生連線錯誤，請檢查伺服器狀態。', 'error');
        }
    }
    
    // 2. 預設顯示近一個月的歷史紀錄
    function setAndFetchDefaultHistory() {
        const today = new Date();
        const thirtyDaysAgo = new Date(today);
        thirtyDaysAgo.setDate(today.getDate() - 30);

        const formatDate = (date) => date.toISOString().split('T')[0];

        startDateInput.value = formatDate(thirtyDaysAgo);
        endDateInput.value = formatDate(today);
        
        fetchHistory(1);
    }

    // 3. 儲存設定
    saveSettingsButton.addEventListener('click', async function() {
        const price_threshold = parseFloat(priceThresholdInput.value);
        const check_interval = parseInt(checkIntervalInput.value);
        const diff_price_threshold = parseFloat(diffPriceThresholdInput.value);
        const check_period = parseInt(checkPeriodInput.value);
        const notification_cooldown_days = parseInt(notifyPeriodInput.value);

        if (isNaN(price_threshold) || isNaN(check_interval) || isNaN(check_period) || isNaN(diff_price_threshold) || isNaN(notification_cooldown_days)
            || price_threshold < 0 || check_interval <= 0 || check_period <= 0 || diff_price_threshold <= 0 || notification_cooldown_days <= 0) {
            showMessage('請輸入有效的數值。', 'error');
            return;
        }

        try {
            const response = await fetch('/api/hpc-usage/settings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ price_threshold, check_interval, diff_price_threshold, check_period, notification_cooldown_days })
            });
            const result = await response.json();

            if (response.ok && result.success) {
                showMessage(result.message, 'success');
            } else {
                showMessage('儲存設定失敗: ' + (result.message || '未知錯誤'), 'error');
            }
        } catch (error) {
            console.error('儲存設定時發生錯誤:', error);
            showMessage('儲存設定時發生連線錯誤，請檢查網路。', 'error');
        }
    });

    // 4. 查詢並顯示歷史通知紀錄 (包含分頁邏輯)
    async function fetchHistory(page) {
        const startDate = startDateInput.value;
        const endDate = endDateInput.value;
        
        const url = `/api/hpc-usage/history?start_date=${startDate}&end_date=${endDate}&page=${page}&limit=${recordsPerPage}`;

        try {
            const response = await fetch(url);
            const data = await response.json();
            const records = data.records;
            totalRecords = data.total_records; // 修正：將總紀錄數存入全域變數
            currentPage = page; // 修正：更新當前頁碼

            historyTableBody.innerHTML = '';
            if (records.length === 0) {
                noRecordsMessage.style.display = 'block';
                paginationContainer.style.display = 'none';
            } else {
                noRecordsMessage.style.display = 'none';
                paginationContainer.style.display = 'flex';
                records.forEach(record => {
                    const row = document.createElement('tr');
                    row.innerHTML = `
                        <td>${record.timestamp}</td>
                        <td>${record.users}(${record.recipients})</td>
                        <td>${record.message}</td>
                    `;
                    historyTableBody.appendChild(row);
                });
                updatePagination(); // 呼叫更新函式
            }
        } catch (error) {
            console.error('查詢歷史紀錄時發生錯誤:', error);
            showMessage('查詢歷史紀錄時發生連線錯誤。', 'error');
            noRecordsMessage.style.display = 'block';
            historyTableBody.innerHTML = '';
            paginationContainer.style.display = 'none';
        }
    }

    // 更新分頁介面狀態的函式
    function updatePagination() {
        const totalPages = Math.ceil(totalRecords / recordsPerPage);
        pageInfoSpan.textContent = `第 ${currentPage} 頁，共 ${totalPages} 頁`;
        prevPageButton.disabled = currentPage === 1;
        nextPageButton.disabled = currentPage >= totalPages;
    }

    // 新增：分頁按鈕的事件監聽器
    prevPageButton.addEventListener('click', () => {
        if (currentPage > 1) {
            fetchHistory(currentPage - 1);
        }
    });

    nextPageButton.addEventListener('click', () => {
        const totalPages = Math.ceil(totalRecords / recordsPerPage);
        if (currentPage < totalPages) {
            fetchHistory(currentPage + 1);
        }
    });

    searchButton.addEventListener('click', () => {
        fetchHistory(1); // 點擊查詢按鈕時，總是回到第一頁
    });

    // 頁面載入時自動執行
    loadSettings();
    setAndFetchDefaultHistory();
});

