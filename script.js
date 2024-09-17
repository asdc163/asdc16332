let tg = window.Telegram.WebApp;

// 初始化 Telegram Web App
tg.ready();

// 設置主按鈕
tg.MainButton.setText('發送分數').hide();

function updateMainButton() {
    if (gameOver) {
        tg.MainButton.setText(`發送分數: ${score}`).show();
    } else {
        tg.MainButton.hide();
    }
}

function revealCell(row, col) {
    // ... 原有的邏輯 ...
    
    if (board[row][col] === 'M') {
        cell.classList.add('mine');
        cell.textContent = '💣';
        gameOver = true;
        alert('遊戲結束！你踩到地雷了。');
        updateMainButton();
    } else {
        // ... 原有的邏輯 ...
    }
    updateMainButton();
}

function resetGame() {
    gameOver = false;
    score = 0;
    createBoard();
    renderBoard();
    updateMainButton();
}

// 發送分數到 Telegram Bot
tg.MainButton.onClick(function () {
    if (gameOver) {
        tg.sendData(JSON.stringify({ score: score }));
    }
});

// 移除舊的發送分數按鈕事件監聽器
document.getElementById('sendScoreButton').remove();

resetGame();
