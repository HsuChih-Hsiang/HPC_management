// static/js/edit_templates.js
// 初始化 Quill.js 編輯器
const quill = new Quill('#templateEditor', {
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
    placeholder: '在這裡編輯你的模板內容...',
});

// 獲取 DOM 元素
const templateNameInput = document.getElementById('templateName');
const templateSubjectInput = document.getElementById('templateSubject');
const saveButton = document.getElementById('saveButton');
const cancelButton = document.getElementById('cancelButton');
const messageBox = document.getElementById('messageBox');

// 模板列表相關元素 (現在直接在頁面左側)
const templateListContainer = document.getElementById('templateList'); // 左側列表容器
const noTemplatesMessage = document.getElementById('noTemplatesMessage');

let currentEditingTemplateId = null; // 用於判斷是新增還是編輯

// 顯示訊息框的函式
function showMessage(message, type) {
    messageBox.textContent = message;
    messageBox.className = 'message-box ' + type;
    messageBox.style.display = 'block';

    setTimeout(() => {
        messageBox.style.display = 'none';
    }, 5000);
}

// 清空編輯器和輸入框
function clearEditor() {
    templateNameInput.value = '';
    templateSubjectInput.value = '';
    quill.setContents([]); // 清空 Quill 編輯器內容
    currentEditingTemplateId = null;
    saveButton.textContent = '儲存模板'; // 重置按鈕文字
}

// ** 加載模板列表到左側區域 **
async function loadTemplates() {
    try {
        const response = await fetch('/api/templates');
        const templates = await response.json();

        templateListContainer.innerHTML = ''; // 清空現有列表

        if (templates.length === 0) {
            noTemplatesMessage.style.display = 'block';
            return;
        } else {
            noTemplatesMessage.style.display = 'none';
        }

        templates.forEach(template => {
            const templateItem = document.createElement('div');
            templateItem.classList.add('template-list-item'); // 使用現有的 template-list-item 樣式
            templateItem.dataset.id = template.id; // 儲存模板 ID

            // 整個列表項目可點擊來編輯
            templateItem.addEventListener('click', () => {
                editTemplate(template.id);
            });

            templateItem.innerHTML = `
                <h3>${template.name}</h3>
                <p>主旨: ${template.subject || '(無主旨)'}</p>
                <div class="template-actions">
                    <button class="delete-btn">刪除</button>
                </div>
            `;
            templateListContainer.appendChild(templateItem);

            // 為刪除按鈕添加事件監聽器 (阻止事件冒泡到父元素，避免同時觸發編輯)
            templateItem.querySelector('.delete-btn').addEventListener('click', (e) => {
                e.stopPropagation();
                deleteTemplate(template.id, template.name);
            });
        });
    } catch (error) {
        console.error('加載模板失敗:', error);
        showMessage('加載模板列表失敗。', 'error');
    }
}

// 編輯模板 (載入到編輯器)
async function editTemplate(id) {
    try {
        const response = await fetch(`/api/templates/${id}`);
        const template = await response.json();
        if (template.success === false) {
            showMessage(template.message, 'error');
            return;
        }

        currentEditingTemplateId = id;
        templateNameInput.value = template.name;
        templateSubjectInput.value = template.subject || '';
        quill.setContents(quill.clipboard.convert(template.html)); // 設定 Quill 內容
        saveButton.textContent = '更新模板'; // 改變按鈕文字
        showMessage(`已載入模板 "${template.name}" 進行編輯。`, 'info');

        // 可選：滾動到編輯器區域，讓使用者更方便操作
        document.getElementById('editForm').scrollIntoView({ behavior: 'smooth', block: 'start' });

    } catch (error) {
        console.error('載入模板內容失敗:', error);
        showMessage('載入模板內容失敗。', 'error');
    }
}

// 刪除模板
async function deleteTemplate(id, name) {
    if (!confirm(`確定要刪除模板 "${name}" 嗎？此操作不可恢復！`)) {
        return;
    }

    try {
        const response = await fetch(`/api/templates/${id}`, {
            method: 'DELETE',
        });
        const result = await response.json();

        if (response.ok && result.success) {
            showMessage(result.message, 'success');
            await loadTemplates(); // 重新加載列表以更新顯示
            // 如果刪除的是正在編輯的模板，則清空編輯器
            if (currentEditingTemplateId === id) {
                clearEditor();
            }
        } else {
            showMessage('刪除模板失敗: ' + (result.message || '未知錯誤'), 'error');
        }
    } catch (error) {
        console.error('刪除模板連線錯誤:', error);
        showMessage('刪除模板失敗，請檢查網路或稍後再試。', 'error');
    }
}

// 保存/更新模板
saveButton.addEventListener('click', async function() {
    const name = templateNameInput.value.trim();
    const subject = templateSubjectInput.value.trim();
    const html = quill.root.innerHTML.trim();

    if (!name) {
        showMessage('模板名稱不能為空。', 'error');
        return;
    }
    if (!html || html === '<p><br></p>') {
        showMessage('模板內容不能為空。', 'error');
        return;
    }

    const dataToSend = { name, subject, html };
    let method = 'POST';
    let url = '/api/templates';

    if (currentEditingTemplateId) { // 如果是編輯模式
        method = 'PUT';
        url = `/api/templates/${currentEditingTemplateId}`;
    }

    try {
        const response = await fetch(url, {
            method: method,
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(dataToSend),
        });
        const result = await response.json();

        if (response.ok && result.success) {
            showMessage(result.message, 'success');
            clearEditor(); // 清空編輯器
            await loadTemplates(); // 操作成功後，重新加載列表以更新顯示
        } else {
            showMessage('操作失敗: ' + (result.message || '未知錯誤'), 'error');
        }
    } catch (error) {
        console.error('模板操作連線錯誤:', error);
        showMessage('操作失敗，請檢查網路或稍後再試。', 'error');
    }
});

// 取消編輯
cancelButton.addEventListener('click', function() {
    clearEditor();
    showMessage('編輯已取消。', 'info');
});

// 頁面加載時自動加載模板列表
document.addEventListener('DOMContentLoaded', loadTemplates);