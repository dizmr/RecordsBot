import sys
import os
import re
import asyncio
import json
import shutil
import tkinter as tk
from tkinter import filedialog, simpledialog, messagebox
from datetime import datetime
import time
import base64

from mutagen.mp3 import MP3
from mutagen.wave import WAVE

if sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(), 0)
    except Exception:
        pass

if getattr(sys, 'frozen', False):
    application_path = os.path.dirname(sys.executable)
else:
    application_path = os.path.dirname(os.path.abspath(__file__))
os.chdir(application_path)

class Logger:
    def __init__(self, filename="debug.log"):
        self.terminal = sys.__stdout__
        self.log = open(filename, "a", encoding="utf-8")

    def write(self, message):
        try:
            self.terminal.write(message)
        except Exception:
            pass
        self.log.write(message)
        self.log.flush()

    def flush(self):
        self.log.flush()

    def close(self):
        self.log.close()

sys.stdout = Logger()
sys.stderr = sys.stdout
print(f"\n[{datetime.now().strftime('%d.%m.%Y %H:%M:%S')}] ===== ПРОГРАММА ЗАПУЩЕНА =====")


class _NoStdin:
    def readline(self): return ""
    def read(self, n=-1): return ""
    def __iter__(self): return iter([])
sys.stdin = _NoStdin()


try:
    loop = asyncio.get_event_loop()
    if loop.is_closed():
        raise RuntimeError
except RuntimeError:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

from pyrogram import Client, raw


async def _authorize_no_input(self):
    return await self.get_me()
Client.authorize = _authorize_no_input


# Задайте эти значения в переменных окружения, не храните их в исходном коде.
API_ID   = 8816351650 #айди апи телеги
API_HASH = "c60f74415092bf10723edf0cd090262b" #хеш апи телеги
CHAT_ID  = -4315693472 #айди чата для записей

TOPIC_ID_SHORT  = 2 #Короткие
TOPIC_ID_MEDIUM = 4 #Средние
TOPIC_ID_LONG   = 6 #Длинные

CONFIG_FILE         = "config.json"
STATS_FILE          = "stats.json"
SENT_RECORDS_FILE   = "sent_records.json"
SESSION_NAME        = "employee_session"
STABILITY_THRESHOLD = 5
FILE_SETTLE_SECONDS = 10
SEND_RETRIES        = 3


def atomic_save_json(filename: str, data: dict):
    temporary_file = f"{filename}.tmp"
    with open(temporary_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temporary_file, filename)

def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Ошибка конфига: {e}")
    return {}

def save_config(data: dict):
    atomic_save_json(CONFIG_FILE, data)

def get_config():
    cfg = load_config()
    if cfg.get("watch_path") and cfg.get("employee_name"):
        return cfg["watch_path"], cfg["employee_name"]

    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)

    employee_name = simpledialog.askstring(
        "Настройка (1/2)", "Введите имя сотрудника:", parent=root
    )
    if not employee_name:
        sys.exit()

    messagebox.showinfo("Настройка (2/2)", "Выберите папку с записями MicroSIP.")
    watch_path = filedialog.askdirectory(title="Выберите папку с записями MicroSIP")
    if not watch_path:
        sys.exit()

    cfg["watch_path"]    = watch_path
    cfg["employee_name"] = employee_name
    save_config(cfg)
    return watch_path, employee_name



def make_client():
    if not API_ID or not API_HASH or not CHAT_ID:
        raise RuntimeError(
            "Задайте TELEGRAM_API_ID, TELEGRAM_API_HASH и TELEGRAM_CHAT_ID."
        )
    cfg   = load_config()
    proxy = cfg.get("proxy", None)
    kwargs = dict(api_id=API_ID, api_hash=API_HASH, ipv6=False)
    if proxy:
        print(f"Прокси: {proxy.get('scheme')}://{proxy.get('hostname')}:{proxy.get('port')}")
        kwargs["proxy"] = proxy
    return Client(SESSION_NAME, **kwargs)



