# Render Ready Code - Same UI, Same Logic, Just changed config to Environment Variables

import asyncio
import re
import os
from datetime import datetime
from flask import Flask, render_template_string, request, jsonify
from telethon import TelegramClient, events
from telethon.sessions import StringSession

app = Flask(__name__)

# Render-এর Environment Variable থেকে ডেটা নেবে
api_id = int(os.environ.get('API_ID', 0))
api_hash = os.environ.get('API_HASH', '')
session_str = os.environ.get('SESSION_STR', '')
TARGET_BOT = '@Taskl1_bot'

client = TelegramClient(StringSession(session_str), api_id, api_hash)

clicked_buttons = set() 
latest_message = "Username Creating....." 

is_username_shown = False 
is_waiting_for_report = False 

@client.on(events.NewMessage(from_users=TARGET_BOT))
async def on_bot_reply(event):
    global latest_message, is_username_shown, is_waiting_for_report
    text = event.text or ""
    
    if not text.strip():
        return

    lines = text.strip().split('\n')
    
    for line in lines:
        if "Login:" in line:
            username = line.replace("Login:", "").replace("`", "").strip()
            latest_message = username 
            is_username_shown = True 
            is_waiting_for_report = False
            return 

    if is_waiting_for_report:
        display_text = lines[0].strip()
        for line in lines:
            if "received" in line.lower() or "report" in line.lower():
                display_text = line.strip()
                break
                
        if "Press the button" in text:
            latest_message = "Submit Done ✅"
        else:
            latest_message = display_text
            
        is_waiting_for_report = False 
        is_username_shown = False 
        return 

async def find_and_click_button(btn_text):
    try:
        messages = await client.get_messages(TARGET_BOT, limit=10)
        for message in messages:
            if message.buttons:
                for row in message.buttons:
                    for btn in row:
                        btn_str = getattr(btn, 'text', '')
                        if hasattr(btn_str, 'text'): btn_str = btn_str.text
                        
                        btn_key = f"{message.id}_{btn_str}"
                        is_match = False
                        
                        if "$0" in btn_text:
                            if re.search(r'\$0', str(btn_str)):
                                is_match = True
                        elif str(btn_text).lower() in str(btn_str).lower():
                            is_match = True
                            
                        if is_match:
                            if btn_key in clicked_buttons:
                                return "already_clicked"
                            
                            await btn.click()
                            clicked_buttons.add(btn_key) 
                            return True
        return False
    except Exception as e:
        print(f"Click Error: {e}")
        return False

