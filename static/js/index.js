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