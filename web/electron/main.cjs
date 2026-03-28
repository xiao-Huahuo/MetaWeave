// web/electron/main.cjs
const { app, BrowserWindow } = require('electron');
const path = require('path');
const isDev = require('electron-is-dev');

function createWindow() {
  const win = new BrowserWindow({
    width: 1200,
    height: 800,
    frame: true,
    title: "MetaWeave",
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  // 根据环境加载不同的 URL
  if (isDev) {
    win.loadURL('http://localhost:5173');
    // 开发模式下自动打开开发者工具
    win.webContents.openDevTools();
  } else {
    // 生产环境加载打包后的静态文件
    win.loadFile(path.join(__dirname, '../dist/index.html'));
  }
}

app.whenReady().then(createWindow);

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
