import os
import time
import ctypes
import threading
import json
import shutil 
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from PIL import Image, ImageTk, ImageGrab, ImageDraw, ImageFont, ImageEnhance
import cv2
import numpy as np
import keyboard

# ---------------------------------------------------------
# 全局状态机 (护栏核心)
# ---------------------------------------------------------
abort_drawing = False
pause_drawing = False

def trigger_pause():
    global pause_drawing, abort_drawing
    if not abort_drawing and not pause_drawing:
        pause_drawing = True
        left_click_up()
        right_click_up()
        print("\n[暂停] 已触发！请放心进行其他操作。")

def trigger_resume():
    global pause_drawing
    if pause_drawing:
        pause_drawing = False
        print("\n[继续] 已触发！恢复绘制。")

def trigger_abort():
    global abort_drawing, pause_drawing
    abort_drawing = True
    pause_drawing = False 
    left_click_up()
    right_click_up()
    print("\n[终止] 清单已销毁，内存已释放！")

def handle_p_key(e):
    if keyboard.is_pressed('ctrl') or keyboard.is_pressed('alt'):
        return 
    trigger_pause()

keyboard.on_press_key('p', handle_p_key)
keyboard.on_press_key('P', handle_p_key)
keyboard.add_hotkey('ctrl+alt+p', trigger_resume)
keyboard.on_press_key('[', lambda _: trigger_abort())

# ---------------------------------------------------------
# Windows 底层鼠标控制 (多屏兼容版)
# ---------------------------------------------------------
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except:
    pass

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_VIRTUALDESK = 0x4000  
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010

SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79

def move_mouse(x, y):
    v_left = ctypes.windll.user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
    v_top = ctypes.windll.user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
    v_width = ctypes.windll.user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
    v_height = ctypes.windll.user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)

    if v_width == 0 or v_height == 0:
        v_width = ctypes.windll.user32.GetSystemMetrics(0)
        v_height = ctypes.windll.user32.GetSystemMetrics(1)
        v_left = 0
        v_top = 0

    nx = int((x - v_left) * 65535 / v_width)
    ny = int((y - v_top) * 65535 / v_height)
    ctypes.windll.user32.mouse_event(MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK | MOUSEEVENTF_MOVE, nx, ny, 0, 0)

def right_click_down():
    ctypes.windll.user32.mouse_event(MOUSEEVENTF_RIGHTDOWN, 0, 0, 0, 0)

def right_click_up():
    ctypes.windll.user32.mouse_event(MOUSEEVENTF_RIGHTUP, 0, 0, 0, 0)

def left_click_down():
    ctypes.windll.user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)

def left_click_up():
    ctypes.windll.user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)

# ---------------------------------------------------------
# UI 组件：现代化圆角拨动开关
# ---------------------------------------------------------
class ToggleSwitch(tk.Canvas):
    def __init__(self, parent, command=None, *args, **kwargs):
        super().__init__(parent, width=64, height=28, highlightthickness=0, bg=parent.cget("bg"), *args, **kwargs)
        self.command = command
        self.is_left_click = False 
        
        self.bg_right = "#2196F3"  
        self.bg_left = "#4CAF50"   
        self.thumb_color = "#FFFFFF"
        
        self.bind("<Button-1>", self.toggle)
        self.draw()

    def draw(self):
        self.delete("all")
        bg_color = self.bg_left if self.is_left_click else self.bg_right
        
        self.create_oval(2, 2, 26, 26, fill=bg_color, outline=bg_color)
        self.create_oval(38, 2, 62, 26, fill=bg_color, outline=bg_color)
        self.create_rectangle(14, 2, 50, 26, fill=bg_color, outline=bg_color)
        
        if self.is_left_click:
            self.create_oval(2, 2, 26, 26, fill=self.thumb_color, outline="")
            self.create_text(46, 14, text="左", fill="white", font=("Microsoft YaHei", 10, "bold"))
        else:
            self.create_oval(38, 2, 62, 26, fill=self.thumb_color, outline="")
            self.create_text(18, 14, text="右", fill="white", font=("Microsoft YaHei", 10, "bold"))

    def toggle(self, event=None):
        self.is_left_click = not self.is_left_click
        self.draw()
        if self.command:
            self.command(self.is_left_click)

    def set_state(self, is_left_click):
        self.is_left_click = is_left_click
        self.draw()

# ---------------------------------------------------------
# 内部弹窗：线稿二次裁剪界面
# ---------------------------------------------------------
class CropOverlay:
    def __init__(self, master, img_path, callback):
        self.top = tk.Toplevel(master)
        self.top.title("✂️ 裁剪线稿 (按住左键框选，松开完成)")
        self.top.attributes('-topmost', True)
        self.callback = callback
        self.img_path = img_path

        self.original_pil = Image.open(img_path)
        self.display_pil = self.original_pil.copy()

        max_display_size = (1000, 800)
        self.display_pil.thumbnail(max_display_size, Image.Resampling.LANCZOS)

        self.scale_x = self.original_pil.width / self.display_pil.width
        self.scale_y = self.original_pil.height / self.display_pil.height

        self.tk_img = ImageTk.PhotoImage(self.display_pil)

        w = self.display_pil.width
        h = self.display_pil.height
        screen_w = master.winfo_screenwidth()
        screen_h = master.winfo_screenheight()
        x = int((screen_w / 2) - (w / 2))
        y = int((screen_h / 2) - (h / 2))
        self.top.geometry(f"{w}x{h}+{x}+{y}")

        self.canvas = tk.Canvas(self.top, width=w, height=h, cursor="crosshair")
        self.canvas.pack()
        self.canvas.create_image(0, 0, image=self.tk_img, anchor=tk.NW)

        self.rect_id = None
        self.start_x = None
        self.start_y = None

        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)

    def on_press(self, event):
        self.start_x = event.x
        self.start_y = event.y
        if self.rect_id:
            self.canvas.delete(self.rect_id)
        self.rect_id = self.canvas.create_rectangle(self.start_x, self.start_y, self.start_x, self.start_y, outline='blue', width=2, dash=(4, 4))

    def on_drag(self, event):
        if self.rect_id:
            self.canvas.coords(self.rect_id, self.start_x, self.start_y, event.x, event.y)

    def on_release(self, event):
        if not self.start_x or not self.start_y: return
        end_x, end_y = event.x, event.y
        rx = min(self.start_x, end_x)
        ry = min(self.start_y, end_y)
        rw = abs(self.start_x - end_x)
        rh = abs(self.start_y - end_y)

        self.top.destroy()

        if rw > 10 and rh > 10:
            orig_x = int(rx * self.scale_x)
            orig_y = int(ry * self.scale_y)
            orig_w = int(rw * self.scale_x)
            orig_h = int(rh * self.scale_y)

            cropped = self.original_pil.crop((orig_x, orig_y, orig_x + orig_w, orig_y + orig_h))
            
            output_dir = os.path.dirname(self.img_path)
            # 使用人类可读的日期时间格式
            time_str = time.strftime("%Y%m%d_%H%M%S")
            new_path = os.path.join(output_dir, f"cropped_{time_str}.png")
            
            cropped.save(new_path)
            self.callback(new_path)