class QRAuthWindow:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Авторизация Telegram")
        self.root.resizable(False, False)
        self.root.attributes('-topmost', True)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._closed = False

        tk.Label(
            self.root,
            text="Войдите через Telegram",
            font=("Segoe UI", 14, "bold"),
            fg="#1a1a2e"
        ).pack(pady=(18, 2))

        tk.Label(
            self.root,
            text="Откройте Telegram на телефоне:\nНастройки → Устройства → Привязать устройство",
            font=("Segoe UI", 9),
            fg="#555555",
            justify="center"
        ).pack(pady=(0, 10))

        self.canvas = tk.Canvas(
            self.root, width=260, height=260,
            bg="white", highlightthickness=1, highlightbackground="#cccccc"
        )
        self.canvas.pack(padx=20, pady=5)

        self.status_var = tk.StringVar(value="⏳ Получаю QR-код...")
        self.status_label = tk.Label(
            self.root,
            textvariable=self.status_var,
            font=("Segoe UI", 9),
            fg="#0077cc"
        )
        self.status_label.pack(pady=(6, 4))

        tk.Button(
            self.root, text="Отмена",
            command=self._on_close,
            font=("Segoe UI", 9), width=12, bg="#f0f0f0"
        ).pack(pady=(2, 14))

        self.root.update_idletasks()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        ww = self.root.winfo_width()
        wh = self.root.winfo_height()
        self.root.geometry(f"+{(sw - ww) // 2}+{(sh - wh) // 2}")

    def _on_close(self):
        self._closed = True
        try:
            self.root.destroy()
        except Exception:
            pass

    def is_closed(self):
        return self._closed

    def set_status(self, text, color="#0077cc"):
        try:
            self.status_var.set(text)
            self.status_label.config(fg=color)
        except Exception:
            pass

    def show_qr(self, url: str):
        try:
            import qrcode


            qr = qrcode.QRCode(border=2)
            qr.add_data(url)
            qr.make(fit=True)
            matrix = qr.get_matrix()

            try:
                from PIL import Image, ImageTk


                size = 256
                cell = size // len(matrix)
                img = Image.new("RGB", (size, size), "white")
                pixels = img.load()
                for y, row in enumerate(matrix):
                    for x, val in enumerate(row):
                        color = (0, 0, 0) if val else (255, 255, 255)
                        for dy in range(cell):
                            for dx in range(cell):
                                px, py = x * cell + dx, y * cell + dy
                                if px < size and py < size:
                                    pixels[px, py] = color


                photo = ImageTk.PhotoImage(img, master=self.root)

                self.canvas._qr_photo = photo
                self.canvas.delete("all")
                self.canvas.create_image(0, 0, anchor="nw", image=photo)

            except ImportError:

                self.canvas.delete("all")
                size = 256
                cell = size // len(matrix)
                for y, row in enumerate(matrix):
                    for x, val in enumerate(row):
                        if val:
                            self.canvas.create_rectangle(
                                x*cell, y*cell,
                                x*cell + cell, y*cell + cell,
                                fill="black", outline="black"
                            )

            self.set_status("📱 Сканируйте QR в Telegram → Устройства")

        except Exception as e:
            print(f"Ошибка отрисовки QR: {e}")
            self.set_status("⚠️ Ошибка генерации QR", color="#cc0000")

    def success(self):
        self.set_status("✅ Авторизация успешна!", color="#009900")
        try:
            self.root.after(1800, self._on_close)
        except Exception:
            pass

    def update(self):
        try:
            self.root.update()
        except tk.TclError:
            self._closed = True


