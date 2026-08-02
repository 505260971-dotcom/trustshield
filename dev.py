"""TrustShield 开发服务器：一条命令同时启动后端与前端。

用法：
    python dev.py                  # 启动前后端并自动打开浏览器
    python dev.py --no-browser     # 只启动服务，不打开浏览器
    python dev.py --port 5174      # 自定义前端端口
    python dev.py --backend-port 8001   # 自定义后端端口

退出：按 Ctrl+C 同时停止前后端（Windows 上会级联结束 uvicorn 子进程）。

特性：
    - 跨平台（Windows / macOS / Linux），不依赖 PowerShell
    - 后端 uvicorn --reload 自动重载代码
    - 前端 Vite 热更新（HMR），/api 请求自动代理到后端
    - 前后端日志统一输出到当前终端，并区分 [backend] / [frontend] 前缀
    - 端口被占用时自动跳过对应服务的重复启动
"""
from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser

ROOT = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.join(ROOT, 'backend')
FRONTEND_DIR = os.path.join(ROOT, 'frontend')
VITE_BIN = os.path.join(FRONTEND_DIR, 'node_modules', 'vite', 'bin', 'vite.js')


def port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(('127.0.0.1', port)) == 0


def _setup_utf8() -> None:
    """管道/重定向输出时强制 UTF-8，避免 Git Bash 等终端中文乱码。

    真正的控制台（cmd/PowerShell 直接运行）保持默认，由 Python 用
    Unicode 控制台 API 输出，不受代码页影响。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            if not stream.isatty():
                stream.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, ValueError):
            pass


def wait_until_up(url: str, timeout: float = 30.0) -> bool:
    """轮询直到后端返回任何 HTTP 响应（401 等错误响应同样视为已启动）。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2):
                return True
        except urllib.error.HTTPError:
            return True
        except Exception:
            time.sleep(1.0)
    return False


def _reader(stream, prefix: str) -> None:
    for line in iter(stream.readline, ''):
        text = line.rstrip()
        if text:
            print(f'{prefix} {text}', flush=True)


def _spawn(command: list[str], cwd: str, label: str, env: dict | None = None) -> subprocess.Popen:
    proc = subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding='utf-8',
        errors='replace',
        bufsize=1,
    )
    threading.Thread(target=_reader, args=(proc.stdout, label), daemon=True).start()
    return proc


def _stop_tree(proc: subprocess.Popen) -> None:
    """结束进程及其子进程树（uvicorn --reload 在 Windows 上有独立 worker 子进程）。"""
    if proc.poll() is not None:
        return
    if sys.platform == 'win32':
        subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        proc.terminate()


def main() -> int:
    _setup_utf8()
    parser = argparse.ArgumentParser(
        description='TrustShield 开发服务器：同时启动 FastAPI 后端与 Vite 前端')
    parser.add_argument('--no-browser', action='store_true', help='启动服务但不自动打开浏览器')
    parser.add_argument('--port', type=int, default=5173, help='前端端口（默认 5173）')
    parser.add_argument('--backend-port', type=int, default=8000, help='后端端口（默认 8000）')
    args = parser.parse_args()

    # 前置检查：.env 与依赖
    env_file = os.path.join(BACKEND_DIR, '.env')
    if not os.path.isfile(env_file):
        print('⚠ 未发现 backend/.env：请先复制 backend/.env.example 为 backend/.env，并填写')
        print('  AUTH_SECRET、DATA_ENCRYPTION_KEY 与初始管理员信息；模型配置在 backend/data/config.json。')
        print('  未配置时后端仍可启动，但登录、加密存储与审查接口将不可用。')
        print()

    node = shutil.which('node')
    if not node:
        print('✗ 未找到 node，请先安装 Node.js LTS 并确保已加入 PATH。')
        return 1
    if not os.path.isfile(VITE_BIN):
        print('✗ 前端依赖未安装：请在 frontend/ 目录执行 npm install。')
        return 1

    procs: list[subprocess.Popen] = []
    # 子进程日志经管道回流：强制 Python 子进程以 UTF-8 输出，保证中文不乱码
    child_env = {**os.environ, 'PYTHONIOENCODING': 'utf-8', 'PYTHONUTF8': '1'}

    # 后端：FastAPI + uvicorn（--reload 自动重载代码）
    if port_in_use(args.backend_port):
        print(f'• 后端端口 {args.backend_port} 已被占用，视为已在运行，跳过启动。')
    else:
        procs.append(_spawn(
            [sys.executable, '-m', 'uvicorn', 'app.main:app',
             '--reload', '--port', str(args.backend_port)],
            BACKEND_DIR, '[backend]', env=child_env))

    # 前端：Vite 开发服务器（直接以 node 启动，避免 npm 包装进程干扰 Ctrl+C）
    if port_in_use(args.port):
        print(f'• 前端端口 {args.port} 已被占用，视为已在运行，跳过启动。')
    else:
        procs.append(_spawn(
            [node, 'node_modules/vite/bin/vite.js', '--port', str(args.port)],
            FRONTEND_DIR, '[frontend]'))

    if not procs:
        print('✗ 前后端都已在运行，无需重复启动。')
        return 0

    print()
    print('TrustShield 开发服务器已启动：')
    print(f'  前端      http://127.0.0.1:{args.port}')
    print(f'  后端      http://127.0.0.1:{args.backend_port}/api/health')
    print(f'  接口文档  http://127.0.0.1:{args.backend_port}/docs')
    print('  按 Ctrl+C 停止全部服务')
    print()

    if not args.no_browser and wait_until_up(f'http://127.0.0.1:{args.backend_port}/api/health'):
        webbrowser.open(f'http://127.0.0.1:{args.port}')

    try:
        while any(proc.poll() is None for proc in procs):
            time.sleep(1)
    except KeyboardInterrupt:
        print('\n正在停止服务…')
    finally:
        for proc in procs:
            _stop_tree(proc)
        for proc in procs:
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
