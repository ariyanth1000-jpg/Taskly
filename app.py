# Version 6.2 - Fixed Student ID Extraction & Colorful UI

import asyncio
import re
import os
from datetime import datetime, timezone
from flask import Flask, render_template_string, request, jsonify
from telethon import TelegramClient, events
from telethon.sessions import StringSession

app = Flask(__name__)

api_id = int(os.environ.get('API_ID', 0))
api_hash = os.environ.get('API_HASH', '') 
session_str = os.environ.get('SESSION_STR', '')
TARGET_BOT = '@Taskl1_bot'

client = TelegramClient(StringSession(session_str), api_id, api_hash)

clicked_buttons = set()
latest_message = "Welcome" 

is_username_shown = False
is_waiting_for_report = False

# ==========================================
# রিপোর্ট ট্র্যাকিং
# ==========================================
tracked_reports = []
pending_student_ids = []
last_synced_id = 0
is_syncing = False

_FANCY_MAP = {
    'ᴀ':'a','ʙ':'b','ᴄ':'c','ᴅ':'d','ᴇ':'e','ꜰ':'f','ɢ':'g','ʜ':'h','ɪ':'i','ᴊ':'j',
    'ᴋ':'k','ʟ':'l','ᴍ':'m','ɴ':'n','ᴏ':'o','ǫ':'q','ʀ':'r','ꜱ':'s','ᴛ':'t',
    'ᴜ':'u','ᴠ':'v','ᴡ':'w','ʏ':'y','ᴢ':'z',
    'Ａ':'a','Ｂ':'b','Ｃ':'c','Ｄ':'d','Ｅ':'e','Ｆ':'f','Ｇ':'g','Ｈ':'h',
    'Ｉ':'i','Ｊ':'j','Ｋ':'k','Ｌ':'l','Ｍ':'m','Ｎ':'n','Ｏ':'o','Ｐ':'p',
    'Ｑ':'q','Ｒ':'r','Ｓ':'s','Ｔ':'t','Ｕ':'u','Ｖ':'v','Ｗ':'w','Ｘ':'x',
    'Ｙ':'y','Ｚ':'z',
}

def _normalize(t):
    result = (t or '').lower()
    for k, v in _FANCY_MAP.items():
        result = result.replace(k, v)
    return result


async def sync_reports_from_telegram():
    global tracked_reports, pending_student_ids, last_synced_id, is_syncing
    if is_syncing:
        return
    is_syncing = True

    try:
        kwargs = {'limit': None}
        if last_synced_id > 0:
            kwargs['min_id'] = last_synced_id

        new_messages = []
        async for msg in client.iter_messages(TARGET_BOT, **kwargs):
            new_messages.append(msg)

        if not new_messages:
            is_syncing = False
            return

        new_messages.sort(key=lambda m: m.id)

        context_messages = []
        if last_synced_id > 0:
            old = await client.get_messages(TARGET_BOT, limit=30, offset_id=new_messages[0].id)
            context_messages = sorted(old, key=lambda m: m.id)

        combined = context_messages + new_messages

        for i, msg in enumerate(combined):
            if msg.id <= last_synced_id:
                continue

            text = msg.text or ""
            if not text.strip():
                continue

            norm = _normalize(text)

            if 'ds_user_id' in text:
                student_id = None
                
                # Try from pending queue first
                if pending_student_ids:
                    student_id = pending_student_ids.pop(0)
                
                # If queue is empty or out of sync, look backward in chat history
                if not student_id:
                    for j in range(i - 1, max(-1, i - 30), -1):
                        if j < 0: break
                        prev_msg = combined[j]
                        if not getattr(prev_msg, 'out', False): continue
                        prev_text = (prev_msg.text or "").strip()
                        
                        if not prev_text: continue
                        if "Account registered" in prev_text: continue
                        if "subscriptions" in prev_text: continue
                        if "ds_user_id" in prev_text: continue # Skip cookies
                        
                        # Found the Student ID / Name
                        student_id = prev_text
                        break

                tracked_reports.append({
                    'submit_id': msg.id,
                    'student_id': student_id,
                    'submit_date': msg.date,
                    'status': 'pending',
                    'status_date': msg.date
                })

            if 'report approved' in norm:
                for r in tracked_reports:
                    if r['status'] == 'pending':
                        r['status'] = 'approved'
                        r['status_date'] = msg.date
                        break

            if 'report rejected' in norm:
                for r in tracked_reports:
                    if r['status'] == 'pending':
                        r['status'] = 'rejected'
                        r['status_date'] = msg.date
                        break

            if msg.id > last_synced_id:
                last_synced_id = msg.id

        if len(pending_student_ids) > 50:
            del pending_student_ids[:30]

    except Exception as e:
        print(f"Sync Error: {e}")
    finally:
        is_syncing = False


# ==========================================
# টেলিগ্রাম লিসেনার
# ==========================================
@client.on(events.NewMessage(from_users=TARGET_BOT))
async def on_bot_reply(event):
    global latest_message, is_username_shown, is_waiting_for_report
    text = event.text or ""
    if not text.strip():
        return

    norm_text = text.lower()

    if "report has been received" in norm_text or "please wait" in norm_text:
        latest_message = "Submit successful ✅"
        is_waiting_for_report = False
        is_username_shown = False
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
            
        if "report has been received" in latest_message.lower() or "please wait" in latest_message.lower():
            latest_message = "Submit successful ✅"

        is_waiting_for_report = False
        is_username_shown = False
        return


# ==========================================
# বাটন খোঁজার ফাংশন
# ==========================================
async def find_and_click_button(btn_text):
    try:
        messages = await client.get_messages(TARGET_BOT, limit=10)
        for message in messages:
            if message.buttons:
                for row in message.buttons:
                    for btn in row:
                        btn_str = getattr(btn, 'text', '')
                        if hasattr(btn_str, 'text'):
                            btn_str = btn_str.text

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
    except Exception:
        return False