async def qr_auth(client: Client):

    win = QRAuthWindow()

    print("Запускаю QR-авторизацию...")

    authorized = False

    try:
        while not win.is_closed():

            try:
                result = await asyncio.wait_for(
                    client.invoke(
                        raw.functions.auth.ExportLoginToken(
                            api_id=API_ID,
                            api_hash=API_HASH,
                            except_ids=[]
                        )
                    ),
                    timeout=15
                )
            except asyncio.TimeoutError:
                win.set_status("⚠️ Таймаут — пробую снова...", color="#cc6600")
                await asyncio.sleep(2)
                continue
            except Exception as e:
                print(f"Ошибка ExportLoginToken: {e}")
                win.set_status(f"⚠️ Ошибка: {e}", color="#cc0000")
                await asyncio.sleep(3)
                continue


            if isinstance(result, raw.types.auth.LoginTokenMigrateTo):
                print(f"Мигрирую на DC {result.dc_id}...")
                win.set_status("🔄 Переключаю сервер...", color="#cc6600")
                try:
                    await client.session.stop()
                    await client.storage.dc_id(result.dc_id)
                    await client.session.start()
                    result = await asyncio.wait_for(
                        client.invoke(
                            raw.functions.auth.ImportLoginToken(token=result.token)
                        ),
                        timeout=15
                    )
                except Exception as e:
                    print(f"Ошибка миграции: {e}")
                    win.set_status("⚠️ Ошибка миграции DC", color="#cc0000")
                    await asyncio.sleep(3)
                    continue


            if isinstance(result, raw.types.auth.LoginTokenSuccess):
                authorized = True
                print("QR авторизация успешна (через ImportLoginToken)!")
                win.success()
                for _ in range(40):
                    if win.is_closed():
                        break
                    win.update()
                    await asyncio.sleep(0.05)
                break


            if isinstance(result, raw.types.auth.LoginToken):

                token_b64 = base64.urlsafe_b64encode(result.token).decode().rstrip("=")
                qr_url = f"tg://login?token={token_b64}"
                expires_in = result.expires - int(time.time())
                print(f"QR получен, истекает через {expires_in} сек")
                win.show_qr(qr_url)


                deadline = result.expires
                scanned = False
                next_check = time.monotonic()
                while not win.is_closed() and int(time.time()) < deadline:
                    win.update()
                    await asyncio.sleep(0.5)


                    if time.monotonic() >= next_check:
                        next_check = time.monotonic() + 3
                        try:
                            check = await asyncio.wait_for(
                                client.invoke(
                                    raw.functions.auth.ExportLoginToken(
                                        api_id=API_ID,
                                        api_hash=API_HASH,
                                        except_ids=[]
                                    )
                                ),
                                timeout=5
                            )
                            if isinstance(check, raw.types.auth.LoginTokenSuccess):
                                authorized = True
                                scanned = True
                                print("QR отсканирован!")
                                win.success()
                                for _ in range(40):
                                    if win.is_closed():
                                        break
                                    win.update()
                                    await asyncio.sleep(0.05)
                                break
                            elif isinstance(check, raw.types.auth.LoginTokenMigrateTo):

                                try:
                                    await client.session.stop()
                                    await client.storage.dc_id(check.dc_id)
                                    await client.session.start()
                                    imp = await asyncio.wait_for(
                                        client.invoke(
                                            raw.functions.auth.ImportLoginToken(token=check.token)
                                        ),
                                        timeout=10
                                    )
                                    if isinstance(imp, raw.types.auth.LoginTokenSuccess):
                                        authorized = True
                                        scanned = True
                                        print("QR авторизован после миграции DC!")
                                        win.success()
                                        for _ in range(40):
                                            if win.is_closed():
                                                break
                                            win.update()
                                            await asyncio.sleep(0.05)
                                        break
                                except Exception as e:
                                    print(f"Ошибка при миграции после скана: {e}")
                        except asyncio.TimeoutError:
                            pass
                        except Exception as e:
                            err = str(e)

                            if "SESSION_PASSWORD_NEEDED" in err or "SessionPasswordNeeded" in err:
                                scanned = True
                                authorized = await _handle_2fa(client)
                                break

                            pass

                if authorized or scanned:
                    break

                if not win.is_closed():

                    win.set_status("🔄 QR истёк, обновляю...", color="#cc6600")
                    await asyncio.sleep(0.3)
                    continue

    except Exception as e:
        print(f"Критическая ошибка QR-авторизации: {e}")
        try:
            win._on_close()
        except Exception:
            pass
        messagebox.showerror("Ошибка авторизации", str(e))
        await client.disconnect()
        sys.exit()
    finally:
        try:
            win._on_close()
        except Exception:
            pass

    if not authorized:
        print("Авторизация отменена пользователем.")
        sys.exit()

    print("QR-авторизация успешна!")


async def _handle_2fa(client: Client) -> bool:

    root2 = tk.Tk()
    root2.withdraw()
    root2.attributes('-topmost', True)
    pwd = simpledialog.askstring(
        "Telegram — 2FA",
        "Введите облачный пароль (2FA):",
        parent=root2, show="*"
    )
    root2.destroy()
    if not pwd:
        await client.disconnect()
        sys.exit()
    try:
        await client.check_password(pwd)
        print("2FA пройдена!")
        return True
    except Exception as e:
        messagebox.showerror("Ошибка 2FA", str(e))
        await client.disconnect()
        sys.exit()



def extract_phone_number(filename: str) -> str:
    match = re.search(r'7\d{9,14}', filename)
    if match:
        return match.group(0)
    nums = re.findall(r'\d+', filename)
    return max(nums, key=len) if nums else "Неизвестен"

def get_audio_duration(file_path: str) -> float:
    try:
        if file_path.lower().endswith(".mp3"):
            return MP3(file_path).info.length
        elif file_path.lower().endswith(".wav"):
            return WAVE(file_path).info.length
    except Exception as e:
        print(f"Ошибка длительности: {e}")
    return 0.0


