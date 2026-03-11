import os
import time
import ctypes
import threading
import json
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from PIL import Image, ImageTk, ImageGrab, ImageDraw, ImageFont, ImageEnhance
import cv2
import numpy as np
import keyboard

# ---------------------------------------------------------
# 全局控制变量
# ---------------------------------------------------------
abort_drawing = False

def trigger_abort():
    global abort_drawing
    abort_drawing = True
    print("\n[中断] 接收到 P 键指令，强制停止当前绘制！")

keyboard.on_press_key('p', lambda _: trigger_abort())
keyboard.on_press_key('P', lambda _: trigger_abort())

# ---------------------------------------------------------
# Windows 底层鼠标控制
# ---------------------------------------------------------
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except:
    pass

MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010

def move_mouse(x, y):
    ctypes.windll.user32.SetCursorPos(int(x), int(y))

def right_click_down():
    ctypes.windll.user32.mouse_event(MOUSEEVENTF_RIGHTDOWN, 0, 0, 0, 0)

def right_click_up():
    ctypes.windll.user32.mouse_event(MOUSEEVENTF_RIGHTUP, 0, 0, 0, 0)

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
            timestamp = int(time.time())
            new_path = os.path.join(output_dir, f"cropped_lineart_{timestamp}.png")
            
            cropped.save(new_path)
            self.callback(new_path)

# ---------------------------------------------------------
# “数字琥珀” 全屏选区界面
# ---------------------------------------------------------
class DigitalAmberOverlay:
    def __init__(self, master, target_image_path, callback):
        self.master = master
        self.target_image_path = target_image_path
        self.callback = callback
        
        self.top = tk.Toplevel(master)
        self.top.attributes('-fullscreen', True)
        self.top.attributes('-topmost', True)
        self.top.config(cursor="crosshair")
        
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
        self.rect_id = self.canvas.create_rectangle(self.start_x, self.start_y, self.start_x, self.start_y, outline='red', width=2)

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
            self.callback(rx, ry, rw, rh, self.target_image_path)