# ==========================================
# HTML (আপনার আগের কোডের মতোই আছে)
# ==========================================
HTML_PAGE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Telegram Control Panel</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; padding: 10px; background-color: #e9ebee; margin: 0; display: flex; justify-content: center; }
        .container { width: 100%; max-width: 500px; box-sizing: border-box; }
        .live-display { text-align: center; padding: 10px; background: linear-gradient(135deg, #e3f2fd, #bbdefb); border: 2px solid #64b5f6; border-radius: 10px; margin-bottom: 10px; box-shadow: 0 4px 10px rgba(0,0,0,0.1); min-height: 90px; display: flex; flex-direction: column; justify-content: center; align-items: center; box-sizing: border-box; }
        .live-display h4 { margin: 0 0 5px 0; font-size: clamp(10px, 3vw, 12px); color: #1565c0; text-transform: uppercase; white-space: nowrap;}
        .live-value { font-size: clamp(16px, 5vw, 22px); font-weight: bold; color: #1565c0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; cursor: pointer; padding: 8px 35px 8px 10px; border-radius: 8px; width: 100%; box-sizing: border-box; background: #ffffff; border: 2px solid #90caf9; position: relative; }
        .live-value.success-text { color: #2e7d32; background: #e8f5e9; border-color: #81c784; text-align: center; padding: 8px 10px;} 
        .copy-icon { position: absolute; right: 10px; top: 50%; transform: translateY(-50%); font-size: 18px; color: #1565c0; }
        .copied-msg { font-size: 10px; color: #28a745; font-weight: bold; display: none; position: absolute; bottom: -18px;}
        .pulse { animation: pulseAnim 1s infinite; }
        @keyframes pulseAnim { 0% { opacity: 1; } 50% { opacity: 0.5; } 100% { opacity: 1; } }
        .send-all-2fa-btn { background: #0078FF; color: white; border: none; padding: 12px; border-radius: 8px; cursor: pointer; font-weight: bold; font-size: clamp(14px, 4vw, 18px); width: 100%; margin-bottom: 10px; box-shadow: 0 4px 8px rgba(0, 120, 255, 0.3); transition: 0.2s; white-space: nowrap; }
        .send-all-2fa-btn:hover { background: #005bb5; }
        .send-all-2fa-btn:disabled { background: #ccc; cursor: not-allowed; }
        .manual-area { background: #e8f5e9; padding: 12px; border-radius: 8px; margin-bottom: 5px; border: 1px solid #81c784; display: flex; flex-direction: column;}
        .manual-area h4 { margin: 0 0 10px 0; font-size: clamp(12px, 3.5vw, 14px); color: #2e7d32; text-align: center; white-space: nowrap;}
        .manual-input-group { display: flex; flex-direction: column; gap: 10px; }
        .manual-input-group textarea { width: 100%; height: 130px; padding: 10px; border: 2px solid #66bb6a; border-radius: 6px; font-size: 14px; outline: none; box-sizing: border-box; resize: none; font-family: inherit; }
        .manual-input-group textarea:focus { border-color: #2e7d32; }
        .manual-send-btn { background: #43a047; color: white; border: none; padding: 10px; border-radius: 6px; cursor: pointer; font-weight: bold; font-size: clamp(14px, 4vw, 16px); width: 100%; white-space: nowrap;}
        .manual-send-btn:hover { background: #2e7d32; }
        .manual-send-btn:disabled { background: #ccc; cursor: not-allowed; }
        .webview-container { width: 100%; height: 220px; border: 2px solid #90caf9; border-radius: 10px; overflow: hidden; box-shadow: 0 4px 10px rgba(0,0,0,0.1); background: white; margin-top: 5px; }
        .webview-container iframe { width: 100%; height: 100%; border: none; display: block; pointer-events: auto; }
    </style>
</head>
<body>
    <div class="container">
        <div class="live-display">
            <h4>Trending Academy Limited </h4>
            <div id="loader" style="display:none; flex-direction:column; align-items:center; gap:5px;">
                <div style="width: 20px; height: 20px; border: 2px solid rgba(21, 101, 192, 0.15); border-top: 2px solid #1565c0; border-radius: 50%; animation: pulseAnim 1s infinite;"></div>
                <div style="font-size: 11px; font-weight: bold; color: #1565c0;">Processing...</div>
            </div>
            <div class="live-value" id="loginDisplay" onclick="copyToClipboard()" style="display:none;">
                <span id="usernameText">Username Creating Robot</span>
            </div>
            <div class="copied-msg" id="copyMsg">✔ Copied </div>
        </div>
        <button id="btnAll2FA" class="send-all-2fa-btn" onclick="startAutoSequence(true)">Get Username</button>
        <div class="manual-area">
            <h4>Cookies Submit Please</h4>
            <div class="manual-input-group">
                <textarea id="manualMsg" placeholder="Paste your Instagram Cookies..."></textarea>
                <button id="btnManual" class="manual-send-btn" onclick="sendManualMsg()">Submit Now</button>
            </div>
        </div>
        <div class="webview-container">
            <iframe src="https://ariyanth1000-jpg.github.io/Cookies-panel/" allow="clipboard-write" title="Cookies Panel Web View"></iframe>
        </div>
    </div>
    
    <script>
        let lastLoginVal = "Processing..";
        async function fetchLogin() {
            try {
                const res = await fetch('/get_login');
                const data = await res.json();
                if (data.login && data.login !== lastLoginVal) {
                    lastLoginVal = data.login;
                    const display = document.getElementById('loginDisplay');
                    const textSpan = document.getElementById('usernameText');
                    const loader = document.getElementById('loader');
                    if (lastLoginVal.includes("Successful") || lastLoginVal.includes("Submit Done")) {
                        loader.style.display = 'none'; display.style.display = 'block'; textSpan.innerText = lastLoginVal; display.classList.add('success-text');
                        const existingIcon = display.querySelector('.copy-icon'); if (existingIcon) existingIcon.remove();
                        display.classList.add('pulse'); setTimeout(() => display.classList.remove('pulse'), 2000);
                    } else {
                        loader.style.display = 'none'; display.style.display = 'block'; textSpan.innerText = lastLoginVal; display.classList.remove('success-text');
                        if (!display.querySelector('.copy-icon') && lastLoginVal !== "অপেক্ষা করা হচ্ছে..." && lastLoginVal !== "Username Creating...") {
                            display.innerHTML = `<span id="usernameText">${lastLoginVal}</span><span class="copy-icon">📋</span>`;
                        }
                        if (lastLoginVal !== "Username Creating...") {
                            display.classList.add('pulse'); setTimeout(() => display.classList.remove('pulse'), 2000);
                        }
                    }
                }
            } catch(e) {}
        }
        setInterval(fetchLogin, 100);
        window.onload = fetchLogin;
        function copyToClipboard() {
            let text = document.getElementById('usernameText').innerText;
            if (text === "Username Creating....." || text === "" || text.includes("Report") || text.includes("Done")) return;
            navigator.clipboard.writeText(text).then(() => {
                const copyMsg = document.getElementById('copyMsg'); copyMsg.style.display = 'block'; setTimeout(() => { copyMsg.style.display = 'none'; }, 2000);
            }).catch(err => {});
        }
        async function startAutoSequence(with2FA) {
            const btnAll2FA = document.getElementById('btnAll2FA'); btnAll2FA.disabled = true;
            const originalText = "Get Username"; const display = document.getElementById('loginDisplay'); const loader = document.getElementById('loader');
            display.style.display = 'none'; loader.style.display = 'flex';
            const buttons = [{ text: "Tasks", isStart: true, percent: 25 },{ text: "$0", isStart: false, percent: 50 },{ text: "Create Inst (No mail)", isStart: false, percent: 75 },{ text: "Start", isStart: false, percent: 100 }];
            for (let i = 0; i < buttons.length; i++) {
                const item = buttons[i]; btnAll2FA.innerText = `Processing... ${item.percent}%`;
                try { await fetch('/click_button_by_text', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({btn_text: item.text, is_start: item.isStart}) }); } catch (e) {}
                if (i < buttons.length - 1) await new Promise(resolve => setTimeout(resolve, 2000)); 
            }
            if (with2FA) {
                btnAll2FA.innerText = `Processing... (100%)`; await new Promise(resolve => setTimeout(resolve, 2000)); 
                try { await fetch('/send_2fa', { method: 'POST' }); } catch(e) {}
            }
            btnAll2FA.innerText = originalText; btnAll2FA.disabled = false;
        }
        async function sendManualMsg() {
            const input = document.getElementById('manualMsg'); const btn = document.getElementById('btnManual'); const text = input.value.trim();
            if(!text || btn.disabled) return;
            btn.disabled = true; btn.innerText = "Processing..";
            const display = document.getElementById('loginDisplay'); const loader = document.getElementById('loader'); display.style.display = 'none'; loader.style.display = 'flex';
            try {
                await fetch('/send_manual_msg', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({text: text}) });
                input.value = ''; await new Promise(resolve => setTimeout(resolve, 2000)); await fetch('/send_manual_registered', { method: 'POST' });
            } catch (e) {}
            setTimeout(() => { btn.disabled = false; btn.innerText = "Submit Now"; }, 5000); 
        }
    </script>
</body>
</html>
'''

@app.route('/')
def index():
    return render_template_string(HTML_PAGE)

@app.route('/get_login')
def get_login():
    global latest_message
    return jsonify({"login": latest_message})

@app.route('/click_button_by_text', methods=['POST'])
def click_button_by_text():
    global latest_message, is_username_shown, is_waiting_for_report
    data = request.get_json()
    btn_text = data.get('btn_text', '')
    is_start = data.get('is_start', False)

    latest_message = "Processing.." 
    is_username_shown = False
    is_waiting_for_report = False

    async def action():
        try:
            if is_start:
                await client.send_message(TARGET_BOT, "/start")
                await asyncio.sleep(2) 
            
            result = await find_and_click_button(btn_text)
            return result
        except Exception as e:
            return False

    result = client.loop.run_until_complete(action())
    
    if result == "already_clicked":
        return jsonify({'status': 'error', 'msg': 'এই বাটনে আগেই ক্লিক করা হয়েছে!'})
    elif result:
        return jsonify({'status': 'ok'})
    else:
        return jsonify({'status': 'error', 'msg': 'বাটনটি পাওয়া যায়নি!'})

@app.route('/send_manual_msg', methods=['POST'])
def send_manual_msg():
    data = request.get_json()
    text = data.get('text', '')
    if not text: return jsonify({'status': 'error'})
    
    async def send_action():
        try:
            await client.send_message(TARGET_BOT, text)
            return True
        except Exception as e:
            return False

    success = client.loop.run_until_complete(send_action())
    return jsonify({'status': 'ok' if success else 'error'})

@app.route('/send_manual_registered', methods=['POST'])
def send_manual_registered():
    global is_waiting_for_report, is_username_shown
    is_waiting_for_report = True 
    is_username_shown = True 
    
    async def send_action():
        try:
            await client.send_message(TARGET_BOT, "✅ Account registered")
            await asyncio.sleep(2) 
            await client.send_message(TARGET_BOT, "✅ Yes, I made 5+ subscriptions")
            return True
        except Exception as e:
            return False

    success = client.loop.run_until_complete(send_action())
    return jsonify({'status': 'ok' if success else 'error'})

@app.route('/send_2fa', methods=['POST'])
def send_2fa():
    async def send_action():
        try:
            await client.send_message(TARGET_BOT, "BQQ6 SYLR NRVW 5DWH")
            return True
        except Exception as e:
            return False

    success = client.loop.run_until_complete(send_action())
    return jsonify({'status': 'ok' if success else 'error'})

# ==========================================
# Startup (Render-এর জন্য connect() এবং dynamic port)
# ==========================================
if __name__ == '__main__':
    print("Connecting..")
    # Render-এ client.start() কাজ করে না, তাই connect() দিতে হবে
    client.connect() 
    print("Success! Website running...")
    
    # Render-এর ডাইনামিক পোর্ট নেওয়া
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False, threaded=False, use_reloader=False)