def file_fingerprint(file_path: str, stat_result=None) -> str:
    st = stat_result or os.stat(file_path)
    normalized_path = os.path.normcase(os.path.abspath(file_path))
    return f"{normalized_path}|{st.st_size}|{st.st_mtime_ns}"


def load_sent_records() -> dict:
    if os.path.exists(SENT_RECORDS_FILE):
        try:
            with open(SENT_RECORDS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError) as e:
            print(f"Ошибка журнала отправок: {e}")
    return {}


def save_sent_records(records: dict):
    atomic_save_json(SENT_RECORDS_FILE, records)


def get_archive_path(watch_path: str) -> str:
    parent = os.path.dirname(os.path.abspath(watch_path))
    folder_name = os.path.basename(os.path.normpath(watch_path))
    return os.path.join(parent, f"{folder_name}_sent")


def move_to_archive(file_path: str, archive_path: str) -> str:
    os.makedirs(archive_path, exist_ok=True)
    destination = os.path.join(archive_path, os.path.basename(file_path))
    if os.path.exists(destination):
        stem, extension = os.path.splitext(os.path.basename(file_path))
        destination = os.path.join(
            archive_path,
            f"{stem}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}{extension}"
        )
    return shutil.move(file_path, destination)

def format_duration(seconds: float) -> str:
    s = int(seconds)
    if s < 60:
        return f"{s} сек"
    m, s = divmod(s, 60)
    return f"{m} мин {s} сек"

def is_file_locked(file_path: str) -> bool:
    try:
        with open(file_path, "a+b"):
            pass
        return False
    except OSError:
        return True

def is_file_stable(file_path: str, stat_result=None) -> bool:
    try:
        st = stat_result or os.stat(file_path)
        if st.st_size <= 1024:
            return False
        if time.time() - st.st_mtime < FILE_SETTLE_SECONDS:
            return False
        if is_file_locked(file_path):
            return False
        return True
    except OSError:
        return False

def classify_call(duration_seconds: float):
    if duration_seconds < 60:
        return "Меньше минуты", TOPIC_ID_SHORT
    elif duration_seconds <= 600:
        return "1-10 минут",    TOPIC_ID_MEDIUM
    else:
        return "Больше 10 минут", TOPIC_ID_LONG



