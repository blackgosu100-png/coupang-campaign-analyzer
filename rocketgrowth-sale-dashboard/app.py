# -*- coding: utf-8 -*-
"""
로켓그로스 마진 대시보드 - Flask 서버
"""
import os, sys, threading, webbrowser
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
from flask import Flask, jsonify, render_template, send_file, abort, request

# 경로 설정 (PyInstaller exe 호환)
BASE_DIR = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))

app = Flask(__name__, template_folder=os.path.join(BASE_DIR, 'templates'),
                       static_folder=os.path.join(BASE_DIR, 'static'))
app.config['JSON_AS_ASCII'] = False

import wing_api as wd
import coupon_manager as cm

_dl_thread     = None
_coupon_thread = None


# ── 페이지 ──────────────────────────────────────────────────────────────
@app.route('/')
def index():
    return render_template('index.html')


# ── 다운로드 시작 ────────────────────────────────────────────────────────
@app.route('/api/start', methods=['POST'])
def api_start():
    global _dl_thread
    if wd.STATUS['state'] == 'running':
        return jsonify({'ok': False, 'msg': '이미 실행 중입니다'})
    data = request.get_json(force=True) or {}
    start_date = data.get('start_date')
    end_date   = data.get('end_date')
    _dl_thread = threading.Thread(
        target=wd.run_download, args=(start_date, end_date), daemon=True)
    _dl_thread.start()
    return jsonify({'ok': True})


# ── 사용자 계속 신호 ─────────────────────────────────────────────────────
@app.route('/api/continue', methods=['POST'])
def api_continue():
    wd.user_continue()
    return jsonify({'ok': True})


# ── 진행상황 조회 ────────────────────────────────────────────────────────
@app.route('/api/status')
def api_status():
    return jsonify(wd.STATUS)


# ── 다운로드된 파일 목록 ─────────────────────────────────────────────────
@app.route('/api/files')
def api_files():
    folder = wd.STATUS.get('folder')
    if not folder or not os.path.exists(folder):
        return jsonify([])
    files = []
    for fname in wd.STATUS.get('files', []):
        files.append({'name': fname, 'url': f'/api/file/{os.path.basename(folder)}/{fname}'})
    return jsonify(files)


# ── 개별 파일 서빙 ───────────────────────────────────────────────────────
@app.route('/api/file/<folder>/<filename>')
def api_file(folder, filename):
    dl_dir = str(Path.home() / 'Downloads')
    path = os.path.join(dl_dir, folder, filename)
    if not os.path.exists(path):
        abort(404)
    return send_file(path, as_attachment=False,
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


# ── 상태 초기화 ──────────────────────────────────────────────────────────
@app.route('/api/reset', methods=['POST'])
def api_reset():
    wd.STATUS.update({'state':'idle','message':'','progress':0,'total':0,
                      'folder':None,'files':[],'logs':[]})
    return jsonify({'ok': True})



# ════════════════ 쿠폰 관리 API ════════════════

@app.route('/api/coupon/scan', methods=['POST'])
def api_coupon_scan():
    global _coupon_thread
    if cm.STATUS['state'] == 'running':
        return jsonify({'ok': False, 'msg': '이미 실행 중입니다'})
    cm.STATUS.update({'state':'idle','message':'','logs':[],'coupons':[]})
    _coupon_thread = threading.Thread(target=cm.run_coupon_scan, daemon=True)
    _coupon_thread.start()
    return jsonify({'ok': True})


@app.route('/api/coupon/renew', methods=['POST'])
def api_coupon_renew():
    global _coupon_thread
    if cm.STATUS['state'] == 'running':
        return jsonify({'ok': False, 'msg': '이미 실행 중입니다'})
    _coupon_thread = threading.Thread(target=cm.run_coupon_renew, daemon=True)
    _coupon_thread.start()
    return jsonify({'ok': True})


@app.route('/api/coupon/renew-selected', methods=['POST'])
def api_coupon_renew_selected():
    global _coupon_thread
    if cm.STATUS['state'] == 'running':
        return jsonify({'ok': False, 'msg': '이미 실행 중입니다'})
    data = request.get_json(force=True) or {}
    coupons = data.get('coupons', [])
    if not coupons:
        return jsonify({'ok': False, 'msg': '선택된 쿠폰이 없습니다'})
    _coupon_thread = threading.Thread(
        target=cm.run_coupon_renew_selected, args=(coupons,), daemon=True)
    _coupon_thread.start()
    return jsonify({'ok': True})


@app.route('/api/coupon/continue', methods=['POST'])
def api_coupon_continue():
    cm.user_continue()
    return jsonify({'ok': True})


@app.route('/api/coupon/status')
def api_coupon_status():
    return jsonify(cm.STATUS)


@app.route('/api/coupon/settings')
def api_coupon_settings():
    return jsonify(cm.load_settings())


@app.route('/api/coupon/reset', methods=['POST'])
def api_coupon_reset():
    cm.STATUS.update({'state':'idle','message':'','logs':[],'coupons':[]})
    return jsonify({'ok': True})


if __name__ == '__main__':
    # 서버 시작 후 2초 뒤 브라우저 자동 오픈
    def open_browser():
        import time, subprocess; time.sleep(1.5)
        chrome_paths = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        ]
        for p in chrome_paths:
            if os.path.exists(p):
                subprocess.Popen([p, 'http://localhost:5000'])
                return
        webbrowser.open('http://localhost:5000')
    threading.Thread(target=open_browser, daemon=True).start()
    app.run(host='127.0.0.1', port=5000, debug=False, threaded=True)
