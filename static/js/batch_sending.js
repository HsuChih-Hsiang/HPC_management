// static/js/script.js - 最終且穩定的版本
document.addEventListener('DOMContentLoaded', function() {
    // 2. 主頁面 (index.html) 的郵件寄送邏輯
    const emailForm = document.getElementById('emailForm');
    const messageBox = document.getElementById('messageBox');
    const toInput = document.getElementById('to');
    const ccInput = document.getElementById('cc');
    const bccInput = document.getElementById('bcc');
    const subjectInput = document.getElementById('subject');
    const emailBodyHidden = document.getElementById('emailBodyHidden');
    const addSelectedEmailsButton = document.getElementById('addSelectedEmailsButton');

    // 郵件標籤容器
    const toEmailsContainer = document.getElementById('toEmails');
    const ccEmailsContainer = document.getElementById('ccEmails');
    const bccEmailsContainer = document.getElementById('bccEmails');

    // 郵件群組模態視窗相關元素
    const groupModal = document.getElementById('groupModal');
    const groupList = document.getElementById('groupList');
    const addGroupButton = document.getElementById('addGroupButton');
    const addGroupButtonCc = document.getElementById('addGroupButtonCc');
    const addGroupButtonBcc = document.getElementById('addGroupButtonBcc');
    const selectAllGroupsButton = document.getElementById('selectAllGroupsButton');
    const groupModalCloseButton = groupModal ? groupModal.querySelector('.close-button') : null;

    let currentInputTarget = null; // 儲存當前正在操作的輸入框

    // Quill.js 編輯器初始化
    const editorContainer = document.getElementById('editor-container');
    let quill;
    if (editorContainer) {
        quill = new Quill('#editor-container', {
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
            placeholder: '在這裡輸入你的郵件內容...',
        });

        quill.on('text-change', function() {
            emailBodyHidden.value = quill.root.innerHTML;
        });
    }

    // 郵件標籤功能
    function initializeEmailTags() {
        [toInput, ccInput, bccInput].forEach(input => {
            if (input) {
                input.addEventListener('keydown', function(e) {
                    if (e.key === 'Enter' || e.key === ',') {
                        e.preventDefault();
                        addEmailTag(input, true); // 仍顯示錯誤
                    }
                });
                
                input.addEventListener('blur', function() {
                    if (this.value.trim()) {
                        addEmailTag(this, true); // 仍顯示錯誤
                    }
                });

                // 【新增的邏輯】處理貼上事件，以支援批量貼上多個郵件
                input.addEventListener('paste', function(e) {
                    e.preventDefault(); // 阻止默認的貼上行為
                    const pastedText = e.clipboardData.getData('text');
                    
                    // 使用逗號、空格或換行符分割郵件，並過濾掉空字串
                    const emails = pastedText.split(/[\s,]+/).filter(email => email.trim() !== '');

                    let addedCount = 0;
                    emails.forEach(email => {
                        // 暫時將單個郵件地址放入輸入框，然後呼叫 addEmailTag 處理
                        // 批量處理時，不顯示錯誤訊息 (false)
                        input.value = email; 
                        if(addEmailTag(input, false)) { 
                            addedCount++;
                        }
                    });

                    // 處理完畢後，清空輸入框
                    input.value = ''; 

                    // 批量貼上時，只在成功新增時顯示一次總結訊息
                    if (addedCount > 0) {
                        window.showMessage(`已成功新增 ${addedCount} 個電子郵件地址。`, 'success');
                    } else if (emails.length > 0) {
                        window.showMessage('所有貼上的郵件地址均無效或已存在。', 'error');
                    }
                });
                // 【新增的邏輯結束】
            }
        });
    }

    function addEmailTag(input, showErrors = true) { // 增加 showErrors 參數，預設為 true
        const email = input.value.trim();
        if (!email || !isValidEmail(email)) {
            if (showErrors) { // 僅在需要時顯示錯誤
                window.showMessage('請輸入有效的電子郵件地址。', 'error');
            }
            input.value = '';
            return false; // 新增：返回 false 表示失敗
        }

        let container;
        if (input === toInput) {
            container = toEmailsContainer;
        } else if (input === ccInput) {
            container = ccEmailsContainer;
        } else if (input === bccInput) {
            container = bccEmailsContainer;
        }

        if (container) {
            const existingTags = container.querySelectorAll('.email-tag');
            for (let tag of existingTags) {
                if (tag.dataset.email === email) {
                    if (showErrors) { // 僅在需要時顯示錯誤
                        window.showMessage('此電子郵件已存在。', 'error');
                    }
                    input.value = '';
                    return false; // 新增：返回 false 表示失敗
                }
            }

            const emailTag = createEmailTag(email);
            if (!emailTag) {
                input.value = '';
                return false;
            }
            
            const inputElement = container.querySelector('.email-input');
            if (inputElement) {
                container.insertBefore(emailTag, inputElement);
            } else {
                container.appendChild(emailTag);
            }
            input.value = '';
            return true; // 新增：返回 true 表示成功
        }
        return false;
    }

    function createEmailTag(email) {
        // 核心修復：在建立標籤前進行最終檢查
        const cleanedEmail = (email && typeof email === 'string' && email.trim().toLowerCase() !== 'on') ? email : null;
        if (!cleanedEmail) {
            return null;
        }

        const tag = document.createElement('div');
        tag.className = 'email-tag';
        tag.draggable = true;
        tag.dataset.email = cleanedEmail;
        
        tag.innerHTML = `
            <span class="email-text">${cleanedEmail}</span>
            <button type="button" class="remove-email-btn" onclick="removeEmailTag(this)">×</button>
        `;

        tag.addEventListener('dragstart', function(e) {
            e.dataTransfer.setData('text/plain', cleanedEmail);
            e.dataTransfer.setData('source', tag.parentElement.id);
        });

        tag.addEventListener('dragover', function(e) {
            e.preventDefault();
        });

        tag.addEventListener('drop', function(e) {
            e.preventDefault();
            const draggedEmail = e.dataTransfer.getData('text/plain');
            const sourceContainer = e.dataTransfer.getData('source');
            
            if (sourceContainer !== tag.parentElement.id) {
                moveEmailTag(draggedEmail, sourceContainer, tag.parentElement.id);
            } else {
                reorderEmailTag(draggedEmail, tag);
            }
        });

        if (!cleanedEmail) {
            return null;
        }
        
        tag.innerHTML = `
            <span class="email-text">${cleanedEmail}</span>
            <button type="button" class="remove-email-btn" onclick="removeEmailTag(this)">×</button>
        `;

        // --- 關鍵修正：確保雙擊事件能觸發編輯 ---
        tag.addEventListener('dblclick', function(e) {
            e.preventDefault();
            e.stopPropagation();
            makeTagEditable(tag);
        });

        // 原有的拖曳邏輯
        tag.addEventListener('dragstart', function(e) {
            e.dataTransfer.setData('text/plain', cleanedEmail);
            e.dataTransfer.setData('source', tag.parentElement.id);
        });

        tag.addEventListener('dragover', function(e) { e.preventDefault(); });

        tag.addEventListener('drop', function(e) {
            e.preventDefault();
            const draggedEmail = e.dataTransfer.getData('text/plain');
            const sourceContainer = e.dataTransfer.getData('source');
            if (sourceContainer !== tag.parentElement.id) {
                moveEmailTag(draggedEmail, sourceContainer, tag.parentElement.id);
            } else {
                reorderEmailTag(draggedEmail, tag);
            }
        });

        return tag;
    }

    window.removeEmailTag = function(button) {
        const tag = button.parentElement;
        tag.remove();
    };

    function moveEmailTag(email, fromContainerId, toContainerId) {
        const fromContainer = document.getElementById(fromContainerId);
        const toContainer = document.getElementById(toContainerId);
        
        if (fromContainer && toContainer) {
            const tagToMove = fromContainer.querySelector(`[data-email="${email}"]`);
            if (tagToMove) {
                // 在移動前檢查目標容器是否已存在該郵件
                const existingTags = toContainer.querySelectorAll('.email-tag');
                for (let tag of existingTags) {
                    if (tag.dataset.email === email) {
                        tagToMove.remove(); // 如果目標容器已存在，則刪除源容器的郵件
                        window.showMessage('目標容器已存在此電子郵件。', 'error');
                        return; 
                    }
                }
                
                const inputElement = toContainer.querySelector('.email-input');

                if (inputElement) {
                    toContainer.insertBefore(tagToMove, inputElement);
                } else {
                    toContainer.appendChild(tagToMove);
                }
            }
        }
    }


    function reorderEmailTag(email, targetTag) {
        const container = targetTag.parentElement;
        const tagToMove = container.querySelector(`[data-email="${email}"]`);
        
        if (tagToMove && tagToMove !== targetTag) {
            const rect = targetTag.getBoundingClientRect();
            const mouseY = event.clientY;
            const tagCenter = rect.top + rect.height / 2;
            
            if (mouseY < tagCenter) {
                container.insertBefore(tagToMove, targetTag);
            } else {
                container.insertBefore(tagToMove, targetTag.nextSibling);
            }
        }
    }

    function isValidEmail(email) {
        const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
        return emailRegex.test(email);
    }

    function getAllEmails(containerId) {
        const container = document.getElementById(containerId);
        if (!container) return '';
        
        const tags = container.querySelectorAll('.email-tag');
        return Array.from(tags).map(tag => tag.dataset.email).join(', ');
    }

    function showMessage(message, type) {
        if (messageBox) {
            messageBox.textContent = message;
            messageBox.className = 'message-box ' + type;
            messageBox.style.display = 'block';

            setTimeout(() => {
                messageBox.style.display = 'none';
            }, 5000);
        }
    }
    window.showMessage = showMessage;

    if (emailForm) {
        emailForm.addEventListener('submit', async function(event) {
            event.preventDefault();

            if (!quill) {
                window.showMessage('編輯器未初始化。', 'error');
                return;
            }

            emailBodyHidden.value = quill.root.innerHTML;

            const to = getAllEmails('toEmails');
            const cc = getAllEmails('ccEmails');
            const bcc = getAllEmails('bccEmails');
            const subject = subjectInput.value;
            const emailBody = emailBodyHidden.value;

            if (!to || !subject || !emailBody || emailBody === '<p><br></p>') {
                window.showMessage('請填寫所有必填欄位 (收件人、主旨、郵件內容)。', 'error');
                return;
            }

            try {
                const response = await fetch('/send_email', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        to: to,
                        cc: cc,
                        bcc: bcc,
                        subject: subject,
                        body: emailBody
                    }),
                });

                const result = await response.json();

                if (response.ok && result.success) {
                    window.showMessage('郵件已成功寄送！', 'success');
                    emailForm.reset();
                    quill.setContents([]);
                    emailBodyHidden.value = '';
                    // 清空所有標籤
                    const containers = [toEmailsContainer, ccEmailsContainer, bccEmailsContainer];
                    containers.forEach(container => {
                        const tags = container.querySelectorAll('.email-tag');
                        tags.forEach(tag => tag.remove());
                    });
                } else {
                    window.showMessage('郵件寄送失敗: ' + (result.message || '未知錯誤'), 'error');
                }
            } catch (error) {
                console.error('郵件寄送連線錯誤:', error);
                window.showMessage('郵件寄送失敗，請檢查網路或稍後再試。', 'error');
            }
        });
    }

    // 3. CC/BCC 顯示/隱藏邏輯
    const toggleBccButton = document.getElementById('toggleBccButton');
    const bccGroup = document.getElementById('bccGroup');

    if (toggleBccButton && bccGroup) {
        toggleBccButton.addEventListener('click', function() {
            if (bccGroup.style.display === 'none') {
                bccGroup.style.display = 'block';
                toggleBccButton.classList.add('active');
            } else {
                bccGroup.style.display = 'none';
                toggleBccButton.classList.remove('active');
                // 隱藏時清空 BCC 標籤和內容
                const bccTags = bccEmailsContainer.querySelectorAll('.email-tag');
                bccTags.forEach(tag => tag.remove());
                bccInput.value = '';
            }
        });
    }

    // 4. 模板功能 (模態視窗邏輯)
    const openTemplateModalButton = document.getElementById('openTemplateModalButton');
    const templateModal = document.getElementById('templateModal');
    const closeTemplateModalButton = templateModal ? templateModal.querySelector('.close-button') : null;
    const templateListInModal = document.getElementById('templateListInModal');
    const clearTemplateButton = document.getElementById('clearTemplateButton');
    const noTemplatesMessageModal = document.getElementById('noTemplatesMessageModal');

    async function loadTemplatesForModal() {
        if (!templateListInModal || !noTemplatesMessageModal) return;

        try {
            const response = await fetch('/api/templates');
            const templates = await response.json();

            templateListInModal.innerHTML = '';

            if (templates.length === 0) {
                noTemplatesMessageModal.style.display = 'block';
                return;
            } else {
                noTemplatesMessageModal.style.display = 'none';
            }

            templates.forEach(template => {
                const templateItem = document.createElement('div');
                templateItem.classList.add('template-list-item-modal');
                templateItem.dataset.html = template.html;
                templateItem.dataset.subject = template.subject;

                templateItem.innerHTML = `
                    <h4>${template.name}</h4>
                    <p>主旨: ${template.subject || '(無主旨)'}</p>
                `;
                templateListInModal.appendChild(templateItem);

                templateItem.addEventListener('click', () => {
                    applyTemplate(template.html, template.subject);
                });
            });
        } catch (error) {
            console.error('加載模板失敗:', error);
            window.showMessage('加載模板列表失敗。', 'error');
        }
    }

    function applyTemplate(htmlContent, subjectContent) {
        if (!quill) {
            window.showMessage('編輯器未初始化，無法應用模板。', 'error');
            return;
        }
        quill.setContents(quill.clipboard.convert(htmlContent));
        subjectInput.value = subjectContent || '';
        if (templateModal) {
            templateModal.style.display = 'none';
        }
        window.showMessage('模板已成功應用。', 'info');
    }

    if (openTemplateModalButton && templateModal) {
        openTemplateModalButton.addEventListener('click', async function() {
            templateModal.style.display = 'flex';
            await loadTemplatesForModal();
        });
    }

    if (closeTemplateModalButton && templateModal) {
        closeTemplateModalButton.addEventListener('click', function() {
            templateModal.style.display = 'none';
        });
    }

    if (templateModal) {
        window.addEventListener('click', function(event) {
            if (event.target == templateModal) {
                templateModal.style.display = 'none';
            }
        });
    }

    if (clearTemplateButton) {
        clearTemplateButton.addEventListener('click', function() {
            if (!quill) {
                window.showMessage('編輯器未初始化，無法清空。', 'error');
                return;
            }
            if (confirm('確定要清空當前郵件內容和主旨嗎？')) {
                quill.setContents([]);
                emailBodyHidden.value = '';
                subjectInput.value = '';
                if (templateModal) {
                    templateModal.style.display = 'none';
                }
                window.showMessage('郵件內容和主旨已清空。', 'info');
            }
        });
    }

    const saveTemplateButton = document.getElementById('saveTemplateButton');
    if (saveTemplateButton) {
        saveTemplateButton.addEventListener('click', async function() {
            if (!quill) {
                window.showMessage('編輯器未初始化，無法儲存模板。', 'error');
                return;
            }

            const htmlContent = quill.root.innerHTML;
            const subjectContent = subjectInput.value.trim();

            if (!htmlContent || htmlContent === '<p><br></p>') {
                window.showMessage('請先輸入郵件內容再儲存為模板。', 'error');
                return;
            }

            const templateName = prompt('請輸入模板名稱：');
            if (!templateName || templateName.trim() === '') {
                window.showMessage('模板名稱不能為空。', 'error');
                return;
            }

            try {
                const response = await fetch('/api/templates', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        name: templateName.trim(),
                        subject: subjectContent,
                        html: htmlContent
                    }),
                });

                const result = await response.json();

                if (response.ok && result.success) {
                    window.showMessage('模板已成功儲存！', 'success');
                } else {
                    window.showMessage('儲存模板失敗: ' + (result.message || '未知錯誤'), 'error');
                }
            } catch (error) {
                console.error('儲存模板連線錯誤:', error);
                window.showMessage('儲存模板失敗，請檢查網路或稍後再試。', 'error');
            }
        });
    }

    // 5. 電子郵件群組模態視窗邏輯
    if (addGroupButton) {
        addGroupButton.addEventListener('click', function() {
            currentInputTarget = 'toEmails';
            if (groupList) {
                groupList.innerHTML = '';
            }
            groupModal.style.display = 'flex';
            loadEmailGroups();
        });
    }

    if (addGroupButtonCc) {
        addGroupButtonCc.addEventListener('click', function() {
            currentInputTarget = 'ccEmails';
            if (groupList) {
                groupList.innerHTML = '';
            }
            groupModal.style.display = 'flex';
            loadEmailGroups();
        });
    }

    if (addGroupButtonBcc) {
        addGroupButtonBcc.addEventListener('click', function() {
            currentInputTarget = 'bccEmails';
            if (groupList) {
                groupList.innerHTML = '';
            }
            groupModal.style.display = 'flex';
            loadEmailGroups();
        });
    }

    function updateSelectAllButtonText() {
        if (!selectAllGroupsButton || !groupList) return;
        const allCheckboxes = groupList.querySelectorAll('.email-checkbox-list input[type="checkbox"]');
        const checkedCheckboxes = groupList.querySelectorAll('.email-checkbox-list input[type="checkbox"]:checked');
        
        if (allCheckboxes.length > 0 && allCheckboxes.length === checkedCheckboxes.length) {
            selectAllGroupsButton.textContent = '取消全選';
        } else {
            selectAllGroupsButton.textContent = '全選';
        }
    }

    async function loadEmailGroups() {
        if (!groupList) return;
        try {
            const response = await fetch('/api/mailboxes');
            const groups = await response.json();
            if (groups.length === 0) {
                groupList.innerHTML = '<p>目前沒有任何群組。</p>';
                return;
            }

            const existingEmails = Array.from(document.getElementById(currentInputTarget).querySelectorAll('.email-tag')).map(tag => tag.dataset.email);

            groupList.innerHTML = ''; // 清空舊內容
            groups.forEach(group => {
                const groupDiv = document.createElement('div');
                groupDiv.classList.add('group-item');
                
                const groupHeader = document.createElement('div');
                groupHeader.classList.add('group-header');
                const groupCheckbox = document.createElement('input');
                groupCheckbox.type = 'checkbox';
                groupCheckbox.classList.add('select-all-group-checkbox');
                groupCheckbox.dataset.groupId = group.id;

                const groupName = document.createElement('h4');
                groupName.classList.add('group-name');
                groupName.textContent = `${group.name} (${group.emails.length})`;

                const groupHeaderLabel = document.createElement('label');
                groupHeaderLabel.appendChild(groupCheckbox);
                groupHeaderLabel.appendChild(groupName);

                groupHeader.appendChild(groupHeaderLabel);
                groupDiv.appendChild(groupHeader);

                const emailList = document.createElement('div');
                emailList.classList.add('email-checkbox-list');

                const validEmails = group.emails.filter(email => {
                    return email && typeof email === 'string' && email.trim() !== '' && email.trim().toLowerCase() !== 'on';
                });
                
                validEmails.forEach(email => {
                    const emailLabel = document.createElement('label');
                    emailLabel.classList.add('email-checkbox-label');
                    
                    const isChecked = existingEmails.includes(email);
                    const checkbox = document.createElement('input');
                    checkbox.type = 'checkbox';
                    
                    // 核心修復：強制賦予一個乾淨的 value
                    checkbox.value = email; 

                    checkbox.dataset.groupId = group.id;
                    checkbox.checked = isChecked;

                    emailLabel.appendChild(checkbox);
                    emailLabel.appendChild(document.createTextNode(email));
                    
                    emailList.appendChild(emailLabel);
                });
                groupDiv.appendChild(emailList);
                groupList.appendChild(groupDiv);
            });

            document.querySelectorAll('.group-item').forEach(groupItem => {
                const groupCheckbox = groupItem.querySelector('.select-all-group-checkbox');
                const emailCheckboxes = groupItem.querySelectorAll('.email-checkbox-list input[type="checkbox"]');
                
                if (emailCheckboxes.length === 0) {
                    groupCheckbox.disabled = true;
                    groupCheckbox.checked = false;
                } else {
                    const allChecked = Array.from(emailCheckboxes).every(cb => cb.checked);
                    groupCheckbox.checked = allChecked;
                }
            });

            updateSelectAllButtonText(); // 載入後更新按鈕文字

        } catch (error) {
            console.error('加載電子郵件群組失敗:', error);
            window.showMessage('加載群組列表失敗。', 'error');
        }
    }
    
    if (groupList) {
        groupList.addEventListener('change', (event) => {
            const target = event.target;
            if (target.type === 'checkbox') {
                if (target.classList.contains('select-all-group-checkbox')) {
                    const groupId = target.dataset.groupId;
                    const emailCheckboxes = groupList.querySelectorAll(`.email-checkbox-list input[data-group-id="${groupId}"]`);
                    emailCheckboxes.forEach(emailCheckbox => {
                        emailCheckbox.checked = target.checked;
                    });
                } else {
                    const groupId = target.dataset.groupId;
                    const groupCheckbox = groupList.querySelector(`.select-all-group-checkbox[data-group-id="${groupId}"]`);
                    const emailCheckboxes = groupList.querySelectorAll(`.email-checkbox-list input[data-group-id="${groupId}"]`);
                    const allChecked = Array.from(emailCheckboxes).every(cb => cb.checked);
                    if (groupCheckbox) {
                        groupCheckbox.checked = allChecked;
                    }
                }
                updateSelectAllButtonText(); // 勾選狀態改變時更新按鈕文字
            }
        });
    }

    if (selectAllGroupsButton) {
        selectAllGroupsButton.addEventListener('click', function() {
            const checkboxes = groupList.querySelectorAll('input[type="checkbox"]');
            const checkedCheckboxes = groupList.querySelectorAll('input[type="checkbox"]:checked');
            
            // 檢查是否有任何一個 checkbox 被勾選
            const isAnyChecked = checkedCheckboxes.length > 0;
            
            checkboxes.forEach(cb => {
                if (!cb.disabled) {
                    cb.checked = !isAnyChecked;
                }
            });
            updateSelectAllButtonText(); // 點擊後更新按鈕文字
        });
    }

    if (addSelectedEmailsButton) {
        addSelectedEmailsButton.addEventListener('click', function() {
            const checkboxes = groupList.querySelectorAll('input[type="checkbox"]:checked');
            const selectedEmails = Array.from(checkboxes).map(cb => cb.value);

            const container = document.getElementById(currentInputTarget);
            if (container) {
                // 清空原有的標籤，然後重新加入選中的標籤
                const existingTags = container.querySelectorAll('.email-tag');
                existingTags.forEach(tag => tag.remove());
                selectedEmails.forEach(email => {
                    const emailTag = createEmailTag(email);
                    if (emailTag) {
                        const inputElement = container.querySelector('.email-input');
                        container.insertBefore(emailTag, inputElement);
                    }
                });
            }

            groupModal.style.display = 'none';
            window.showMessage(`已成功新增 ${selectedEmails.length} 個電子郵件。`, 'success');
        });
    }

    if (groupModalCloseButton) {
        groupModalCloseButton.addEventListener('click', function() {
            groupModal.style.display = 'none';
        });
    }

    if (groupModal) {
        window.addEventListener('click', function(event) {
            if (event.target == groupModal) {
                groupModal.style.display = 'none';
            }
        });
    }

    if (toEmailsContainer && ccEmailsContainer && bccEmailsContainer) {
        initializeEmailTags();
    }