# ---------------------------------------------------------
# “数字琥珀” 全屏选区界面
# ---------------------------------------------------------
class DigitalAmberOverlay:
    def __init__(self, master, target_image_path, callback, mode="lineart"):
        self.master = master
        self.target_image_path = target_image_path
        self.callback = callback
        self.mode = mode 
        
        self.top = tk.Toplevel(master)
        self.top.overrideredirect(True) 
        self.top.attributes('-topmost', True)
        self.top.config(cursor="crosshair")
        
        self.v_left = ctypes.windll.user32.GetSystemMetrics(76)
        self.v_top = ctypes.windll.user32.GetSystemMetrics(77)
        v_width = ctypes.windll.user32.GetSystemMetrics(78)
        v_height = ctypes.windll.user32.GetSystemMetrics(79)

        if v_width == 0:
            v_width = self.top.winfo_screenwidth()
            v_height = self.top.winfo_screenheight()
            self.v_left = 0
            self.v_top = 0

        self.top.geometry(f"{v_width}x{v_height}+{self.v_left}+{self.v_top}")
        
        try:
            screen_img = ImageGrab.grab(all_screens=True)
        except:
            screen_img = ImageGrab.grab()
            
        enhancer = ImageEnhance.Brightness(screen_img)
        self.dimmed_img = enhancer.enhance(0.5)
        
        self.tk_img = ImageTk.PhotoImage(self.dimmed_img)
        
        self.canvas = tk.Canvas(self.top, highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.create_image(0, 0, image=self.tk_img, anchor=tk.NW)
        
        self.rect_id = None
        self.start_x = None
        self.start_y = None
        
        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)

    def on_press(self, event):
        self.start_x = event.x
        self.start_y = event.y
        if self.rect_id:
            self.canvas.delete(self.rect_id)
        
        outline_color = '#00FF00' if self.mode == "fill" else 'red'
        dash_pattern = (4, 4) if self.mode == "fill" else None
        self.rect_id = self.canvas.create_rectangle(self.start_x, self.start_y, self.start_x, self.start_y, outline=outline_color, width=2, dash=dash_pattern)

    def on_drag(self, event):
        cur_x, cur_y = event.x, event.y
        self.canvas.coords(self.rect_id, self.start_x, self.start_y, cur_x, cur_y)

    def on_release(self, event):
        end_x, end_y = event.x, event.y
        rx = min(self.start_x, end_x)
        ry = min(self.start_y, end_y)
        rw = abs(self.start_x - end_x)
        rh = abs(self.start_y - end_y)
        
        self.top.destroy()
        if rw > 10 and rh > 10:
            abs_rx = self.v_left + rx
            abs_ry = self.v_top + ry
            self.callback(abs_rx, abs_ry, rw, rh, self.target_image_path, self.mode)

