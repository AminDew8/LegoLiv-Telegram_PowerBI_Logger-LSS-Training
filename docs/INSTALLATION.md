# Installation guide

Works on **Windows 10 and 11**. You need an internet connection and a Microsoft account (for Power BI).

Prefer to watch? The [video tutorial](https://youtu.be/h4aG33HNhrA?t=72) shows the launcher and first start step by step.

## What gets installed

| Program | Used for | Installed by |
|---|---|---|
| **Python 3** | Runs the bot | `INSTALL.bat` |
| **Telegram Desktop** | Talk to the bot from the PC (phones work too) | `INSTALL.bat` |
| **Power BI Desktop** | Opens and edits the dashboard | `INSTALL.bat` |
| Python libraries (`pyTelegramBotAPI`, `requests`) | Bot code | `INSTALL.bat` |

## Step 1 - Download

On the GitHub page press the green **Code** button, then **Download ZIP**. Right-click the ZIP, **Extract All**, and open the folder.

## Step 2 - Run the installer

Double-click **`INSTALL.bat`**.

- A black window shows each step. Programs that are already installed are skipped.
- If Windows asks "Do you want to allow this app to make changes?", press **Yes**.
- Power BI Desktop comes from the Microsoft Store. If the automatic install does not finish, the Store page opens: press **Get**.
- When it says **Finished**, a shortcut named **Legoliv Data Logger** is on your Desktop (it starts the bot). Close the window.

> If Windows shows a blue "Windows protected your PC" box, press **More info**, then **Run anyway**. This happens for any downloaded script.

**Install by hand instead** (if the installer fails):

| Program | Where |
|---|---|
| Python | python.org/downloads (tick **Add python.exe to PATH**) |
| Telegram Desktop | desktop.telegram.org |
| Power BI Desktop | Microsoft Store, search "Power BI Desktop" |
| Libraries | open Command Prompt in the folder and run `pip install -r requirements.txt` |

## Step 3 - Create your Telegram bot (once)

1. In Telegram search for **@BotFather** and press **Start**.
2. Send `/newbot`, choose a name (for example `Lean6SigmaTools`) and a username ending in `bot`.
3. BotFather replies with a **token** like `123456789:ABCdef...`. Keep it private.

(If you are using the existing class bot, ask the owner for its token.)

## Step 4 - Power BI setup (once)

Follow **[POWERBI_SETUP.md](POWERBI_SETUP.md)**. You will end with a **Push URL**.

## Step 5 - Start the bot

Double-click the **Legoliv Data Logger** shortcut on your Desktop (or **`START_BOT.bat`** in the folder).

The first time it asks:

1. `Paste the bot token` : paste the token from BotFather and press Enter.
2. `Paste the Push URL` : paste the URL from Power BI and press Enter.

(Right-click inside the black window to paste.) They are saved in `config.ini`, so you are not asked again. When you see **BOT IS RUNNING**, the bot is live.

Keep this window open during class. Closing it stops the bot.

## Step 6 - Try it

Open your bot in Telegram, send `/start`, press **I Understand**, choose the wave, press **RUN 1**, **Group 1**, and send `18, 166, 33, 65`. Then see **[USER_GUIDE.md](USER_GUIDE.md)**.

## Optional - a single .exe

Double-click **`BUILD_EXE.bat`**. It creates `legobot.exe`. Copy that file and `config.ini` to any PC and double-click the exe; no Python is needed there.

## Troubleshooting

| Problem | Fix |
|---|---|
| Bot does not answer | Is the black window open and online? Only **one** copy of the bot may run at a time (two copies block each other). |
| "Python is not installed" | Run `INSTALL.bat` again, or restart the PC after installing Python. |
| `pip` errors | Check the internet connection and run `INSTALL.bat` again. |
| Wrong token / URL saved | Open `config.ini` in Notepad, clear the wrong value, save, and start the bot again. |
| No shortcut on the Desktop | Run `INSTALL.bat` again (safe to repeat), or right-click `START_BOT.bat` and choose **Send to**, then **Desktop (create shortcut)**. |
