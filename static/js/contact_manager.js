// 全域變數
let currentPage = 1;

/**
 * 初始化：確保所有 DOM 元素載入後才綁定事件
 */
document.addEventListener('DOMContentLoaded', function() {
    initYearFilter();      // 初始化年份下拉選單
    fetchAndRenderHosts(); // 動態載入主機清單
    loadData(1);           // 初始載入表格資料
    initAutocomplete();    // 初始化正式帳號搜尋功能
});

/// 2. 全域點擊事件：點擊彈窗外部背景關閉介面
window.onclick = function(event) {
    const contactModal = document.getElementById('contactModal');
    const detailModal = document.getElementById('detailViewModal');
    const quotaModal = document.getElementById('quotaEditorModal');
    const resultsDiv = document.getElementById('search-results');
    const accountInput = document.getElementById('account_search');

    // 點擊新增/修改彈窗背景遮罩層
    if (event.target === contactModal) {
        closeModal(); // 這裡會自動觸發上面改好的 confirm 通知
    }
    if (event.target === detailModal) {
        closeDetailModal(); // 詳細資訊通常是唯讀的，若需要防呆也可以比照辦理
    }
    if (event.target === quotaModal) {
        closeQuotaModal();
    }

    // 點擊搜尋清單以外區域則隱藏搜尋建議
    if (resultsDiv && event.target !== accountInput && !resultsDiv.contains(event.target)) {
        resultsDiv.style.display = 'none';
    }
};

// 切換選單顯示/隱藏
function toggleFilterMenu(event) {
    event.stopPropagation(); // 防止事件冒泡觸啟動其他的點擊事件
    const menu = document.getElementById('filterDropdown');
    menu.classList.toggle('show');
}

// 點擊頁面其他地方時，自動關閉選單
window.addEventListener('click', function(event) {
    const menu = document.getElementById('filterDropdown');
    const btn = document.querySelector('.btn-filter-dropdown');
    
    if (menu && !menu.contains(event.target) && event.target !== btn) {
        menu.classList.remove('show');
    }
});

/**
 * 核心功能：載入列表資料
 */
async function loadData(page = 1) {
    currentPage = page;
    const searchInput = document.getElementById('searchInput');
    const search = searchInput ? searchInput.value : '';
    const yearFilter = document.getElementById('yearFilter');
    const year = yearFilter ? yearFilter.value : '';
    const isCourse = document.getElementById('filterCourse').checked;
    const isFormal = document.getElementById('filterFormal').checked;
    const isTrial = document.getElementById('filterTrial').checked;
    
    try {
        // 建議後端 API 支援 year 參數
        const res = await fetch(`/api/contacts?page=${page}&search=${encodeURIComponent(search)}&year=${year}&is_course=${isCourse}&is_formal=${isFormal}&is_trial=${isTrial}`);
        const data = await res.json();
        
        const tbody = document.getElementById('contactTableBody');
        if (tbody) {
            tbody.innerHTML = data.records.map(r => {
                // ★ 1. 判斷是否為試用帳號：沒有正式帳號且有試用帳號
                const isTrialAccount = !r.formal_account && r.trial_account;
                // ★ 2. 判斷是否為課程帳號
                const isCourseAccount = r.is_course_account === true;
                // ★ 3. 課程或試用帳號皆不允許操作額度
                const isQuotaDisabled = isCourseAccount || isTrialAccount;
                
                return `
                <tr>
                    <td class="col-team">${r.team_name}<br><small>${r.dept_level1 || ''}</small></td>
                    <td class="col-name">${r.applicant.replace(',', ',<br>')}</td>
                    <td class="col-trail-acc">${r.trial_account || ''}</td>
                    <td class="col-trail-acc-password">${(r.trail_account_password || '').replace(',', ',<br>')}</td>
                    <td class="col-acc">${r.formal_account || ''}</td>
                    <td class="col-host">${(r.hosts || []).map(h => `<span class="badge">${h}</span>`).join(', ')}</td>
                    <td class="col-date">apply: ${r.apply_date || ''}<br>deadline: ${r.test_deadline || ''}</td>
                    
                    <td class="col-other-data">
                        <button class="btn-more" 
                            data-research="${r.research_content || ''}" 
                            data-software="${r.used_software || ''}" 
                            data-calc="${r.calc_resource || ''}" 
                            data-notes="${r.notes || ''}" 
                            onclick="showInfoFromData(this)">...</button>
                    </td>

                    <td class="col-quota-discount">
                        <div>${isQuotaDisabled ? '-' : (r.discount_remaining || 0)}</div>
                    </td>

                    <td class="col-quota-total">
                        <span>${isQuotaDisabled ? '-' : (r.total_remaining || 0)}</span>
                        <div class="quota-popover">明細內容預留位置</div>
                    </td>

                    <td class="col-action">
                        <div class="action-buttons">
                            <button onclick="editItem(${r.id})" class="text-button">編輯</button>
                            <button onclick="handleQuotaButtonClick(event, ${r.id}, '${r.applicant}', ${isCourseAccount}, ${isTrialAccount})" 
                                    class="text-button btn-quota" 
                                    ${isQuotaDisabled ? 'disabled style="color: #cbd5e0; cursor: not-allowed;" title="課程帳號與試用帳號無法操作額度"' : ''}>
                                額度
                            </button>
                            <button onclick="deleteItem(${r.id})" class="text-button btn-delete">刪除</button>
                        </div>
                    </td>
                </tr>
            `}).join('');
        }
        renderPagination(data.total_pages, data.current_page);
    } catch (err) {
        console.error("載入資料失敗:", err);
    }
}

/**
 * 核心功能：儲存表單 (新增或修改)
 */
const contactForm = document.getElementById('contactForm');
if (contactForm) {
    contactForm.onsubmit = async (e) => {
        e.preventDefault();

        const editId = document.getElementById('editId').value;
        const method = editId ? 'PUT' : 'POST';
        const url = editId ? `/api/contacts/${editId}` : '/api/contacts';

        const getVal = (id) => {
            const el = document.getElementById(id);
            return el ? el.value.trim() : '';
        };

        try {
            // --- 帳號邏輯處理 ---
            const formalId = getVal('formal_account_id');
            const formalText = getVal('account_search');
            
            // 優先傳 ID，若無 ID 則傳手動輸入的文字
            const finalFormalAccount = formalId ? formalId : formalText;

            const payload = {
                team_name: getVal('team_name'),
                dept_level1: getVal('dept_level1'),
                applicant: getVal('applicant'),
                apply_date: getVal('apply_date'),
                
                // 這裡發送給後端：可能是 ID (int) 或 帳號名稱 (string)
                formal_account: finalFormalAccount || null,
                
                trial_account: getVal('trial_account'),
                trail_account_password: getVal('trail_account_password'),
                test_deadline: getVal('test_deadline'),
                research_content: getVal('research_content'),
                used_software: getVal('used_software'),
                calc_resource: getVal('calc_resource'),
                notes: getVal('notes'),
                hosts: Array.from(document.querySelectorAll('input[name="hosts"]:checked')).map(c => c.value),
                secondary_contacts: Array.from(document.querySelectorAll('.contact-row')).map(row => {
                    const inputs = row.querySelectorAll('input');
                    return { name: inputs[0]?.value || '', info: inputs[1]?.value || '' };
                }),
                is_course_account: document.getElementById('is_course_account').checked,
                course_students: getCourseData()
            };

            const response = await fetch(url, {
                method: method,
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });

            if (response.ok) {
                alert(editId ? '修改成功！' : '新增成功！');
                
                // 繞過 confirm，直接強制隱藏彈窗
                const modal = document.getElementById('contactModal');
                if (modal) modal.style.display = 'none';
                
                loadData(currentPage);
            } else {
                alert("儲存失敗");
            }
        } catch (err) {
            console.error("執行出錯:", err);
            alert("前端程式錯誤");
        }
    };
}

