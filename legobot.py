"""
Legoliv Data Logger - Telegram bot -> Power BI bridge (handover version)

Changes from the original FYP version:
  * Bot token and Power BI push URL are read from config.ini (next to the
    program) instead of being written inside the code.
  * Every row is stamped with a Session name and a Timestamp, so the
    dashboard can be filtered to the current class. No more deleting data.
  * Reports a real error when Power BI rejects the data.
All cost / profit / LMPU calculations are unchanged.
"""
import configparser
import json
import os
import re
import shutil
import sys
import threading
import time
from datetime import datetime, timezone

import requests
import telebot
from telebot import types

# --- CONSTANTS (unchanged) ---
WAGE_PER_PERSON = 200
COMPONENT_COST = 150
FINISHED_UNIT_COST = 200
SHIPPED_UNIT_COST = 200

BTN_START = '🚀 I Understand, Start Simulation'
BTN_BACK = '⬅️ Back to Menu'
BTN_YES = '✅ Yes, Send it'
BTN_EDIT = '✏️ Edit Data'
BTN_CANCEL = '⬅️ Cancel'

# /manage menu
BTN_M_EDIT = '✏️ Edit / delete an entry'
BTN_M_REMOVE = '🗑️ Remove a whole session'
BTN_M_RESTORE = '♻️ Restore removed data'
BTN_M_FORGET = '🧼 Reset bot list (advanced)'
ALL_SESSIONS = '*ALL*'
BTN_E_EDIT = '✏️ Enter corrected numbers'
BTN_E_DEL = '🗑️ Delete this entry'
BTN_RM_YES = '✅ Yes, remove'
BTN_EDIT_YES = '✅ Yes, apply correction'
BTN_RESTORE_ALL = '♻️ Restore ALL removed'
BTN_FORGET_YES = '🧼 Yes, reset the bot list'


# ------------------------------------------------------------------
# SETTINGS (config.ini sits in the same folder as the program)
# ------------------------------------------------------------------
def app_folder():
    if getattr(sys, 'frozen', False):          # running as legobot.exe
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


CONFIG_PATH = os.path.join(app_folder(), 'config.ini')


def load_settings():
    cfg = configparser.ConfigParser(interpolation=None)
    cfg.read(CONFIG_PATH, encoding='utf-8-sig')
    if not cfg.has_section('legoliv'):
        cfg.add_section('legoliv')
    token = cfg.get('legoliv', 'telegram_token', fallback='').strip()
    url = cfg.get('legoliv', 'powerbi_push_url', fallback='').strip()

    changed = False
    if not token:
        print("\nFIRST-TIME SETUP: Telegram bot token is missing.")
        token = input("Paste the bot token (from @BotFather) and press Enter:\n> ").strip()
        changed = True
    if not url.lower().startswith('https://api.powerbi.com/'):
        print("\nFIRST-TIME SETUP: Power BI Push URL is missing.")
        print("(Power BI website > your streaming dataset > ... > API info > Push URL)")
        url = input("Paste the Push URL and press Enter:\n> ").strip()
        changed = True
    if changed:
        cfg.set('legoliv', 'telegram_token', token)
        cfg.set('legoliv', 'powerbi_push_url', url)
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            cfg.write(f)
        print("Saved to config.ini - you will not be asked again.\n")
    return token, url


SESSION_PREFIX = 'YB Wave'      # YB = Yellow Belt, Wave = generation
DEFAULT_WAVE = 14               # used only if config.ini has no saved wave yet


def load_session():
    """Session name is 'YB Wave <number>'. The number is set from Telegram
    (/session) and remembered in config.ini, so a restart keeps the same wave."""
    cfg = configparser.ConfigParser(interpolation=None)
    cfg.read(CONFIG_PATH, encoding='utf-8-sig')
    name = cfg.get('legoliv', 'session_name', fallback='').strip()
    if name.startswith(SESSION_PREFIX):
        return name
    return f"{SESSION_PREFIX} {DEFAULT_WAVE}"


def save_session(name):
    cfg = configparser.ConfigParser(interpolation=None)
    cfg.read(CONFIG_PATH, encoding='utf-8-sig')
    if not cfg.has_section('legoliv'):
        cfg.add_section('legoliv')
    cfg.set('legoliv', 'session_name', name)
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        cfg.write(f)


def cfg_get(key, fallback=''):
    cfg = configparser.ConfigParser(interpolation=None)
    cfg.read(CONFIG_PATH, encoding='utf-8-sig')
    return cfg.get('legoliv', key, fallback=fallback).strip()


# ------------------------------------------------------------------
# LEDGER + BACKUPS
# Power BI cannot delete single rows through the push URL, so every row
# the bot sends is also written to ledger.json. To "remove" or "edit" data
# the bot sends a REVERSAL row (same row with all numbers negated), which
# cancels the original in every SUM on the dashboard. Nothing is lost:
# before each change a copy of the ledger goes to the backups folder, and
# removed entries can be restored (their original rows are sent again).
# ------------------------------------------------------------------
LEDGER_PATH = os.path.join(app_folder(), 'ledger.json')
BACKUP_DIR = os.path.join(app_folder(), 'backups')
LEDGER_LOCK = threading.RLock()
NUM_FIELDS = ["Labor_Cost", "Process_Inv", "Finished_Inv", "Shipped_Cost",
              "Earnings", "Total_Cost", "Profit", "LMPU",
              "Labor_Qty", "WIP_Qty", "Finished_Qty", "Shipped_Qty"]


