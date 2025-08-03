import tkinter as tk
from tkinter import ttk, scrolledtext
import threading
import sys
import re
import json
import os
import requests
# tqdm 在GUI中不再需要，可以移除，但为了后端逻辑完整性，暂时保留
# from tqdm import tqdm
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# ==============================================================================
# 1. 后端核心逻辑 (新增 playlist 更新函数)
# ==============================================================================

def intercept_douyin_api_response(text_blob: str):
    """
    使用Playwright启动浏览器，访问抖音链接，并拦截特定的API请求以获取其响应。
    """
    match = re.search(r'https?://[^\s]+', text_blob)
    if not match:
        print("错误：未在文本中找到URL。")
        return None, None

    start_url = match.group(0)
    print(f"步骤 1: 成功提取到初始URL -> {start_url}")

    target_api_url = "aweme/v1/web/aweme/detail/"
    api_response_json = None
    final_url = None

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36'
        )
        page = context.new_page()
        print("步骤 2: 浏览器已启动，准备开始拦截网络请求。")

        def handle_response(response):
            nonlocal api_response_json
            if target_api_url in response.url and response.status == 200:
                print(f"--- 拦截成功！---\n捕获到目标API请求: {response.url}")
                try:
                    api_response_json = response.json()
                    print("成功解析响应内容为JSON。\n-----------------")
                except Exception as e:
                    print(f"解析响应为JSON时出错: {e}")

        page.on("response", handle_response)
        try:
            print(f"步骤 3: 正在导航到初始URL -> {start_url}")
            page.goto(start_url, wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(3000)
            final_url = page.url
            print(f"步骤 4: 页面加载完成，最终URL为 -> {final_url}")
        except PlaywrightTimeoutError:
            print("页面加载超时。但可能目标API已经加载，继续检查结果。")
        except Exception as e:
            print(f"导航或页面加载过程中发生错误: {e}")
        finally:
            browser.close()

    if api_response_json:
        print("步骤 5: 成功获取API响应。")
        return api_response_json, final_url
    else:
        print("\n错误：未能成功拦截到目标API的有效响应。")
        return None, None

def download_video_from_uri(video_uri: str, filename_base: str):
    """
    根据视频URI下载视频并使用指定的文件名基础。
    """
    if not all([video_uri, filename_base]):
        print("错误：缺少下载视频所需的 video_uri 或 filename_base。")
        return False

    video_url = f"https://www.douyin.com/aweme/v1/play/?video_id={video_uri}"
    print(f"\n[视频下载模块] 准备下载视频，URL: {video_url}")

    folder_name = "MP4"
    if not os.path.exists(folder_name):
        print(f"[视频下载模块] 文件夹 '{folder_name}' 不存在，正在创建...")
        os.makedirs(folder_name)

    filepath = os.path.join(folder_name, f"{filename_base}.mp4")
    if os.path.exists(filepath):
        print(f"[视频下载模块] 视频 '{filepath}' 已存在，跳过下载。")
        return True # 已存在也算成功

    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36'}
    try:
        with requests.get(video_url, headers=headers, stream=True, timeout=60) as r:
            r.raise_for_status()
            total_size = int(r.headers.get('content-length', 0))
            print(f"开始下载 {filename_base}.mp4, 文件大小: {total_size / 1024 / 1024:.2f} MB")
            with open(filepath, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
        print(f"\n[视频下载模块] 视频下载成功！已保存至: {filepath}")
        return True
    except Exception as e:
        print(f"\n[视频下载模块] 下载视频时发生错误: {e}")
        return False

def download_static_cover(cover_url: str, filename_base: str):
    """
    根据封面URL下载封面并使用指定的文件名基础。
    """
    if not all([cover_url, filename_base]):
        print("错误：缺少下载封面所需的 cover_url 或 filename_base。")
        return False

    print(f"\n[封面下载模块] 准备下载封面，URL: {cover_url}")

    folder_name = "albumArt"
    if not os.path.exists(folder_name):
        print(f"[封面下载模块] 文件夹 '{folder_name}' 不存在，正在创建...")
        os.makedirs(folder_name)

    filepath = os.path.join(folder_name, f"{filename_base}.jpg")
    if os.path.exists(filepath):
        print(f"[封面下载模块] 封面 '{filepath}' 已存在，跳过下载。")
        return True # 已存在也算成功

    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36'}
    try:
        with requests.get(cover_url, headers=headers, stream=True, timeout=30) as r:
            r.raise_for_status()
            print(f"开始下载封面 {filename_base}.jpg")
            with open(filepath, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
        print(f"\n[封面下载模块] 封面下载成功！已保存至: {filepath}")
        return True
    except Exception as e:
        print(f"\n[封面下载模块] 下载封面时发生错误: {e}")
        return False

# ==============================================================================
# 新增功能: 更新 playlist.json
# ==============================================================================
def update_playlist_json(title: str, artist: str, video_path: str, cover_path: str, description: str):
    """
    读取、更新并写回 playlist.json 文件。
    """
    playlist_file = "playlist.json"
    print(f"\n[JSON模块] 准备更新播放列表文件: {playlist_file}")

    # 1. 构造新条目
    new_entry = {
        "type": "video",
        "src": video_path.replace(os.sep, '/'),  # 确保路径使用/
        "title": title,
        "artist": artist,
        "albumArt": cover_path.replace(os.sep, '/'), # 确保路径使用/
        "lyrics": description or "" # 使用视频描述作为歌词，如果没有则为空字符串
    }

    # 2. 读取现有数据
    playlist = []
    if os.path.exists(playlist_file):
        try:
            with open(playlist_file, 'r', encoding='utf-8') as f:
                playlist = json.load(f)
                if not isinstance(playlist, list): # 确保文件内容是列表
                    print(f"警告: {playlist_file} 内容格式不正确，将创建新的列表。")
                    playlist = []
        except (json.JSONDecodeError, UnicodeDecodeError):
            print(f"警告: 读取或解析 {playlist_file} 失败，将创建新的列表。")
            playlist = []

    # 3. 检查是否重复
    if any(item.get("src") == new_entry["src"] for item in playlist):
        print(f"[JSON模块] 条目 '{new_entry['src']}' 已存在于播放列表中，跳过添加。")
        return

    # 4. 追加新条目并写回文件
    playlist.append(new_entry)
    try:
        with open(playlist_file, 'w', encoding='utf-8') as f:
            # ensure_ascii=False 保证中文正常显示，indent=2 格式化输出
            json.dump(playlist, f, ensure_ascii=False, indent=2)
        print(f"[JSON模块] 成功将新条目追加到 {playlist_file}")
    except Exception as e:
        print(f"[JSON模块] 写入 {playlist_file} 时发生错误: {e}")


# ==============================================================================
# 2. GUI界面和逻辑
# ==============================================================================

class TextRedirector:
    """一个将print输出重定向到Tkinter Text小部件的类"""
    def __init__(self, widget, tag="stdout"):
        self.widget = widget
        self.tag = tag

    def write(self, str):
        self.widget.configure(state="normal")
        self.widget.insert("end", str, (self.tag,))
        self.widget.see("end") # 自动滚动到底部
        self.widget.configure(state="disabled")

    def flush(self):
        pass

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("抖音视频下载器")
        self.geometry("700x550")

        self.video_details_cache = None # 用于缓存解析结果

        # --- 创建控件 ---
        main_frame = ttk.Frame(self, padding="10")
        main_frame.pack(fill="both", expand=True)

        # 链接输入
        ttk.Label(main_frame, text="抖音分享口令/链接:").grid(row=0, column=0, sticky="w", pady=2)
        self.link_entry = ttk.Entry(main_frame, width=80)
        self.link_entry.grid(row=1, column=0, columnspan=2, sticky="ew", pady=2)

        # 作者名输入
        ttk.Label(main_frame, text="作者名称 (解析后自动填充):").grid(row=2, column=0, sticky="w", pady=2)
        self.author_entry = ttk.Entry(main_frame, width=80)
        self.author_entry.grid(row=3, column=0, columnspan=2, sticky="ew", pady=2)

        # 歌曲名输入
        ttk.Label(main_frame, text="歌曲/视频标题 (解析后自动填充):").grid(row=4, column=0, sticky="w", pady=2)
        self.song_entry = ttk.Entry(main_frame, width=80)
        self.song_entry.grid(row=5, column=0, columnspan=2, sticky="ew", pady=2)

        # 按钮
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=6, column=0, columnspan=2, pady=10)
        self.parse_button = ttk.Button(button_frame, text="1. 解析链接", command=self.start_parsing)
        self.parse_button.pack(side="left", padx=5)
        self.download_button = ttk.Button(button_frame, text="2. 开始下载并更新列表", command=self.start_downloading, state="disabled")
        self.download_button.pack(side="left", padx=5)

        # 日志输出框
        ttk.Label(main_frame, text="日志输出:").grid(row=7, column=0, sticky="w", pady=2)
        self.log_text = scrolledtext.ScrolledText(main_frame, height=15, wrap=tk.WORD, state="disabled")
        self.log_text.grid(row=8, column=0, columnspan=2, sticky="nsew")

        main_frame.grid_rowconfigure(8, weight=1)
        main_frame.grid_columnconfigure(0, weight=1)

        # --- 重定向stdout ---
        sys.stdout = TextRedirector(self.log_text, "stdout")
        sys.stderr = TextRedirector(self.log_text, "stderr")

    def set_ui_state(self, is_busy):
        """统一管理UI控件状态"""
        state = "disabled" if is_busy else "normal"
        self.parse_button.config(state=state)
        # 只有解析成功后才启用下载按钮
        if not is_busy and self.video_details_cache:
            self.download_button.config(state="normal")
        else:
            self.download_button.config(state="disabled")

    def start_parsing(self):
        """启动一个新线程来解析链接，避免GUI卡死"""
        link = self.link_entry.get()
        if not link:
            print("错误：请输入分享链接！")
            return

        self.log_text.configure(state="normal")
        self.log_text.delete(1.0, "end") # 清空日志
        self.log_text.configure(state="disabled")

        self.set_ui_state(is_busy=True)
        self.video_details_cache = None # 清除旧缓存

        thread = threading.Thread(target=self.parse_worker, args=(link,))
        thread.daemon = True
        thread.start()

    def parse_worker(self, link):
        """在后台线程中执行的解析任务"""
        print("开始解析，请稍候...\n")
        try:
            video_details, _ = intercept_douyin_api_response(link)
            if video_details:
                self.video_details_cache = video_details
                aweme_detail = video_details.get("aweme_detail", {})

                author_nickname = aweme_detail.get("author", {}).get("nickname", "未知作者")
                # 视频标题优先于音乐标题
                title = aweme_detail.get("desc", "未知标题")
                if not title: # 如果视频标题为空，尝试用音乐标题
                    title = aweme_detail.get("music", {}).get("title", "未知标题")

                # 在主线程中更新UI
                self.after(0, self.update_parse_results, author_nickname, title)
            else:
                print("\n解析失败，请检查链接或网络。")
        except Exception as e:
            print(f"\n解析过程中发生严重错误: {e}")
        finally:
            # 无论成功失败，都在主线程中恢复UI状态
            self.after(0, self.set_ui_state, False)

    def update_parse_results(self, author, title):
        """在GUI主线程中安全地更新输入框内容"""
        self.author_entry.delete(0, "end")
        self.author_entry.insert(0, author)
        self.song_entry.delete(0, "end")
        self.song_entry.insert(0, title)
        print("\n解析成功！已自动填充作者和标题信息。")
        print("您可以修改文件名后，点击“开始下载”。")

    def start_downloading(self):
        """启动下载线程"""
        if not self.video_details_cache:
            print("错误：请先成功解析一个链接。")
            return

        author = self.author_entry.get()
        song = self.song_entry.get()

        if not author or not song:
            print("错误：作者名和标题不能为空！")
            return

        self.set_ui_state(is_busy=True)

        thread = threading.Thread(target=self.download_worker, args=(author, song))
        thread.daemon = True
        thread.start()

    def download_worker(self, author, song):
        """在后台线程中执行的下载任务"""
        try:
            # 清理文件名中的非法字符
            sanitized_author = re.sub(r'[\\/*?:"<>|]', "", author)
            sanitized_song = re.sub(r'[\\/*?:"<>|]', "", song)
            filename_base = f"{sanitized_author}-{sanitized_song}"

            print(f"\n准备下载，使用文件名: {filename_base}")

            aweme_detail = self.video_details_cache.get("aweme_detail", {})
            video_uri = aweme_detail.get("video", {}).get("play_addr", {}).get("uri")
            static_cover_urls = aweme_detail.get("video", {}).get("cover", {}).get("url_list", [])
            static_cover_url = static_cover_urls[0] if static_cover_urls else None
            description = aweme_detail.get("desc", "")

            # 1. 下载视频和封面
            video_success = download_video_from_uri(video_uri=video_uri, filename_base=filename_base)
            cover_success = download_static_cover(cover_url=static_cover_url, filename_base=filename_base)

            # 2. 如果都成功，则更新JSON文件
            if video_success and cover_success:
                video_path = os.path.join("MP4", f"{filename_base}.mp4")
                cover_path = os.path.join("albumArt", f"{filename_base}.jpg")
                update_playlist_json(
                    title=song,
                    artist=author,
                    video_path=video_path,
                    cover_path=cover_path,
                    description=description
                )

            print("\n--- 所有任务完成！ ---")
        except Exception as e:
            print(f"\n下载过程中发生严重错误: {e}")
        finally:
            # 无论成功失败，都在主线程中恢复UI状态
            self.after(0, self.set_ui_state, False)


if __name__ == "__main__":
    app = App()
    app.mainloop()