/**
 * 正式帳號自動完成搜尋邏輯
 */
function initAutocomplete() {
    const accountInput = document.getElementById('account_search');
    const resultsDiv = document.getElementById('search-results');
    const hiddenIdInput = document.getElementById('formal_account_id');

    if (!accountInput || !resultsDiv) return;

    accountInput.addEventListener('input', async function() {
        const val = this.value.trim();
        
        // 重要：一旦使用者開始打字，先清空隱藏的 ID
        // 這樣如果使用者最後沒點選建議清單，後端就會收到這串「純文字」
        if (hiddenIdInput) hiddenIdInput.value = ''; 

        if (val.length < 1) {
            resultsDiv.style.display = 'none';
            return;
        }

        try {
            const response = await fetch(`/api/hpc-usage/search_users?q=${encodeURIComponent(val)}`);
            const users = await response.json();

            if (users.length > 0) {
                resultsDiv.innerHTML = users.map(user => `
                    <div class="autocomplete-item" onclick="selectUser(${user.id}, '${user.username}')">
                        <span><strong>${user.username}</strong></span>
                    </div>
                `).join('');
                resultsDiv.style.display = 'block';
            } else {
                resultsDiv.style.display = 'none';
            }
        } catch (err) {
            console.error("搜尋失敗:", err);
        }
    });
}

/**
 * 選取使用者的處理函式 (必須定義在全域，讓 onclick 抓得到)
 * @param {number} id 使用者的資料庫 ID
 * @param {string} username 使用者的帳號名稱
 */
function selectUser(id, username) {
    const accountInput = document.getElementById('account_search');
    const resultsDiv = document.getElementById('search-results');
    const hiddenIdInput = document.getElementById('formal_account_id');

    // 1. 將帳號名稱顯示在搜尋框
    if (accountInput) accountInput.value = username;

    // 2. 將真正的使用者 ID 存入隱藏欄位，供儲存 API 使用
    if (hiddenIdInput) {
        hiddenIdInput.value = id;
        console.log("選取的使用者 ID:", id); // 除錯用
    }

    // 3. 隱藏搜尋結果清單
    if (resultsDiv) resultsDiv.style.display = 'none';
}

/**
 * 彈窗控制邏輯
 */
function openModal() {
    const modal = document.getElementById('contactModal');
    const form = document.getElementById('contactForm');
    
    // 1. 重置表單與清空隱藏的 ID
    if (form) form.reset();
    document.getElementById('editId').value = ''; 
    
    // 2. 恢復標題
    document.getElementById('modalTitle').innerText = '新增聯絡人';
    
    // 3. 重置所有隱藏與細項欄位
    document.getElementById('formal_account_id').value = '';
    document.getElementById('research_content').value = '';
    document.getElementById('used_software').value = '';
    document.getElementById('calc_resource').value = '';
    document.getElementById('notes').value = '';
    
    // 4. [關鍵修正] 重置主機選擇區：傳入兩個空陣列，確保「全不勾選」
    if (typeof renderHostInterface === 'function') {
        renderHostInterface([], []); 
    }

    // 5. 重置動態聯絡人
    const container = document.getElementById('other-contacts-container');
    if (container) container.innerHTML = '';

    // 6. 重置課程帳號區塊 (將檔案末尾的邏輯移至此處)
    const courseCheckbox = document.getElementById('is_course_account');
    if (courseCheckbox) courseCheckbox.checked = false;
    const courseSection = document.getElementById('courseAccountSection');
    if (courseSection) courseSection.style.display = 'none';
    const courseBody = document.getElementById('courseAccountBody');
    if (courseBody) courseBody.innerHTML = '';

    // 7. 顯示彈窗
    if (modal) {
        modal.style.display = 'block';
        modal.scrollTop = 0;
    }
}

function closeModal() {
    const modal = document.getElementById('contactModal');
    if (modal) {
        if (confirm('確定要關閉視窗嗎？未儲存的變更將會遺失。')) {
            modal.style.display = 'none';
        }
    }
}

async function editItem(id) {
    try {
        // 1. 從 API 取得資料
        const res = await fetch(`/api/contacts/${id}`);
        if (!res.ok) throw new Error('無法取得資料');
        const data = await res.json();
        
        // 2. 只有資料成功取得後，才呼叫 openModal() 重置並打開介面
        openModal(); 

        // 3. 修改介面標題與暗中存下 ID
        document.getElementById('modalTitle').innerText = '修改聯絡人資料';
        document.getElementById('editId').value = data.id;

        // 4. 回填基本欄位
        const fields = [
            'team_name', 'dept_level1', 'applicant', 'apply_date', 
            'trial_account', 'trail_account_password', 'test_deadline', 
            'research_content', 'used_software', 'calc_resource', 'notes',
        ];
        
        fields.forEach(field => {
            const el = document.getElementById(field);
            if (el) el.value = data[field] || '';
        });

        // 5. 回填正式帳號搜尋框與隱藏 ID
        document.getElementById('account_search').value = data.formal_account || ''; 
        document.getElementById('formal_account_id').value = data.user_id || '';

        // --- 6. [核心修正] 回填主機勾選 (含自定義主機) ---
        // 呼叫我們先前定義的 render 函數，並傳入該筆資料的 hosts。
        // 這會確保：標準主機被渲染 + 這筆資料獨有的自定義主機也被渲染。
        if (typeof renderHostInterface === "function") {
            renderHostInterface(data.hosts || []);
        } else {
            // 備援方案：如果沒有 render 函數，則僅對現有 checkbox 進行勾選
            const hostCheckboxes = document.querySelectorAll('input[name="hosts"]');
            const activeHosts = data.hosts || [];
            hostCheckboxes.forEach(cb => {
                cb.checked = activeHosts.includes(cb.value);
            });
        }

        // 7. 回填動態聯絡人區塊
        const container = document.getElementById('other-contacts-container');
        if (container) {
            container.innerHTML = ''; 
            console.log("收到的次要聯絡人資料:", data.secondary_contacts);

            if (data.secondary_contacts && data.secondary_contacts.length > 0) {
                data.secondary_contacts.forEach(sc => {
                    // 確保 sc.name 與 sc.info 存在
                    addContactRow(sc.name || '', sc.info || '');
                });
            } else {
                console.warn("沒有次要聯絡人資料或格式錯誤");
            }
        }

        // 8. 處理「是否為課程帳號」勾選框與區塊顯示
        const isCourse = data.is_course_account || false;
        const courseCheckbox = document.getElementById('is_course_account');
        const courseSection = document.getElementById('courseAccountSection');
        
        if (courseCheckbox) {
            courseCheckbox.checked = isCourse;
        }
        if (courseSection) {
            courseSection.style.display = isCourse ? 'block' : 'none';
        }

        // 9. 回填學生帳號清單表格
        const courseBody = document.getElementById('courseAccountBody');
        if (courseBody) {
            courseBody.innerHTML = ''; 
            
            if (isCourse && data.course_students && data.course_students.length > 0) {
                data.course_students.forEach(cs => {
                    // 確保欄位名稱與後端 match
                    if (typeof addCourseRow === "function") {
                        addCourseRow(cs.account || '', cs.password || ''); 
                    }
                });
            }
        }

    } catch (err) {
        console.error("讀取編輯資料失敗:", err);
        alert("讀取資料失敗，請檢查網路或後端服務");
    }
}