def now_iso():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.000Z')


def ledger_load():
    data = {}
    try:
        with open(LEDGER_PATH, 'r', encoding='utf-8-sig') as f:
            data = json.load(f)
    except FileNotFoundError:
        pass
    except Exception as e:                      # damaged file: keep it, start a new one
        bad = LEDGER_PATH + '.damaged_' + datetime.now().strftime('%Y%m%d_%H%M%S')
        try:
            os.replace(LEDGER_PATH, bad)
        except Exception:
            pass
        print(f"WARNING: ledger.json was unreadable ({e}); saved as {bad}")
        data = {}
    data.setdefault('next_id', 1)
    data.setdefault('entries', [])
    return data


def ledger_save(data):
    tmp = LEDGER_PATH + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
    os.replace(tmp, LEDGER_PATH)


def ledger_backup(label):
    """Copy ledger.json into backups/ before any change. Returns the file name."""
    if not os.path.exists(LEDGER_PATH):
        return ''
    os.makedirs(BACKUP_DIR, exist_ok=True)
    name = f"ledger_{datetime.now():%Y%m%d_%H%M%S}_{label}.json"
    shutil.copy2(LEDGER_PATH, os.path.join(BACKUP_DIR, name))
    return name


def ledger_add(data, session, run_label, group, numbers, row):
    entry = {"id": data['next_id'], "session": session, "run": run_label,
             "group": group, "numbers": list(numbers), "row": row,
             "status": "active", "created": now_iso()}
    data['next_id'] += 1
    data['entries'].append(entry)
    return entry


def ledger_find(data, entry_id):
    for e in data['entries']:
        if e['id'] == entry_id:
            return e
    return None


def reversal_row(row):
    rev = dict(row)
    for k in NUM_FIELDS:
        v = row.get(k, 0)
        rev[k] = -v if v else 0
    rev["Timestamp"] = now_iso()
    return rev


def post_rows(url, rows):
    """Returns (ok, error_text)."""
    try:
        resp = requests.post(url, json=rows, timeout=20)
        if resp.status_code == 200:
            return True, ''
        return False, f"Power BI error {resp.status_code}: {resp.text[:200]}"
    except Exception as e:
        return False, f"network error: {e}"


def fmt_numbers(numbers):
    return ', '.join(f"{n:g}" for n in numbers)


def entry_label(e):
    return f"#{e['id']} {e['run']} {e['group']} · {fmt_numbers(e['numbers'])}"


# ------------------------------------------------------------------
# CALCULATION (same formulas as the original)
# ------------------------------------------------------------------
def calculate(run_label, num_people, num_wip, num_finished, num_shipped):
    if run_label in ['RUN 1', 'RUN 2']:
        sales_price = 350
    elif run_label == 'RUN 3':
        sales_price = 300
    else:
        sales_price = 250

    labor_cost = num_people * WAGE_PER_PERSON
    wip_cost = num_wip * COMPONENT_COST
    finished_cost = num_finished * FINISHED_UNIT_COST
    shipped_cost = num_shipped * SHIPPED_UNIT_COST
    total_cost = labor_cost + wip_cost + finished_cost + shipped_cost

    earnings = num_shipped * sales_price
    profit = earnings - total_cost

    if run_label in ['RUN 2', 'RUN 3', 'RUN 4']:
        lmpu_numerator = 72
    elif run_label == 'RUN 6':
        lmpu_numerator = 24
    else:
        lmpu_numerator = 48
    lmpu = round(lmpu_numerator / num_shipped, 2) if num_shipped > 0 else 0

    return {
        "Labor_Cost": labor_cost,
        "Process_Inv": wip_cost,
        "Finished_Inv": finished_cost,
        "Shipped_Cost": shipped_cost,
        "Earnings": earnings,
        "Total_Cost": total_cost,
        "Profit": profit,
        "LMPU": lmpu,
        "Labor_Qty": num_people,
        "WIP_Qty": num_wip,
        "Finished_Qty": num_finished,
        "Shipped_Qty": num_shipped,
    }


def build_row(session, run_label, group_name, numbers):
    row = {"Session": session, "Run_Label": run_label, "Group_Name": group_name}
    row.update(calculate(run_label, *numbers))
    row["Timestamp"] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.000Z')
    return row