// 新增此函式到 script.js 末尾
function makeTagEditable(tag) {
    const originalEmail = tag.dataset.email;
    const textSpan = tag.querySelector('.email-text');
    const removeBtn = tag.querySelector('.remove-email-btn');
    
    // 建立臨時輸入框
    const editInput = document.createElement('input');
    editInput.type = 'text';
    editInput.className = 'email-edit-input';
    editInput.value = originalEmail;
    
    // 隱藏原有文字與刪除按鈕
    textSpan.style.display = 'none';
    removeBtn.style.display = 'none';
    tag.classList.add('editing');
    tag.appendChild(editInput);
    
    // 聚焦並選取內容
    editInput.focus();
    editInput.select();

    const saveEdit = () => {
        const newEmail = editInput.value.trim();
        // 使用您原本定義的 isValidEmail 進行驗證
        if (newEmail && isValidEmail(newEmail)) {
            const container = tag.parentElement;
            const isDuplicate = Array.from(container.querySelectorAll('.email-tag'))
                .some(t => t !== tag && t.dataset.email === newEmail);

            if (isDuplicate) {
                window.showMessage('此電子郵件已重複。', 'error');
                revertEdit();
            } else {
                tag.dataset.email = newEmail;
                textSpan.textContent = newEmail;
                revertEdit();
            }
        } else if (!newEmail) {
            tag.remove();
        } else {
            window.showMessage('請輸入有效的電子郵件地址。', 'error');
            revertEdit();
        }
    };

    const revertEdit = () => {
        if (editInput.parentNode) editInput.remove();
        textSpan.style.display = '';
        removeBtn.style.display = '';
        tag.classList.remove('editing');
    };

    // 綁定鍵盤事件
    editInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') { e.preventDefault(); saveEdit(); }
        if (e.key === 'Escape') { revertEdit(); }
    });

    // 失去焦點時自動儲存
    editInput.addEventListener('blur', saveEdit);
}
});