/**
 * 其他輔助功能 (年份、主機、刪除)
 */
function addContactRow(name = '', info = '') {
    const container = document.getElementById('other-contacts-container');
    if (!container) return;
    const row = document.createElement('div');
    row.className = 'contact-row'; 
    row.innerHTML = `
        <input type="text" value="${name}" placeholder="姓名">
        <input type="text" value="${info}" placeholder="聯絡資訊">
        <button type="button" class="btn-remove-row" onclick="this.parentElement.remove()">✕</button>
    `;
    container.appendChild(row);
}

async function initYearFilter() {
    const yearSelect = document.getElementById('yearFilter');
    if (!yearSelect) return;
    try {
        const response = await fetch('/api/contacts/years');
        if (!response.ok) throw new Error('無法取得年份資料');
        
        const years = await response.json();
        let html = '<option value="">所有年份</option>';
        years.forEach(year => {
            html += `<option value="${year}">${year} 年</option>`;
        });
        
        yearSelect.innerHTML = html;
    } catch (error) {
        console.error('初始化年份失敗:', error);
        const currentYear = new Date().getFullYear();
        yearSelect.innerHTML = `<option value="">所有年份</option><option value="${currentYear}">${currentYear} 年</option>`;
    }
}

// 頁面載入時執行一次即可
document.addEventListener('DOMContentLoaded', initYearFilter);

let standardServers = []; // 儲存從 API 抓到的標準清單

async function fetchAndRenderHosts() {
    const hostContainer = document.getElementById('hostContainer');
    if (!hostContainer) return;
    
    try {
        const res = await fetch('/api/hpc-usage/serverlist');
        const servers = await res.json();
        // 取得標準清單
        standardServers = [...new Set(servers.map(s => s.server))].filter(Boolean);
        
        // 關鍵修正：初始渲染傳入空陣列，這樣就不會預設打勾了
        renderHostInterface([], []); 
    } catch (err) { 
        console.error("主機載入失敗", err); 
        hostContainer.innerHTML = '<span style="color: red;">載入失敗</span>';
    }
}

function renderHostInterface(savedHosts = [], optionsToInclude = []) {
    const hostContainer = document.getElementById('hostContainer');
    if (!hostContainer) return;

    // 1. 取得目前畫面上的勾選狀態
    // 增加判斷：如果 savedHosts 為空且 optionsToInclude 也為空 (代表是 openModal 觸發的初始重置)
    // 則強制不抓取現有狀態，避免抓到舊資料。
    let currentChecked = [];
    if (savedHosts.length > 0 || optionsToInclude.length > 0) {
        currentChecked = Array.from(hostContainer.querySelectorAll('input[name="hosts"]:checked'))
                              .map(c => c.value);
    }

    // 2. 建立勾選白名單
    const mustBeChecked = new Set([...savedHosts, ...optionsToInclude, ...currentChecked]);

    // 3. 顯示清單：標準清單 + 目前被勾選的自定義項目
    const displayList = [...new Set([...standardServers, ...Array.from(mustBeChecked)])].filter(Boolean);

    // 4. 渲染 Checkbox 列表
    let html = `<div class="host-checkbox-grid" style="display: grid; grid-template-columns: repeat(auto-fill, minmax(120px, 1fr)); gap: 10px; margin-bottom: 10px; width: 100%;">`;

    html += displayList.map(s => {
        const isChecked = mustBeChecked.has(s);
        return `
            <label class="host-item" style="cursor: pointer; display: flex; align-items: center; gap: 4px; padding: 2px;">
                <input type="checkbox" name="hosts" value="${s}" ${isChecked ? 'checked' : ''}>
                <span>${s}</span>
            </label>
        `;
    }).join('');

    html += `</div>`;

    // 更新列表
    hostContainer.innerHTML = html;

    // 5. 確保輸入框固定、長度一半且靠右
    if (!document.getElementById('customHostInputGroup')) {
        const inputGroup = document.createElement('div');
        inputGroup.id = 'customHostInputGroup';
        inputGroup.style = "border-top: 1px solid #edf2f7; padding-top: 12px; display: flex; gap: 8px; justify-content: flex-end; align-items: center; margin-top: 10px;";
        
        inputGroup.innerHTML = `
            <input type="text" id="customHostName" placeholder="其他主機..." 
                style="width: 50%; padding: 4px 8px; border: 1px solid #cbd5e0; border-radius: 4px; box-sizing: border-box;">
            <button type="button" onclick="handleAddCustomHost()" 
                style="padding: 4px 12px; background: #4a5568; color: white; border-radius: 4px; border: none; cursor: pointer; white-space: nowrap;">
                + 新增
            </button>
        `;
        hostContainer.parentNode.insertBefore(inputGroup, hostContainer.nextSibling);
    }
}

// 點擊新增
function handleAddCustomHost() {
    const input = document.getElementById('customHostName');
    const value = input.value.trim();
    if (!value) return;
    renderHostInterface([], [value]);
    input.value = '';
}

async function deleteItem(id) {
    if (!confirm('確定要刪除這筆資料嗎？')) return;
    await fetch(`/api/contacts/${id}`, { method: 'DELETE' });
    loadData(currentPage);
}

/**
 * 渲染分頁按鈕
 * @param {number} totalPages 總頁數
 * @param {number} currentPage 當前頁碼
 */