# ---------------------------------------------------------
# 主程序界面
# ---------------------------------------------------------
class SpirePainterApp:
    def __init__(self, root):
        self.root = root
        self.root.withdraw() 
        self.root.title("杀戮尖塔2 - 数字琥珀画板")
        self.root.configure(bg="#F3F3F3")
        
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

        self.style = ttk.Style()
        if 'clam' in self.style.theme_names():
            self.style.theme_use('clam')
            
        self.style.configure("TLabelframe", background="#F3F3F3", bordercolor="#DDDDDD")
        self.style.configure("TLabelframe.Label", background="#F3F3F3", font=("Microsoft YaHei", 9, "bold"), foreground="#333333")
        
        self.style.map('TCombobox',
            fieldbackground=[('readonly', '#FFFDF2')],
            selectbackground=[('readonly', '#FFE0B2')],
            selectforeground=[('readonly', '#E65100')],
            background=[('readonly', '#F3F3F3')],
            foreground=[('readonly', '#333333')]
        )
        
        self.style.configure("Blue.Horizontal.TScale", troughcolor="#BBDEFB", background="#2196F3", lightcolor="#2196F3", darkcolor="#2196F3", bordercolor="#F3F3F3")
        self.style.configure("Green.Horizontal.TScale", troughcolor="#C8E6C9", background="#4CAF50", lightcolor="#4CAF50", darkcolor="#4CAF50", bordercolor="#F3F3F3")

        self.output_dir = "output_lines"
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)
            
        try:
            myappid = 'wzf.spirepainter.v1.1' 
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
        except:
            pass
            
        icon_paths = ["brush.ico", os.path.join(self.output_dir, "brush.ico")]
        for ipath in icon_paths:
            if os.path.exists(ipath):
                try:
                    self.root.iconbitmap(ipath)
                    break
                except:
                    pass
        
        # 标准 16:9 (1280x720) 
        window_width = 1280
        window_height = 720 
        screen_width = root.winfo_screenwidth()
        screen_height = root.winfo_screenheight()
        center_x = int((screen_width / 2) - (window_width / 2))
        center_y = int((screen_height / 2) - (window_height / 2))
        self.root.geometry(f"{window_width}x{window_height}+{center_x}+{center_y}") 
        
        self.current_lineart_path = None
        self.last_raw_image_path = None 
        
        self.tk_preview_image = None 
        self.base_preview_img = None 
        self.zoom_level = 1.0
        self.preview_img_id = None
        
        self.drag_x = 0
        self.drag_y = 0
        self.last_cw = None
        self.last_ch = None
        
        self.config_path = os.path.join(self.output_dir, "config.json")
        init_topmost = True
        init_detail = 5
        init_speed = 3
        init_fill_gap = 10 
        init_is_left_click = False 
        self.is_first_run = True 
        
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    conf = json.load(f)
                    init_topmost = conf.get("topmost", True)
                    init_detail = conf.get("detail", 5)
                    init_speed = conf.get("speed", 3)
                    init_fill_gap = conf.get("fill_gap", 10)
                    self.is_first_run = conf.get("is_first_run", True)
                    if "is_left_click" in conf:
                        init_is_left_click = conf["is_left_click"]
                    elif "click_mode" in conf:
                        init_is_left_click = "左键" in conf["click_mode"]
            except:
                pass
                
        self.topmost_var = tk.BooleanVar(value=init_topmost)
        self.root.attributes('-topmost', self.topmost_var.get())

        self.font_map = {
            "微软雅黑 (默认)": "msyh.ttc",
            "黑体 (粗犷)": "simhei.ttf",
            "楷体 (毛笔)": "simkai.ttf",
            "宋体 (锋利)": "simsun.ttc",
            "仿宋 (清秀)": "simfang.ttf",
            "华文行楷 (类草书)": "STXINGKA.TTF",
            "华文新魏 (行草风)": "STXINWEI.TTF",
            "隶书 (古风)": "SIMLI.TTF",
            "幼圆 (圆润)": "SIMYOU.TTF",
            "华文彩云 (艺术)": "STCAIYUN.TTF",
            "方正舒体 (柔美)": "FZSTK.TTF"
        }

        # 强制锁定绝对的 3:7 物理布局
        self.root.grid_columnconfigure(0, weight=3, uniform="main_layout") 
        self.root.grid_columnconfigure(1, weight=7, uniform="main_layout") 
        self.root.grid_rowconfigure(0, weight=1)    

        self.left_panel = tk.Frame(root, bg="#F3F3F3")
        self.left_panel.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)

        self.right_panel = tk.Frame(root, bg="white", highlightbackground="#DDDDDD", highlightthickness=1)
        self.right_panel.grid(row=0, column=1, sticky="nsew", padx=(0, 10), pady=10)
        self.right_panel.grid_propagate(False)

        self.btn_start = tk.Button(self.left_panel, text="🚀 开始绘制线稿 (进入数字琥珀)", bg="#4CAF50", fg="white", 
                                   font=("Microsoft YaHei", 11, "bold"), command=lambda: self.start_digital_amber(mode="lineart"), state=tk.DISABLED, 
                                   height=2, relief="flat", activebackground="#45A049", activeforeground="white", cursor="hand2")
        self.btn_start.pack(side="bottom", fill="x", padx=10, pady=(0, 5))

        top_bar = tk.Frame(self.left_panel, bg="#F3F3F3")
        top_bar.pack(side="top", fill="x", pady=(0, 5))
        
        right_info_frame = tk.Frame(top_bar, bg="#F3F3F3")
        right_info_frame.pack(side="right", anchor="ne")
        
        self.chk_topmost = tk.Checkbutton(right_info_frame, text="📌 窗口置顶", font=("Microsoft YaHei", 9), variable=self.topmost_var, command=self.save_config, bg="#F3F3F3")
        self.chk_topmost.pack(anchor="e")
        
        # 醒目的独立快捷键区（绝不随输出文字刷新消失）
        hotkeys_text = "P: 暂停  |  Ctrl+Alt+P: 继续\n[ : 终止"
        self.lbl_hotkeys = tk.Label(right_info_frame, text=hotkeys_text, fg="#E53935", bg="#F3F3F3", font=("Microsoft YaHei", 9, "bold"), justify="right")
        self.lbl_hotkeys.pack(anchor="e", pady=(2, 0))
        
        # 输出框高度压缩至 2 行，完美适配 720p
        self.status_text = tk.Text(top_bar, height=2, bg="#F3F3F3", fg="#1976D2", 
                                   font=("Microsoft YaHei", 10, "bold"), 
                                   relief="flat", wrap="word", highlightthickness=0)
        self.status_text.pack(side="left", fill="both", expand=True, padx=(0, 10))
        self.status_text.insert("1.0", "请先准备线稿...")
        self.status_text.config(state=tk.DISABLED)

        def create_flat_button(parent, text, command, state=tk.NORMAL, bg="#FFFFFF", active_bg="#EAEAEA", fg="#333333"):
            return tk.Button(parent, text=text, command=command, state=state, 
                             relief="solid", bd=1, bg=bg, fg=fg, activebackground=active_bg, activeforeground=fg, 
                             font=("Microsoft YaHei", 9), cursor="hand2")

        frame1 = ttk.LabelFrame(self.left_panel, text=" 方案A：外部图片 ", padding=(10, 5))
        frame1.pack(side="top", fill="both", expand=True, padx=10, pady=(0, 2))
        wrap1 = tk.Frame(frame1, bg="#F3F3F3")
        wrap1.pack(expand=True, fill="x")
        detail_frame = tk.Frame(wrap1, bg="#F3F3F3")
        detail_frame.pack(fill="x")
        tk.Label(detail_frame, text="精细度:", bg="#F3F3F3", font=("Microsoft YaHei", 9)).pack(side="left")
        self.detail_slider = ttk.Scale(detail_frame, from_=1, to=10, orient="horizontal", style="Blue.Horizontal.TScale", command=self.on_detail_change)
        self.detail_slider.set(init_detail) 
        self.detail_slider.pack(side="left", fill="x", expand=True, padx=5)
        self.lbl_detail_val = tk.Label(detail_frame, text=str(init_detail), font=("Microsoft YaHei", 10, "bold"), fg="#2196F3", bg="#F3F3F3")
        self.lbl_detail_val.pack(side="left")
        btn_frame1 = tk.Frame(wrap1, bg="#F3F3F3")
        btn_frame1.pack(fill="x", pady=(5,0))
        self.btn_image = create_flat_button(btn_frame1, "1. 选择图片", self.select_image, bg="#E3F2FD", active_bg="#BBDEFB", fg="#0D47A1")
        self.btn_image.pack(side="left", fill="x", expand=True, padx=(0, 3))
        self.btn_reprocess = create_flat_button(btn_frame1, "2. 刷新线稿", self.generate_image_lineart, state=tk.DISABLED, bg="#E3F2FD", active_bg="#BBDEFB", fg="#0D47A1")
        self.btn_reprocess.pack(side="left", fill="x", expand=True, padx=(3, 0))

        frame2 = ttk.LabelFrame(self.left_panel, text=" 方案B：输入文字 ", padding=(10, 5))
        frame2.pack(side="top", fill="both", expand=True, padx=10, pady=(0, 2))
        wrap2 = tk.Frame(frame2, bg="#F3F3F3")
        wrap2.pack(expand=True, fill="x")
        self.text_input = ttk.Entry(wrap2, font=("Microsoft YaHei", 9))
        self.text_input.insert(0, "输入想画的文字...")
        self.text_input.pack(fill="x", pady=(0, 5))
        font_frame = tk.Frame(wrap2, bg="#F3F3F3")
        font_frame.pack(fill="x", pady=2)
        tk.Label(font_frame, text="字体风格:", bg="#F3F3F3", font=("Microsoft YaHei", 9)).pack(side="left")
        self.font_combo = ttk.Combobox(font_frame, values=list(self.font_map.keys()), state="readonly", width=15, font=("Microsoft YaHei", 9))
        self.font_combo.current(0)
        self.font_combo.pack(side="left", fill="x", expand=True, padx=5)
        self.btn_text = create_flat_button(wrap2, "生成文字自适应线稿", self.process_text, bg="#FFF3E0", active_bg="#FFE0B2", fg="#E65100")
        self.btn_text.pack(fill="x", pady=(5, 0))

        frame3 = ttk.LabelFrame(self.left_panel, text=" 方案C：现成线稿 ", padding=(10, 5))
        frame3.pack(side="top", fill="both", expand=True, padx=10, pady=(0, 2))
        wrap3 = tk.Frame(frame3, bg="#F3F3F3")
        wrap3.pack(expand=True, fill="x")
        self.btn_load_existing = create_flat_button(wrap3, "打开已保存的线稿图", self.load_existing_lineart, bg="#F3E5F5", active_bg="#E1BEE7", fg="#4A148C")
        self.btn_load_existing.pack(fill="x")

        frame_fog = ttk.LabelFrame(self.left_panel, text=" 方案D：战争迷雾 ", padding=(10, 5))
        frame_fog.pack(side="top", fill="both", expand=True, padx=10, pady=(0, 2))
        wrap_fog = tk.Frame(frame_fog, bg="#F3F3F3")
        wrap_fog.pack(expand=True, fill="x")
        fog_conf_frame = tk.Frame(wrap_fog, bg="#F3F3F3")
        fog_conf_frame.pack(fill="x")
        tk.Label(fog_conf_frame, text="涂抹间距:", bg="#F3F3F3", font=("Microsoft YaHei", 9)).pack(side="left")
        self.fill_gap_slider = ttk.Scale(fog_conf_frame, from_=5, to=30, orient="horizontal", style="Green.Horizontal.TScale", command=self.on_fill_gap_change)
        self.fill_gap_slider.set(init_fill_gap)
        self.fill_gap_slider.pack(side="left", fill="x", expand=True, padx=5)
        self.lbl_gap_val = tk.Label(fog_conf_frame, text=f"{init_fill_gap} px", font=("Microsoft YaHei", 10, "bold"), fg="#4CAF50", bg="#F3F3F3")
        self.lbl_gap_val.pack(side="left")
        self.btn_fill_fog = create_flat_button(wrap_fog, "开始扫荡迷雾", lambda: self.start_digital_amber(mode="fill"), bg="#E8F5E9", active_bg="#B2DFDB", fg="#004D40")
        self.btn_fill_fog.pack(fill="x", pady=(5, 0))

        frame4 = ttk.LabelFrame(self.left_panel, text=" ⚙️ 全局绘制设置 ", padding=(10, 5))
        frame4.pack(side="top", fill="both", expand=True, padx=10, pady=(0, 5))
        wrap4 = tk.Frame(frame4, bg="#F3F3F3")
        wrap4.pack(expand=True, fill="x")
        click_frame = tk.Frame(wrap4, bg="#F3F3F3")
        click_frame.pack(fill="x", pady=(0, 5))
        tk.Label(click_frame, text="绘制按键:", bg="#F3F3F3", font=("Microsoft YaHei", 9)).pack(side="left")
        self.toggle_switch = ToggleSwitch(click_frame, command=self.save_config)
        self.toggle_switch.set_state(init_is_left_click)
        self.toggle_switch.pack(side="left", padx=(10, 5))
        speed_frame = tk.Frame(wrap4, bg="#F3F3F3")
        speed_frame.pack(fill="x")
        tk.Label(speed_frame, text="绘制速度:", bg="#F3F3F3", font=("Microsoft YaHei", 9)).pack(side="left")
        self.speed_slider = ttk.Scale(speed_frame, from_=1, to=20, orient="horizontal", style="Blue.Horizontal.TScale", command=self.on_speed_change)
        self.speed_slider.set(init_speed) 
        self.speed_slider.pack(side="left", fill="x", expand=True, padx=5)
        self.lbl_speed_val = tk.Label(speed_frame, text=str(init_speed), font=("Microsoft YaHei", 10, "bold"), fg="#2196F3", bg="#F3F3F3")
        self.lbl_speed_val.pack(side="left")

        # ---------------------------------------------------------
        # 右侧：实时预览面板
        # ---------------------------------------------------------
        tk.Label(self.right_panel, text="实时线稿预览区", font=("Microsoft YaHei", 12, "bold"), bg="white", fg="#333333").pack(pady=10)
        
        self.preview_canvas = tk.Canvas(self.right_panel, bg="#FAFAFA", highlightthickness=0, cursor="fleur")
        self.preview_canvas.pack(fill="both", expand=True, padx=10, pady=5)
        
        self.preview_canvas.bind("<ButtonPress-1>", self.on_drag_start)
        self.preview_canvas.bind("<B1-Motion>", self.on_drag_motion)
        self.preview_canvas.bind("<MouseWheel>", self.on_preview_zoom)
        self.preview_canvas.bind("<Configure>", self.on_canvas_resize)

        btn_action_frame = tk.Frame(self.right_panel, bg="white")
        btn_action_frame.pack(side="bottom", fill="x", padx=10, pady=(0, 10))
        
        self.btn_open_folder = create_flat_button(btn_action_frame, "📁 打开线稿保存目录", self.open_output_folder, bg="#FFF8E1", active_bg="#FFECB3", fg="#FF8F00")
        self.btn_open_folder.pack(side="bottom", fill="x", pady=(10, 0))

        btn_top_action = tk.Frame(btn_action_frame, bg="white")
        btn_top_action.pack(side="bottom", fill="x")

        self.btn_crop = create_flat_button(btn_top_action, "✂️ 裁剪", self.start_crop, state=tk.DISABLED, bg="#E0F2F1", active_bg="#B2DFDB", fg="#00695C")
        self.btn_crop.pack(side="left", fill="x", expand=True, padx=(0, 3))

        self.btn_save_lineart = create_flat_button(btn_top_action, "💾 保存", self.save_current_lineart, state=tk.DISABLED, bg="#E8EAF6", active_bg="#C5CAE9", fg="#283593")
        self.btn_save_lineart.pack(side="left", fill="x", expand=True, padx=(3, 0))

        self.root.deiconify() 
        self.root.update() 
        
        cw = self.preview_canvas.winfo_width()
        ch = self.preview_canvas.winfo_height()
        self.last_cw = cw
        self.last_ch = ch
        
        self.preview_hint_id = self.preview_canvas.create_text(
            cw//2, ch//2, text="（暂无预览）\n请在左侧生成或选择线稿\n\n💡 提示：生成后可使用滚轮缩放，按住鼠标拖拽",
            fill="gray", font=("Microsoft YaHei", 11), justify="center"
        )
        
        if self.is_first_run:
            self.root.after(500, self.show_first_run_tutorial)

    def update_status(self, msg):
        self.status_text.config(state=tk.NORMAL)
        self.status_text.delete("1.0", tk.END)
        self.status_text.insert("1.0", msg)
        self.status_text.see(tk.END)
        self.status_text.config(state=tk.DISABLED)

    def show_first_run_tutorial(self):
        tut = tk.Toplevel(self.root)
        tut.overrideredirect(True) 
        tut.attributes('-topmost', True)
        
        w, h = 480, 360
        x = self.root.winfo_x() + (self.root.winfo_width() // 2) - (w // 2)
        y = self.root.winfo_y() + (self.root.winfo_height() // 2) - (h // 2)
        tut.geometry(f"{w}x{h}+{x}+{y}")
        
        frame = tk.Frame(tut, bg="#FFFFFF", highlightbackground="#2196F3", highlightthickness=2)
        frame.pack(fill="both", expand=True)
        
        lbl_title = tk.Label(frame, text="✨ 欢迎使用数字琥珀画板", font=("Microsoft YaHei", 16, "bold"), bg="#FFFFFF", fg="#1976D2")
        lbl_title.pack(pady=(20, 10))

        lbl_desc = tk.Label(frame, text="为了防止画笔乱飞，请务必牢记以下【护栏快捷键】：", font=("Microsoft YaHei", 10), bg="#FFFFFF", fg="#555555")
        lbl_desc.pack(pady=(0, 15))
        
        hk_frame = tk.Frame(frame, bg="#F9F9F9", bd=1, relief="solid")
        hk_frame.pack(padx=30, fill="x")
        
        tk.Label(hk_frame, text="P", font=("Microsoft YaHei", 14, "bold"), bg="#F9F9F9", fg="#E53935", width=12, anchor="e").grid(row=0, column=0, pady=10)
        tk.Label(hk_frame, text="暂停绘制 (并自动抬笔)", font=("Microsoft YaHei", 10), bg="#F9F9F9", fg="#333333", anchor="w").grid(row=0, column=1, sticky="w", padx=10)
        
        tk.Label(hk_frame, text="Ctrl + Alt + P", font=("Microsoft YaHei", 14, "bold"), bg="#F9F9F9", fg="#4CAF50", width=12, anchor="e").grid(row=1, column=0, pady=10)
        tk.Label(hk_frame, text="恢复绘制 (记忆坐标点)", font=("Microsoft YaHei", 10), bg="#F9F9F9", fg="#333333", anchor="w").grid(row=1, column=1, sticky="w", padx=10)
        
        tk.Label(hk_frame, text="[", font=("Microsoft YaHei", 14, "bold"), bg="#F9F9F9", fg="#E53935", width=12, anchor="e").grid(row=2, column=0, pady=10)
        tk.Label(hk_frame, text="强制终止 (彻底销毁任务)", font=("Microsoft YaHei", 10), bg="#F9F9F9", fg="#333333", anchor="w").grid(row=2, column=1, sticky="w", padx=10)

        def on_close():
            tut.destroy()
            self.is_first_run = False
            self.save_config()

        btn_ok = tk.Button(frame, text="我已牢记，开始使用", font=("Microsoft YaHei", 11, "bold"), bg="#2196F3", fg="#FFFFFF", relief="flat", activebackground="#1976D2", activeforeground="#FFFFFF", command=on_close, cursor="hand2")
        btn_ok.pack(pady=(20, 20), ipadx=40, ipady=10)

    def on_closing(self):
        trigger_abort()
        self.root.destroy()

    # ---------------------------------------------------------
    # 动态居中与无极缩放引擎核心逻辑
    # ---------------------------------------------------------
    def on_canvas_resize(self, event):
        cw, ch = event.width, event.height
        if self.last_cw is not None and self.last_ch is not None:
            dx = (cw - self.last_cw) / 2
            dy = (ch - self.last_ch) / 2
            if hasattr(self, 'preview_img_id') and self.preview_img_id:
                self.preview_canvas.move(self.preview_img_id, dx, dy)
            if hasattr(self, 'preview_hint_id') and self.preview_hint_id:
                self.preview_canvas.move(self.preview_hint_id, dx, dy)
        self.last_cw = cw
        self.last_ch = ch

    def on_drag_start(self, event):
        self.drag_x = event.x
        self.drag_y = event.y

    def on_drag_motion(self, event):
        dx = event.x - self.drag_x
        dy = event.y - self.drag_y
        
        if hasattr(self, 'preview_img_id') and self.preview_img_id:
            self.preview_canvas.move(self.preview_img_id, dx, dy)
        if hasattr(self, 'preview_hint_id') and self.preview_hint_id:
            self.preview_canvas.move(self.preview_hint_id, dx, dy)
            
        self.drag_x = event.x
        self.drag_y = event.y

    def on_preview_zoom(self, event):
        if not self.base_preview_img: return
        
        if event.delta > 0:
            self.zoom_level *= 1.15  
        elif event.delta < 0:
            self.zoom_level *= 0.85  
            
        self.zoom_level = max(0.05, min(self.zoom_level, 10.0))
        self.redraw_preview()

    def redraw_preview(self):
        if not self.base_preview_img: return
        
        new_w = int(self.base_preview_img.width * self.zoom_level)
        new_h = int(self.base_preview_img.height * self.zoom_level)
        
        if new_w <= 0 or new_h <= 0 or new_w > 8000 or new_h > 8000:
            return

        resample_filter = Image.Resampling.LANCZOS if self.zoom_level < 1.0 else Image.Resampling.NEAREST
        resized = self.base_preview_img.resize((new_w, new_h), resample_filter)
        
        self.tk_preview_image = ImageTk.PhotoImage(resized)

        if hasattr(self, 'preview_img_id') and self.preview_img_id:
            self.preview_canvas.itemconfig(self.preview_img_id, image=self.tk_preview_image)
        else:
            cw = self.preview_canvas.winfo_width()
            ch = self.preview_canvas.winfo_height()
            if cw <= 1: cw, ch = 500, 500
            self.preview_img_id = self.preview_canvas.create_image(cw//2, ch//2, image=self.tk_preview_image, anchor="center")

    def update_preview_panel(self, image_path):
        if not image_path or not os.path.exists(image_path):
            return
            
        try:
            self.base_preview_img = Image.open(image_path).convert("RGB")
            
            if hasattr(self, 'preview_hint_id') and self.preview_hint_id:
                self.preview_canvas.delete(self.preview_hint_id)
                self.preview_hint_id = None
                
            cw = self.preview_canvas.winfo_width()
            ch = self.preview_canvas.winfo_height()
            if cw <= 1: cw, ch = 500, 500

            scale_w = cw / self.base_preview_img.width
            scale_h = ch / self.base_preview_img.height
            self.zoom_level = min(scale_w, scale_h) * 0.9 

            self.redraw_preview()
            
            if hasattr(self, 'preview_img_id') and self.preview_img_id:
                self.preview_canvas.coords(self.preview_img_id, cw//2, ch//2)

            self.btn_crop.config(state=tk.NORMAL)
            self.btn_save_lineart.config(state=tk.NORMAL)
        except Exception as e:
            print(f"预览加载失败: {e}")

    # ---------------------------------------------------------
    # 滑块防死循环与阻尼吸附逻辑核心
    # ---------------------------------------------------------
    def on_detail_change(self, val):
        v = round(float(val))
        if abs(float(val) - v) > 0.001:  
            self.detail_slider.set(v)
        if hasattr(self, 'lbl_detail_val') and self.lbl_detail_val.cget("text") != str(v):
            self.lbl_detail_val.config(text=str(v))
            self.save_config()

    def on_speed_change(self, val):
        v = round(float(val))
        if abs(float(val) - v) > 0.001:
            self.speed_slider.set(v)
        if hasattr(self, 'lbl_speed_val') and self.lbl_speed_val.cget("text") != str(v):
            self.lbl_speed_val.config(text=str(v))
            self.save_config()
        
    def on_fill_gap_change(self, val):
        v = round(float(val))
        if abs(float(val) - v) > 0.001:
            self.fill_gap_slider.set(v)
        if hasattr(self, 'lbl_gap_val') and self.lbl_gap_val.cget("text") != f"{v} px":
            self.lbl_gap_val.config(text=f"{v} px")
            self.save_config()

    # ---------------------------------------------------------
    # 配置保存逻辑
    # ---------------------------------------------------------
    def save_config(self, *args):
        if not hasattr(self, 'detail_slider') or not hasattr(self, 'speed_slider') or not hasattr(self, 'toggle_switch') or not hasattr(self, 'fill_gap_slider'):
            return
            
        is_top = self.topmost_var.get()
        self.root.attributes('-topmost', is_top) 
        
        try:
            conf = {
                "topmost": is_top,
                "detail": int(round(float(self.detail_slider.get()))),
                "speed": int(round(float(self.speed_slider.get()))),
                "fill_gap": int(round(float(self.fill_gap_slider.get()))),
                "is_left_click": self.toggle_switch.is_left_click,
                "is_first_run": getattr(self, 'is_first_run', False)
            }
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(conf, f)
        except Exception as e:
            pass

    # ---------------------------------------------------------
    # 保存线稿防覆盖 (时间戳命名优化版)
    # ---------------------------------------------------------
    def save_current_lineart(self):
        if self.current_lineart_path and os.path.exists(self.current_lineart_path):
            # 使用人类可读时间
            time_str = time.strftime("%Y%m%d_%H%M%S")
            new_filename = f"saved_{time_str}.png"
            new_path = os.path.join(self.output_dir, new_filename)
            try:
                shutil.copy(self.current_lineart_path, new_path)
                self.current_lineart_path = new_path
                self.update_status(f"✅ 已成功保存:\n{new_filename}")
            except Exception as e:
                messagebox.showerror("保存失败", f"无法保存文件：{e}")

    # --- 裁剪功能 ---
    def start_crop(self):
        if self.current_lineart_path:
            CropOverlay(self.root, self.current_lineart_path, self.finish_crop)

    def finish_crop(self, new_cropped_path):
        self.current_lineart_path = new_cropped_path
        self.update_status(f"已生成裁剪版线稿！\n{os.path.basename(new_cropped_path)}")
        self.update_preview_panel(new_cropped_path)

    # --- 打开文件夹 ---
    def open_output_folder(self):
        try:
            os.startfile(os.path.abspath(self.output_dir))
        except Exception as e:
            messagebox.showerror("错误", f"无法打开文件夹：{e}")

    # ---------------------------------------------------------
    # 护栏：任何变更图片的动作都会提前清空可能正在运行的绘图进程
    # ---------------------------------------------------------
    def select_image(self):
        trigger_abort()
        file_path = filedialog.askopenfilename(title="选择原图片", filetypes=[("Images", "*.png *.jpg *.jpeg *.bmp")])
        if file_path:
            self.last_raw_image_path = file_path
            self.btn_reprocess.config(state=tk.NORMAL)
            self.generate_image_lineart() 

    def generate_image_lineart(self):
        trigger_abort()
        if not self.last_raw_image_path: return
        
        img = cv2.imdecode(np.fromfile(self.last_raw_image_path, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
        detail = int(round(float(self.detail_slider.get())))

        k_size = int(max(1, (11 - detail) // 2 * 2 + 1))
        if k_size > 1:
            img = cv2.GaussianBlur(img, (k_size, k_size), 0)

        lower_thresh = int(180 - detail * 15)
        upper_thresh = int(250 - detail * 15)
        
        edges = cv2.Canny(img, lower_thresh, upper_thresh)
        inverted = cv2.bitwise_not(edges)
        
        save_path = os.path.join(self.output_dir, "last_image_lineart.png")
        cv2.imencode('.png', inverted)[1].tofile(save_path)
        
        self.current_lineart_path = save_path
        self.update_status(f"图片线稿已生成/刷新！\n当前精细度: {detail}")
        self.btn_start.config(state=tk.NORMAL)
        
        self.update_preview_panel(save_path)

    def process_text(self):
        trigger_abort()
        text = self.text_input.get()
        if not text:
            messagebox.showwarning("提示", "请先输入文字！")
            return
            
        selected_font_name = self.font_combo.get()
        actual_font_file = self.font_map.get(selected_font_name, "msyh.ttc")
        
        font_dirs = [
            os.path.join(os.environ.get('WINDIR', 'C:\\Windows'), 'Fonts'),
            os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Microsoft', 'Windows', 'Fonts')
        ]
        
        target_font_path = None
        fallback_font_path = None
        
        for d in font_dirs:
            test_path = os.path.join(d, actual_font_file)
            if os.path.exists(test_path):
                target_font_path = test_path
                break
                
        if not target_font_path:
            for d in font_dirs:
                test_path = os.path.join(d, 'msyh.ttc')
                if os.path.exists(test_path):
                    fallback_font_path = test_path
                    break
        
        final_font_path = target_font_path or fallback_font_path
        
        if not final_font_path:
            messagebox.showerror("致命错误", "在您的电脑上找不到任何中文字体！请检查系统字体库。")
            return
            
        try:
            fnt = ImageFont.truetype(final_font_path, 150)
            if not target_font_path: 
                messagebox.showinfo("提示", f"您的电脑系统未安装【{selected_font_name}】。\n已自动为您安全替换为【微软雅黑】。")
        except Exception as e:
            messagebox.showerror("字体读取错误", f"字体文件可能损坏：\n{e}")
            return
            
        dummy_img = Image.new('RGB', (1, 1))
        dummy_draw = ImageDraw.Draw(dummy_img)
        bbox = dummy_draw.textbbox((0, 0), text, font=fnt)
        
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        
        padding = 20
        canvas_w = int(text_w + padding * 2)
        canvas_h = int(text_h + padding * 2)
        
        img = Image.new('RGB', (canvas_w, canvas_h), color='white')
        d = ImageDraw.Draw(img)
        
        draw_x = padding - bbox[0]
        draw_y = padding - bbox[1]
        d.text((draw_x, draw_y), text, font=fnt, fill='black')
        
        open_cv_image = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2GRAY)
        edges = cv2.Canny(open_cv_image, 100, 200)
        inverted = cv2.bitwise_not(edges)
        
        save_path = os.path.join(self.output_dir, "last_text_lineart.png")
        cv2.imencode('.png', inverted)[1].tofile(save_path)
        
        self.current_lineart_path = save_path
        
        display_font = selected_font_name if target_font_path else "微软雅黑 (保底)"
        self.update_status(f"自适应文字线稿已生成！\n{display_font}")
        self.btn_start.config(state=tk.NORMAL)
        
        self.update_preview_panel(save_path)

    def load_existing_lineart(self):
        trigger_abort()
        initial_dir = os.path.abspath(self.output_dir)
        file_path = filedialog.askopenfilename(
            initialdir=initial_dir,
            title="选择已保存的线稿图",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.bmp")]
        )
        if file_path:
            self.current_lineart_path = file_path
            self.update_status(f"已加载线稿:\n{os.path.basename(file_path)}")
            self.btn_start.config(state=tk.NORMAL)
            self.update_preview_panel(file_path)

    def start_digital_amber(self, mode="lineart"):
        trigger_abort()
        self.root.iconify()
        self.root.after(300, lambda: self.launch_overlay(mode))

    def launch_overlay(self, mode):
        global abort_drawing, pause_drawing
        abort_drawing = False
        pause_drawing = False
        
        current_step = int(round(float(self.speed_slider.get())))
        fill_gap = int(round(float(self.fill_gap_slider.get()))) if hasattr(self, 'fill_gap_slider') else 10
        is_left_click = self.toggle_switch.is_left_click
        
        DigitalAmberOverlay(self.root, self.current_lineart_path, 
                            lambda rx, ry, rw, rh, img_path, m: self.run_draw_thread(rx, ry, rw, rh, img_path, m, current_step, fill_gap, is_left_click), mode=mode)

    def run_draw_thread(self, rx, ry, rw, rh, img_path, mode, current_step, fill_gap, is_left_click):
        threading.Thread(target=self.draw_logic, args=(rx, ry, rw, rh, img_path, mode, current_step, fill_gap, is_left_click), daemon=True).start()

    def draw_logic(self, rx, ry, rw, rh, img_path, mode, current_step, fill_gap, is_left_click):
        global abort_drawing, pause_drawing
        time.sleep(1) 
        
        def check_pause_state(cx, cy):
            if abort_drawing: return False
            if pause_drawing:
                if is_left_click: left_click_up()
                else: right_click_up()
                
                while pause_drawing:
                    time.sleep(0.1)
                    if abort_drawing: return False
                    
                time.sleep(0.1)
                move_mouse(cx, cy)
                time.sleep(0.02)
                if is_left_click: left_click_down()
                else: right_click_down()
                time.sleep(0.02)
            return True
        
        # ---------------------------------------------------------
        # 战争迷雾：双十字交叉法 (无缝填涂)
        # ---------------------------------------------------------
        if mode == "fill":
            current_y = ry
            direction_x = 1 
            move_mouse(rx, current_y)
            time.sleep(0.01)
            if is_left_click: left_click_down()
            else: right_click_down()
            time.sleep(0.01)
            
            while current_y <= ry + rh:
                if abort_drawing: break
                
                start_x = rx if direction_x == 1 else rx + rw
                end_x = rx + rw if direction_x == 1 else rx
                
                dist = abs(end_x - start_x)
                jump_pixels = current_step * 5 
                steps = int(max(1, dist // jump_pixels))
                
                for i in range(1, steps + 1):
                    cur_x = start_x + (end_x - start_x) * i / steps
                    if not check_pause_state(cur_x, current_y): break
                    move_mouse(cur_x, current_y)
                    time.sleep(0.002)
                
                if abort_drawing: break
                move_mouse(end_x, current_y)
                time.sleep(0.005)
                
                current_y += fill_gap
                if current_y <= ry + rh:
                    if not check_pause_state(end_x, current_y): break
                    move_mouse(end_x, current_y)
                    time.sleep(0.005)
                    
                direction_x *= -1
            
            if is_left_click: left_click_up()
            else: right_click_up()
            time.sleep(0.1) 
            
            if abort_drawing:
                print("填涂已被强行终止，内存已回收！")
                return
                
            current_x = rx
            direction_y = 1
            move_mouse(current_x, ry)
            time.sleep(0.01)
            if is_left_click: left_click_down()
            else: right_click_down()
            time.sleep(0.01)
            
            while current_x <= rx + rw:
                if abort_drawing: break
                
                start_y = ry if direction_y == 1 else ry + rh
                end_y = ry + rh if direction_y == 1 else ry
                
                dist = abs(end_y - start_y)
                jump_pixels = current_step * 5 
                steps = int(max(1, dist // jump_pixels))
                
                for i in range(1, steps + 1):
                    cur_y = start_y + (end_y - start_y) * i / steps
                    if not check_pause_state(current_x, cur_y): break
                    move_mouse(current_x, cur_y)
                    time.sleep(0.002)
                
                if abort_drawing: break
                move_mouse(current_x, end_y)
                time.sleep(0.005)
                
                current_x += fill_gap
                if current_x <= rx + rw:
                    if not check_pause_state(current_x, end_y): break
                    move_mouse(current_x, end_y)
                    time.sleep(0.005)
                    
                direction_y *= -1
            
            if is_left_click: left_click_up()
            else: right_click_up()
            
            if not abort_drawing:
                print("迷雾双重填涂完成！内存已自动回收。")
            return
            
        # ---------------------------------------------------------
        # 线稿边缘绘制
        # ---------------------------------------------------------
        img = cv2.imdecode(np.fromfile(img_path, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
        edges = cv2.bitwise_not(img) 
        
        img_h, img_w = edges.shape
        scale = min(rw / img_w, rh / img_h)
        
        offset_x = rx + (rw - img_w * scale) / 2
        offset_y = ry + (rh - img_h * scale) / 2

        contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
        
        for contour in contours:
            if abort_drawing: break
            if len(contour) == 0: continue
            
            start_x = int(offset_x + contour[0][0][0] * scale)
            start_y = int(offset_y + contour[0][0][1] * scale)
            
            if not check_pause_state(start_x, start_y): break
            move_mouse(start_x, start_y)
            time.sleep(0.005) 
            
            if is_left_click: left_click_down()
            else: right_click_down()
            time.sleep(0.005) 
            
            for point in contour[1::current_step]:
                px = int(offset_x + point[0][0] * scale)
                py = int(offset_y + point[0][1] * scale)
                
                if not check_pause_state(px, py): break
                move_mouse(px, py)
                time.sleep(0.002) 
            
            if is_left_click: left_click_up()
            else: right_click_up()
            time.sleep(0.005) 
        
        if abort_drawing: print("绘图任务已被强制销毁！")
        else: print("绘制顺利完成！内存自动释放。")

if __name__ == "__main__":
    root = tk.Tk()
    app = SpirePainterApp(root)
    root.mainloop()