# ------------------------------------------------------------------
# BOT
# ------------------------------------------------------------------
def main():
    print("============================================================")
    print("  LEGOLIV DATA LOGGER  (Telegram -> Power BI)")
    print("============================================================")
    token, powerbi_url = load_settings()
    state = {'session': load_session()}

    bot = telebot.TeleBot(token)
    user_data = {}

    # If Telegram cannot parse the Markdown in a message, resend it as plain text
    # instead of failing (file names with underscores can trigger this).
    _send = bot.send_message

    def send_with_fallback(chat_id, text, *args, **kwargs):
        try:
            return _send(chat_id, text, *args, **kwargs)
        except Exception as e:
            if kwargs.get('parse_mode') and 'parse' in str(e).lower():
                kwargs.pop('parse_mode')
                return _send(chat_id, text.replace('*', '').replace('`', ''), *args, **kwargs)
            raise

    bot.send_message = send_with_fallback

    def route_command(message):
        """Slash commands must work even while a menu step is waiting."""
        t = (message.text or '').strip().lower()
        if t.startswith('/session'):
            cmd_session(message)
            return True
        if t.startswith('/manage'):
            cmd_manage(message)
            return True
        if t.startswith('/resetledger'):
            cmd_resetledger(message)
            return True
        if t.startswith('/start') or t.startswith('/help'):
            welcome_screen(message)
            return True
        return False

    @bot.message_handler(commands=['session'])
    def cmd_session(message):
        require_admin(message, ask_session)

    def ask_session(message):
        msg = bot.send_message(
            message.chat.id,
            f"🏷️ **Current session:** `{state['session']}`\n\n"
            f"Which **wave number** is this class?\n"
            f"Type only the number, e.g. `12` → saved as `{SESSION_PREFIX} 12`\n"
            "(or send /cancel to keep the current one).",
            parse_mode='Markdown', reply_markup=types.ReplyKeyboardRemove())
        bot.register_next_step_handler(msg, set_session)

    def set_session(message):
        text = (message.text or '').strip()
        if text.lower().startswith('/session'):
            ask_session(message)
            return
        if text.startswith('/'):
            bot.send_message(message.chat.id, f"Session unchanged: `{state['session']}`",
                             parse_mode='Markdown')
            show_main_menu(message)
            return
        found = re.search(r'\d{1,3}', text)
        if not found:
            msg = bot.send_message(message.chat.id,
                                   "⚠️ Please type just the wave **number**, e.g. `12`.",
                                   parse_mode='Markdown')
            bot.register_next_step_handler(msg, set_session)
            return
        state['session'] = f"{SESSION_PREFIX} {int(found.group())}"
        save_session(state['session'])
        print(f"[{datetime.now():%H:%M:%S}] session set to: {state['session']}")
        bot.send_message(message.chat.id,
                         f"✅ Session set to **{state['session']}**.\n"
                         "All new entries will be saved under this name.",
                         parse_mode='Markdown')
        show_main_menu(message)

    @bot.message_handler(commands=['start', 'help'])
    def welcome_screen(message):
        markup = types.ReplyKeyboardMarkup(row_width=1, one_time_keyboard=True)
        markup.add(BTN_START)
        text = (
            "👋 **Welcome to Legoliv Data Logger!**\n\n"
            "🤖 **SYSTEM FUNCTION:**\n"
            "This bot serves as a **Real-Time Data Bridge**. It instantly transmits your simulation inputs "
            "directly to the **Power BI Dashboard** for live visualization.\n\n"
            "⚠️ **INSTRUCTIONS (READ FIRST):**\n"
            "1. Please enter data for **YOUR GROUP** only.\n"
            "2. **Data Format** (4 Numbers separated by commas):\n"
            "   - A: Number of People\n"
            "   - B: Components (WIP)\n"
            "   - C: Finished Units\n"
            "   - D: Shipped Units\n\n"
            "📝 **Example Input:**\n"
            "`18, 166, 33, 65`\n\n"
            "Click the button below to proceed."
        )
        bot.send_message(message.chat.id, text, reply_markup=markup, parse_mode='Markdown')

    @bot.message_handler(func=lambda m: m.text == BTN_START)
    def on_start_button(message):
        wave_check(message)

    def wave_check(message):
        """Ask for the wave number before any data can be entered."""
        markup = types.ReplyKeyboardMarkup(row_width=1, one_time_keyboard=True, resize_keyboard=True)
        markup.add(f"✅ Continue with {state['session']}")
        msg = bot.send_message(
            message.chat.id,
            f"🏷️ **Which wave is this class?**\n"
            f"Saved wave: `{state['session']}`\n\n"
            "Press the button to continue, or type a different **wave number** (e.g. `15`).",
            parse_mode='Markdown', reply_markup=markup)
        bot.register_next_step_handler(msg, got_wave)

    def got_wave(message):
        if route_command(message):
            return
        text = (message.text or '').strip()
        if text.startswith('✅ Continue'):
            show_main_menu(message)
            return
        found = re.search(r'\d{1,3}', text)
        if not found:
            bot.send_message(message.chat.id, "⚠️ Please press the button, or type the wave number (e.g. 15).")
            wave_check(message)
            return
        number = int(found.group())
        require_admin(message, lambda m: apply_wave(m, number))

    def apply_wave(message, number):
        state['session'] = f"{SESSION_PREFIX} {number}"
        save_session(state['session'])
        print(f"[{datetime.now():%H:%M:%S}] session set to: {state['session']}")
        bot.send_message(message.chat.id, f"✅ Wave set to **{state['session']}**.", parse_mode='Markdown')
        show_main_menu(message)

    def show_main_menu(message):
        markup = types.ReplyKeyboardMarkup(row_width=3, one_time_keyboard=True)
        markup.add('RUN 1', 'RUN 2', 'RUN 3', 'RUN 4', 'RUN 5', 'RUN 6')
        msg = bot.send_message(message.chat.id,
                               f"🔄 **Main Menu**\n🏷️ Session: `{state['session']}`\nSelect the current RUN:",
                               reply_markup=markup, parse_mode='Markdown')
        bot.register_next_step_handler(msg, select_group)

    def select_group(message):
        if route_command(message):
            return
        chat_id = message.chat.id
        run_label = message.text or ''

        if run_label in (BTN_BACK, BTN_START):
            show_main_menu(message)
            return
        if not run_label.startswith("RUN"):
            bot.reply_to(message, "⚠️ Please click the buttons provided.")
            show_main_menu(message)
            return

        user_data[chat_id] = {'Run_Label': run_label}

        markup = types.ReplyKeyboardMarkup(row_width=3, one_time_keyboard=True)
        markup.add('Group 1', 'Group 2', 'Group 3', 'Group 4', 'Group 5', 'Group 6')
        markup.add(BTN_BACK)
        msg = bot.reply_to(message, f"Selected **{run_label}**.\nWhich Group are you representing?",
                           reply_markup=markup, parse_mode='Markdown')
        bot.register_next_step_handler(msg, ask_inputs)

    def ask_inputs(message):
        if route_command(message):
            return
        chat_id = message.chat.id
        text_input = message.text or ''

        if text_input == BTN_BACK or chat_id not in user_data:
            show_main_menu(message)
            return

        user_data[chat_id]['Group_Name'] = text_input
        prompt_numbers(message)

    def prompt_numbers(message):
        chat_id = message.chat.id
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        markup.add(BTN_BACK)
        text = (
            f"📝 **{user_data[chat_id]['Group_Name']} - {user_data[chat_id]['Run_Label']}**\n\n"
            "Enter the 4 numbers (A, B, C, D):\n"
            "Example: `18, 166, 33, 65`"
        )
        msg = bot.reply_to(message, text, parse_mode='Markdown', reply_markup=markup)
        bot.register_next_step_handler(msg, confirm_data)

    def confirm_data(message):
        if route_command(message):
            return
        chat_id = message.chat.id
        text_input = message.text or ''

        if text_input == BTN_BACK or chat_id not in user_data:
            show_main_menu(message)
            return

        try:
            parts = [float(x.strip()) for x in text_input.split(',')]
            if len(parts) != 4 or any(p < 0 for p in parts):
                raise ValueError("Need 4 non-negative values")
        except Exception:
            bot.reply_to(message, "❌ **Format Error!**\nUse commas: `18, 166, 33, 65`", parse_mode='Markdown')
            prompt_numbers(message)   # ask again, keeping the chosen group
            return

        user_data[chat_id]['temp_input'] = parts
        markup = types.ReplyKeyboardMarkup(row_width=2, one_time_keyboard=True)
        markup.add(BTN_YES, BTN_EDIT)
        markup.add(BTN_CANCEL)
        msg = bot.reply_to(message,
                           f"🧐 **Please Confirm:**\nData: `{text_input}`\n\nIs this correct?",
                           parse_mode='Markdown', reply_markup=markup)
        bot.register_next_step_handler(msg, process_confirmation)

    def process_confirmation(message):
        if route_command(message):
            return
        chat_id = message.chat.id
        choice = message.text or ''
        data = user_data.get(chat_id)

        if choice == BTN_EDIT and data:
            msg = bot.reply_to(message, "✍️ **Okay, re-enter the numbers:**",
                               reply_markup=types.ReplyKeyboardRemove(), parse_mode='Markdown')
            bot.register_next_step_handler(msg, confirm_data)
            return

        if choice == BTN_YES and data and 'temp_input' in data:
            row = build_row(state['session'], data['Run_Label'], data['Group_Name'], data['temp_input'])
            try:
                resp = requests.post(powerbi_url, json=[row], timeout=20)
                if resp.status_code == 200:
                    summary = (
                        f"✅ **Saved Successfully!**\n"
                        f"---------------------------\n"
                        f"💰 Total Cost: RM{row['Total_Cost']:,.0f}\n"
                        f"📈 **PROFIT: RM{row['Profit']:,.0f}**\n"
                        f"⚡ LMPU: {row['LMPU']}\n"
                    )
                    bot.reply_to(message, summary, parse_mode='Markdown')
                    print(f"[{datetime.now():%H:%M:%S}] saved  {data['Group_Name']} {data['Run_Label']}")
                    try:
                        with LEDGER_LOCK:
                            ledger = ledger_load()
                            ledger_add(ledger, row['Session'], data['Run_Label'],
                                       data['Group_Name'], data['temp_input'], row)
                            ledger_save(ledger)
                    except Exception as e:
                        print(f"WARNING: sent to Power BI but could not write ledger.json: {e}")
                else:
                    bot.reply_to(message, "⚠️ Power BI did not accept the data. Please tell your lecturer.")
                    print(f"[{datetime.now():%H:%M:%S}] POWER BI ERROR {resp.status_code}: {resp.text[:300]}")
                    print("   -> Check the Push URL in config.ini and that the dataset has all 16 fields.")
            except Exception as e:
                bot.reply_to(message, "⚠️ **Network Error!** Check WiFi.", parse_mode='Markdown')
                print(f"[{datetime.now():%H:%M:%S}] network error: {e}")

        show_main_menu(message)

    # ------------------------------------------------------------------
    # DATA MANAGEMENT  (/manage): edit / delete entries, remove or restore
    # whole sessions. Every change makes a backup of ledger.json first.
    # ------------------------------------------------------------------
    admin_pin = cfg_get('admin_pin')          # optional: set admin_pin in config.ini
    admin_chats = set()

    def require_admin(message, proceed):
        if not admin_pin or message.chat.id in admin_chats:
            proceed(message)
            return
        msg = bot.send_message(message.chat.id, "🔒 Enter the admin PIN:",
                               reply_markup=types.ReplyKeyboardRemove())
        bot.register_next_step_handler(msg, check_pin, proceed)

    def check_pin(message, proceed):
        if route_command(message):
            return
        if (message.text or '').strip() == admin_pin:
            admin_chats.add(message.chat.id)
            try:
                bot.delete_message(message.chat.id, message.message_id)   # hide the PIN
            except Exception:
                pass
            proceed(message)
        else:
            bot.send_message(message.chat.id, "❌ Wrong PIN.")
            show_main_menu(message)

    @bot.message_handler(commands=['manage'])
    def cmd_manage(message):
        require_admin(message, show_manage_menu)

    # Hidden on purpose (not in any menu): clearing the bot's list orphans any data that is
    # still on the dashboard, so it can never be removed or edited again from Telegram.
    @bot.message_handler(commands=['resetledger'])
    def cmd_resetledger(message):
        require_admin(message, confirm_forget)

    def show_manage_menu(message):
        with LEDGER_LOCK:
            ledger = ledger_load()
        active = sum(1 for e in ledger['entries'] if e['status'] == 'active')
        removed = sum(1 for e in ledger['entries'] if e['status'] == 'removed')
        markup = types.ReplyKeyboardMarkup(row_width=1, one_time_keyboard=True, resize_keyboard=True)
        markup.add(BTN_M_EDIT, BTN_M_REMOVE, BTN_M_RESTORE, BTN_BACK)
        msg = bot.send_message(
            message.chat.id,
            f"🛠 **Manage data**\n"
            f"Entries tracked: {active} active, {removed} removed.\n"
            f"A backup is saved before every change, and removed data can be restored.",
            parse_mode='Markdown', reply_markup=markup)
        bot.register_next_step_handler(msg, manage_choice)

    def manage_choice(message):
        if route_command(message):
            return
        t = message.text or ''
        if t == BTN_M_EDIT:
            pick_session(message, 'edit')
        elif t == BTN_M_REMOVE:
            pick_session(message, 'remove')
        elif t == BTN_M_RESTORE:
            pick_session(message, 'restore')
        elif t == BTN_M_FORGET:
            confirm_forget(message)
        elif t == BTN_BACK:
            show_main_menu(message)
        else:
            show_manage_menu(message)

    def pick_session(message, mode):
        want = 'removed' if mode == 'restore' else 'active'
        with LEDGER_LOCK:
            ledger = ledger_load()
        counts, last_id = {}, {}
        for e in ledger['entries']:
            if e['status'] == want:
                counts[e['session']] = counts.get(e['session'], 0) + 1
                last_id[e['session']] = e['id']
        if not counts:
            what = 'removed entries' if mode == 'restore' else 'entries sent by the bot yet'
            bot.send_message(message.chat.id, f"ℹ️ There are no {what}.")
            show_manage_menu(message)
            return
        mapping = {}
        markup = types.ReplyKeyboardMarkup(row_width=1, one_time_keyboard=True, resize_keyboard=True)
        if mode == 'remove' and len(counts) > 1:
            label = f"🗑️ ALL sessions ({sum(counts.values())})"
            mapping[label] = ALL_SESSIONS
            markup.add(label)
        for name in sorted(counts, key=lambda s: -last_id[s]):
            label = f"{name} ({counts[name]})"
            mapping[label] = name
            markup.add(label)
        markup.add(BTN_BACK)
        msg = bot.send_message(message.chat.id, "Choose the session:", reply_markup=markup)
        bot.register_next_step_handler(msg, handle_session_pick, mode, mapping)

    def handle_session_pick(message, mode, mapping):
        if route_command(message):
            return
        text = message.text or ''
        name = mapping.get(text)
        if not name:
            show_manage_menu(message)
            return
        if mode == 'remove':
            confirm_remove_session(message, name)
        else:
            list_entries(message, name, mode)

    # ---- remove a whole session ------------------------------------
    def confirm_remove_session(message, name):
        with LEDGER_LOCK:
            ledger = ledger_load()
        n = sum(1 for e in ledger['entries']
                if (name == ALL_SESSIONS or e['session'] == name) and e['status'] == 'active')
        shown = "**every session**" if name == ALL_SESSIONS else f"`{name}`"
        markup = types.ReplyKeyboardMarkup(row_width=1, one_time_keyboard=True, resize_keyboard=True)
        markup.add(BTN_RM_YES, BTN_CANCEL)
        msg = bot.send_message(
            message.chat.id,
            f"🗑️ Remove **all {n} entries** of {shown} from the dashboard?\n\n"
            "Their values are cancelled out. A backup is saved first, and you can "
            "bring them back with ♻️ Restore.",
            parse_mode='Markdown', reply_markup=markup)
        bot.register_next_step_handler(msg, do_remove_session, name)

    def do_remove_session(message, name):
        if route_command(message):
            return
        if (message.text or '') != BTN_RM_YES:
            bot.send_message(message.chat.id, "Cancelled. Nothing was changed.")
            show_manage_menu(message)
            return
        with LEDGER_LOCK:
            ledger = ledger_load()
            entries = [e for e in ledger['entries']
                       if (name == ALL_SESSIONS or e['session'] == name) and e['status'] == 'active']
            if not entries:
                bot.send_message(message.chat.id, "ℹ️ Nothing left to remove in that session.")
                show_manage_menu(message)
                return
            backup = ledger_backup('before_remove_session')
            ok, err = post_rows(powerbi_url, [reversal_row(e['row']) for e in entries])
            if ok:
                stamp = now_iso()
                for e in entries:
                    e['status'] = 'removed'
                    e['removed_at'] = stamp
                    e['removed_via'] = 'session'
                ledger_save(ledger)
                print(f"[{datetime.now():%H:%M:%S}] removed session {name} ({len(entries)} entries)")
                bot.send_message(message.chat.id,
                                 f"✅ Removed {len(entries)} entries of "
                                 f"{'every session' if name == ALL_SESSIONS else '`' + name + '`'}.\n"
                                 f"💾 Backup: `{backup}`\n"
                                 "Use ♻️ Restore removed data to bring them back.",
                                 parse_mode='Markdown')
            else:
                print(f"[{datetime.now():%H:%M:%S}] REMOVE FAILED: {err}")
                bot.send_message(message.chat.id, f"⚠️ Nothing was changed. {err}")
        show_manage_menu(message)

    # ---- pick one entry (edit / delete / restore) -------------------
    def list_entries(message, name, mode):
        want = 'removed' if mode == 'restore' else 'active'
        with LEDGER_LOCK:
            ledger = ledger_load()
        entries = [e for e in ledger['entries'] if e['session'] == name and e['status'] == want]
        entries.sort(key=lambda e: -e['id'])
        shown = entries[:40]
        if not shown:
            bot.send_message(message.chat.id, "ℹ️ No entries found.")
            show_manage_menu(message)
            return
        mapping = {}
        markup = types.ReplyKeyboardMarkup(row_width=1, one_time_keyboard=True, resize_keyboard=True)
        if mode == 'restore':
            markup.add(BTN_RESTORE_ALL)
        for e in shown:
            label = entry_label(e)
            mapping[label] = e['id']
            markup.add(label)
        markup.add(BTN_BACK)
        extra = f"\n(showing the latest {len(shown)} of {len(entries)})" if len(entries) > len(shown) else ""
        action = "restore" if mode == 'restore' else "edit or delete"
        msg = bot.send_message(message.chat.id,
                               f"Choose the entry to {action} in `{name}`:{extra}\n"
                               "Format: #id RUN · Group · A, B, C, D",
                               parse_mode='Markdown', reply_markup=markup)
        bot.register_next_step_handler(msg, handle_entry_pick, name, mode, mapping)

    def handle_entry_pick(message, name, mode, mapping):
        if route_command(message):
            return
        text = message.text or ''
        if mode == 'restore':
            if text == BTN_RESTORE_ALL:
                do_restore(message, name, None)
                return
            if text in mapping:
                do_restore(message, name, [mapping[text]])
                return
        elif text in mapping:
            show_entry_actions(message, mapping[text])
            return
        show_manage_menu(message)

    # ---- restore ----------------------------------------------------
    def do_restore(message, name, ids):
        with LEDGER_LOCK:
            ledger = ledger_load()
            entries = [e for e in ledger['entries']
                       if e['session'] == name and e['status'] == 'removed'
                       and (ids is None or e['id'] in ids)]
            if not entries:
                bot.send_message(message.chat.id, "ℹ️ Nothing to restore.")
                show_manage_menu(message)
                return
            backup = ledger_backup('before_restore')
            rows = []
            for e in entries:
                r = dict(e['row'])
                r['Timestamp'] = now_iso()
                rows.append(r)
            ok, err = post_rows(powerbi_url, rows)
            if ok:
                for e in entries:
                    e['status'] = 'active'
                    e.pop('removed_at', None)
                    e.pop('removed_via', None)
                ledger_save(ledger)
                print(f"[{datetime.now():%H:%M:%S}] restored {len(entries)} entries of {name}")
                bot.send_message(message.chat.id,
                                 f"♻️ Restored {len(entries)} entries of `{name}`.\n💾 Backup: `{backup}`",
                                 parse_mode='Markdown')
            else:
                print(f"[{datetime.now():%H:%M:%S}] RESTORE FAILED: {err}")
                bot.send_message(message.chat.id, f"⚠️ Nothing was changed. {err}")
        show_manage_menu(message)

    # ---- edit / delete one entry ------------------------------------
    def show_entry_actions(message, entry_id):
        with LEDGER_LOCK:
            e = ledger_find(ledger_load(), entry_id)
        if not e or e['status'] != 'active':
            bot.send_message(message.chat.id, "ℹ️ That entry is no longer active.")
            show_manage_menu(message)
            return
        r = e['row']
        markup = types.ReplyKeyboardMarkup(row_width=1, one_time_keyboard=True, resize_keyboard=True)
        markup.add(BTN_E_EDIT, BTN_E_DEL, BTN_BACK)
        msg = bot.send_message(
            message.chat.id,
            f"📄 **Entry #{e['id']}** · `{e['session']}`\n"
            f"{e['run']} · {e['group']}\n"
            f"A, B, C, D = `{fmt_numbers(e['numbers'])}`\n"
            f"💰 Total cost RM{r['Total_Cost']:,.0f} · 📈 Profit RM{r['Profit']:,.0f}",
            parse_mode='Markdown', reply_markup=markup)
        bot.register_next_step_handler(msg, entry_action, entry_id)

    def entry_action(message, entry_id):
        if route_command(message):
            return
        t = message.text or ''
        if t == BTN_E_EDIT:
            ask_corrected(message, entry_id)
        elif t == BTN_E_DEL:
            markup = types.ReplyKeyboardMarkup(row_width=1, one_time_keyboard=True, resize_keyboard=True)
            markup.add(BTN_RM_YES, BTN_CANCEL)
            msg = bot.send_message(message.chat.id,
                                   f"🗑️ Delete entry #{entry_id}? (a backup is saved, and it can be restored)",
                                   reply_markup=markup)
            bot.register_next_step_handler(msg, do_delete_entry, entry_id)
        else:
            show_manage_menu(message)

    def do_delete_entry(message, entry_id):
        if route_command(message):
            return
        if (message.text or '') != BTN_RM_YES:
            bot.send_message(message.chat.id, "Cancelled. Nothing was changed.")
            show_manage_menu(message)
            return
        with LEDGER_LOCK:
            ledger = ledger_load()
            e = ledger_find(ledger, entry_id)
            if not e or e['status'] != 'active':
                bot.send_message(message.chat.id, "ℹ️ That entry is no longer active.")
                show_manage_menu(message)
                return
            backup = ledger_backup('before_delete_entry')
            ok, err = post_rows(powerbi_url, [reversal_row(e['row'])])
            if ok:
                e['status'] = 'removed'
                e['removed_at'] = now_iso()
                e['removed_via'] = 'entry'
                ledger_save(ledger)
                print(f"[{datetime.now():%H:%M:%S}] deleted entry #{entry_id}")
                bot.send_message(message.chat.id,
                                 f"✅ Entry #{entry_id} deleted.\n💾 Backup: {backup}")
            else:
                print(f"[{datetime.now():%H:%M:%S}] DELETE FAILED: {err}")
                bot.send_message(message.chat.id, f"⚠️ Nothing was changed. {err}")
        show_manage_menu(message)

    def ask_corrected(message, entry_id):
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        markup.add(BTN_BACK)
        with LEDGER_LOCK:
            e = ledger_find(ledger_load(), entry_id)
        msg = bot.send_message(
            message.chat.id,
            f"Enter the **corrected** 4 numbers (A, B, C, D) for entry #{entry_id}\n"
            f"Now: `{fmt_numbers(e['numbers'])}`\nExample: `18, 166, 33, 65`",
            parse_mode='Markdown', reply_markup=markup)
        bot.register_next_step_handler(msg, got_corrected, entry_id)

    def got_corrected(message, entry_id):
        if route_command(message):
            return
        text_input = message.text or ''
        if text_input == BTN_BACK:
            show_manage_menu(message)
            return
        try:
            parts = [float(x.strip()) for x in text_input.split(',')]
            if len(parts) != 4 or any(p < 0 for p in parts):
                raise ValueError("Need 4 non-negative values")
        except Exception:
            bot.send_message(message.chat.id, "❌ **Format Error!**\nUse commas: `18, 166, 33, 65`",
                             parse_mode='Markdown')
            ask_corrected(message, entry_id)
            return
        with LEDGER_LOCK:
            e = ledger_find(ledger_load(), entry_id)
        if not e or e['status'] != 'active':
            bot.send_message(message.chat.id, "ℹ️ That entry is no longer active.")
            show_manage_menu(message)
            return
        new = calculate(e['run'], *parts)
        old = e['row']
        markup = types.ReplyKeyboardMarkup(row_width=1, one_time_keyboard=True, resize_keyboard=True)
        markup.add(BTN_EDIT_YES, BTN_CANCEL)
        msg = bot.send_message(
            message.chat.id,
            f"🧐 **Please confirm the correction** (entry #{entry_id}, {e['run']} · {e['group']})\n"
            f"Before: `{fmt_numbers(e['numbers'])}` → profit RM{old['Profit']:,.0f}\n"
            f"After:  `{fmt_numbers(parts)}` → profit RM{new['Profit']:,.0f}",
            parse_mode='Markdown', reply_markup=markup)
        bot.register_next_step_handler(msg, do_edit_entry, entry_id, parts)

    def do_edit_entry(message, entry_id, parts):
        if route_command(message):
            return
        if (message.text or '') != BTN_EDIT_YES:
            bot.send_message(message.chat.id, "Cancelled. Nothing was changed.")
            show_manage_menu(message)
            return
        with LEDGER_LOCK:
            ledger = ledger_load()
            old = ledger_find(ledger, entry_id)
            if not old or old['status'] != 'active':
                bot.send_message(message.chat.id, "ℹ️ That entry is no longer active.")
                show_manage_menu(message)
                return
            backup = ledger_backup('before_edit_entry')
            new_row = build_row(old['session'], old['run'], old['group'], parts)
            ok, err = post_rows(powerbi_url, [reversal_row(old['row']), new_row])
            if ok:
                new = ledger_add(ledger, old['session'], old['run'], old['group'], parts, new_row)
                new['replaces'] = old['id']
                old['status'] = 'edited'
                old['replaced_by'] = new['id']
                ledger_save(ledger)
                print(f"[{datetime.now():%H:%M:%S}] edited entry #{entry_id} -> #{new['id']}")
                bot.send_message(message.chat.id,
                                 f"✅ **Corrected!** Entry #{entry_id} → #{new['id']}\n"
                                 f"💰 Total Cost: RM{new_row['Total_Cost']:,.0f}\n"
                                 f"📈 **PROFIT: RM{new_row['Profit']:,.0f}**\n"
                                 f"⚡ LMPU: {new_row['LMPU']}\n💾 Backup: `{backup}`",
                                 parse_mode='Markdown')
            else:
                print(f"[{datetime.now():%H:%M:%S}] EDIT FAILED: {err}")
                bot.send_message(message.chat.id, f"⚠️ Nothing was changed. {err}")
        show_manage_menu(message)

    # ---- forget the ledger (use after resetting the dashboard) ------
    def confirm_forget(message):
        markup = types.ReplyKeyboardMarkup(row_width=1, one_time_keyboard=True, resize_keyboard=True)
        markup.add(BTN_FORGET_YES, BTN_CANCEL)
        msg = bot.send_message(
            message.chat.id,
            "🧼 **Reset the bot's own list?** (advanced)\n\n"
            "⚠️ This does **NOT** remove anything from the dashboard. It only makes the bot forget "
            "what it sent. If that data is still on the dashboard, the bot can no longer edit or remove it.\n\n"
            "To clear the dashboard from here, use 🗑️ Remove a whole session (→ ALL sessions) instead. "
            "Use this reset only AFTER you wiped the dashboard yourself in Power BI "
            "(Historic data analysis Off → Done → On → Done).\n"
            "A backup of the list is saved first.",
            parse_mode='Markdown', reply_markup=markup)
        bot.register_next_step_handler(msg, do_forget)

    def do_forget(message):
        if route_command(message):
            return
        if (message.text or '') != BTN_FORGET_YES:
            bot.send_message(message.chat.id, "Cancelled. Nothing was changed.")
            show_manage_menu(message)
            return
        with LEDGER_LOCK:
            backup = ledger_backup('before_forget')
            ledger_save({'next_id': ledger_load()['next_id'], 'entries': []})
        print(f"[{datetime.now():%H:%M:%S}] ledger cleared (backup {backup})")
        bot.send_message(message.chat.id, f"🧼 Ledger cleared.\n💾 Backup: {backup or '(was empty)'}")
        show_manage_menu(message)

    try:
        bot.set_my_commands([
            types.BotCommand("/start", "🚀 Start Simulation / Reset"),
            types.BotCommand("/help", "❓ Show Instructions"),
            types.BotCommand("/session", "🏷️ Set / change the session name"),
            types.BotCommand("/manage", "🛠 Edit / remove data (with backup)"),
        ])
    except Exception as e:
        print(f"Could not reach Telegram ({e}).")
        print("Check the internet connection and the token in config.ini.")

    print("============================================================")
    print(f"  BOT IS RUNNING.   Session: {state['session']}")
    print("  In Telegram:  /session = set wave number,  /manage = edit / remove data")
    if admin_pin:
        print("  Admin PIN is ON (from config.ini).")
    print("  Keep this window open during class. Close it to stop.")
    print("============================================================")

    while True:
        try:
            bot.polling(none_stop=True, timeout=40)
        except Exception as e:
            print(f"Internet error ({e}). Reconnecting in 5s...")
            time.sleep(5)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"\nERROR: {e}")
        input("Press Enter to close...")