function renderPagination(totalPages, currentPage) {
    const paginationContainer = document.getElementById('pagination');
    if (!paginationContainer) return;

    // 如果沒有資料 (totalPages 為 0)，清空分頁或顯示特定訊息
    if (totalPages <= 0) {
        paginationContainer.innerHTML = '<span style="color: #999; font-size: 14px;">暫無資料</span>';
        return;
    }

    let html = '';
    
    // 上一頁：如果是第 1 頁則禁用
    const isFirstPage = currentPage === 1;
    html += `<button onclick="loadData(${currentPage - 1})" ${isFirstPage ? 'disabled' : ''}>上一頁</button>`;

    // 頁碼
    for (let i = 1; i <= totalPages; i++) {
        html += `<button onclick="loadData(${i})" class="${i === currentPage ? 'active' : ''}">${i}</button>`;
    }

    // 下一頁：如果是最後一頁 OR 總頁數為 0 則禁用
    const isLastPage = currentPage >= totalPages;
    html += `<button onclick="loadData(${currentPage + 1})" ${isLastPage ? 'disabled' : ''}>下一頁</button>`;

    paginationContainer.innerHTML = html;
}

function showInfoFromData(btn) {
    const d = btn.dataset;
    // 呼叫下方真正負責顯示的函式
    showInfoModal(d.research, d.software, d.calc, d.notes);
}

function showInfoModal(content, software, resource, note) {
    const modal = document.getElementById('detailViewModal');

    if (!modal) {
        console.error("找不到 detailViewModal 元素");
        return;
    }

    const formatToHtml = (text) => {
        if (!text) return '未填寫';
        
        // 1. 先處理可能存在的 <br> (有些資料可能已經帶有標籤)
        // 2. 再處理全形或半形逗號，將其轉換為 <br>
        // 3. 移除多餘的空白
        return text
            .toString()
            .replace(/<br\s*\/?>/gi, '\n') // 先把 <br> 轉回換行符號
            .replace(/，/g, ',')           // 統一逗號
            .split(/[,\n]/)               // 根據逗號或換行符號分割
            .map(item => item.trim())     // 去除前後空白
            .filter(item => item !== '')  // 過濾空字串
            .join('<br>');                // 最後用 <br> 接起來
    };
    
    // 填入資料，若無資料顯示「未填寫」
    document.getElementById('infoContent').innerHTML = formatToHtml(content) || '未填寫';
    document.getElementById('infoSoftware').innerHTML = formatToHtml(software) || '未填寫';
    document.getElementById('infoResource').innerHTML = formatToHtml(resource) || '未填寫';
    document.getElementById('infoNote').innerHTML = formatToHtml(note) || '未填寫';

    // 顯示 Modal
    modal.style.display = 'block';
}

/**
 * 關閉資訊 Modal
 */
function closeDetailModal() {
    const modal = document.getElementById('detailViewModal');
    if (modal) modal.style.display = 'none';
}

// 1. 監聽勾選框變化
document.getElementById('is_course_account').addEventListener('change', function() {
    const section = document.getElementById('courseAccountSection');
    const body = document.getElementById('courseAccountBody');
    section.style.display = this.checked ? 'block' : 'none';
    // 只有在「真的沒資料」且「勾選」時才自動補一行
    if (this.checked && body.children.length === 0) {
        addCourseRow();
    }
});

// 2. 新增課程帳號行
function addCourseRow(account = '', password = '') {
    const body = document.getElementById('courseAccountBody');
    const row = document.createElement('tr');
    row.innerHTML = `
        <td><input type="text" class="hpc-input student-account" value="${account}" placeholder="請輸入帳號"></td>
        <td><input type="text" class="hpc-input student-password" value="${password}" placeholder="請輸入密碼"></td>
        <td style="text-align: center; vertical-align: middle;">
            <button type="button" class="btn-delete-row" onclick="this.closest('tr').remove()">
                ✕
            </button>
        </td>
    `;
    body.appendChild(row);
}
// 3. 獲取表格數據 (用於表單提交)
function getCourseData() {
    const rows = document.querySelectorAll('#courseAccountBody tr');
    const data = [];
    rows.forEach(row => {
        const acc = row.querySelector('.student-account').value.trim();
        const pwd = row.querySelector('.student-password').value.trim();
        if (acc || pwd) data.push({ account: acc, password: pwd });
    });
    return data;
}

/**
 * 切換顯示餘額明細懸浮窗
 */
function toggleQuotaDetail(btn, id) {
    const popover = btn.nextElementSibling;
    const isVisible = popover.style.display === 'block';
    
    // 先關閉所有其他的 popover
    document.querySelectorAll('.quota-popover').forEach(p => p.style.display = 'none');
    
    popover.style.display = isVisible ? 'none' : 'block';
}

/**
 * 取得今天日期的 YYYY-MM-DD 字串 (考量在地時區)
 */
function getTodayDateString() {
    const today = new Date();
    const yyyy = today.getFullYear();
    const mm = String(today.getMonth() + 1).padStart(2, '0');
    const dd = String(today.getDate()).padStart(2, '0');
    return `${yyyy}-${mm}-${dd}`;
}

/**
 * 輔助函式：統一金額顯示格式（雙位小數）
 */
function formatCurrency(value) {
    const num = parseFloat(value);
    return isNaN(num) ? '0.00' : num.toFixed(2);
}

