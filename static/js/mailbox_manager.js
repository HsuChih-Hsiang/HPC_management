// static/js/mailbox_manager.js

document.addEventListener('DOMContentLoaded', function() {
    // --- 信箱管理 JS ---
    async function fetchGroups() {
        const res = await fetch('/api/mailboxes');
        return res.json();
    }

    async function renderGroups() {
        const groupList = document.getElementById('groupList');
        const unassignedEmailList = document.getElementById('unassignedEmailList');
        if (!groupList || !unassignedEmailList) return;

        groupList.innerHTML = '';
        unassignedEmailList.innerHTML = '';
        const groups = await fetchGroups();

        if (groups.length === 0) {
            groupList.innerHTML = '<p>目前沒有分組。</p>';
            unassignedEmailList.innerHTML = '<p>目前沒有待分組信箱。</p>';
            return;
        }

        // 先處理待分組信箱（id=0）
        const unassignedGroup = groups.find(g => g.name === "待分組信箱")
        if (unassignedGroup && unassignedGroup.emails.length > 0) {
            unassignedEmailList.innerHTML = unassignedGroup.emails.map(email => `
                <div class="email-item" draggable="true" ondragstart="onEmailDragStart(event, '${email}')">
                    <span>${email}</span>
                    <button class="delete-btn" onclick="deleteEmail(${unassignedGroup.id}, '${email}')">刪除</button>
                </div>
            `).join('');
        } else {
            unassignedEmailList.innerHTML = '<p>目前沒有待分組信箱。</p>';
        }

        // 只渲染 id !== 0 的分組到右側
        groups.filter(g => g.name !== "待分組信箱").forEach(group => {
            const groupDiv = document.createElement('div');
            groupDiv.className = 'group-item';
            groupDiv.innerHTML = `
                <div class="group-header">
                    <strong>${group.name}</strong>
                    <button class="delete-btn" onclick="deleteGroup(${group.id})">刪除分組</button>
                </div>
                <div class="email-list" id="email-list-${group.id}">
                    ${group.emails.map(email => `
                        <div class="email-item">
                            <span>${email}</span>
                            <button class="delete-btn" onclick="deleteEmail(${group.id}, '${email}')">刪除</button>
                        </div>
                    `).join('')}
                </div>
                <form class="email-form add-email-form" onsubmit="addEmail(event, ${group.id})">
                    <input type="email" placeholder="新增信箱" required id="add-email-input-${group.id}" ondragover="onInputDragOver(event)" ondrop="onInputDrop(event, ${group.id})">
                    <button type="submit" class="save-template-button">新增信箱</button>
                </form>
            `;
            groupList.appendChild(groupDiv);
        });
    }

    async function addGroup(event) {
        event.preventDefault();
        const newGroupNameInput = document.getElementById('newGroupName');
        if (!newGroupNameInput) return; // Add null check
        const name = newGroupNameInput.value.trim();
        if (!name) return;

        try {
            const response = await fetch('/api/mailboxes', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name })
            });
            if (!response.ok) {
                console.error('Failed to add group:', await response.text());
                // Optionally show an error message to the user
            }
        } catch (error) {
            console.error('Error adding group:', error);
        } finally {
            newGroupNameInput.value = '';
            renderGroups();
        }
    }

    async function deleteGroup(id) {
        if (!confirm('確定要刪除此分組？')) return;
        try {
            const response = await fetch(`/api/mailboxes/${id}`, { method: 'DELETE' });
            if (!response.ok) {
                console.error('Failed to delete group:', await response.text());
            }
        } catch (error) {
            console.error('Error deleting group:', error);
        } finally {
            renderGroups();
        }
    }

    async function addEmail(event, groupId) {
        event.preventDefault();
        const input = document.getElementById(`add-email-input-${groupId}`);
        if (!input) return; // Add null check
        const email = input.value.trim();
        if (!email) return;

        try {
            const response = await fetch(`/api/mailboxes/${groupId}/add_email`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email })
            });
            if (!response.ok) {
                console.error('Failed to add email:', await response.text());
            }
        } catch (error) {
            console.error('Error adding email:', error);
        } finally {
            input.value = '';
            renderGroups();
        }
    }

    async function deleteEmail(groupId, email) {
        if (!confirm(`確定要從此分組中刪除郵箱 ${email} 嗎？`)) return;
        try {
            const response = await fetch(`/api/mailboxes/${groupId}/delete_email`, {
                method: 'DELETE',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email })
            });
            if (!response.ok) {
                console.error('Failed to delete email:', await response.text());
            }
        } catch (error) {
            console.error('Error deleting email:', error);
        } finally {
            renderGroups();
        }
    }

    // 拖曳事件處理
    window.onEmailDragStart = function(event, email) {
        event.dataTransfer.setData('text/plain', email);
    };
    window.onInputDragOver = function(event) {
        event.preventDefault();
    };
    window.onInputDrop = function(event, groupId) {
        event.preventDefault();
        const email = event.dataTransfer.getData('text/plain');
        const input = document.getElementById(`add-email-input-${groupId}`);
        if (input) {
            input.value = email;
        }
    };

    // 將這些函式附加到 window 物件，以便在動態生成的 HTML 中可以直接調用
    window.deleteGroup = deleteGroup;
    window.addEmail = addEmail;
    window.deleteEmail = deleteEmail;

    const addGroupForm = document.getElementById('addGroupForm');
    if (addGroupForm) {
        addGroupForm.addEventListener('submit', addGroup);
    }

    // 初始化渲染分組列表
    renderGroups();
});