# ---------------------------------------------------------
# 主程序界面
# ---------------------------------------------------------
class SpirePainterApp:
    def __init__(self, root):
        self.root = root
        self.root.title("杀戮尖塔2 - 数字琥珀画板")
        
        window_width = 950
        window_height = 650
        screen_width = root.winfo_screenwidth()
        screen_height = root.winfo_screenheight()
        center_x = int((screen_width / 2) - (window_width / 2))
        center_y = int((screen_height / 2) - (window_height / 2))
        self.root.geometry(f"{window_width}x{window_height}+{center_x}+{center_y}") 
        
        self.current_lineart_path = None
        self.last_raw_image_path = None 
        self.tk_preview_image = None 
        self.output_dir = "output_lines"
        
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)

        # ---------------------------------------------------------
        # 核心改动：初始化读取所有的配置数据
        # ---------------------------------------------------------
        self.config_path = os.path.join(self.output_dir, "config.json")
        init_topmost = True
        init_detail = 5
        init_speed = 3
        
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    conf = json.load(f)
                    init_topmost = conf.get("topmost", True)
                    init_detail = conf.get("detail", 5)
                    init_speed = conf.get("speed", 3)
            except:
                pass
                
        self.topmost_var = tk.BooleanVar(value=init_topmost)
        self.root.attributes('-topmost', self.topmost_var.get())

        self.font_map = {
            "微软雅黑 (默认)": "msyh.ttc",
            "黑体 (粗犷)": "simhei.ttf",
            "楷体 (毛笔)": "simkai.ttf",
            "宋体 (锋利)": "simsun.ttc",
            "仿宋 (清秀)": "simfang.ttf"
        }

        # ---------------------------------------------------------
        # 左右分栏布局
        # ---------------------------------------------------------
        self.left_panel = tk.Frame(root, width=420)
        self.left_panel.pack(side="left", fill="y", padx=10, pady=10)
        self.left_panel.pack_propagate(False) 

        self.right_panel = tk.Frame(root, bg="#E0E0E0", bd=2, relief="sunken")
        self.right_panel.pack(side="right", fill="both", expand=True, padx=(0, 10), pady=10)

        # ---------------------------------------------------------
        # 左侧：顶部状态栏 
        # ---------------------------------------------------------
        top_bar = tk.Frame(self.left_panel)
        top_bar.pack(fill="x", pady=(5, 15))
        
        self.status_label = tk.Label(top_bar, text="请先准备线稿\n(随时按 P 键紧急停止)", fg="blue")
        self.status_label.pack(side="left")
        
        # 将复选框绑定到全局配置保存函数
        self.chk_topmost = tk.Checkbutton(top_bar, text="📌 窗口置顶", variable=self.topmost_var, command=self.save_config)
        self.chk_topmost.pack(side="right", anchor="n", pady=5)

        # --- 区域1：图片转线稿 ---
        frame1 = tk.LabelFrame(self.left_panel, text="方案A：外部图片", padx=10, pady=10)
        frame1.pack(fill="x", padx=10, pady=(0, 15))
        
        detail_frame = tk.Frame(frame1)
        detail_frame.pack(fill="x")
        tk.Label(detail_frame, text="线稿精细度 (1低=快, 10高=慢):").pack(side="left")
        
        # 精细度滑块，初始化数值并绑定保存函数
        self.detail_slider = tk.Scale(detail_frame, from_=1, to=10, orient="horizontal", length=140)
        self.detail_slider.set(init_detail) 
        self.detail_slider.config(command=self.save_config) # 设完默认值再绑定，防止报错
        self.detail_slider.pack(side="left", padx=5)

        btn_frame1 = tk.Frame(frame1)
        btn_frame1.pack(fill="x", pady=(10,0))
        self.btn_image = tk.Button(btn_frame1, text="1. 选择图片", command=self.select_image)
        self.btn_image.pack(side="left", fill="x", expand=True, padx=(0, 2))
        self.btn_reprocess = tk.Button(btn_frame1, text="2. 刷新线稿", command=self.generate_image_lineart, state=tk.DISABLED)
        self.btn_reprocess.pack(side="left", fill="x", expand=True, padx=(2, 0))

        # --- 区域2：文字转线稿 ---
        frame2 = tk.LabelFrame(self.left_panel, text="方案B：输入文字", padx=10, pady=10)
        frame2.pack(fill="x", padx=10, pady=(0, 15))
        
        self.text_input = tk.Entry(frame2)
        self.text_input.insert(0, "输入想画的文字...")
        self.text_input.pack(fill="x", pady=(0, 8))
        
        font_frame = tk.Frame(frame2)
        font_frame.pack(fill="x", pady=2)
        tk.Label(font_frame, text="字体风格:").pack(side="left")
        
        self.font_combo = ttk.Combobox(font_frame, values=list(self.font_map.keys()), state="readonly", width=15)
        self.font_combo.current(0)
        self.font_combo.pack(side="left", padx=5)
        
        self.btn_text = tk.Button(frame2, text="生成文字自适应线稿", command=self.process_text)
        self.btn_text.pack(fill="x", pady=(10, 0))

        # --- 区域3：直接使用已有线稿 ---
        frame3 = tk.LabelFrame(self.left_panel, text="方案C：现成线稿", padx=10, pady=10)
        frame3.pack(fill="x", padx=10, pady=(0, 15))
        self.btn_load_existing = tk.Button(frame3, text="打开保存的线稿图进行绘制", command=self.load_existing_lineart)
        self.btn_load_existing.pack(fill="x")

        # --- 区域4：狂暴调速器 ---
        speed_frame = tk.Frame(self.left_panel)
        speed_frame.pack(fill="x", padx=10, pady=(15, 25))
        tk.Label(speed_frame, text="绘制速度(跳帧步长):", font=("Arial", 9, "bold")).pack(side="left")
        
        # 速度滑块，初始化数值并绑定保存函数
        self.speed_slider = tk.Scale(speed_frame, from_=1, to=15, orient="horizontal", length=200)
        self.speed_slider.set(init_speed) 
        self.speed_slider.config(command=self.save_config) # 设完默认值再绑定
        self.speed_slider.pack(side="left", padx=5)

        # --- 启动按钮 ---
        self.btn_start = tk.Button(self.left_panel, text="🚀 开始绘制 (进入数字琥珀)", bg="#4CAF50", fg="white", 
                                   font=("Arial", 10, "bold"), command=self.start_digital_amber, state=tk.DISABLED, height=2)
        self.btn_start.pack(fill="x", padx=10, pady=(0, 10))

        # ---------------------------------------------------------
        # 右侧：实时预览面板
        # ---------------------------------------------------------
        tk.Label(self.right_panel, text="实时线稿预览区", font=("Arial", 12, "bold"), bg="#E0E0E0", fg="#333333").pack(pady=10)
        
        self.preview_label = tk.Label(self.right_panel, text="（暂无预览）\n请在左侧生成或选择线稿", bg="white", fg="gray")
        self.preview_label.pack(fill="both", expand=True, padx=10, pady=5)

        self.btn_crop = tk.Button(self.right_panel, text="✂️ 局部裁剪当前线稿 (框出想要保留的部分)", command=self.start_crop, state=tk.DISABLED)
        self.btn_crop.pack(fill="x", padx=10, pady=(0, 5))

        self.btn_open_folder = tk.Button(self.right_panel, text="📁 打开线稿保存目录 (管理/删除文件)", command=self.open_output_folder)
        self.btn_open_folder.pack(fill="x", padx=10, pady=(0, 10))

    # ---------------------------------------------------------
    # 核心改动：统一的全局配置保存函数
    # ---------------------------------------------------------
    def save_config(self, *args):
        # 加上容错判断，确保所有控件都被创建出来了再保存，避免启动时报错
        if not hasattr(self, 'detail_slider') or not hasattr(self, 'speed_slider'):
            return
            
        is_top = self.topmost_var.get()
        self.root.attributes('-topmost', is_top) # 实时更新置顶状态
        
        try:
            conf = {
                "topmost": is_top,
                "detail": self.detail_slider.get(),
                "speed": self.speed_slider.get()
            }
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(conf, f)
        except Exception as e:
            print(f"保存配置失败: {e}")

    # --- 裁剪功能的核心逻辑 ---
    def start_crop(self):
        if self.current_lineart_path:
            CropOverlay(self.root, self.current_lineart_path, self.finish_crop)

    def finish_crop(self, new_cropped_path):
        self.current_lineart_path = new_cropped_path
        self.status_label.config(text=f"已生成裁剪版线稿！\n({os.path.basename(new_cropped_path)})")
        self.update_preview_panel(new_cropped_path)

    # --- 打开文件夹逻辑 ---
    def open_output_folder(self):
        try:
            os.startfile(os.path.abspath(self.output_dir))
        except Exception as e:
            messagebox.showerror("错误", f"无法打开文件夹：{e}")

    # ---------------------------------------------------------
    def update_preview_panel(self, image_path):
        if not image_path or not os.path.exists(image_path):
            return
            
        try:
            img = Image.open(image_path)
            max_size = (480, 440) 
            img.thumbnail(max_size, Image.Resampling.LANCZOS)
            self.tk_preview_image = ImageTk.PhotoImage(img)
            self.preview_label.config(image=self.tk_preview_image, text="", bg="#E0E0E0")
            
            self.btn_crop.config(state=tk.NORMAL)
        except Exception as e:
            print(f"预览加载失败: {e}")

    # ---------------------------------------------------------
    # 业务逻辑更新
    # ---------------------------------------------------------
    def select_image(self):
        file_path = filedialog.askopenfilename(title="选择原图片", filetypes=[("Images", "*.png *.jpg *.jpeg *.bmp")])
        if file_path:
            self.last_raw_image_path = file_path
            self.btn_reprocess.config(state=tk.NORMAL)
            self.generate_image_lineart() 

    def generate_image_lineart(self):
        if not self.last_raw_image_path: return
        
        img = cv2.imdecode(np.fromfile(self.last_raw_image_path, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
        detail = self.detail_slider.get() 

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
        self.status_label.config(text=f"图片线稿已生成/刷新！\n(当前精细度: {detail})")
        self.btn_start.config(state=tk.NORMAL)
        
        self.update_preview_panel(save_path)

    def process_text(self):
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
        self.status_label.config(text=f"自适应文字线稿已生成！\n({display_font})")
        self.btn_start.config(state=tk.NORMAL)
        
        self.update_preview_panel(save_path)

    def load_existing_lineart(self):
        initial_dir = os.path.abspath(self.output_dir)
        file_path = filedialog.askopenfilename(
            initialdir=initial_dir,
            title="选择已保存的线稿图",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.bmp")]
        )
        if file_path:
            self.current_lineart_path = file_path
            self.status_label.config(text=f"已加载线稿: {os.path.basename(file_path)}")
            self.btn_start.config(state=tk.NORMAL)
            self.update_preview_panel(file_path)

    def start_digital_amber(self):
        self.root.iconify()
        self.root.after(200, self.launch_overlay)

    def launch_overlay(self):
        DigitalAmberOverlay(self.root, self.current_lineart_path, self.run_draw_thread)

    def run_draw_thread(self, rx, ry, rw, rh, img_path):
        threading.Thread(target=self.draw_logic, args=(rx, ry, rw, rh, img_path), daemon=True).start()

    def draw_logic(self, rx, ry, rw, rh, img_path):
        global abort_drawing
        abort_drawing = False 
        
        time.sleep(1) 
        
        img = cv2.imdecode(np.fromfile(img_path, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
        edges = cv2.bitwise_not(img) 
        
        img_h, img_w = edges.shape
        scale = min(rw / img_w, rh / img_h)
        
        offset_x = rx + (rw - img_w * scale) / 2
        offset_y = ry + (rh - img_h * scale) / 2

        contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
        
        current_step = self.speed_slider.get()
        
        for contour in contours:
            if abort_drawing:
                break
                
            if len(contour) == 0:
                continue
            
            start_x = int(offset_x + contour[0][0][0] * scale)
            start_y = int(offset_y + contour[0][0][1] * scale)
            move_mouse(start_x, start_y)
            time.sleep(0.005) 
            
            right_click_down()
            time.sleep(0.005) 
            
            for point in contour[1::current_step]:
                if abort_drawing:
                    break
                    
                px = int(offset_x + point[0][0] * scale)
                py = int(offset_y + point[0][1] * scale)
                move_mouse(px, py)
                time.sleep(0.002) 
            
            right_click_up()
            time.sleep(0.005) 
        
        if abort_drawing:
            print("绘图已被玩家强行中断！")
        else:
            print("绘制顺利完成！")

if __name__ == "__main__":
    root = tk.Tk()
    app = SpirePainterApp(root)
    root.mainloop()