async function openQuotaModal(id, name) {
    // 強制轉換為整數數字，確保符合後端 Flask <int:id> 的嚴格規範
    const targetId = parseInt(id, 10);
    if (isNaN(targetId)) {
        console.error("致命錯誤：無法解析聯絡人 ID");
        alert("無法讀取該聯絡人的識別 ID，請重新整理網頁再試。");
        return;
    }

    // 1. 立即將確認無誤的 ID 與姓名更新至 Modal 欄位上
    document.getElementById('quotaTargetId').value = targetId;
    document.getElementById('quotaTargetName').innerText = name || '選擇的帳號';
    
    // 💡 核心修復：在發送任何請求前，先把所有顯示區塊強制清空/重設！
    document.getElementById('current_total_remaining').innerText = '載入中...';
    
    const expirationList = document.getElementById('discount_expiration_list');
    if (expirationList) expirationList.innerHTML = '<div style="color: #999; padding: 10px;">資料載入中...</div>';
    
    const rechargeHistoryList = document.getElementById('recharge_history_list');
    if (rechargeHistoryList) rechargeHistoryList.innerHTML = '<div style="color: #999; padding: 10px;">歷史紀錄載入中...</div>';
    
    // 🌟 新增點：初始化歷史消費與扣款明細容器
    const consumptionHistoryList = document.getElementById('consumption_history_list');
    if (consumptionHistoryList) consumptionHistoryList.innerHTML = '<div style="color: #999; padding: 10px;">消費與扣款明細載入中...</div>';

    // 🌟 新增點：初始化底部的繳費單明細表格
    const billsTableBody = document.getElementById('billsTableBody');
    if (billsTableBody) billsTableBody.innerHTML = '<tr><td colspan="5" class="table-placeholder" style="text-align:center; color:#999; padding:12px;">帳單紀錄載入中...</td></tr>';
    
    // 抓出待確認帳單的三個欄位
    const billAmountInput = document.getElementById('pending_bill_amount');
    const billDateInput = document.getElementById('pending_bill_date');
    const billNotesInput = document.getElementById('pending_bill_notes');
    
    // 強制清空舊資料，顯示 placeholder
    if (billAmountInput) {
        billAmountInput.value = ''; 
        billAmountInput.placeholder = '計算建議金額中...';
    }
    if (billDateInput) billDateInput.value = '';
    if (billNotesInput) billNotesInput.value = '';

    // 將新增購買額度區塊也同步重設
    const addQuotaInput = document.getElementById('add_quota_amount');
    const purchaseDateInput = document.getElementById('purchase_date');
    if (addQuotaInput) addQuotaInput.value = 0;
    if (purchaseDateInput) purchaseDateInput.value = getTodayDateString();
    
    // 立即顯示 Modal 框架
    document.getElementById('quotaEditorModal').style.display = 'block';
    
    // 2. 平行發送非同步請求，避免其中一個卡死導致另一個不更新
    try {
        // 請求 A：聯絡人基本額度與完整歷史軌跡
        fetch(`/api/contacts/${targetId}`)
            .then(res => res.json())
            .then(data => {
                //呈現經後端歸戶統計、且格式化後的漂亮金額
                document.getElementById('current_total_remaining').innerText = formatCurrency(data.total_remaining);
                
                // 【A-1】 處理「年度可用餘額明細」
                if (expirationList) {
                    expirationList.innerHTML = '';
                    if (data.discount_details && data.discount_details.length > 0) {
                        data.discount_details.forEach(item => {
                            const row = document.createElement('div');
                            row.style.marginBottom = '12px';
                            row.style.padding = '8px';
                            row.style.borderRadius = '4px';
                            row.style.backgroundColor = item.is_expired ? '#fcf8e3' : '#f7fafc';
                            row.style.borderLeft = item.is_expired ? '4px solid #dc3545' : '4px solid #28a745';
                            
                            row.innerHTML = item.is_expired ? `
                                <div style="display: flex; justify-content: space-between; font-weight: bold; color: #dc3545; margin-bottom: 4px;">
                                    <span><i class="fas fa-exclamation-circle"></i> ${item.purchase_year} 年額度 [已過期]</span>
                                    <span style="text-decoration: line-through;">剩餘總額: $${formatCurrency(item.total_amount)}</span>
                                </div>
                                <div style="font-size: 13px; color: #718096; padding-left: 18px; display: flex; gap: 15px;">
                                    <span>購買餘額: <span style="text-decoration: line-through;">$${formatCurrency(item.purchase_amount)}</span></span>
                                    <span>優惠餘額: <span style="text-decoration: line-through;">$${formatCurrency(item.discount_amount)}</span></span>
                                    <span>截止日: ${item.expire_date}</span>
                                </div>
                            ` : `
                                <div style="display: flex; justify-content: space-between; font-weight: bold; color: #2d3748; margin-bottom: 4px;">
                                    <span><i class="far fa-calendar-alt"></i> ${item.purchase_year} 年額度</span>
                                    <span style="color: #2b6cb0; font-weight: bold;">剩餘總額: $${formatCurrency(item.total_amount)}</span>
                                </div>
                                <div style="font-size: 13px; color: #4a5568; padding-left: 18px; display: flex; gap: 15px;">
                                    <span>購買餘額: <strong>$${formatCurrency(item.purchase_amount)}</strong></span>
                                    <span>優惠餘額: <span style="color: #28a745; font-weight: bold;">$${formatCurrency(item.discount_amount)}</span></span>
                                    <span>將於 ${item.expire_date} 截止</span>
                                </div>
                            `;
                            expirationList.appendChild(row);
                        });
                    } else {
                        expirationList.innerHTML = '<span style="color: #999;">目前無任何年度額度儲值資訊</span>';
                    }
                }

                // 【A-2】 處理「儲值紀錄明細」
                if (rechargeHistoryList) {
                    rechargeHistoryList.innerHTML = '';
                    if (data.recharge_history && data.recharge_history.length > 0) {
                        data.recharge_history.forEach(item => {
                            const row = document.createElement('div');
                            row.style.marginBottom = '10px';
                            row.style.padding = '10px';
                            row.style.borderRadius = '5px';
                            row.style.display = 'block';
                            
                            if (item.is_paid) {
                                row.style.backgroundColor = '#f0fff4';
                                row.style.borderLeft = '4px solid #38a169';
                            } else {
                                row.style.backgroundColor = '#fff5f5';
                                row.style.borderLeft = '4px solid #e53e3e';
                            }
                            
                            const statusBadge = item.is_paid 
                                ? `<span style="background-color: #38a169; color: white; padding: 2px 6px; border-radius: 4px; font-size: 11px; font-weight: bold; display: inline-flex; align-items: center; gap: 4px; vertical-align: middle;"><i class="fas fa-check-circle"></i> 已入帳</span>` 
                                : `<span style="background-color: #e53e3e; color: white; padding: 2px 6px; border-radius: 4px; font-size: 11px; font-weight: bold; display: inline-flex; align-items: center; gap: 4px; vertical-align: middle;"><i class="fas fa-times-circle"></i> 尚未付款</span>`;
                            
                            const isBonus = item.amount === 0;
                            const titleText = isBonus ? `${item.year} 年學術獎勵額度` : `${item.year} 年儲值單`;

                            row.innerHTML = `
                                <div style="font-weight: bold; color: #2d3748; margin-bottom: 6px;">
                                    <i class="fas fa-file-invoice-dollar"></i> ${titleText}
                                    <span style="font-size: 12px; color: #718096; font-weight: normal; margin-left: 10px;">日期: ${item.payment_date || '未設定'}</span>
                                </div>
                                <div style="font-size: 13px; color: #4a5568; display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
                                    <span>自費金額: <strong>$${formatCurrency(item.amount)}</strong></span>
                                    <span style="color: #cbd5e0;">|</span>
                                    <span>優惠額度: <strong style="color: #38a169;">$${formatCurrency(item.discount)}</strong></span>
                                    <span style="margin-left: 4px; display: inline-flex;">${statusBadge}</span>
                                </div>
                            `;
                            rechargeHistoryList.appendChild(row);
                        });
                    } else {
                        rechargeHistoryList.innerHTML = '<span style="color: #999;">目前無任何儲值歷史紀錄</span>';
                    }
                }
                // 🌟 【A-3】 核心變更：動態渲染「歷史消費與扣款日期明細」 (對應 QuotaTransaction)
                if (consumptionHistoryList) {
                    consumptionHistoryList.innerHTML = '';
                    if (data.consumption_history && data.consumption_history.length > 0) {
                        data.consumption_history.forEach(tx => {
                            const row = document.createElement('div');
                            row.style.marginBottom = '10px';
                            row.style.padding = '10px';
                            row.style.borderRadius = '5px';
                            row.style.backgroundColor = '#f7fafc';
                            
                            let badgeColor = '#718096';
                            let badgeText = tx.tx_type;
                            let amountDetail = [];

                            // 根據後端 tx_type 劃分精細的 UI 樣式
                            if (tx.tx_type === 'deduct') {
                                row.style.borderLeft = '4px solid #e53e3e';
                                row.style.backgroundColor = '#fff5f5';
                                badgeColor = '#e53e3e';
                                badgeText = '帳單扣款';
                                if (tx.amount_changed < 0) amountDetail.push(`自費: <strong style="color:#e53e3e;">-$${formatCurrency(Math.abs(tx.amount_changed))}</strong>`);
                                if (tx.discount_changed < 0) amountDetail.push(`優惠: <strong style="color:#e53e3e;">-$${formatCurrency(Math.abs(tx.discount_changed))}</strong>`);
                            } else if (tx.tx_type === 'charge' || tx.tx_type === 'bonus') {
                                row.style.borderLeft = '4px solid #38a169';
                                row.style.backgroundColor = '#f0fff4';
                                badgeColor = '#38a169';
                                // 🛠️ 修正原先「儲值儲值」贅字，並精準對應學術獎勵 (Bonus)
                                badgeText = tx.tx_type === 'charge' ? '線上儲值' : '學術獎勵';
                                if (tx.amount_changed > 0) amountDetail.push(`自費: <strong style="color:#38a169;">+$${formatCurrency(tx.amount_changed)}</strong>`);
                                if (tx.discount_changed > 0) amountDetail.push(`優惠: <strong style="color:#38a169;">+$${formatCurrency(tx.discount_changed)}</strong>`);
                            } else if (tx.tx_type === 'refund') {
                                row.style.borderLeft = '4px solid #3182ce';
                                row.style.backgroundColor = '#ebf8ff';
                                badgeColor = '#3182ce';
                                badgeText = '退款返還';
                                if (tx.amount_changed > 0) amountDetail.push(`自費: <strong style="color:#3182ce;">+$${formatCurrency(tx.amount_changed)}</strong>`);
                                if (tx.discount_changed > 0) amountDetail.push(`優惠: <strong style="color:#3182ce;">+$${formatCurrency(tx.discount_changed)}</strong>`);
                            }

                            const typeBadge = `<span style="background-color: ${badgeColor}; color: white; padding: 2px 6px; border-radius: 4px; font-size: 11px; font-weight: bold; margin-right: 6px; display: inline-block; vertical-align: middle;">${badgeText}</span>`;
                            const billAnchor = tx.bill_id ? `<span style="color: #718096; font-size: 11px; margin-left: 8px;">(關聯帳單 #${tx.bill_id})</span>` : '';

                            row.innerHTML = `
                                <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 6px;">
                                    <div style="font-weight: bold; color: #2d3748; font-size: 13px;">
                                        ${typeBadge} ${tx.description || ''} ${billAnchor}
                                    </div>
                                    <div style="font-size: 12px; color: #a0aec0; white-space: nowrap;">${tx.created_at || ''}</div>
                                </div>
                                <div style="font-size: 12px; color: #4a5568;">
                                    額度異動：${amountDetail.length > 0 ? amountDetail.join(' | ') : '$0.00'}
                                </div>
                            `;
                            consumptionHistoryList.appendChild(row);
                        });
                    } else {
                        consumptionHistoryList.innerHTML = '<span style="color: #999; padding: 10px; display: block;">目前無任何消費與扣款明細紀錄</span>';
                    }
                }

                // 🌟 【A-4】 核心新增：動態渲染底部「繳費單紀錄明細與銷帳」表格 (Bills Table Body)
                if (billsTableBody) {
                    billsTableBody.innerHTML = '';
                    if (data.bills && data.bills.length > 0) {
                        data.bills.forEach(bill => {
                            const tr = document.createElement('tr');
                            
                            // 狀態標籤判定
                            let statusBadge = '';
                            if (bill.status === 'paid') {
                                statusBadge = '<span style="background-color: #38a169; color: white; padding: 2px 6px; border-radius: 4px; font-size: 11px; font-weight: bold; display: inline-block;">已繳費</span>';
                            } else if (bill.status === 'unpaid') {
                                statusBadge = '<span style="background-color: #e53e3e; color: white; padding: 2px 6px; border-radius: 4px; font-size: 11px; font-weight: bold; display: inline-block;">未繳費</span>';
                            } else {
                                statusBadge = `<span style="background-color: #718096; color: white; padding: 2px 6px; border-radius: 4px; font-size: 11px; font-weight: bold; display: inline-block;">${bill.status}</span>`;
                            }

                            // 動作按鈕防呆
                            let actionHtml = '';
                            if (bill.status === 'unpaid') {
                                actionHtml = `<button type="button" onclick="triggerManualWriteOff(${bill.id}, ${bill.amount})" style="background-color: #3182ce; color: white; border: none; padding: 3px 8px; border-radius: 3px; font-size: 11px; cursor: pointer;"><i class="fas fa-check"></i> 銷帳</button>`;
                            } else {
                                actionHtml = '<span style="color: #cbd5e0; font-size: 11px;">無</span>';
                            }

                            tr.innerHTML = `
                                <td class="text-left" style="padding: 10px; font-size: 13px; color:#4a5568;">${bill.created_at || '---'}</td>
                                <td class="text-right" style="padding: 10px; font-size: 13px; font-weight: bold; color: ${bill.amount > 0 ? '#e53e3e' : '#2d3748'}">$${formatCurrency(bill.amount)}</td>
                                <td class="text-center" style="padding: 10px;">${statusBadge}</td>
                                <td class="text-left" style="padding: 10px; font-size: 12px; color: #718096; max-width: 250px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${bill.notes || ''}">${bill.notes || '---'}</td>
                                <td class="text-center" style="padding: 10px;">${actionHtml}</td>
                            `;
                            billsTableBody.appendChild(tr);
                        });
                    } else {
                        billsTableBody.innerHTML = '<tr><td colspan="5" class="table-placeholder" style="text-align: center; color: #999; padding: 20px;">該聯絡人查無歷史繳費單紀錄。</td></tr>';
                    }
                }
            })
            .catch(err => console.error("基本額度與流水帳明細載入失敗:", err));

        // 請求 B：動態試算建議扣款金額
        fetch(`/api/contacts/${targetId}/calculate_pending_bill`)
            .then(res => {
                if (res.status === 404) throw new Error("後端找不到對帳路由 404");
                return res.json();
            })
            .then(billData => {
                if (billAmountInput) {
                    billAmountInput.value = billData.suggested_amount !== undefined ? billData.suggested_amount : 0;
                    billAmountInput.placeholder = ''; 
                }
                if (billDateInput) billDateInput.value = billData.bill_date || getTodayDateString();
                if (billNotesInput) billNotesInput.value = billData.notes || '';
                
                // 💡 優化：若備註包含警告標籤(⚠️)或成功標籤(✅)，可調整輸入框提示顏色或禁用按鈕防呆
                if (billNotesInput && (billData.notes.includes('⚠️') || billData.notes.includes('✅'))) {
                    billNotesInput.style.color = billData.notes.includes('⚠️') ? '#e53e3e' : '#38a169';
                    billNotesInput.style.fontWeight = 'bold';
                }

                console.log(`成功載入 ID: ${targetId} 的新建議扣款金額: ${billData.suggested_amount}`);
            })
            .catch(billErr => {
                console.error("無法取得待確認帳單數據:", billErr);
                if (billAmountInput) {
                    billAmountInput.value = 0;
                    billAmountInput.placeholder = '無法取得建議金額';
                }
                if (billDateInput) billDateInput.value = getTodayDateString();
            });

    } catch (err) {
        console.error("開窗通訊異常:", err);
    }
}
function closeQuotaModal() {
    document.getElementById('quotaEditorModal').style.display = 'none';
}

