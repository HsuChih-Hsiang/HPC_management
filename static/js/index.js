document.addEventListener('DOMContentLoaded', function() {
    // 1. 側邊導航選單邏輯
    const menuButton = document.getElementById('menuButton');
    const sideMenu = document.getElementById('sideMenu');
    const closeMenuButton = document.getElementById('closeMenuButton');

    if (menuButton) {
        menuButton.addEventListener('click', function() {
            sideMenu.classList.add('open');
        });
    }

    if (closeMenuButton) {
        closeMenuButton.addEventListener('click', function() {
            sideMenu.classList.remove('open');
        });
    }

    window.addEventListener('click', function(event) {
        if (sideMenu && menuButton && !sideMenu.contains(event.target) && !menuButton.contains(event.target) && sideMenu.classList.contains('open')) {
            sideMenu.classList.remove('open');
        }
    });
});

document.addEventListener("DOMContentLoaded", function() {
    // 取得當前頁面路徑，例如 "/batch_sending"
    const currentPath = window.location.pathname;
    
    // 尋找選單中所有連結
    const menuItems = document.querySelectorAll('.side-menu nav ul li a');
    
    menuItems.forEach(item => {
        // 移除所有項目的 active 類別
        item.classList.remove('active');
        
        // 如果連結的 href 符合當前路徑，則加上 active
        if (item.getAttribute('href') === currentPath) {
            item.classList.add('active');
        }
    });
});