const BOARD_SIZE = 8;
const MINE_COUNT = 10;

let board = [];
let gameOver = false;
let score = 0;

function createBoard() {
    board = Array(BOARD_SIZE).fill().map(() => Array(BOARD_SIZE).fill(0));
    placeMines();
    calculateNumbers();
}

function placeMines() {
    let minesPlaced = 0;
    while (minesPlaced < MINE_COUNT) {
        const row = Math.floor(Math.random() * BOARD_SIZE);
        const col = Math.floor(Math.random() * BOARD_SIZE);
        if (board[row][col] !== 'M') {
            board[row][col] = 'M';
            minesPlaced++;
        }
    }
}

function calculateNumbers() {
    for (let row = 0; row < BOARD_SIZE; row++) {
        for (let col = 0; col < BOARD_SIZE; col++) {
            if (board[row][col] !== 'M') {
                board[row][col] = countAdjacentMines(row, col);
            }
        }
    }
}

function countAdjacentMines(row, col) {
    let count = 0;
    for (let i = -1; i <= 1; i++) {
        for (let j = -1; j <= 1; j++) {
            const newRow = row + i;
            const newCol = col + j;
            if (newRow >= 0 && newRow < BOARD_SIZE && newCol >= 0 && newCol < BOARD_SIZE) {
                if (board[newRow][newCol] === 'M') {
                    count++;
                }
            }
        }
    }
    return count;
}

function revealCell(row, col) {
    if (gameOver || row < 0 || row >= BOARD_SIZE || col < 0 || col >= BOARD_SIZE) return;

    const cell = document.querySelector(`[data-row="${row}"][data-col="${col}"]`);
    if (cell.classList.contains('revealed')) return;

    cell.classList.add('revealed');

    if (board[row][col] === 'M') {
        cell.classList.add('mine');
        cell.textContent = '💣';
        gameOver = true;
        alert('遊戲結束！你踩到地雷了。');
    } else {
        const mineCount = board[row][col];
        if (mineCount > 0) {
            cell.textContent = mineCount;
            score += mineCount; // 增加分數
        } else {
            for (let i = -1; i <= 1; i++) {
                for (let j = -1; j <= 1; j++) {
                    revealCell(row + i, col + j);
                }
            }
        }
    }
}

function renderBoard() {
    const gameBoard = document.getElementById('game-board');
    gameBoard.innerHTML = '';

    for (let row = 0; row < BOARD_SIZE; row++) {
        for (let col = 0; col < BOARD_SIZE; col++) {
            const cell = document.createElement('div');
            cell.classList.add('cell');
            cell.dataset.row = row;
            cell.dataset.col = col;
            cell.addEventListener('click', () => revealCell(row, col));
            gameBoard.appendChild(cell);
        }
    }
}

function resetGame() {
    gameOver = false;
    score = 0; // 重置分數
    createBoard();
    renderBoard();
}

// 初始化 Telegram Web App
Telegram.WebApp.ready();

// 發送分數到 Telegram Bot
document.getElementById('sendScoreButton').addEventListener('click', function () {
    if (gameOver) {
        Telegram.WebApp.sendData(JSON.stringify({ score: score }));
    } else {
        alert('請先完成遊戲！');
    }
});

resetGame();