function handleQuotaButtonClick(event, id, applicant, isCourse, isTrial) {
    if (isCourse || isTrial) {
        event.preventDefault();
        alert("課程帳號與試用帳號不適用此功能，無法開啟額度管理。");
        return;
    }
    // 驗證通過，才允許呼叫原本的開啟彈窗功能
    openQuotaModal(id, applicant);
}

// 綁定額度表單提交
document.addEventListener('DOMContentLoaded', function() {
    // ==========================================
    // 宣告小視窗所需的 DOM 物件（已改為複選結構）
    // ==========================================
    const modal = document.getElementById('rewardQuotaModal');
    const openBtn = document.getElementById('btn-open-reward-modal');
    const closeBtn = document.getElementById('btn-close-modal');
    const cancelBtn = document.getElementById('btn-cancel-modal');
    const confirmBtn = document.getElementById('btn-confirm-reward');
    
    // 🌟 改為獲取對應的 Checkbox 與數量輸入框
    const chkFree = document.getElementById('chk-reward-free');
    const chkAcademic = document.getElementById('chk-reward-academic');
    const quantityInput = document.getElementById('reward_quantity');

    // ==========================================
    // 1. 小視窗開關與重置邏輯
    // ==========================================
    openBtn.addEventListener('click', () => modal.style.display = 'block');

    function closeModal() {
        modal.style.display = 'none';
        // 🌟 關閉時重置複選框狀態與行內輸入框
        chkFree.checked = false;
        chkAcademic.checked = false;
        quantityInput.style.display = 'none';
        quantityInput.value = 1;
    }

    closeBtn.addEventListener('click', closeModal);
    cancelBtn.addEventListener('click', closeModal);
    window.addEventListener('click', (e) => { if (e.target === modal) closeModal(); });

    // 🌟 監聽學術額度勾選狀態：勾選才顯示行內的數量輸入框
    chkAcademic.addEventListener('change', function() {
        if (this.checked) {
            quantityInput.style.display = 'inline-block';
            quantityInput.focus();
        } else {
            quantityInput.style.display = 'none';
        }
    });

    // ==========================================
    // 分流一：小視窗【確認發放獎勵額度】點擊事件（優化：單次 API 批量送出）
    // ==========================================
    confirmBtn.addEventListener('click', async () => {
        const id = document.getElementById('quotaTargetId').value; // 取得當前對象 ID
        
        // 蒐集被勾選的任務與確認訊息
        let selectedItems = [];
        let confirmDetails = [];

        if (chkFree.checked) {
            selectedItems.push({ type: 'free', quantity: 1 });
            confirmDetails.push("・免費額度 $10,000 元 (限今年度帳單折抵)");
        }

        if (chkAcademic.checked) {
            const qty = parseInt(quantityInput.value) || 1;
            if (qty <= 0) { 
                alert("學術額度數量必須大於 0"); 
                return; 
            }
            selectedItems.push({ type: 'academic', quantity: qty });
            confirmDetails.push(`・學術額度 $1,000 × ${qty} 份 = $${1000 * qty} 元`);
        }

        // 防呆：什麼都沒勾選
        if (selectedItems.length === 0) {
            alert("請至少選擇一種額度類型");
            return;
        }

        // 組裝統一的確認提示視窗
        const confirmMsg = `【確認發放以下研究獎勵？】\n\n${confirmDetails.join('\n')}`;
        if (!confirm(confirmMsg)) return;

        try {
            // 🌟 關鍵改動：整包 items 一次打包送過去
            const res = await fetch(`/api/contacts/${id}/research_bonus`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ items: selectedItems }) 
            });
            
            const data = await res.json();
            
            if (res.ok) {
                // 顯示後端組合好、帶有精美換行與千分位的成功訊息
                alert(data.message);
                closeModal();          // 關閉小視窗
                closeQuotaModal();     // 關閉原本的分配額度大彈窗
                if (typeof loadData === 'function') loadData(currentPage);
            } else {
                alert(`發放失敗：${data.message || '伺服器錯誤'}`);
            }
        } catch (err) {
            alert("連線失敗，無法完成獎勵額度發放");
        }
    });
});
    