# ==========================================
# HTML
# ==========================================
HTML_PAGE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Telegram Control Panel</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        /* Colorful Background */
        body { 
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; 
            padding: 10px; 
            background: linear-gradient(135deg, #e0f2f1 0%, #b2dfdb 50%, #80cbc4 100%); 
            margin: 0; 
            min-height: 100vh;
        }

        /* Unified Display Container - Highlighted */
        .unified-display {
            background: linear-gradient(to bottom, #ffffff, #e3f2fd);
            border: 3px solid #64b5f6;
            border-radius: 12px;
            padding: 15px;
            margin-bottom: 12px;
            box-shadow: 0 8px 20px rgba(33, 150, 243, 0.25);
            display: flex;
            flex-direction: column;
            gap: 10px;
        }

        .main-title {
            margin: 0;
            font-size: clamp(16px, 4vw, 20px);
            font-weight: 700;
            background: linear-gradient(90deg, #1565c0, #42a5f5, #1565c0);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            text-align: center;
            letter-spacing: 1px;
            white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
            width: 100%;
            text-shadow: 1px 1px 2px rgba(0,0,0,0.05);
        }

        /* Student ID Area */
        .sid-area { width: 100%; display: flex; gap: 6px; justify-content: center; }
        .student-id-input { 
            flex: 1; padding: 12px; border: 2px solid #ff9800; border-radius: 10px;
            font-size: 16px; outline: none; box-sizing: border-box; text-align: center;
            font-weight: bold; letter-spacing: 1px; font-family: inherit; 
            background: #fff8e1; color: #e65100;
            transition: all 0.3s;
        }
        .student-id-input::placeholder { color: #ffb74d; }
        .student-id-input:focus { 
            border-color: #f57c00; 
            box-shadow: 0 0 10px rgba(245, 124, 0, 0.4); 
            background: #ffffff;
        }
        
        .sid-title-group { 
            flex: 1; display: none; align-items: center; justify-content: center;
            background: linear-gradient(135deg, #e8f5e9, #c8e6c9); padding: 12px; border-radius: 10px; 
            border: 2px solid #66bb6a; box-shadow: inset 0 2px 5px rgba(0,0,0,0.05);
        }
        .sid-title { font-size: 18px; font-weight: 900; color: #2e7d32; letter-spacing: 1px; text-align: center; width: 100%; text-shadow: 1px 1px 1px white;}

        /* Status Area */
        .status-area { width: 100%; min-height: 45px; display: flex; align-items: center; justify-content: center; }
        .welcome-msg { display: block; color: #0277bd; font-size: 15px; font-weight: bold; text-align: center; white-space: nowrap; text-shadow: 1px 1px 1px white;}
        
        .loader-row {
            display: none; width: 100%; justify-content: space-between; align-items: center;
            padding: 0 5px; box-sizing: border-box;
            background: #fff;
            border-radius: 8px;
            padding: 8px;
            border: 1px solid #ffcdd2;
        }
        .percent-text { font-size: 14px; color: #d32f2f; font-weight: 900; }
        .timer-text { font-size: 14px; color: #2e7d32; font-weight: 900; }

        .live-value {
            display: none; background: #ffffff; color: #1565c0; border: 3px solid #42a5f5; 
            padding: 12px; border-radius: 10px; font-weight: 900; font-size: clamp(16px, 4.5vw, 22px); 
            white-space: nowrap; overflow: hidden; text-overflow: ellipsis; width: 100%; box-sizing: border-box;
            cursor: pointer; text-align: center; box-shadow: 0 4px 10px rgba(66, 165, 245, 0.3);
            transition: all 0.2s;
        }
        .live-value:hover { background: #e3f2fd; transform: scale(1.01); }
        .live-value.success-text { color: #1b5e20; border-color: #66bb6a; background: #e8f5e9; box-shadow: 0 4px 10px rgba(102, 187, 106, 0.3); }
        
        .copied-msg { font-size: 12px; color: #2e7d32; font-weight: bold; display: none; position: absolute; right: 15px; top: 10px; }

        /* Action Row */
        .action-row { display: flex; gap: 10px; align-items: center; width: 100%; margin-top: 5px; }
        
        .send-all-2fa-btn { 
            flex: 1; background: linear-gradient(135deg, #1e88e5, #00bcd4); 
            color: white; border: none; padding: 14px; border-radius: 10px; 
            cursor: pointer; font-weight: 900; font-size: 16px; 
            box-shadow: 0 6px 15px rgba(0, 188, 212, 0.5); transition: 0.3s; 
            text-transform: uppercase; letter-spacing: 1px;
        }
        .send-all-2fa-btn:hover { background: linear-gradient(135deg, #1565c0, #0097a7); transform: translateY(-2px); box-shadow: 0 8px 20px rgba(0, 188, 212, 0.7); }
        .send-all-2fa-btn:disabled { background: #9e9e9e; box-shadow: none; transform: none; cursor: not-allowed; color: #e0e0e0; }

        .sid-lock-btn-small {
            width: 48px; height: 48px; font-size: 22px; cursor: pointer; user-select: none;
            display: flex; align-items: center; justify-content: center;
            background: #ffffff; border: 2px solid #90caf9; border-radius: 10px;
            transition: 0.2s; box-shadow: 0 4px 8px rgba(144, 202, 249, 0.4);
        }
        .sid-lock-btn-small:hover { background: #e3f2fd; transform: scale(1.05); border-color: #42a5f5; }

        /* Manual Submit Area */
        .manual-area { 
            background: linear-gradient(to bottom right, #e8f5e9, #c8e6c9); 
            padding: 15px; border-radius: 12px; margin-bottom: 12px; 
            box-shadow: 0 6px 15px rgba(76, 175, 80, 0.2); 
            border: 2px solid #81c784; display: flex; flex-direction: column;
        }
        .manual-area h4 { margin: 0 0 10px 0; font-size: 15px; font-weight: 900; color: #1b5e20; text-align: center; text-transform: uppercase; letter-spacing: 0.5px;}
        .manual-input-group { display: flex; flex-direction: column; gap: 10px; }
        
        .manual-input-group textarea { 
            width: 100%; height: 160px; padding: 12px; border: 2px solid #4caf50; border-radius: 8px; 
            font-size: 14px; outline: none; box-sizing: border-box; transition: 0.2s; resize: vertical; 
            font-family: inherit; background: #ffffff; color: #333;
        }
        .manual-input-group textarea:focus { border-color: #2e7d32; box-shadow: 0 0 10px rgba(76, 175, 80, 0.5); }
        .manual-send-btn { 
            background: linear-gradient(135deg, #43a047, #66bb6a); color: white; border: none; 
            padding: 12px; border-radius: 8px; cursor: pointer; font-weight: 900; font-size: 16px; 
            width: 100%; transition: 0.3s; display: none; box-shadow: 0 6px 15px rgba(67, 160, 71, 0.4);
        }
        .manual-send-btn:hover { background: linear-gradient(135deg, #2e7d32, #43a047); transform: translateY(-2px); }
        .manual-send-btn:disabled { background: #bdbdbd; box-shadow: none; transform: none; cursor: not-allowed; }

        .follow-area {
            display: none; align-items: center; justify-content: center; gap: 8px;
            padding: 10px; background: #ffffff; border: 2px dashed #81c784; border-radius: 8px;
            font-size: 13px; flex-wrap: wrap; margin-top: 5px; box-shadow: inset 0 0 10px rgba(129, 199, 132, 0.2);
        }
        .follow-label { display: flex; align-items: center; gap: 6px; cursor: pointer; font-weight: 900; color: #2e7d32; user-select: none; }
        .follow-checkbox { width: 20px; height: 20px; cursor: pointer; accent-color: #43a047; }
        .follow-hint { font-size: 10px; color: #757575; font-style: italic; }

        /* Report Analytics Area */
        .report-area { 
            background: #ffffff; padding: 15px; border-radius: 12px; margin-bottom: 15px; 
            box-shadow: 0 8px 25px rgba(0,0,0,0.1); border: 3px solid #90caf9; 
        }
        
        .report-header-row { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; gap: 5px; }
        .report-header-row h4 { margin: 0; font-size: 16px; font-weight: 900; color: #1565c0; letter-spacing: 0.5px; white-space: nowrap; }
        
        .header-actions { display: flex; align-items: center; gap: 8px; }
        .analytics-dropdown {
            padding: 6px 10px; border-radius: 8px; border: 2px solid #64b5f6;
            background: #e3f2fd; color: #0d47a1; font-weight: 900; font-size: 12px;
            outline: none; cursor: pointer; font-family: inherit;
            box-shadow: 0 2px 5px rgba(100, 181, 246, 0.3);
            transition: 0.2s;
        }
        .analytics-dropdown:hover { background: #bbdefb; }
        
        .reset-icon {
            display: none; font-size: 20px; cursor: pointer; user-select: none;
            padding: 6px; border-radius: 50%; transition: all 0.4s ease; line-height: 1;
        }
        .reset-icon:hover { background: #ffcdd2; transform: rotate(180deg); }

        .filter-area { display: flex; flex-direction: column; gap: 8px; margin-bottom: 12px; background:#f1f8e9; padding: 12px; border-radius: 8px; border: 1px solid #c5e1a5; }
        .filter-group { display: flex; flex-direction: column; gap: 4px; width: 100%; }
        .filter-group label { font-weight: 900; color: #33691e; font-size: 12px; }
        .filter-group input { padding: 10px; border: 2px solid #aed581; border-radius: 6px; font-size: 13px; width: 100%; box-sizing: border-box; font-family: inherit; transition: 0.2s; }
        .filter-group input:focus { border-color: #7cb342; outline: none; box-shadow: 0 0 8px rgba(124, 179, 66, 0.4); }
        .filter-group input:disabled { background: #e0e0e0; color: #9e9e9e; cursor: not-allowed; border-color: #bdbdbd; }
        
        .btn-row { display: flex; justify-content: center; align-items: center; gap: 6px; width: 100%; margin-top: 6px;}
        .filter-btn { 
            background: linear-gradient(135deg, #1e88e5, #42a5f5); color: white; border: none; 
            padding: 8px 10px; border-radius: 6px; cursor: pointer; font-weight: 900; font-size: 12px; 
            transition: 0.2s; flex: 1; white-space: nowrap; box-shadow: 0 3px 8px rgba(30, 136, 229, 0.3);
        }
        .filter-btn:hover { background: linear-gradient(135deg, #1565c0, #1e88e5); transform: translateY(-1px); }
        .filter-btn:disabled { background: #bdbdbd; box-shadow: none; cursor: not-allowed; transform: none;}
        .filter-btn.reset { background: linear-gradient(135deg, #757575, #9e9e9e); box-shadow: 0 3px 8px rgba(117, 117, 117, 0.3); }
        .filter-btn.reset:hover { background: linear-gradient(135deg, #616161, #757575); }
        
        .icon-btn { font-size: 16px; cursor: pointer; user-select: none; padding: 8px; border-radius: 6px; background: #ffffff; display: flex; align-items: center; justify-content: center; transition: 0.2s; line-height: 1; border: 2px solid #e0e0e0;}
        .icon-btn:hover { transform: scale(1.1); background: #f5f5f5; box-shadow: 0 2px 5px rgba(0,0,0,0.1);}
        .icon-btn.locked { color: #d32f2f; border-color: #ffcdd2; background: #ffebee;}
        .icon-btn.unlocked { color: #2e7d32; border-color: #c8e6c9; background: #e8f5e9;}

        .admin-login-box { display: flex; flex-direction: column; gap: 10px; align-items: center; padding: 12px; background: linear-gradient(to right, #fff3e0, #ffe0b2); border: 2px solid #ffb74d; border-radius: 10px; }
        .admin-login-box label { font-weight: 900; color: #e65100; font-size: 13px; }
        .admin-login-box input { width: 100%; max-width: 200px; padding: 10px; border: 2px solid #ffb74d; border-radius: 6px; text-align: center; font-size: 16px; letter-spacing: 3px; font-weight: bold; }
        .admin-login-box input:focus { outline: none; border-color: #f57c00; box-shadow: 0 0 10px rgba(245, 124, 0, 0.4);}
        .admin-login-box button { background: linear-gradient(135deg, #f57c00, #ff9800); color: white; border: none; padding: 10px 24px; border-radius: 6px; font-weight: 900; cursor: pointer; transition: 0.2s; box-shadow: 0 4px 10px rgba(245, 124, 0, 0.4);}
        .admin-login-box button:hover { background: linear-gradient(135deg, #e65100, #f57c00); transform: scale(1.05); }
        .admin-msg { font-size: 12px; font-weight: 900; }

        .summary-table-container { overflow-x: auto; border: 2px solid #bbdefb; border-radius: 8px; }
        .summary-table { width: 100%; border-collapse: collapse; text-align: center; font-size: 12px; }
        .summary-table th { background: linear-gradient(135deg, #1565c0, #1976d2); color: white; padding: 10px 4px; font-weight: 900; }
        .summary-table td { padding: 10px 4px; border-bottom: 1px solid #e3f2fd; font-weight: bold; }
        .summary-table tr:last-child td { border-bottom: none; }
        .summary-table tbody tr:nth-child(even) { background-color: #f8f9fa; }
        .summary-table tbody tr:hover { background-color: #e3f2fd; }
        .summary-table .col-sid { text-align: left; padding-left: 10px; font-weight: 900; color: #0d47a1; }
        .summary-table .col-total { color: #1565c0; }
        .summary-table .col-appr { color: #2e7d32; }
        .summary-table .col-rej { color: #c62828; }

        /* Vibrant Counters */
        .counters { display: flex; gap: 8px; margin-bottom: 12px; flex-wrap: nowrap; }
        .counter-box { 
            flex: 1; min-width: 0; padding: 10px 5px; border-radius: 10px; text-align: center; 
            background: linear-gradient(135deg, #42a5f5, #1e88e5); 
            border: 2px solid #1565c0; color: white;
            box-shadow: 0 4px 10px rgba(30, 136, 229, 0.4);
        }
        .counter-box.approved { 
            background: linear-gradient(135deg, #66bb6a, #43a047); 
            border-color: #2e7d32;
            box-shadow: 0 4px 10px rgba(67, 160, 71, 0.4);
        }
        .counter-box.rejected { 
            background: linear-gradient(135deg, #ef5350, #e53935); 
            border-color: #c62828;
            box-shadow: 0 4px 10px rgba(229, 57, 53, 0.4);
        }
        .counter-label { display: block; font-size: 9px; font-weight: 900; color: #ffffff; margin-bottom: 2px; text-transform: uppercase; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; text-shadow: 1px 1px 2px rgba(0,0,0,0.3);}
        .counter-value { display: block; font-size: 20px; font-weight: 900; color: #ffffff; text-shadow: 1px 1px 2px rgba(0,0,0,0.4);}

        /* Vibrant Tabs */
        .tabs { display: flex; width: 100%; margin-bottom: 0; border-radius: 8px 8px 0 0; overflow: hidden; border-bottom: none; background: #e0e0e0;}
        .tab-btn { 
            flex: 1; padding: 10px 2px; text-align: center; border: none; font-weight: 900; 
            cursor: pointer; font-size: clamp(10px, 3vw, 13px); transition: 0.2s; 
            display: flex; flex-direction: column; align-items: center; gap: 4px;
            white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
            color: white; opacity: 0.6;
        }
        .tab-btn:hover { opacity: 0.8; }
        
        .tab-btn.submit { background: #1e88e5; }
        .tab-btn.approved { background: #43a047; }
        .tab-btn.rejected { background: #e53935; }
        
        .tab-btn.active { opacity: 1; transform: scale(1.05); z-index: 1; box-shadow: 0 0 15px rgba(0,0,0,0.2); border-radius: 8px 8px 0 0;}

        .list-section { border: 2px solid #bbdefb; border-top: none; border-radius: 0 0 8px 8px; overflow: hidden; background: white; }
        .report-list { max-height: 300px; overflow-y: auto; padding: 0; }
        
        .report-item { 
            display: flex; align-items: center; justify-content: space-between; 
            padding: 12px 15px; border-bottom: 1px solid #e0e0e0; gap: 8px; 
            transition: background 0.2s;
        }
        .report-item:hover { background: #f5f5f5; }
        .report-item:last-child { border-bottom: none; }
        
        .report-info { display: flex; flex-direction: column; gap: 2px; flex: 1; min-width: 0; text-align: left; }
        .report-sid { font-weight: 900; color: #0d47a1; font-size: clamp(13px, 3.5vw, 15px); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .report-time { font-size: clamp(9px, 2.5vw, 10px); color: #757575; font-weight: bold; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        
        .report-status { font-weight: 900; flex-shrink: 0; font-size: clamp(10px, 3vw, 12px); padding: 4px 8px; border-radius: 6px;}
        .report-status.success { color: #1b5e20; background: #c8e6c9; border: 1px solid #81c784;}
        .report-status.error { color: #b71c1c; background: #ffcdd2; border: 1px solid #e57373;}
        .report-status.info { color: #0d47a1; background: #bbdefb; border: 1px solid #64b5f6;}
        
        .empty-msg { padding: 25px; text-align: center; color: #9e9e9e; font-style: italic; font-size: 13px; font-weight: bold; }
    </style>
</head>
<body>

    <div class="container">
        <!-- Unified Display: Title + Student ID + Live Status -->
        <div class="unified-display">
            <h4 class="main-title">Trending Academy Limited</h4>
            
            <!-- Student ID Area (Input or Title) -->
            <div class="sid-area" id="sidInputGroup">
                <input type="text" id="studentId" class="student-id-input" placeholder="Student ID / Name" maxlength="20" oninput="updateSidState()">
            </div>
            <div class="sid-area" id="sidTitleGroup" style="display: none;">
                <div class="sid-title" id="sidTitleText">Student ID</div>
            </div>

            <!-- Live Status Area -->
            <div class="status-area">
                <div id="welcomeMsg" class="welcome-msg">🖥️ Welcome to Live Projects</div>
                
                <div id="loaderRow" class="loader-row">
                    <div class="percent-text" id="percentDisplay">Processing... 0%</div>
                    <div class="timer-text" id="timerDisplay">Wait 30s</div>
                </div>
                
                <div class="live-value" id="loginDisplay" onclick="copyToClipboard()"></div>
                <div class="copied-msg" id="copyMsg">✔ Copied</div>
            </div>

            <!-- Action Row: Get Username + Edit/Lock Icon -->
            <div class="action-row">
                <button id="btnAll2FA" class="send-all-2fa-btn" onclick="startAutoSequence(true)">Get Username</button>
                <div class="sid-lock-btn-small" id="sidLockToggleBtn" onclick="toggleSidLock()" title="Lock/Unlock ID">🔒</div>
            </div>
        </div>

        <!-- Manual Submit Area -->
        <div class="manual-area">
            <h4>Cookies Submit Please</h4>
            <div class="manual-input-group">
                <textarea id="manualMsg" placeholder="Paste your Instragram Cookies..."></textarea>
                <button id="btnManual" class="manual-send-btn" onclick="sendManualMsg()">Submit Now</button>
                
                <div class="follow-area" id="followArea">
                    <label class="follow-label">
                        <input type="checkbox" id="followCheck" class="follow-checkbox">
                        <span>Follow (5+ Subscriptions)</span>
                    </label>
                    <span class="follow-hint">টিক দিলে "5+ subscriptions" মেসেজ যাবে</span>
                </div>
            </div>
        </div>

        <!-- Report Analytics Area -->
        <div class="report-area">
            <div class="report-header-row">
                <h4>📊 Report Analytics</h4>
                <div class="header-actions">
                    <span class="reset-icon" id="resetIcon" onclick="resetReports()" title="Reset All Reports">🔄</span>
                    <select id="analyticsMenu" class="analytics-dropdown" onchange="switchAnalyticsView(this.value)">
                        <option value="date">📅 Date Filter</option>
                        <option value="student">🆔 My Reports</option>
                        <option value="admin">🔐 Admin Login</option>
                        <option value="summary">📈 Summary</option>
                    </select>
                </div>
            </div>

            <div id="viewDateFilter" class="filter-area">
                <div class="filter-group">
                    <label>From:</label>
                    <input type="datetime-local" id="fromDate">
                </div>
                <div class="filter-group">
                    <label>To:</label>
                    <input type="datetime-local" id="toDate">
                </div>
                <div class="btn-row">
                    <button class="filter-btn" id="btnFilter" onclick="fetchReports(event)">🔍 Filter</button>
                    <button class="filter-btn reset" onclick="resetFilter()">↺ Date</button>
                    <div class="icon-btn unlocked" id="lockIcon" onclick="toggleLock()" title="Lock Date">🔓</div>
                </div>
            </div>

            <div id="viewStudentFilter" class="filter-area" style="display: none;">
                <div class="filter-group" style="text-align: center; padding: 10px;">
                    <label style="font-size: 14px; margin-bottom: 4px; color: #1b5e20;">Filtering by Student ID</label>
                    <div style="font-size: 18px; font-weight: 900; color: #2e7d32; text-shadow: 1px 1px 1px #fff;" id="filterStudentIdText">—</div>
                </div>
                <div class="btn-row">
                    <button class="filter-btn" onclick="applyStudentFilter()">🔄 Apply Filter</button>
                </div>
            </div>

            <div id="viewAdmin" class="filter-area" style="display: none;">
                <div class="admin-login-box">
                    <label>Enter Admin Password</label>
                    <input type="password" id="adminPwd" placeholder="****">
                    <button onclick="doAdminLogin()">🔓 Login</button>
                    <div class="admin-msg" id="adminMsg"></div>
                </div>
            </div>

            <div id="viewSummary" style="display: none; margin-bottom: 10px;">
                <div class="summary-table-container">
                    <table class="summary-table">
                        <thead>
                            <tr>
                                <th>Student ID</th>
                                <th>Total</th>
                                <th>Appr</th>
                                <th>Rej</th>
                            </tr>
                        </thead>
                        <tbody id="summaryBody">
                            <tr><td colspan="4" style="padding: 15px; color: #888;">Loading summary...</td></tr>
                        </tbody>
                    </table>
                </div>
            </div>

            <div class="counters">
                <div class="counter-box">
                    <span class="counter-label">Total Submit</span>
                    <span class="counter-value" id="cntSubmit">0</span>
                </div>
                <div class="counter-box approved">
                    <span class="counter-label">Approved</span>
                    <span class="counter-value" id="cntApproved">0</span>
                </div>
                <div class="counter-box rejected">
                    <span class="counter-label">Rejected</span>
                    <span class="counter-value" id="cntRejected">0</span>
                </div>
            </div>

            <div id="reportTabsContainer">
                <div class="tabs">
                    <button class="tab-btn submit active" id="tabBtn-submit" onclick="switchTab('submit')">📥<br>Submit</button>
                    <button class="tab-btn approved" id="tabBtn-approved" onclick="switchTab('approved')">✅<br>Approved</button>
                    <button class="tab-btn rejected" id="tabBtn-rejected" onclick="switchTab('rejected')">❌<br>Rejected</button>
                </div>

                <div class="list-section">
                    <div id="tabContent-submit" class="report-list" style="display: block;">
                        <div class="empty-msg">Loading data...</div>
                    </div>
                    <div id="tabContent-approved" class="report-list" style="display: none;">
                        <div class="empty-msg">Loading data...</div>
                    </div>
                    <div id="tabContent-rejected" class="report-list" style="display: none;">
                        <div class="empty-msg">Loading data...</div>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <script>
        let lastLoginVal = "Welcome";
        let autoRefreshTimer = null;
        let isFetchingReports = false;
        let isLocked = false;
        let isManualSubmitting = false; 
        let currentView = 'date';
        let timerInterval = null;

        function initSettings() {
            const savedFollow = localStorage.getItem('followCheckState');
            if (savedFollow === 'true') {
                document.getElementById('followCheck').checked = true;
            }
            document.getElementById('followCheck').addEventListener('change', function() {
                localStorage.setItem('followCheckState', this.checked);
            });

            const savedView = localStorage.getItem('analyticsView') || 'date';
            document.getElementById('analyticsMenu').value = savedView;
            switchAnalyticsView(savedView);
        }

        function switchAnalyticsView(view) {
            currentView = view;
            localStorage.setItem('analyticsView', view);
            
            document.getElementById('viewDateFilter').style.display = 'none';
            document.getElementById('viewStudentFilter').style.display = 'none';
            document.getElementById('viewAdmin').style.display = 'none';
            document.getElementById('viewSummary').style.display = 'none';
            document.getElementById('reportTabsContainer').style.display = 'none';

            if (view === 'date') {
                document.getElementById('viewDateFilter').style.display = 'flex';
                document.getElementById('reportTabsContainer').style.display = 'block';
                fetchReports();
            } else if (view === 'student') {
                document.getElementById('viewStudentFilter').style.display = 'flex';
                document.getElementById('reportTabsContainer').style.display = 'block';
                updateStudentFilterText();
                fetchReports();
            } else if (view === 'admin') {
                document.getElementById('viewAdmin').style.display = 'flex';
                document.getElementById('reportTabsContainer').style.display = 'block';
                fetchReports();
            } else if (view === 'summary') {
                document.getElementById('viewSummary').style.display = 'block';
                fetchReports();
            }
        }

        function updateStudentFilterText() {
            const sid = document.getElementById('studentId').value.trim() || localStorage.getItem('savedStudentId');
            document.getElementById('filterStudentIdText').innerText = sid ? sid : 'No ID entered above';
        }

        function applyStudentFilter() {
            updateStudentFilterText();
            fetchReports();
        }

        function doAdminLogin() {
            const pwd = document.getElementById('adminPwd').value;
            const msg = document.getElementById('adminMsg');
            if (pwd === "1122") {
                document.getElementById('resetIcon').style.display = 'block';
                document.getElementById('followArea').style.display = 'flex';
                msg.innerText = "✅ Admin Mode Enabled!";
                msg.style.color = "#2e7d32";
                document.getElementById('adminPwd').value = '';
            } else {
                msg.innerText = "❌ Wrong Password!";
                msg.style.color = "#c62828";
            }
        }

        // Unified Student ID Logic
        function initSid() {
            const input = document.getElementById('studentId');
            input.value = localStorage.getItem('savedStudentId') || '';
            const locked = localStorage.getItem('sidLocked') === 'true';
            applySidState(locked);
            updateSubmitBtnVisibility();
        }

        function applySidState(locked) {
            const val = document.getElementById('studentId').value.trim();
            const lockBtn = document.getElementById('sidLockToggleBtn');
            
            if (locked && val) {
                document.getElementById('sidTitleText').innerText = val;
                document.getElementById('sidInputGroup').style.display = 'none';
                document.getElementById('sidTitleGroup').style.display = 'flex';
                lockBtn.innerText = '✏️'; // Show Edit icon when locked
                lockBtn.style.color = '#d32f2f';
            } else {
                document.getElementById('sidInputGroup').style.display = 'flex';
                document.getElementById('sidTitleGroup').style.display = 'none';
                lockBtn.innerText = '🔒'; // Show Lock icon when unlocked
                lockBtn.style.color = '#1565c0';
            }
            updateSubmitBtnVisibility();
        }

        function toggleSidLock() {
            let isLocked = localStorage.getItem('sidLocked') === 'true';
            if (!isLocked) {
                const val = document.getElementById('studentId').value.trim();
                if (!val) {
                    alert("Please enter Student ID first!");
                    return;
                }
                localStorage.setItem('sidLocked', 'true');
                applySidState(true);
            } else {
                localStorage.setItem('sidLocked', 'false');
                applySidState(false);
                document.getElementById('studentId').focus();
            }
        }

        function updateSidState() {
            const val = document.getElementById('studentId').value.trim();
            localStorage.setItem('savedStudentId', val);
            updateSubmitBtnVisibility();
        }

        function updateSubmitBtnVisibility() {
            const val = document.getElementById('studentId').value.trim();
            document.getElementById('btnManual').style.display = val ? 'block' : 'none';
        }

        function initLock() {
            isLocked = localStorage.getItem('dateFilterLocked') === 'true';
            updateLockUI();
            
            if (isLocked) {
                const savedFrom = localStorage.getItem('savedFromDate');
                const savedTo = localStorage.getItem('savedToDate');
                if (savedFrom) document.getElementById('fromDate').value = savedFrom;
                if (savedTo) document.getElementById('toDate').value = savedTo;
            }
        }

        function toggleLock() {
            isLocked = !isLocked;
            localStorage.setItem('dateFilterLocked', isLocked);
            
            if (isLocked) {
                localStorage.setItem('savedFromDate', document.getElementById('fromDate').value);
                localStorage.setItem('savedToDate', document.getElementById('toDate').value);
            }
            updateLockUI();
        }

        function updateLockUI() {
            const lockIcon = document.getElementById('lockIcon');
            const fromInput = document.getElementById('fromDate');
            const toInput = document.getElementById('toDate');
            
            if (isLocked) {
                lockIcon.innerText = '🔒';
                lockIcon.classList.add('locked');
                lockIcon.classList.remove('unlocked');
                fromInput.disabled = true;
                toInput.disabled = true;
            } else {
                lockIcon.innerText = '🔓';
                lockIcon.classList.add('unlocked');
                lockIcon.classList.remove('locked');
                fromInput.disabled = false;
                toInput.disabled = false;
            }
        }

        async function fetchLogin() {
            try {
                const res = await fetch('/get_login');
                const data = await res.json();
                
                if (isManualSubmitting && (data.login === "Submit Done ✅" || data.login === "Submit successful ✅")) {
                    return;
                }

                if (data.login && data.login !== lastLoginVal) {
                    lastLoginVal = data.login;
                    
                    const display = document.getElementById('loginDisplay');
                    const loaderRow = document.getElementById('loaderRow');
                    const welcome = document.getElementById('welcomeMsg');

                    if (lastLoginVal === "Loading..." || lastLoginVal === "Processing..." || lastLoginVal.includes("Creating")) {
                        welcome.style.display = 'none';
                        loaderRow.style.display = 'flex';
                        display.style.display = 'none';
                    } else if (lastLoginVal === "Welcome") {
                        welcome.style.display = 'block';
                        loaderRow.style.display = 'none';
                        display.style.display = 'none';
                    } else {
                        welcome.style.display = 'none';
                        loaderRow.style.display = 'none';
                        display.style.display = 'block';
                        display.innerText = lastLoginVal; 
                        display.title = lastLoginVal;
                        
                        if (lastLoginVal.includes("Successful") || lastLoginVal.includes("Done") || lastLoginVal.includes("✅")) {
                            display.classList.add('success-text');
                        } else {
                            display.classList.remove('success-text');
                        }
                    }
                }
            } catch(e) {}
        }
        setInterval(fetchLogin, 100);
        window.onload = fetchLogin;

        function copyToClipboard() {
            let text = document.getElementById('loginDisplay').innerText;
            if (text === "" || text.includes("Report") || text.includes("Successful") || text.includes("Welcome")) return;
            
            navigator.clipboard.writeText(text).then(() => {
                const copyMsg = document.getElementById('copyMsg');
                copyMsg.style.display = 'block';
                setTimeout(() => { copyMsg.style.display = 'none'; }, 2000);
            }).catch(err => {});
        }

        function startTimer(seconds) {
            return new Promise((resolve) => {
                const timerDisplay = document.getElementById('timerDisplay');
                let timeLeft = seconds;
                timerDisplay.innerText = `Wait ${timeLeft}s`;
                if (timerInterval) clearInterval(timerInterval);
                
                timerInterval = setInterval(() => {
                    timeLeft--;
                    if (timeLeft > 0) {
                        timerDisplay.innerText = `Wait ${timeLeft}s`;
                    } else {
                        clearInterval(timerInterval);
                        timerDisplay.innerText = `0s`;
                        resolve();
                    }
                }, 1000);
            });
        }

        async function startAutoSequence(with2FA) {
            const btnAll2FA = document.getElementById('btnAll2FA');
            btnAll2FA.disabled = true;
            
            // Start 30s timer concurrently
            const timerPromise = startTimer(30);

            // Show Loader
            document.getElementById('welcomeMsg').style.display = 'none';
            document.getElementById('loginDisplay').style.display = 'none';
            document.getElementById('loaderRow').style.display = 'flex';
            const percentDisplay = document.getElementById('percentDisplay');
            lastLoginVal = "Loading...";
            
            const steps = [
                { text: "Tasks", isStart: true, percent: 25 },
                { text: "🍪", isStart: false, percent: 50 },
                { text: "🍪 Create Inst", isStart: false, percent: 75 },
                { text: "Start", isStart: false, percent: 100 }
            ];
            
            for (let i = 0; i < steps.length; i++) {
                percentDisplay.innerText = `Processing... ${steps[i].percent}%`;
                await sendSpecificText(steps[i].text, steps[i].isStart);
                if (i < steps.length - 1) {
                    await new Promise(r => setTimeout(r, 500));
                }
            }
            
            if (with2FA) {
                percentDisplay.innerText = `Processing... 100%`;
                await new Promise(r => setTimeout(r, 1000));
                try { await fetch('/send_2fa', { method: 'POST' }); } catch(e) {}
            }
            
            // Wait for timer to finish before enabling button
            await timerPromise;
            btnAll2FA.disabled = false;
        }

        async function sendSpecificText(text, isStart) {
            try {
                await fetch('/click_button_by_text', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({btn_text: text, is_start: isStart})
                });
            } catch (e) {}
        }

        async function sendManualMsg() {
            const input = document.getElementById('manualMsg');
            const studentIdInput = document.getElementById('studentId');
            const btn = document.getElementById('btnManual');
            const text = input.value.trim();
            const studentId = studentIdInput.value.trim();
            const sendSubs = document.getElementById('followCheck').checked;
            
            if(!text || !studentId || btn.disabled) return;
            
            isManualSubmitting = true; 
            btn.disabled = true;
            btn.innerText = "Processing..";
            
            document.getElementById('welcomeMsg').style.display = 'none';
            document.getElementById('loginDisplay').style.display = 'none';
            document.getElementById('loaderRow').style.display = 'flex';
            document.getElementById('percentDisplay').innerText = 'Processing...';
            document.getElementById('timerDisplay').innerText = ''; // hide timer
            lastLoginVal = "Loading...";
            
            try {
                await fetch('/send_manual_msg', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({text: text})
                });
                input.value = '';
                
                await new Promise(r => setTimeout(r, 1000));
                
                await fetch('/send_student_id', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({student_id: studentId})
                });
                
                await new Promise(r => setTimeout(r, 1000));
                
                await fetch('/send_manual_registered', { 
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ send_subscriptions: sendSubs })
                });
            } catch (e) {}
            
            setTimeout(() => {
                btn.disabled = false;
                btn.innerText = "Submit Now"; 
                isManualSubmitting = false;
                showSuccessAndRevert();
            }, 3000);
        }

        function showSuccessAndRevert() {
            const display = document.getElementById('loginDisplay');
            const loaderRow = document.getElementById('loaderRow');
            const welcome = document.getElementById('welcomeMsg');

            welcome.style.display = 'none';
            loaderRow.style.display = 'none';
            display.style.display = 'block';
            display.innerText = "Submit successful ✅";
            display.classList.add('success-text');
            lastLoginVal = "Submit successful ✅";

            setTimeout(async () => {
                welcome.style.display = 'block';
                display.style.display = 'none';
                display.classList.remove('success-text');
                lastLoginVal = "Welcome";
                try { await fetch('/reset_welcome', { method: 'POST' }); } catch(e) {}
            }, 5000);
        }

        function escapeHtml(s) {
            return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
        }

        function formatDate(isoString) {
            const d = new Date(isoString);
            const day = String(d.getDate()).padStart(2, '0');
            const month = String(d.getMonth() + 1).padStart(2, '0');
            const year = d.getFullYear();
            let hours = d.getHours();
            const minutes = String(d.getMinutes()).padStart(2, '0');
            const seconds = String(d.getSeconds()).padStart(2, '0');
            const ampm = hours >= 12 ? 'PM' : 'AM';
            hours = hours % 12;
            hours = hours ? hours : 12;
            const strHours = String(hours).padStart(2, '0');
            return `${day}/${month}/${year}, ${strHours}:${minutes}:${seconds} ${ampm}`;
        }

        async function fetchReports(event) {
            if (isFetchingReports) return;
            isFetchingReports = true;

            const btn = document.getElementById('btnFilter');
            if (event && event.type === 'click') {
                btn.disabled = true;
                btn.innerText = "Loading...";
            }

            const fromVal = document.getElementById('fromDate').value;
            const toVal = document.getElementById('toDate').value;
            const start = fromVal ? new Date(fromVal).toISOString() : null;
            const end = toVal ? new Date(toVal).toISOString() : null;
            
            let sidFilter = null;
            if (currentView === 'student') {
                sidFilter = document.getElementById('studentId').value.trim() || localStorage.getItem('savedStudentId');
            }

            try {
                const res = await fetch('/get_reports', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ start: start, end: end, student_id: sidFilter })
                });
                const data = await res.json();

                if (data.error) {
                    console.error("Error: " + data.error);
                    return;
                }

                document.getElementById('cntSubmit').innerText = data.total_submit;
                document.getElementById('cntApproved').innerText = data.approved;
                document.getElementById('cntRejected').innerText = data.rejected;

                if (currentView === 'summary') {
                    renderSummary(data.summary);
                } else {
                    renderTabList('tabContent-submit', data.submit_list, 'submit');
                    renderTabList('tabContent-approved', data.approved_list, 'approved');
                    renderTabList('tabContent-rejected', data.rejected_list, 'rejected');
                }

            } catch (e) {
                console.error("Failed: " + e.message);
            } finally {
                isFetchingReports = false;
                if (event && event.type === 'click') {
                    btn.disabled = false;
                    btn.innerText = "🔍 Filter";
                }
            }
        }

        function renderSummary(summary) {
            const tbody = document.getElementById('summaryBody');
            if (!summary || summary.length === 0) {
                tbody.innerHTML = '<tr><td colspan="4" style="padding: 15px; color: #888;">No data found.</td></tr>';
                return;
            }
            
            summary.sort((a, b) => b.total - a.total);

            tbody.innerHTML = summary.map(row => {
                return `<tr>
                    <td class="col-sid">${escapeHtml(row.student_id)}</td>
                    <td class="col-total">${row.total}</td>
                    <td class="col-appr">${row.approved}</td>
                    <td class="col-rej">${row.rejected}</td>
                </tr>`;
            }).join('');
        }

        function renderTabList(id, items, type) {
            const container = document.getElementById(id);
            if (!items || items.length === 0) {
                container.innerHTML = '<div class="empty-msg">No data found</div>';
                return;
            }

            let icon = "📥";
            let text = "Report Submitted";
            let className = "info";

            if (type === 'approved') {
                icon = "✅";
                text = "Report Verified";
                className = "success";
            } else if (type === 'rejected') {
                icon = "❌";
                text = "Report Rejected";
                className = "error";
            }

            container.innerHTML = items.map(item => {
                const localTime = formatDate(item.time);
                const sidText = item.student_id ? escapeHtml(item.student_id) : '—';
                return `<div class="report-item">
                    <div class="report-info">
                        <div class="report-sid">🆔 ${sidText}</div>
                        <div class="report-time">🕐 ${escapeHtml(localTime)}</div>
                    </div>
                    <div class="report-status ${className}">${icon} ${text}</div>
                </div>`;
            }).join('');
        }

        function switchTab(tabName) {
            document.getElementById('tabContent-submit').style.display = 'none';
            document.getElementById('tabContent-approved').style.display = 'none';
            document.getElementById('tabContent-rejected').style.display = 'none';
            
            document.getElementById('tabBtn-submit').classList.remove('active');
            document.getElementById('tabBtn-approved').classList.remove('active');
            document.getElementById('tabBtn-rejected').classList.remove('active');

            document.getElementById('tabContent-' + tabName).style.display = 'block';
            document.getElementById('tabBtn-' + tabName).classList.add('active');
        }

        function resetFilter() {
            document.getElementById('fromDate').value = '';
            document.getElementById('toDate').value = '';
            if (isLocked) {
                localStorage.removeItem('savedFromDate');
                localStorage.removeItem('savedToDate');
            }
            fetchReports();
        }

        async function resetReports() {
            if (!confirm('সব রিপোর্ট মুছে ফেলবেন?\\n\\nএই মুহূর্ত থেকে নতুন করে পড়া শুরু হবে।')) {
                return;
            }
            const icon = document.getElementById('resetIcon');
            icon.style.pointerEvents = 'none';
            icon.style.opacity = '0.5';

            try {
                await fetch('/reset_reports', { method: 'POST' });
                document.getElementById('cntSubmit').innerText = '0';
                document.getElementById('cntApproved').innerText = '0';
                document.getElementById('cntRejected').innerText = '0';
                document.getElementById('tabContent-submit').innerHTML = '<div class="empty-msg">No data found</div>';
                document.getElementById('tabContent-approved').innerHTML = '<div class="empty-msg">No data found</div>';
                document.getElementById('tabContent-rejected').innerHTML = '<div class="empty-msg">No data found</div>';
                document.getElementById('summaryBody').innerHTML = '<tr><td colspan="4" style="padding: 15px; color: #888;">No data found.</td></tr>';
            } catch (e) {
                console.error("Reset failed:", e);
            } finally {
                icon.style.pointerEvents = 'auto';
                icon.style.opacity = '1';
            }
        }

        window.addEventListener('DOMContentLoaded', () => {
            initSid();
            initLock();
            initSettings(); 
            autoRefreshTimer = setInterval(() => fetchReports(null), 10000); 
        });
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

@app.route('/reset_welcome', methods=['POST'])
def reset_welcome():
    global latest_message
    latest_message = "Welcome"
    return jsonify({'status': 'ok'})

@app.route('/reset_reports', methods=['POST'])
def reset_reports():
    global tracked_reports, pending_student_ids, last_synced_id
    tracked_reports = []
    pending_student_ids = []

    async def action():
        try:
            msgs = await client.get_messages(TARGET_BOT, limit=1)
            if msgs:
                return msgs[0].id
        except Exception:
            pass
        return 0

    latest_id = client.loop.run_until_complete(action())
    if latest_id:
        last_synced_id = latest_id

    print(f"[RESET] Reports cleared. last_synced_id = {last_synced_id}")
    return jsonify({'status': 'ok', 'last_synced_id': last_synced_id})

@app.route('/get_reports', methods=['POST'])
def get_reports():
    data = request.get_json() or {}
    start_str = data.get('start')
    end_str = data.get('end')
    filter_student_id = data.get('student_id')

    def parse_dt(s):
        if not s:
            return None
        try:
            dt = datetime.fromisoformat(s.replace('Z', '+00:00'))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            return None

    start_dt = parse_dt(start_str)
    end_dt = parse_dt(end_str)

    async def fetch_data():
        await sync_reports_from_telegram()

        result = {
            'total_submit': 0,
            'approved': 0,
            'rejected': 0,
            'submit_list': [],
            'approved_list': [],
            'rejected_list': [],
            'summary': []
        }

        summary_map = {}

        for r in tracked_reports:
            rdate = r['submit_date']
            if rdate.tzinfo is None:
                rdate = rdate.replace(tzinfo=timezone.utc)
            else:
                rdate = rdate.astimezone(timezone.utc)

            if start_dt is not None and rdate < start_dt:
                continue
            if end_dt is not None and rdate > end_dt:
                continue
            
            if filter_student_id and r['student_id'] != filter_student_id:
                continue

            item = {
                'student_id': r['student_id'],
                'time': rdate.isoformat(),
                'status': r['status']
            }

            result['total_submit'] += 1
            result['submit_list'].append(item)

            if r['status'] == 'approved':
                result['approved'] += 1
                result['approved_list'].append(item)
            elif r['status'] == 'rejected':
                result['rejected'] += 1
                result['rejected_list'].append(item)

            sid = r['student_id'] or 'Unknown'
            if sid not in summary_map:
                summary_map[sid] = {'student_id': sid, 'total': 0, 'approved': 0, 'rejected': 0}
            
            summary_map[sid]['total'] += 1
            if r['status'] == 'approved': summary_map[sid]['approved'] += 1
            elif r['status'] == 'rejected': summary_map[sid]['rejected'] += 1

        result['submit_list'].sort(key=lambda x: x['time'], reverse=True)
        result['approved_list'].sort(key=lambda x: x['time'], reverse=True)
        result['rejected_list'].sort(key=lambda x: x['time'], reverse=True)
        result['summary'] = list(summary_map.values())

        return result

    result = client.loop.run_until_complete(fetch_data())
    return jsonify(result)


@app.route('/click_button_by_text', methods=['POST'])
def click_button_by_text():
    global latest_message, is_username_shown, is_waiting_for_report
    data = request.get_json()
    btn_text = data.get('btn_text', '')
    is_start = data.get('is_start', False)

    latest_message = "Loading..."
    is_username_shown = False
    is_waiting_for_report = False

    async def action():
        try:
            if is_start:
                await client.send_message(TARGET_BOT, "/start")
                await asyncio.sleep(0.7)
            result = await find_and_click_button(btn_text)
            await asyncio.sleep(0.7)
            return result
        except Exception:
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
    global latest_message
    data = request.get_json()
    text = data.get('text', '')
    if not text:
        return jsonify({'status': 'error'})

    latest_message = "Loading..."

    async def send_action():
        try:
            await client.send_message(TARGET_BOT, text)
            return True
        except Exception:
            return False

    success = client.loop.run_until_complete(send_action())
    return jsonify({'status': 'ok' if success else 'error'})


@app.route('/send_student_id', methods=['POST'])
def send_student_id():
    global latest_message, pending_student_ids
    data = request.get_json() or {}
    sid = (data.get('student_id') or '').strip()

    if not sid:
        return jsonify({'status': 'error', 'msg': 'Empty Student ID'})

    latest_message = "Loading..."

    async def send_action():
        try:
            await client.send_message(TARGET_BOT, sid)
            return True
        except Exception:
            return False

    success = client.loop.run_until_complete(send_action())

    if success:
        pending_student_ids.append(sid)
        if len(pending_student_ids) > 50:
            del pending_student_ids[:30]

    return jsonify({'status': 'ok' if success else 'error'})


@app.route('/send_manual_registered', methods=['POST'])
def send_manual_registered():
    global is_waiting_for_report, is_username_shown
    is_waiting_for_report = True
    is_username_shown = True

    data = request.get_json() or {}
    send_subs = data.get('send_subscriptions', False)

    async def send_action():
        try:
            await client.send_message(TARGET_BOT, "✅ Account registered")
            if send_subs:
                await asyncio.sleep(2)
                await client.send_message(TARGET_BOT, "✅ Yes, I made 5+ subscriptions")
            return True
        except Exception:
            return False

    success = client.loop.run_until_complete(send_action())
    return jsonify({'status': 'ok' if success else 'error'})


@app.route('/send_2fa', methods=['POST'])
def send_2fa():
    async def send_action():
        try:
            await client.send_message(TARGET_BOT, "BQQ6 SYLR NRVW 5DWH")
            return True
        except Exception:
            return False

    success = client.loop.run_until_complete(send_action())
    return jsonify({'status': 'ok' if success else 'error'})


if __name__ == '__main__':
    print("Connecting..")
    client.start()
    print("Success! Website running...")
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False, threaded=False, use_reloader=False)