def load_stats() -> dict:
    default = {"total_sent": 0, "total_errors": 0}
    if os.path.exists(STATS_FILE):
        try:
            with open(STATS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            for k, v in default.items():
                data.setdefault(k, v)
            return data
        except Exception:
            pass
    return default

def save_stats(stats: dict):
    atomic_save_json(STATS_FILE, stats)


async def send_audio_with_retry(client: Client, **kwargs):
    for attempt in range(1, SEND_RETRIES + 1):
        try:
            return await client.send_audio(**kwargs)
        except (OSError, ConnectionError, asyncio.TimeoutError):
            if attempt == SEND_RETRIES:
                raise
            delay = 2 ** (attempt - 1)
            print(f"Сетевая ошибка отправки, повтор через {delay} сек.")
            await asyncio.sleep(delay)
            if not getattr(client, "is_connected", False):
                await client.connect()



async def monitor_and_upload(client: Client, watch_path: str, employee_name: str):
    stats        = load_stats()
    sent_records = load_sent_records()
    file_tracker : dict = {}
    archive_path = get_archive_path(watch_path)

    print("Прогреваю кэш диалогов...")
    try:
        async for dialog in client.get_dialogs():
            if dialog.chat.id == CHAT_ID:
                print(f"Группа найдена: {dialog.chat.title}")
                break
    except Exception as e:
        print(f"Ошибка поиска диалогов: {e}")

    print(f"Мониторинг запущен. Сотрудник: {employee_name} | Папка: {watch_path}")

    while True:
        try:
            if not os.path.exists(watch_path):
                print(f"Папка не найдена: {watch_path}")
                await asyncio.sleep(5)
                continue

            with os.scandir(watch_path) as entries:
                audio_files = [
                    (entry.path, entry.stat())
                    for entry in entries
                    if entry.is_file() and entry.name.lower().endswith((".wav", ".mp3"))
                ]

            pending = []

            for file_path, stat_result in audio_files:
                try:
                    curr_size = stat_result.st_size
                    curr_mtime = stat_result.st_mtime_ns
                    fingerprint = file_fingerprint(file_path, stat_result)
                    info = file_tracker.get(file_path, {"size": 0, "stable_ticks": 0})

                    if curr_size > 1024 and curr_size == info["size"]:
                        info["stable_ticks"] += 1
                    else:
                        info["stable_ticks"] = 0
                        info["sent"] = False

                    if curr_mtime != info.get("mtime"):
                        info["stable_ticks"] = 0
                        info["sent"] = False

                    info["size"] = curr_size
                    info["mtime"] = curr_mtime
                    file_tracker[file_path] = info

                    if fingerprint in sent_records:
                        try:
                            move_to_archive(file_path, archive_path)
                            file_tracker.pop(file_path, None)
                            print(f"Перенесен ранее отправленный файл: {os.path.basename(file_path)}")
                        except OSError as e:
                            print(f"Ошибка переноса ранее отправленного файла {file_path}: {e}")
                        continue

                    if info.get("sent"):
                        continue

                    stable = (
                        info["stable_ticks"] >= STABILITY_THRESHOLD
                        and is_file_stable(file_path, stat_result)
                    )

                    fname = os.path.basename(file_path)
                    print(
                        f"  {fname} | {curr_size}б | "
                        f"тики:{info['stable_ticks']}/{STABILITY_THRESHOLD} | "
                        f"stable:{stable}"
                    )

                    if stable:
                        pending.append(file_path)

                except FileNotFoundError:
                    file_tracker.pop(file_path, None)
                except Exception as e:
                    print(f"Ошибка файла {file_path}: {e}")

            stats_dirty = False
            for file_path in pending:
                fname = os.path.basename(file_path)
                try:
                    stat_result = os.stat(file_path)
                    fingerprint = file_fingerprint(file_path, stat_result)
                    if fingerprint in sent_records:
                        continue

                    phone     = extract_phone_number(fname)
                    dur_sec   = get_audio_duration(file_path)
                    dur_label, topic_id = classify_call(dur_sec)
                    date_str  = datetime.now().strftime("%d.%m.%Y %H:%M:%S")

                    caption = (
                        f"Сотрудник: {employee_name}\n"
                        f"Дата: {date_str}\n"
                        f"Номер: {phone}\n"
                        f"Длительность: {format_duration(dur_sec)}\n"
                        f"Категория: {dur_label}"
                    )

                    print(f"Отправляю: {fname} -> тема #{topic_id}")

                    await send_audio_with_retry(
                        client,
                        chat_id=CHAT_ID,
                        audio=file_path,
                        caption=caption,
                        reply_to_message_id=topic_id,
                    )

                    sent_records[fingerprint] = {
                        "sent_at": datetime.now().isoformat(timespec="seconds"),
                        "filename": fname,
                    }
                    save_sent_records(sent_records)

                    try:
                        move_to_archive(file_path, archive_path)
                        file_tracker.pop(file_path, None)
                    except OSError as e:
                        print(f"Отправлен, но не перенесен в архив {fname}: {e}")

                    if file_path in file_tracker:
                        file_tracker[file_path]["sent"] = True

                    stats["total_sent"] += 1
                    stats_dirty = True
                    print(f"Отправлен: {fname}")

                except Exception as e:
                    print(f"Ошибка отправки {fname}: {e}")
                    stats["total_errors"] = stats.get("total_errors", 0) + 1
                    stats_dirty = True
                    if file_path in file_tracker:
                        file_tracker[file_path]["stable_ticks"] = 0

            if stats_dirty:
                save_stats(stats)

            for path in list(file_tracker.keys()):
                if not os.path.exists(path):
                    file_tracker.pop(path, None)

        except Exception as e:
            print(f"Ошибка главного цикла: {e}")

        await asyncio.sleep(3)


async def main():
    watch_path, employee_name = get_config()

    client = make_client()


    print("Подключаюсь к Telegram...")
    await client.connect()


    try:
        me = await client.get_me()
        client.me = me  
        print(f"Уже авторизован как: {me.first_name}")
    except Exception:

        print("Сессия не найдена, запускаю QR-авторизацию...")
        await qr_auth(client)

        me = await client.get_me()
        client.me = me 
        print(f"Авторизован как: {me.first_name}")


    try:
        await monitor_and_upload(client, watch_path, employee_name)
    finally:
        await client.disconnect()


if __name__ == "__main__":
    try:
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        print("Выход.")
    finally:
        logger = sys.stdout
        if isinstance(logger, Logger):
            logger.flush()
            logger.close()