/**
 * 處理情境：直接開立繳費單 (已修正 ID)
 */
function submitDirectBill() {
    console.log("🚀 submitDirectBill 被點擊了！");

    // 🛠️ 修正點：將 'current_contact_id' 改為 'quotaTargetId'
    const elContactId = document.getElementById('quotaTargetId'); 
    const elAmount = document.getElementById('pending_bill_amount');
    const elNotes = document.getElementById('pending_bill_notes');

    // 🛡️ 安全防護：避免找不到元素時程式直接當掉
    if (!elContactId || !elAmount) {
        alert('🛑 前端錯誤：找不到必要的網頁元素！請確認 HTML 欄位是否完整。');
        return;
    }

    const contactId = elContactId.value;
    const amount = elAmount.value;
    const notes = elNotes ? elNotes.value : '管理員手動直接開單';

    if (!amount || parseFloat(amount) <= 0) {
        alert('請輸入要開立的繳費單金額');
        return;
    }

    if (!confirm(`【確認直接開立繳費單？】\n\n系統將跳過預付額度扣款，直接建立一筆 $${amount} 元的未繳帳單。`)) {
        return;
    }

    fetch(`/api/contacts/${contactId}/direct_create_bill`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ amount: parseFloat(amount), notes: notes })
    })
    .then(res => res.json())
    .then(data => {
        alert(data.message || '繳費單直接開立成功！');
        elAmount.value = '';
        if (elNotes) elNotes.value = '';
        
        // 成功開單後，重新載入面板與外圍表格
        if (typeof reloadQuotaPanel === 'function') {
            reloadQuotaPanel(contactId);
        } else {
            const elTargetName = document.getElementById('quotaTargetName');
            const targetName = elTargetName ? elTargetName.innerText : '';
            if (typeof openQuotaModal === 'function') openQuotaModal(parseInt(contactId, 10), targetName);
        }

        if (typeof loadData === 'function') {
            const page = (typeof currentPage !== 'undefined') ? currentPage : 1;
            loadData(page);
        }
    })
    .catch(err => alert('直接開單失敗: ' + err));
}

/**
 * 處理情境：額度扣款後，開立繳費單 (已修正 ID)
 */
function handleConfirmDeduct() {
    console.log("🚀 handleConfirmDeduct 被點擊了！");

    // 🛠️ 修正點：將 'current_contact_id' 改為 'quotaTargetId'
    const elContactId = document.getElementById('quotaTargetId'); 
    const elAmount = document.getElementById('pending_bill_amount');
    const elBillDate = document.getElementById('pending_bill_date');
    const elNotes = document.getElementById('pending_bill_notes');

    if (!elContactId || !elAmount) {
        alert('🛑 前端錯誤：找不到必要的網頁元素！');
        return;
    }

    const contactId = elContactId.value;
    const amount = elAmount.value;
    const billDate = elBillDate ? elBillDate.value : '';
    const notes = elNotes ? elNotes.value : '管理員核定扣款';

    // 1. 前端基本驗證
    if (!amount || parseFloat(amount) <= 0) {
        alert('請輸入有效的扣款金額');
        return;
    }

    // 2. 執行前二次確認
    if (!confirm(`【確認執行額度扣款？】\n系統將優先扣除該帳號的預付優惠額度。\n若額度不足，將自動就剩餘差額生成未繳繳費單。 \n學術獎勵要先點選才折抵。`)) {
        return;
    }

    // 3. 發送請求至後端 confirm_deduct 路由
    fetch(`/api/contacts/${contactId}/confirm_deduct`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            final_amount: parseFloat(amount),
            bill_date: billDate, // 若留空，後端會自動預設為今天
            notes: notes
        })
    })
    .then(res => {
        // 💡 關鍵連動：如果後端回傳 400 (防呆阻擋)，將錯誤訊息丟給 catch 處理
        return res.json().then(data => {
            if (!res.ok) {
                throw new Error(data.message || '計費扣款程序異常');
            }
            return data;
        });
    })
    .then(data => {
        // 4. 根據後端回傳的 status 狀態進行客製化提示
        if (data.status === 'need_bill') {
            alert(`⚠️ 提示：${data.message}\n\n執行明細：\n${data.detail.join('\n')}`);
        } else {
            alert(`✅ 成功：${data.message}`);
        }

        // 5. 清空輸入表單
        elAmount.value = '';
        if (elNotes) elNotes.value = '';
        if (elBillDate) elBillDate.value = '';

        // 6. 重新載入 UI 面板與外圍表格資料
        if (typeof reloadQuotaPanel === 'function') {
            reloadQuotaPanel(contactId);
        } else {
            const elTargetName = document.getElementById('quotaTargetName');
            const targetName = elTargetName ? elTargetName.innerText : '';
            if (typeof openQuotaModal === 'function') openQuotaModal(parseInt(contactId, 10), targetName);
        }
        
        if (typeof loadData === 'function') {
            const page = (typeof currentPage !== 'undefined') ? currentPage : 1;
            loadData(page);
        }
    })
    .catch(err => {
        alert(err.message);
    });
}

/**
 * 處理情境：兩階段驗證——先檢視 PDF 繳費單，確認無誤後再執行郵件寄送 (已修正 ID)
 */
async function handlePreviewAndSend() {
    console.log("🚀 handlePreviewAndSend 被點擊了！");

    const elContactId = document.getElementById('quotaTargetId'); 
    const elAmount = document.getElementById('pending_bill_amount');
    const elBillDate = document.getElementById('pending_bill_date');
    const elNotes = document.getElementById('pending_bill_notes');
    const elEmail = document.getElementById('current_contact_email'); 

    if (!elContactId || !elAmount) {
        alert('🛑 前端錯誤：找不到必要的網頁元素！');
        return;
    }

    const contactId = elContactId.value;
    const amount = elAmount.value;
    const billDate = elBillDate ? elBillDate.value : '';
    const notes = elNotes ? elNotes.value : '管理員手動直接開單';
    const recipientEmail = elEmail ? elEmail.value : '';

    if (!amount || parseFloat(amount) <= 0) {
        alert('請輸入有效的繳費單金額以產生帳單項目');
        return;
    }

    if (!recipientEmail) {
        alert('無法取得客戶電子郵件，請確認外圍畫面的 Email 欄位設定正確');
        return;
    }

    const payloadData = {
        recipient: recipientEmail,
        title: `HPC 運算服務繳費通知單`,
        executor: "系統管理員",
        date: billDate,
        items: [{ name: notes, amount: parseFloat(amount) }]
    };

    alert('系統即將產生繳費單 PDF 預覽，請在即將開啟的新分頁中進行核對。');

    try {
        // ==========================================
        // 階段一：發送預覽請求並開啟新分頁檢視
        // ==========================================
        const res = await fetch('/api/contacts/send-quotation', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ...payloadData, preview: true })
        });

        if (!res.ok) {
            const data = await res.json();
            throw new Error(data.message || '無法生成預覽檔');
        }

        const blob = await res.blob();
        const pdfUrl = URL.createObjectURL(blob);
        const previewWindow = window.open(pdfUrl, '_blank');
        
        if (!previewWindow) {
            alert('偵測到瀏覽器封鎖了彈出視窗，請允許彈出視窗以檢視 PDF 帳單！');
        }

        // ==========================================
        // 階段二：留在原分頁等待管理員核對（優化：用 Promise 替代 setTimeout 嵌套）
        // ==========================================
        await new Promise(resolve => setTimeout(resolve, 800));

        const isConfirmed = confirm(`【繳費單檢視確認】\n\n請確認新分頁中的 PDF 帳單明細。\n\n金額：$${amount} 元\n收件人：${recipientEmail}\n\n確認內容完全無誤並現在寄出信件嗎？`);
        
        if (isConfirmed) {
            const response = await fetch('/api/contacts/send-quotation', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ ...payloadData, preview: false })
            });
            
            const result = await response.json();
            
            if (result.status === 'success') {
                alert(`✅ 信件發送成功：${result.message}`);
                elAmount.value = '';
                if (elNotes) elNotes.value = '';
            } else {
                alert(`❌ 寄送失敗：${result.message}`);
            }
        }

    } catch (err) {
        // 統一捕捉階段一與階段二的所有連線與系統異常
        alert('系統發生異常: ' + err.message);
    }
}