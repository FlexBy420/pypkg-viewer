#!/usr/bin/env python3
import io
import os
import sys
import time
import struct
import zlib
import threading
import hashlib
import tempfile
import subprocess
import json
import re
import urllib.request
import customtkinter as ctk
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
from PIL import Image, DdsImagePlugin
from concurrent.futures import ThreadPoolExecutor
import pygame
import imageio_ffmpeg

try:
    import PIL._tkinter_finder
except ImportError:
    pass

try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
    HAS_DND = True
except ImportError:
    HAS_DND = False

if HAS_DND:
    class DragDropCTk(ctk.CTk, TkinterDnD.DnDWrapper):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.TkdndVersion = TkinterDnD._require(self)
else:
    class DragDropCTk(ctk.CTk):
        pass

pygame.mixer.init()

# AES Keys 
PKG_PS3_AES_KEY            = bytes.fromhex("2E7B71D7C9C9A14EA3221F188828B8F8")
PKG_PS3_IDU_AES_KEY        = bytes.fromhex("5DB911E6B7E50A7D321538FD7C66F17B")
PKG_PSP_AES_KEY            = bytes.fromhex("07F2C68290B50D2C33818D709B60E62B")
PKG_PSP_IDU_AES_KEY        = bytes.fromhex("7547EE76CA8C55AC1BA8D22535E05593")
PKG_PSP2_AES_KEY           = bytes.fromhex("E31A70C9CE1DD72BF3C0622963F2ECCB") # PSP2 = internal name for Vita
PKG_PSP2_LIVEAREA_AES_KEY  = bytes.fromhex("423ACA3A2BD5649F9686ABAD6FD8801F")
PKG_PSM_AES_KEY            = bytes.fromhex("AF07FD59652527BAF13389668B17D9EA")

# PKG constants 
PKG_FILE_ENTRY_PSP      = 0x10000000
PKG_RELEASE_TYPE_DEBUG  = 0x0000
PKG_RELEASE_TYPE_RELEASE = 0x8000
PKG_PLATFORM_TYPE_PS3   = 0x0001
PKG_PLATFORM_TYPE_PSP_PSVITA = 0x0002

# Content Type values 
PKG_CONTENT_TYPE_UNKNOWN_1      = 0x01
PKG_CONTENT_TYPE_UNKNOWN_2      = 0x02
PKG_CONTENT_TYPE_UNKNOWN_3      = 0x03
PKG_CONTENT_TYPE_GAME_DATA      = 0x04  # GameData (also patches)
PKG_CONTENT_TYPE_GAME_EXEC      = 0x05  # GameExec
PKG_CONTENT_TYPE_PS1_EMU        = 0x06  # PS1emu
PKG_CONTENT_TYPE_PC_ENGINE      = 0x07  # PSP & PCEngine
PKG_CONTENT_TYPE_UNKNOWN_4      = 0x08
PKG_CONTENT_TYPE_THEME          = 0x09  # Theme
PKG_CONTENT_TYPE_WIDGET         = 0x0A  # Widget
PKG_CONTENT_TYPE_LICENSE        = 0x0B  # License
PKG_CONTENT_TYPE_VSH_MODULE     = 0x0C  # VSHModule
PKG_CONTENT_TYPE_PSN_AVATAR     = 0x0D  # PSN Avatar
PKG_CONTENT_TYPE_PSP_GO         = 0x0E  # PSPgo
PKG_CONTENT_TYPE_MINIS          = 0x0F  # Minis
PKG_CONTENT_TYPE_NEOGEO         = 0x10  # NEOGEO
PKG_CONTENT_TYPE_VMC            = 0x11  # VMC
PKG_CONTENT_TYPE_PS2_CLASSIC    = 0x12  # PS2Classic
PKG_CONTENT_TYPE_ISO2PKG        = 0x13  # ISO2PKG
PKG_CONTENT_TYPE_PSP_REMASTERED = 0x14
PKG_CONTENT_TYPE_PSP2_GD        = 0x15  # PSVita Game Data
PKG_CONTENT_TYPE_PSP2_AC        = 0x16  # PSVita Additional Content
PKG_CONTENT_TYPE_PSP2_LA        = 0x17  # PSVita LiveArea
PKG_CONTENT_TYPE_PSM_1          = 0x18  # PSVita PSM
PKG_CONTENT_TYPE_WT             = 0x19  # Web TV
PKG_CONTENT_TYPE_PS4_GD         = 0x1A  # PS4 GameData
PKG_CONTENT_TYPE_PS4_AC         = 0x1B  # PS4 Additional Content
PKG_CONTENT_TYPE_PS4_AL         = 0x1C  # PS4 Additional License
PKG_CONTENT_TYPE_PSM_2          = 0x1D  # PSVita PSM
PKG_CONTENT_TYPE_PS4_DP         = 0x1E  # PS4 Delta Package/Patch
PKG_CONTENT_TYPE_PSP2_THEME     = 0x1F  # PSVita Theme
PKG_CONTENT_TYPE_PS5_GD         = 0x20  # PS5 GameData

# DRM Type (source: psdevwiki.com/ps3/PKG_files)
DRM_TYPE_NAMES = {
    0x0000: "Unknown / No License (SDATA)",
    0x0001: "Network",
    0x0002: "Local (PS3)",
    0x0003: "Free (PS3)",
    0x0004: "PSP",
    0x000D: "Free (PSP2/PSM)",
    0x000F: "Local (PS4)",
    0x0010: "Local (PS5)",
    0x0100: "Network (PSP/PSP2)",
    0x0400: "GameCard (PSP2)",
    0x2000: "Unknown (PS3)",
}

# PKG Metadata IDs (source: psdevwiki.com/ps3/PKG_files)
PKG_META_DRM_TYPE        = 0x01
PKG_META_CONTENT_TYPE    = 0x02
PKG_META_PKG_TYPE        = 0x03 # Package type/flags
PKG_META_PKG_SIZE        = 0x04 # Install size
PKG_META_NPDRM_VERSION   = 0x05 # NPDRM version
PKG_META_APP_VERSION_PSP = 0x06 # Version + App Version / TitleID (on size 0xC)
PKG_META_QA_DIGEST       = 0x07 # QA Digest (described as "This is a digest of packaged files and attributes.")
PKG_META_UNKNOWN_08      = 0x08 # unk (1 byte) + PS3/PSP/PSP2 System Version (3 bytes) + Package Version (2 bytes) + App Version (2 bytes)
PKG_META_UNKNOWN_09      = 0x09
PKG_META_INSTALL_DIR     = 0x0A # Install directory name (string)
PKG_META_UNKNOWN_0B      = 0x0B # unk seen in PSP cumulative patch
PKG_META_UNKNOWN_0C      = 0x0C
PKG_META_ENTRIES_PSP2    = 0x0D
PKG_META_SFO_PSP2        = 0x0E

# Icon file pattern (root or C00/ subfolder) 
ICON_FILE_RE = re.compile(
    r'^(C00/)?(ICON\d+(_\d+)?\.(PNG|PAM)|PIC\d+(_\d+)?\.PNG|SND\d+(_\d+)?\.AT3)$',
    re.IGNORECASE
)

ALL_POTENTIAL_KEYS = [
    (PKG_PS3_AES_KEY,           "PS3 Retail"),
    (PKG_PSP2_AES_KEY,          "PS Vita Retail"),
    (PKG_PSP2_LIVEAREA_AES_KEY, "PS Vita Live Area"),
    (PKG_PSP_AES_KEY,           "PSP Retail"),
    (PKG_PS3_IDU_AES_KEY,       "PS3 IDU"),
    (PKG_PSP_IDU_AES_KEY,       "PSP IDU"),
    (PKG_PSM_AES_KEY,           "PS Mobile"),
]

def get_debug_keystream_block(qa_digest, block_index):
    qa_0 = qa_digest[0:8]
    qa_1 = qa_digest[8:16]
    buffer = bytearray(64)
    buffer[0:8]   = qa_0
    buffer[8:16]  = qa_0
    buffer[16:24] = qa_1
    buffer[24:32] = qa_1
    buffer[56:64] = struct.pack(">Q", block_index)
    return hashlib.sha1(buffer).digest()[:16]

def decrypt_data_blocks(file, data_offset, relative_offset, size, key, klicensee, pkg_type, qa_digest):
    if size <= 0: return b""
    block_offset = relative_offset // 16
    byte_offset  = relative_offset % 16
    num_blocks   = (byte_offset + size + 15) // 16

    file.seek(data_offset + block_offset * 16)
    encrypted = file.read(num_blocks * 16)

    if pkg_type == PKG_RELEASE_TYPE_DEBUG:
        decrypted = bytearray()
        for i in range(num_blocks):
            keystream = get_debug_keystream_block(qa_digest, block_offset + i)
            chunk = encrypted[i * 16: (i + 1) * 16]
            decrypted.extend(a ^ b for a, b in zip(chunk, keystream))
        return bytes(decrypted)[byte_offset: byte_offset + size]
    else:
        klic_int = int.from_bytes(klicensee, byteorder='big')
        nonce    = ((klic_int + block_offset) % (1 << 128)).to_bytes(16, byteorder='big')
        cipher   = Cipher(algorithms.AES(key), modes.CTR(nonce), backend=default_backend())
        decryptor = cipher.decryptor()
        decrypted = decryptor.update(encrypted) + decryptor.finalize()
        return decrypted[byte_offset: byte_offset + size]

def _decrypt_entry_to_bytes(pkg_path, entry, data_offset, klicensee, pkg_type, qa_digest):
    klic_int   = int.from_bytes(klicensee, byteorder='big')
    remaining  = entry['sz']
    curr_off   = entry['off']
    CHUNK      = 4 * 1024 * 1024
    result     = bytearray()

    with open(pkg_path, 'rb') as fh:
        while remaining > 0:
            to_read    = min(remaining, CHUNK)
            block_off  = curr_off // 16
            byte_off   = curr_off % 16
            num_blocks = (byte_off + to_read + 15) // 16

            fh.seek(data_offset + block_off * 16)
            enc = fh.read(num_blocks * 16)

            if pkg_type == PKG_RELEASE_TYPE_DEBUG:
                dec = bytearray()
                for i in range(num_blocks):
                    ks = get_debug_keystream_block(qa_digest, block_off + i)
                    dec.extend(a ^ b for a, b in zip(enc[i * 16:(i + 1) * 16], ks))
                dec = bytes(dec)
            elif pkg_type == PKG_RELEASE_TYPE_RELEASE:
                nonce  = ((klic_int + block_off) % (1 << 128)).to_bytes(16, 'big')
                cipher = Cipher(algorithms.AES(entry['key']), modes.CTR(nonce), backend=default_backend())
                dec    = cipher.decryptor().update(enc) + cipher.decryptor().finalize()
            else:
                dec = enc

            result.extend(dec[byte_off: byte_off + to_read])
            remaining -= to_read
            curr_off  += to_read

    return bytes(result)

class AudioPlayerWindow(ctk.CTkToplevel):
    def __init__(self, master, wav_path, title_name):
        super().__init__(master)
        self.title(f"Audio Player: {title_name}")
        self.geometry("400x140")
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        self.wav_path = wav_path
        pygame.mixer.music.load(self.wav_path)
        sound = pygame.mixer.Sound(self.wav_path)
        self.length = sound.get_length()

        self.is_playing = True
        self.start_time = time.time()
        self.offset     = 0.0

        self.btn_play_pause = ctk.CTkButton(self, text="⏸ Pause", width=100, command=self.toggle_play)
        self.btn_play_pause.pack(pady=(15, 5))

        self.slider = ctk.CTkSlider(self, from_=0, to=self.length, command=self.seek)
        self.slider.set(0)
        self.slider.pack(fill="x", padx=20, pady=5)

        self.lbl_time = ctk.CTkLabel(self, text=f"00:00 / {self.format_time(self.length)}")
        self.lbl_time.pack()

        pygame.mixer.music.play()
        self.update_loop()

    def format_time(self, seconds):
        m = int(seconds // 60)
        s = int(seconds % 60)
        return f"{m:02d}:{s:02d}"

    def toggle_play(self):
        if self.is_playing:
            pygame.mixer.music.pause()
            self.btn_play_pause.configure(text="▶ Play")
            self.offset += time.time() - self.start_time
        else:
            if not pygame.mixer.music.get_busy():
                pygame.mixer.music.play(loops=0, start=self.offset)
            else:
                pygame.mixer.music.unpause()
            self.btn_play_pause.configure(text="⏸ Pause")
            self.start_time = time.time()
        self.is_playing = not self.is_playing

    def seek(self, value):
        value = float(value)
        self.offset     = value
        self.start_time = time.time()
        pygame.mixer.music.play(loops=0, start=self.offset)
        if not self.is_playing:
            pygame.mixer.music.pause()

    def update_loop(self):
        if not self.winfo_exists():
            return
        if self.is_playing:
            current = self.offset + (time.time() - self.start_time)
            if current >= self.length:
                self.is_playing = False
                self.btn_play_pause.configure(text="▶ Play")
                self.slider.set(0)
                self.offset = 0
                pygame.mixer.music.stop()
                self.lbl_time.configure(text=f"00:00 / {self.format_time(self.length)}")
            else:
                self.slider.set(current)
                self.lbl_time.configure(text=f"{self.format_time(current)} / {self.format_time(self.length)}")
        self.after(100, self.update_loop)

    def on_close(self):
        pygame.mixer.music.stop()
        pygame.mixer.music.unload()
        self.destroy()

class PKGViewerApp(DragDropCTk):
    def __init__(self, initial_filepath=None):
        super().__init__()
        self.title("PKG Viewer")
        self.geometry("1000x820")
        self.current_pkg_path   = None
        self.klicensee          = None
        self.qa_digest          = None
        self.pkg_type           = None
        self.data_offset        = 0
        self.file_entries       = {}
        self.current_folder_name = "Extracted_PKG"
        self.setup_ui()

        if HAS_DND:
            self.drop_target_register(DND_FILES)
            self.dnd_bind('<<Drop>>', self.handle_drop)

        if initial_filepath and os.path.exists(initial_filepath):
            self.current_pkg_path = initial_filepath
            self.lbl_filepath.configure(text=os.path.basename(self.current_pkg_path), text_color="white")
            self.after(100, self.load_pkg)

    # Drag & drop 
    def handle_drop(self, event):
        files = self.tk.splitlist(event.data)
        if files:
            filepath = files[0]
            if filepath.lower().endswith('.pkg'):
                self.current_pkg_path = filepath
                self.lbl_filepath.configure(text=os.path.basename(filepath), text_color="white")
                self.load_pkg()
            else:
                messagebox.showerror("Error", "Please drop a valid .pkg file.")

    def setup_ui(self):
        self.top_frame = ctk.CTkFrame(self)
        self.top_frame.pack(pady=10, padx=10, fill="x")

        self.btn_open = ctk.CTkButton(self.top_frame, text="Choose PKG File", command=self.open_file)
        self.btn_open.pack(side="left", padx=10, pady=10)

        self.lbl_filepath = ctk.CTkLabel(self.top_frame, text="No PKG chosen", text_color="gray")
        self.lbl_filepath.pack(side="left", padx=10)

        self.btn_batch_json = ctk.CTkButton(self.top_frame, text="Batch JSON (Folder)", command=self.batch_json_folder)
        self.btn_batch_json.pack(side="left", padx=10, pady=10)

        self.btn_process_links = ctk.CTkButton(self.top_frame, text="Process JSON Links", command=self.process_links_from_json)
        self.btn_process_links.pack(side="left", padx=10, pady=10)

        self.tabs = ctk.CTkTabview(self)
        self.tabs.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.tab_files = self.tabs.add("Content")
        self.tab_info  = self.tabs.add("Information")
        self.setup_files_tab()
        self.setup_info_tab()

    def setup_files_tab(self):
        tree_frame = ctk.CTkFrame(self.tab_files)
        tree_frame.pack(fill="both", expand=True, padx=5, pady=5)

        style = ttk.Style()
        style.theme_use("default")
        style.layout("Treeview", [('Treeview.treearea', {'sticky': 'nswe'})])
        style.configure("Treeview", background="#2b2b2b", foreground="white",
                        fieldbackground="#2b2b2b", borderwidth=0, rowheight=25)
        style.map('Treeview', background=[('selected', '#1f538d')])
        style.configure("Treeview.Heading", background="#383737", foreground="white", relief="flat")
        style.map("Treeview.Heading", background=[('active', '#1f538d')])

        self.tree = ttk.Treeview(tree_frame, columns=("Size", "Type"), show="tree headings")
        self.tree.heading("#0",    text="Files",  anchor="center")
        self.tree.heading("Size",  text="Size",   anchor="center")
        self.tree.heading("Type",  text="Type",   anchor="center")
        self.tree.column("#0",    width=600)
        self.tree.column("Size",  width=120, anchor="center")
        self.tree.column("Type",  width=100, anchor="center")

        scrollbar = ctk.CTkScrollbar(tree_frame, command=self.tree.yview)
        self.tree.configure(yscrollcommand=lambda f, l: self.autohide_scrollbar(scrollbar, f, l))
        self.tree.pack(side="left", fill="both", expand=True)

        # Status & Progress
        status_frame = ctk.CTkFrame(self.tab_files)
        status_frame.pack(fill="x", padx=10, pady=5)

        self.lbl_status = ctk.CTkLabel(status_frame, text="Ready")
        self.lbl_status.pack(side="left", padx=10)

        self.progress_bar = ctk.CTkProgressBar(status_frame)
        self.progress_bar.pack(side="right", fill="x", expand=True, padx=10)
        self.progress_bar.set(0)

        # Action buttons + icon checkbox
        action_frame = ctk.CTkFrame(self.tab_files)
        action_frame.pack(fill="x", pady=5)

        self.btn_extract_sel = ctk.CTkButton(action_frame, text="Extract Highlighted",
                                              command=self.extract_selected, state="disabled")
        self.btn_extract_sel.pack(side="right", padx=10, pady=5)

        self.btn_extract_all = ctk.CTkButton(action_frame, text="Extract All",
                                              command=self.extract_all, state="disabled")
        self.btn_extract_all.pack(side="right", padx=5, pady=5)

        self.btn_export_json = ctk.CTkButton(action_frame, text="Export JSON",
                                              command=self.export_current_json, state="disabled")
        self.btn_export_json.pack(side="left", padx=10, pady=5)

        # Icon extraction checkbox 
        self.var_extract_icons = ctk.BooleanVar(value=False)
        self.chk_extract_icons = ctk.CTkCheckBox(
            action_frame,
            text="Extract Icons (ICONx/PICx/SNDx + C00)",
            variable=self.var_extract_icons,
        )
        self.chk_extract_icons.pack(side="left", padx=15, pady=5)

        # Right-click context menu
        self.context_menu = tk.Menu(self, tearoff=0, bg="#2b2b2b", fg="white",
                                    activebackground="#1f538d")
        self.context_menu.add_command(label="Preview File", command=self.preview_selected_file)
        self.tree.bind("<Button-3>", self.show_context_menu)

    def show_context_menu(self, event):
        item = self.tree.identify_row(event.y)
        if item:
            self.tree.selection_set(item)
            entry = self.file_entries.get(item)
            if entry and entry['path'].lower().endswith(('.png', '.jpg', '.jpeg', '.dds', '.pam', '.at3')):
                self.context_menu.tk_popup(event.x_root, event.y_root)

    def setup_info_tab(self):
        self.info_text = ctk.CTkTextbox(self.tab_info, font=("Consolas", 14), wrap="none")
        self.info_text.pack(fill="both", expand=True, padx=10, pady=10)
        self.info_text.insert("0.0", "Metadata will show after loading the file...")

    def autohide_scrollbar(self, sbar, first, last):
        if float(first) <= 0.0 and float(last) >= 1.0:
            sbar.pack_forget()
        else:
            sbar.pack(side="right", fill="y")
        sbar.set(first, last)

    def parse_sfo(self, data):
        if len(data) < 20 or data[:4] != b'\x00PSF':
            return {}
        try:
            key_ptr, data_ptr, count = struct.unpack('<I I I', data[8:20])
            entries = [
                struct.unpack('<H H I I I', data[20 + i * 16: 36 + i * 16])
                for i in range(count)
            ]
            sfo_dict = {}
            for k_off, fmt, d_len, d_max, d_off in entries:
                k_start = key_ptr + k_off
                k_end   = data.find(b'\x00', k_start)
                key     = data[k_start:k_end].decode('utf-8', errors='ignore')
                v_start = data_ptr + d_off
                val_raw = data[v_start: v_start + d_len]
                if fmt == 0x0204:
                    sfo_dict[key] = val_raw.decode('utf-8', errors='ignore').strip('\x00')
                elif fmt == 0x0404:
                    sfo_dict[key] = struct.unpack('<I', val_raw)[0]
                else:
                    sfo_dict[key] = val_raw
            return sfo_dict
        except Exception:
            return {}

    def format_size(self, size):
        if size >= 1_073_741_824:
            return f"{size} ({size / 1_073_741_824:.2f} GB)"
        elif size >= 1_048_576:
            return f"{size} ({size / 1_048_576:.2f} MB)"
        elif size >= 1024:
            return f"{size} ({size / 1024:.2f} KB)"
        return f"{size} B"

    def get_sfo_category_name(self, cat):
        categories = {
            "AP": "Application Photo",
            "AM": "Application Music",
            "AV": "Application Video",
            "AS": "Application Streaming",
            "AT": "Application TV",
            "BV": "Broadcast Video",
            "WT": "Web TV",
            "HG": "HDD Game",
            "CB": "Channel Broadcast",
            "HM": "Home",
            "SF": "Store Frontend",
            "2G": "PS2 Game",
            "2P": "PS2 Classic",
            "1P": "PS1 Classic",
            "MN": "Minis",
            "PE": "PSP Emulation",
            "PP": "PSP Package",
            "GD": "Game Data",
            "2D": "PS2 Data",
            "SD": "Save Data",
            "MS": "Memory Stick",
        }
        return categories.get(cat, "Unknown")

    def get_pkg_content_type_name(self, type_id):
        types = {
            0x01: "Unknown (0x01)",
            0x02: "Unknown (0x02)",
            0x03: "Unknown (0x03)",
            0x04: "Game Data / Patch",
            0x05: "Game Executable",
            0x06: "PS1 Emulator",
            0x07: "PSP & PC Engine",
            0x08: "Unknown (0x08)",
            0x09: "Theme",
            0x0A: "Widget",
            0x0B: "License",
            0x0C: "VSH Module",
            0x0D: "PSN Avatar",
            0x0E: "PSP Go",
            0x0F: "Minis",
            0x10: "NEOGEO",
            0x11: "VMC",
            0x12: "PS2 Classic",
            0x13: "ISO2PKG",
            0x14: "PSP Remaster",
            0x15: "PS Vita Game Data",
            0x16: "PS Vita Additional Content",
            0x17: "PS Vita LiveArea",
            0x18: "PS Mobile (PSM)",
            0x19: "Web TV",
            0x1A: "PS4 Game Data",
            0x1B: "PS4 Additional Content",
            0x1C: "PS4 Additional License",
            0x1D: "PS Mobile (PSM) v2",
            0x1E: "PS4 Delta Package / Patch",
            0x1F: "PS Vita Theme",
            0x20: "PS5 Game Data",
        }
        return types.get(type_id, f"Unknown (0x{type_id:02X})")

    def get_drm_type_name(self, drm_val):
        return DRM_TYPE_NAMES.get(drm_val, f"Unknown (0x{drm_val:04X})")

    def get_sfo_sound_format(self, val):
        if not isinstance(val, int):
            return str(val)
        formats = []
        if val & (1 << 0): formats.append("LPCM 2 Ch.")
        if val & (1 << 2): formats.append("LPCM 5.1 Ch.")
        if val & (1 << 4): formats.append("LPCM 7.1 Ch.")
        if val & (1 << 8): formats.append("Dolby Digital 5.1 Ch.")
        if val & (1 << 9): formats.append("DTS 5.1 Ch.")
        return ", ".join(formats) if formats else f"Unknown ({val})"

    def get_sfo_resolution(self, val):
        if not isinstance(val, int):
            return str(val)
        resolutions = []
        if val & (1 << 0): resolutions.append("480p")
        if val & (1 << 1): resolutions.append("576p")
        if val & (1 << 2): resolutions.append("720p")
        if val & (1 << 3): resolutions.append("1080p")
        if val & (1 << 4): resolutions.append("480p (16:9)")
        if val & (1 << 5): resolutions.append("576p (16:9)")
        return ", ".join(resolutions) if resolutions else f"Unknown ({val})"

    def open_file(self):
        path = filedialog.askopenfilename(filetypes=[("PKG", ("*.pkg", "*.PKG"))])
        if path:
            self.current_pkg_path = path
            self.lbl_filepath.configure(text=os.path.basename(path), text_color="white")
            self.load_pkg()

    def _parse_pkg_header(self, f):
        header_fmt = '> 4s H H I I I I Q Q Q 48s 16s 16s'
        hdr = struct.unpack(header_fmt, f.read(struct.calcsize(header_fmt)))
        if hdr[0] != b'\x7FPKG':
            raise ValueError("Invalid PKG magic")
        return {
            'magic':        hdr[0],
            'pkg_type':     hdr[1],
            'pkg_platform': hdr[2],
            'meta_offset':  hdr[3],
            'meta_count':   hdr[4],
            'file_count':   hdr[6],
            'pkg_size':     hdr[7],
            'data_offset':  hdr[8],
            'content_id':   hdr[10].decode('ascii', errors='ignore').strip('\x00').strip(),
            'qa_digest':    hdr[11],
            'klicensee':    hdr[12],
        }

    def _parse_meta_table(self, f, meta_offset, meta_count):
        meta = {
            'npdrm_version':      "N/A",
            'content_type_str':   "N/A",
            'drm_type':           None,
            'drm_type_str':       "N/A",
            'pkg_flags':          None,
            'install_size':       None,
            'app_version_meta':   "N/A",
            'title_id_meta':      "N/A",
        }
        f.seek(meta_offset)
        for _ in range(meta_count):
            meta_id, meta_size = struct.unpack('>I I', f.read(8))
            meta_data = f.read(meta_size)
            if meta_id == PKG_META_DRM_TYPE and meta_size >= 4:
                drm_val = struct.unpack('>I', meta_data[:4])[0]
                meta['drm_type']     = drm_val
                meta['drm_type_str'] = self.get_drm_type_name(drm_val)
            elif meta_id == PKG_META_CONTENT_TYPE and meta_size >= 4:
                ctype_val = struct.unpack('>I', meta_data[:4])[0]
                meta['content_type_str'] = self.get_pkg_content_type_name(ctype_val)
            elif meta_id == PKG_META_PKG_TYPE and meta_size >= 4:
                meta['pkg_flags'] = struct.unpack('>I', meta_data[:4])[0]
            elif meta_id == PKG_META_PKG_SIZE and meta_size >= 8:
                meta['install_size'] = struct.unpack('>Q', meta_data[:8])[0]
            elif meta_id == PKG_META_NPDRM_VERSION and meta_size >= 2:
                meta['npdrm_version'] = meta_data[:2].hex()
            elif meta_id == PKG_META_APP_VERSION_PSP and meta_size >= 4:
                raw = meta_data[:4]
                try:
                    meta['app_version_meta'] = raw.decode('ascii', errors='ignore').strip('\x00')
                except Exception:
                    meta['app_version_meta'] = raw.hex()
        return meta

    def load_pkg(self):
        for i in self.tree.get_children():
            self.tree.delete(i)
        self.info_text.delete("0.0", "end")
        self.file_entries = {}

        try:
            with open(self.current_pkg_path, 'rb') as f:
                hdr  = self._parse_pkg_header(f)
                meta = self._parse_meta_table(f, hdr['meta_offset'], hdr['meta_count'])

                self.pkg_type     = hdr['pkg_type']
                self.data_offset  = hdr['data_offset']
                self.qa_digest    = hdr['qa_digest']
                self.klicensee    = hdr['klicensee']
                content_id        = hdr['content_id']
                self.current_folder_name = content_id

                pkg_platform      = hdr['pkg_platform']
                pkg_size          = hdr['pkg_size']
                file_count        = hdr['file_count']

                # Find AES key 
                entry_size  = 32
                raw_table   = None
                main_key    = None
                used_key_name = ""

                if self.pkg_type == PKG_RELEASE_TYPE_DEBUG:
                    used_key_name = "Debug"
                    raw_table = decrypt_data_blocks(
                        f, self.data_offset, 0, file_count * entry_size,
                        None, self.klicensee, self.pkg_type, self.qa_digest
                    )
                else:
                    for key, kname in ALL_POTENTIAL_KEYS:
                        candidate = decrypt_data_blocks(
                            f, self.data_offset, 0, file_count * entry_size,
                            key, self.klicensee, self.pkg_type, self.qa_digest
                        )
                        if file_count > 0:
                            n_off, n_sz, _, _, _, _ = struct.unpack('>I I Q Q I I', candidate[:32])
                            if n_sz > 0 and n_sz < 512 and n_off < pkg_size:
                                raw_table = candidate
                                main_key  = key
                                used_key_name = kname
                                break

                if not raw_table:
                    raise ValueError("Failed to decrypt file table.")

                folders     = {}
                sfo_entry   = None
                c00_sfo_entry = None

                for i in range(file_count):
                    e_raw = raw_table[i * entry_size: (i + 1) * entry_size]
                    n_off, n_sz, f_off, f_sz, f_type, _ = struct.unpack('>I I Q Q I I', e_raw)
                    if n_sz == 0:
                        continue

                    name_raw = decrypt_data_blocks(
                        f, self.data_offset, n_off, n_sz,
                        main_key, self.klicensee, self.pkg_type, self.qa_digest
                    )
                    current_file_key = main_key
                    try:
                        full_path = name_raw.decode('utf-8').strip('\x00').replace("\\", "/")
                        if not all(31 < ord(c) < 127 or c in "/._- " for c in full_path[:min(len(full_path), 10)]):
                            raise ValueError("Bad name")
                    except Exception:
                        full_path = None
                        for test_key, _ in ALL_POTENTIAL_KEYS:
                            try:
                                alt = decrypt_data_blocks(
                                    f, self.data_offset, n_off, n_sz,
                                    test_key, self.klicensee, self.pkg_type, self.qa_digest
                                )
                                decoded = alt.decode('utf-8').strip('\x00').replace("\\", "/")
                                if all(31 < ord(c) < 127 or c in "/._- " for c in decoded[:min(len(decoded), 10)]):
                                    full_path        = decoded
                                    current_file_key = test_key
                                    break
                            except Exception:
                                continue
                        if full_path is None:
                            continue

                    parts  = [p for p in full_path.split('/') if p]
                    parent = ""
                    for j, part in enumerate(parts):
                        current_path = "/".join(parts[:j + 1])
                        is_last      = (j == len(parts) - 1)
                        if current_path not in folders:
                            if is_last and (f_type & 0xFF) not in (4, 0x12):
                                sz_str = self.format_size(f_sz)
                                node   = self.tree.insert(parent, "end", text=part, values=(sz_str, "File"))
                                self.file_entries[node] = {
                                    'path': full_path, 'off': f_off, 'sz': f_sz, 'key': current_file_key
                                }
                                if full_path.upper().endswith("PARAM.SFO"):
                                    if "C00" in full_path.upper().split('/')[:-1]:
                                        c00_sfo_entry = self.file_entries[node]
                                    else:
                                        sfo_entry = self.file_entries[node]
                            else:
                                node = self.tree.insert(parent, "end", text=part, values=("", "Folder"))
                                folders[current_path] = node
                        if current_path in folders:
                            parent = folders[current_path]

                platform_str = "PS3" if pkg_platform == PKG_PLATFORM_TYPE_PS3 else "PSP / PS Vita"
                release_str  = "Debug" if self.pkg_type == PKG_RELEASE_TYPE_DEBUG else "Retail"

                lines = [
                    "PKG INFO:",
                    "-" * 60,
                    f"Content ID:        {content_id}",
                    f"Platform:          {platform_str}",
                    f"Release Type:      {release_str}",
                    f"Content Type:      {meta['content_type_str']}",
                    f"DRM Type:          {meta['drm_type_str']}",
                    f"Package Size:      {self.format_size(pkg_size)}",
                    f"Install Size:      {self.format_size(meta['install_size']) if meta['install_size'] else 'N/A'}",
                    f"NPDRM Version:     {meta['npdrm_version']}",
                    f"PKG Flags:         {('0x%08X' % meta['pkg_flags']) if meta['pkg_flags'] is not None else 'N/A'}",
                    f"QA Digest:         {self.qa_digest.hex().upper()}",
                    f"Klicensee:         {self.klicensee.hex().upper()}",
                    f"Key Type:          {used_key_name}",
                    f"File Count:        {file_count}",
                    "",
                ]

                def sfo_lines(sfo_data_raw, label):
                    sfo_meta = self.parse_sfo(sfo_data_raw)
                    out = [label, "-" * 60]
                    if not sfo_meta:
                        out.append("PARAM.SFO not found or corrupted.")
                        return out, sfo_meta
                    category = sfo_meta.get("CATEGORY", "N/A")
                    out += [
                        f"Game Title:           {sfo_meta.get('TITLE', 'N/A')}",
                        f"Title ID:             {sfo_meta.get('TITLE_ID', 'N/A')}",
                        f"Communication ID:     {sfo_meta.get('NP_COMMUNICATION_ID', 'N/A')}",
                        f"Version:              {sfo_meta.get('VERSION', 'N/A')}",
                        f"App Version:          {sfo_meta.get('APP_VER', 'N/A')}",
                        f"Target App Version:   {sfo_meta.get('TARGET_APP_VER', 'N/A')}",
                        f"Firmware Version:     {sfo_meta.get('PS3_SYSTEM_VER', 'N/A')}",
                        f"Parental Level:       {sfo_meta.get('PARENTAL_LEVEL', 'N/A')}",
                        f"Category:             {category} ({self.get_sfo_category_name(category)})",
                        f"Resolution:           {self.get_sfo_resolution(sfo_meta.get('RESOLUTION', 'N/A'))}",
                        f"Sound Format:         {self.get_sfo_sound_format(sfo_meta.get('SOUND_FORMAT', 'N/A'))}",
                        f"Bootable:             {sfo_meta.get('BOOTABLE', 'N/A')}",
                        f"Attribute:            {sfo_meta.get('ATTRIBUTE', 'N/A')}",
                        "",
                    ]
                    return out, sfo_meta

                sfo_meta_main = {}
                if sfo_entry:
                    sfo_raw  = decrypt_data_blocks(
                        f, self.data_offset, sfo_entry['off'], sfo_entry['sz'],
                        sfo_entry['key'], self.klicensee, self.pkg_type, self.qa_digest
                    )
                    sfo_out, sfo_meta_main = sfo_lines(sfo_raw, "SFO INFO (PARAM.SFO):")
                    title = sfo_meta_main.get("TITLE", "")
                    if title:
                        self.title(f"PKG Viewer - {title}")
                else:
                    sfo_out = ["SFO INFO:", "-" * 60, "PARAM.SFO not found or corrupted.", ""]

                lines += sfo_out

                if c00_sfo_entry:
                    c00_raw = decrypt_data_blocks(
                        f, self.data_offset, c00_sfo_entry['off'], c00_sfo_entry['sz'],
                        c00_sfo_entry['key'], self.klicensee, self.pkg_type, self.qa_digest
                    )
                    c00_out, _ = sfo_lines(c00_raw, "SFO INFO (C00/PARAM.SFO):")
                    lines += c00_out

                self.info_text.insert("end", "\n".join(lines))

            self.btn_extract_all.configure(state="normal")
            self.btn_extract_sel.configure(state="normal")
            self.btn_export_json.configure(state="normal")

        except Exception as e:
            messagebox.showerror("Error", f"Unable to open PKG:\n{e}")

    def extract_file(self, pkg_f, entry, dest_dir, current_progress_callback=None):
        out_path = os.path.join(dest_dir, entry['path'].lstrip('/'))
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        klic_int = int.from_bytes(self.klicensee, byteorder='big')

        with open(out_path, 'wb') as out_f:
            remaining = entry['sz']
            curr_off  = entry['off']
            CHUNK     = 1024 * 1024

            while remaining > 0:
                to_read    = min(remaining, CHUNK)
                block_off  = curr_off // 16
                byte_off   = curr_off % 16
                num_blocks = (byte_off + to_read + 15) // 16

                pkg_f.seek(self.data_offset + block_off * 16)
                enc = pkg_f.read(num_blocks * 16)

                if self.pkg_type == PKG_RELEASE_TYPE_DEBUG:
                    dec = bytearray()
                    for i in range(num_blocks):
                        ks = get_debug_keystream_block(self.qa_digest, block_off + i)
                        dec.extend(a ^ b for a, b in zip(enc[i * 16:(i + 1) * 16], ks))
                    dec = bytes(dec)
                elif self.pkg_type == PKG_RELEASE_TYPE_RELEASE:
                    nonce  = ((klic_int + block_off) % (1 << 128)).to_bytes(16, 'big')
                    cipher = Cipher(algorithms.AES(entry['key']), modes.CTR(nonce), backend=default_backend())
                    dec    = cipher.decryptor().update(enc) + cipher.decryptor().finalize()
                else:
                    dec = enc

                out_f.write(dec[byte_off: byte_off + to_read])
                remaining -= to_read
                curr_off  += to_read
                if current_progress_callback:
                    current_progress_callback(to_read)

    def extract_file_to_memory(self, pkg_f, entry):
        klic_int  = int.from_bytes(self.klicensee, byteorder='big')
        remaining = entry['sz']
        curr_off  = entry['off']
        result    = bytearray()

        while remaining > 0:
            to_read    = min(remaining, 1024 * 1024)
            block_off  = curr_off // 16
            byte_off   = curr_off % 16
            num_blocks = (byte_off + to_read + 15) // 16

            pkg_f.seek(self.data_offset + block_off * 16)
            enc = pkg_f.read(num_blocks * 16)

            if self.pkg_type == PKG_RELEASE_TYPE_DEBUG:
                dec = bytearray()
                for i in range(num_blocks):
                    ks = get_debug_keystream_block(self.qa_digest, block_off + i)
                    dec.extend(a ^ b for a, b in zip(enc[i * 16:(i + 1) * 16], ks))
                dec = bytes(dec)
            elif self.pkg_type == PKG_RELEASE_TYPE_RELEASE:
                nonce  = ((klic_int + block_off) % (1 << 128)).to_bytes(16, 'big')
                cipher = Cipher(algorithms.AES(entry['key']), modes.CTR(nonce), backend=default_backend())
                dec    = cipher.decryptor().update(enc) + cipher.decryptor().finalize()
            else:
                dec = enc

            result.extend(dec[byte_off: byte_off + to_read])
            remaining -= to_read
            curr_off  += to_read

        return bytes(result)

    def extract_icons_worker(self, pkg_path, file_entries_list, icons_base_dir,
                              data_offset, klicensee, pkg_type, qa_digest,
                              pkg_name, content_id):
        safe_pkg     = re.sub(r'[<>:"/\\|?*]', '_', pkg_name)
        safe_cid     = re.sub(r'[<>:"/\\|?*]', '_', content_id) if content_id else "UNKNOWN"
        target_dir   = os.path.join(icons_base_dir, "icons", safe_pkg, safe_cid)
        os.makedirs(target_dir, exist_ok=True)

        extracted = 0
        for entry in file_entries_list:
            fname        = os.path.basename(entry['path'])
            subdir_parts = entry['path'].split('/')
            rel = '/'.join(subdir_parts[-2:]) if len(subdir_parts) >= 2 else fname
            if not ICON_FILE_RE.match(rel) and not ICON_FILE_RE.match(fname):
                continue
            try:
                data = _decrypt_entry_to_bytes(pkg_path, entry, data_offset,
                                               klicensee, pkg_type, qa_digest)
                # Preserve C00 sub-folder inside target_dir
                if len(subdir_parts) >= 2 and subdir_parts[-2].upper() == "C00":
                    out_dir = os.path.join(target_dir, "C00")
                    os.makedirs(out_dir, exist_ok=True)
                else:
                    out_dir = target_dir
                out_path = os.path.join(out_dir, fname)
                with open(out_path, 'wb') as fh:
                    fh.write(data)
                print(f"[icons] {entry['path']} {out_path}")
                extracted += 1
            except Exception as e:
                print(f"[icons] Failed to extract {entry['path']}: {e}")
        return extracted, target_dir

    # File preview 
    def preview_selected_file(self):
        selection = self.tree.selection()
        if not selection:
            return
        item  = selection[0]
        entry = self.file_entries.get(item)
        if not entry:
            return

        ext = entry['path'].lower().rsplit('.', 1)[-1]

        try:
            with open(self.current_pkg_path, 'rb') as f:
                file_data = self.extract_file_to_memory(f, entry)

            if ext in ('png', 'jpg', 'jpeg', 'dds'):
                image = Image.open(io.BytesIO(file_data))
                preview_win = ctk.CTkToplevel(self)
                filename    = os.path.basename(entry['path'])
                preview_win.title(f"Preview: {filename}")

                max_size = 900
                width, height = image.size
                if width > max_size or height > max_size:
                    ratio  = min(max_size / width, max_size / height)
                    width  = int(width * ratio)
                    height = int(height * ratio)

                preview_win.geometry(f"{width + 40}x{height + 40}")
                preview_win.focus()
                ctk_img = ctk.CTkImage(light_image=image, dark_image=image, size=(width, height))
                ctk.CTkLabel(preview_win, image=ctk_img, text="").pack(expand=True, fill="both", padx=10, pady=10)

            elif ext in ('pam', 'at3'):
                temp_dir  = tempfile.gettempdir()
                filename  = os.path.basename(entry['path'])
                base_path = os.path.join(temp_dir, f"temp_preview_{filename}")

                if ext == 'pam' and file_data.startswith(b'PAMF'):
                    mpeg_start = file_data.find(b'\x00\x00\x01\xBA')
                    if mpeg_start != -1:
                        file_data = file_data[mpeg_start:]
                    temp_path = base_path + ".mpg"
                else:
                    temp_path = base_path + f".{ext}"

                with open(temp_path, 'wb') as tf:
                    tf.write(file_data)

                if ext == 'at3':
                    wav_path   = base_path + ".wav"
                    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
                    subprocess.run(
                        [ffmpeg_exe, '-y', '-i', temp_path, wav_path],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                    )
                    if os.path.exists(wav_path):
                        AudioPlayerWindow(self, wav_path, filename)
                    else:
                        messagebox.showerror("Error", "Failed to convert AT3 audio to WAV.")

                elif ext == 'pam':
                    ffplay_path = None
                    # 1) try PATH
                    try:
                        result = subprocess.run(
                            ['which', 'ffplay'] if os.name != 'nt' else ['where', 'ffplay'],
                            capture_output=True, text=True
                        )
                        ffplay_path = result.stdout.strip() or None
                    except Exception:
                        pass
                    # 2) try sibling of ffmpeg
                    if not ffplay_path:
                        try:
                            ffmpeg_exe      = imageio_ffmpeg.get_ffmpeg_exe()
                            potential_ffplay = ffmpeg_exe.replace('ffmpeg', 'ffplay').replace('FFMPEG', 'FFPLAY')
                            if os.path.exists(potential_ffplay):
                                ffplay_path = potential_ffplay
                        except Exception:
                            pass

                    if ffplay_path:
                        env = os.environ.copy()
                        env.pop("LD_LIBRARY_PATH", None)
                        subprocess.Popen(
                            [ffplay_path, '-autoexit', '-window_title', filename, '-loop', '0', temp_path],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env
                        )
                    else:
                        messagebox.showwarning("Missing ffplay", "ffplay not found. Install FFmpeg to preview PAM files.")

        except Exception as e:
            messagebox.showerror("Error", f"Failed to open the file:\n{e}")

    def update_progress(self, bytes_done, total_bytes):
        pct = bytes_done / total_bytes if total_bytes else 0
        self.progress_bar.set(pct)
        self.lbl_status.configure(text=f"Extracting: {int(pct * 100)}%")

    def reset_ui_after_work(self):
        self.btn_extract_all.configure(state="normal")
        self.btn_extract_sel.configure(state="normal")
        self.btn_open.configure(state="normal")
        self.btn_batch_json.configure(state="normal")
        self.btn_process_links.configure(state="normal")
        if self.current_pkg_path:
            self.btn_export_json.configure(state="normal")
        self.progress_bar.set(0)
        self.lbl_status.configure(text="Ready")

    def toggle_buttons(self, state):
        for btn in (self.btn_batch_json, self.btn_process_links,
                    self.btn_open, self.btn_extract_all, self.btn_extract_sel,
                    self.btn_export_json):
            btn.configure(state=state)

    def extraction_worker(self, nodes_to_extract, dest, mode="all"):
        self.after(0, self.toggle_buttons, "disabled")
        try:
            entries = []
            if mode == "all":
                entries = list(self.file_entries.values())
            else:
                def collect(nodes):
                    for n in nodes:
                        if n in self.file_entries:
                            entries.append(self.file_entries[n])
                        collect(self.tree.get_children(n))
                collect(nodes_to_extract)

            total_size   = sum(e['sz'] for e in entries)
            current_done = 0

            if total_size == 0:
                self.after(0, lambda: messagebox.showinfo("Info", "Nothing to extract."))
                return

            with open(self.current_pkg_path, 'rb') as f:
                for entry in entries:
                    def cb(chunk, _cd=None):
                        nonlocal current_done
                        current_done += chunk
                        self.after(0, self.update_progress, current_done, total_size)
                    self.extract_file(f, entry, dest, current_progress_callback=cb)

            # Also extract icons if checkbox is ticked
            if self.var_extract_icons.get():
                pkg_base  = os.path.splitext(os.path.basename(self.current_pkg_path))[0]
                n, icon_path = self.extract_icons_worker(
                    self.current_pkg_path,
                    list(self.file_entries.values()),
                    dest,
                    self.data_offset, self.klicensee, self.pkg_type, self.qa_digest,
                    pkg_name=pkg_base,
                    content_id=self.current_folder_name,
                )
                self.after(0, lambda p=icon_path, c=n: messagebox.showinfo(
                    "Success",
                    f"Extraction done.\nExtracted {c} icon/pic/snd file(s) to:\n{p}"))
            else:
                self.after(0, lambda: messagebox.showinfo("Success", "Extraction finished successfully."))

        except Exception as e:
            self.after(0, lambda: messagebox.showerror("Error", str(e)))
        finally:
            self.after(0, self.reset_ui_after_work)

    def extract_selected(self):
        selection = self.tree.selection()
        if not selection:
            return
        dest = filedialog.askdirectory()
        if not dest:
            return
        dest = os.path.join(dest, self.current_folder_name)
        threading.Thread(target=self.extraction_worker, args=(selection, dest, "selected"), daemon=True).start()

    def extract_all(self):
        dest = filedialog.askdirectory()
        if not dest:
            return
        dest = os.path.join(dest, self.current_folder_name)
        threading.Thread(target=self.extraction_worker, args=(None, dest, "all"), daemon=True).start()

    def batch_json_folder(self):
        folder_path = filedialog.askdirectory(title="Choose folder with PKGs")
        if not folder_path:
            return
        pkg_files = [
            os.path.join(folder_path, f)
            for f in os.listdir(folder_path)
            if f.lower().endswith('.pkg')
        ]
        if not pkg_files:
            messagebox.showinfo("No Files", "Unable to find any PKG files in this folder.")
            return
        threading.Thread(target=self.json_worker, args=(pkg_files,), daemon=True).start()

    def export_current_json(self):
        if not self.current_pkg_path:
            return
        threading.Thread(target=self.json_worker, args=([self.current_pkg_path],), daemon=True).start()

    def json_worker(self, files_to_process):
        self.after(0, self.toggle_buttons, "disabled")
        success_count = 0
        total         = len(files_to_process)

        for i, pkg_path in enumerate(files_to_process):
            self.after(0, lambda i=i: self.lbl_status.configure(text=f"Working {i + 1}/{total}..."))
            success, msg = self.generate_json_for_pkg(pkg_path)
            if success:
                success_count += 1
            else:
                print(f"Failed: {pkg_path}: {msg}")

        self.after(0, lambda: messagebox.showinfo(
            "Finished", f"Generated JSON for {success_count}/{total} PKG files."))
        self.after(0, self.reset_ui_after_work)

    def _hash_file_entry(self, pkg_path, entry, data_offset, klicensee, pkg_type, qa_digest):
        file_md5  = hashlib.md5()
        file_sha1 = hashlib.sha1()
        crc32_val = 0
        klic_int  = int.from_bytes(klicensee, byteorder='big')
        remaining = entry['sz']
        curr_off  = entry['off']
        CHUNK     = 4 * 1024 * 1024

        with open(pkg_path, 'rb') as fh:
            while remaining > 0:
                to_read    = min(remaining, CHUNK)
                block_off  = curr_off // 16
                byte_off   = curr_off % 16
                num_blocks = (byte_off + to_read + 15) // 16

                fh.seek(data_offset + block_off * 16)
                enc = fh.read(num_blocks * 16)

                if pkg_type == PKG_RELEASE_TYPE_DEBUG:
                    dec = bytearray()
                    for i in range(num_blocks):
                        ks = get_debug_keystream_block(qa_digest, block_off + i)
                        dec.extend(a ^ b for a, b in zip(enc[i * 16:(i + 1) * 16], ks))
                    dec = bytes(dec)
                elif pkg_type == PKG_RELEASE_TYPE_RELEASE:
                    nonce  = ((klic_int + block_off) % (1 << 128)).to_bytes(16, 'big')
                    cipher = Cipher(algorithms.AES(entry['key']), modes.CTR(nonce), backend=default_backend())
                    dec    = cipher.decryptor().update(enc) + cipher.decryptor().finalize()
                else:
                    dec = enc

                block = dec[byte_off: byte_off + to_read]
                file_md5.update(block)
                file_sha1.update(block)
                crc32_val = zlib.crc32(block, crc32_val)
                remaining -= to_read
                curr_off  += to_read

        return {
            "path":  entry['path'],
            "size":  entry['sz'],
            "md5":   file_md5.hexdigest(),
            "sha1":  file_sha1.hexdigest(),
            "crc32": f"{crc32_val & 0xFFFFFFFF:08X}",
        }

    def generate_json_for_pkg(self, pkg_path, output_dir=None, pre_hashes=None, extract_icons=None):
        try:
            pkg_name  = os.path.basename(pkg_path)
            do_icons  = extract_icons if extract_icons is not None else self.var_extract_icons.get()

            # Hash entire PKG file 
            if pre_hashes:
                pkg_md5_str, pkg_sha1_str = pre_hashes
                self.after(0, lambda: self.lbl_status.configure(text=f"Analyzing PKG... ({pkg_name})"))
                self.after(0, self.progress_bar.set, 0)
            else:
                self.after(0, lambda: self.lbl_status.configure(text=f"Hashing PKG... ({pkg_name})"))
                self.after(0, self.progress_bar.set, 0)

                pkg_md5       = hashlib.md5()
                pkg_sha1      = hashlib.sha1()
                pkg_crc32     = 0
                total_sz      = os.path.getsize(pkg_path)
                hashed_sz     = 0
                last_ui       = 0.0

                with open(pkg_path, 'rb') as f:
                    while True:
                        chunk = f.read(4 * 1024 * 1024)
                        if not chunk:
                            break
                        pkg_md5.update(chunk)
                        pkg_sha1.update(chunk)
                        pkg_crc32  = zlib.crc32(chunk, pkg_crc32)
                        hashed_sz += len(chunk)
                        now = time.monotonic()
                        if now - last_ui >= 0.5 and total_sz > 0:
                            last_ui = now
                            self.after(0, self.progress_bar.set, hashed_sz / total_sz)

                pkg_md5_str  = pkg_md5.hexdigest()
                pkg_sha1_str = pkg_sha1.hexdigest()
                pkg_crc32_str = f"{pkg_crc32 & 0xFFFFFFFF:08X}"
            if pre_hashes:
                pkg_crc32_str = "N/A"

            # Parse PKG 
            with open(pkg_path, 'rb') as f:
                hdr = self._parse_pkg_header(f)
                if hdr is None:
                    return False, "Invalid PKG"

                pkg_type     = hdr['pkg_type']
                pkg_platform = hdr['pkg_platform']
                meta_offset  = hdr['meta_offset']
                meta_count   = hdr['meta_count']
                file_count   = hdr['file_count']
                pkg_size     = hdr['pkg_size']
                data_offset  = hdr['data_offset']
                content_id   = hdr['content_id']
                qa_digest    = hdr['qa_digest']
                klicensee    = hdr['klicensee']

                meta = self._parse_meta_table(f, meta_offset, meta_count)

                # Find AES key 
                entry_size    = 32
                raw_table     = None
                main_key      = None
                used_key_name = ""
                potential_keys = ALL_POTENTIAL_KEYS  # always defined

                if pkg_type == PKG_RELEASE_TYPE_DEBUG:
                    used_key_name = "Debug"
                    raw_table = decrypt_data_blocks(
                        f, data_offset, 0, file_count * entry_size,
                        None, klicensee, pkg_type, qa_digest
                    )
                else:
                    for key, kname in potential_keys:
                        candidate = decrypt_data_blocks(
                            f, data_offset, 0, file_count * entry_size,
                            key, klicensee, pkg_type, qa_digest
                        )
                        if file_count > 0:
                            n_off, n_sz, _, _, _, _ = struct.unpack('>I I Q Q I I', candidate[:32])
                            if n_sz > 0 and n_sz < 512 and n_off < pkg_size:
                                raw_table     = candidate
                                main_key      = key
                                used_key_name = kname
                                break

                if not raw_table:
                    return False, "Failed to decode files table."

                file_entries  = []
                sfo_entry     = None
                c00_sfo_entry = None

                for i in range(file_count):
                    e_raw = raw_table[i * entry_size: (i + 1) * entry_size]
                    n_off, n_sz, f_off, f_sz, f_type, _ = struct.unpack('>I I Q Q I I', e_raw)
                    if n_sz == 0:
                        continue

                    name_raw = decrypt_data_blocks(
                        f, data_offset, n_off, n_sz,
                        main_key, klicensee, pkg_type, qa_digest
                    )
                    current_file_key = main_key
                    full_path        = None
                    try:
                        fp = name_raw.decode('utf-8').strip('\x00').replace("\\", "/")
                        if not all(31 < ord(c) < 127 or c in "/._- " for c in fp[:min(len(fp), 10)]):
                            raise ValueError("Bad name")
                        full_path = fp
                    except Exception:
                        for test_key, _ in potential_keys:
                            try:
                                alt = decrypt_data_blocks(
                                    f, data_offset, n_off, n_sz,
                                    test_key, klicensee, pkg_type, qa_digest
                                )
                                decoded = alt.decode('utf-8').strip('\x00').replace("\\", "/")
                                if all(31 < ord(c) < 127 or c in "/._- " for c in decoded[:min(len(decoded), 10)]):
                                    full_path        = decoded
                                    current_file_key = test_key
                                    break
                            except Exception:
                                continue

                    if full_path is None:
                        continue

                    if (f_type & 0xFF) not in (4, 0x12):
                        entry = {'path': full_path, 'off': f_off, 'sz': f_sz, 'key': current_file_key}
                        file_entries.append(entry)
                        up = full_path.upper()
                        if up.endswith("PARAM.SFO"):
                            parts = up.split('/')
                            if len(parts) >= 2 and parts[-2] == "C00":
                                c00_sfo_entry = entry
                            elif sfo_entry is None:
                                sfo_entry = entry

                # Parse PARAM.SFO 
                def read_sfo_entry(entry):
                    data = bytearray()
                    klic_int  = int.from_bytes(klicensee, byteorder='big')
                    remaining = entry['sz']
                    curr_off  = entry['off']
                    with open(pkg_path, 'rb') as fh:
                        while remaining > 0:
                            to_read    = min(remaining, 1024 * 1024)
                            block_off  = curr_off // 16
                            byte_off   = curr_off % 16
                            num_blocks = (byte_off + to_read + 15) // 16
                            fh.seek(data_offset + block_off * 16)
                            enc = fh.read(num_blocks * 16)
                            if pkg_type == PKG_RELEASE_TYPE_DEBUG:
                                dec = bytearray()
                                for i in range(num_blocks):
                                    ks = get_debug_keystream_block(qa_digest, block_off + i)
                                    dec.extend(a ^ b for a, b in zip(enc[i*16:(i+1)*16], ks))
                                dec = bytes(dec)
                            elif pkg_type == PKG_RELEASE_TYPE_RELEASE:
                                nonce  = ((klic_int + block_off) % (1 << 128)).to_bytes(16, 'big')
                                cipher = Cipher(algorithms.AES(entry['key']), modes.CTR(nonce), backend=default_backend())
                                dec    = cipher.decryptor().update(enc) + cipher.decryptor().finalize()
                            else:
                                dec = enc
                            data.extend(dec[byte_off: byte_off + to_read])
                            remaining -= to_read
                            curr_off  += to_read
                    return self.parse_sfo(bytes(data))

                sfo_meta     = read_sfo_entry(sfo_entry)     if sfo_entry     else {}
                c00_sfo_meta = read_sfo_entry(c00_sfo_entry) if c00_sfo_entry else {}

                # Hash all internal files
                n_workers   = min(4, max(1, len(file_entries)))
                total_files = len(file_entries)
                done_lock   = threading.Lock()
                done_count  = [0]

                self.after(0, lambda: self.lbl_status.configure(text=f"Hashing internal files 0/{total_files} ({pkg_name})"))
                self.after(0, self.progress_bar.set, 0)

                def hash_with_progress(entry):
                    result = self._hash_file_entry(pkg_path, entry, data_offset, klicensee, pkg_type, qa_digest)
                    with done_lock:
                        done_count[0] += 1
                        done = done_count[0]
                    self.after(0, lambda done=done: self.lbl_status.configure(text=f"Hashing internal files {done}/{total_files} ({pkg_name})"))
                    self.after(0, self.progress_bar.set,done / total_files if total_files else 1)
                    return result

                with ThreadPoolExecutor(max_workers=n_workers) as pool:
                    files_json_list = list(pool.map(hash_with_progress, file_entries))

                # Icon extraction (if requested) 
                icons_extracted = 0
                icons_final_path = ""
                if do_icons:
                    if output_dir:
                        icons_base = output_dir
                    else:
                        icons_base = os.path.dirname(os.path.abspath(pkg_path))
                    pkg_base_name = os.path.splitext(os.path.basename(pkg_path))[0]
                    icons_extracted, icons_final_path = self.extract_icons_worker(
                        pkg_path, file_entries, icons_base,
                        data_offset, klicensee, pkg_type, qa_digest,
                        pkg_name=pkg_base_name,
                        content_id=content_id,
                    )
                    self.after(0, lambda: self.lbl_status.configure(text=f"Extracted {icons_extracted} icon(s) {icons_final_path}"))

                # Build JSON 
                platform_str = "PS3" if pkg_platform == PKG_PLATFORM_TYPE_PS3 else "PSP/Vita"
                release_str  = "Debug" if pkg_type == PKG_RELEASE_TYPE_DEBUG else "Retail"

                pkg_info = {
                    "Content_ID":      content_id,
                    "Platform":        platform_str,
                    "Release_Type":    release_str,
                    "Content_Type":    meta['content_type_str'],
                    "DRM_Type":        meta['drm_type_str'],
                    "PKG_Flags":       f"0x{meta['pkg_flags']:08X}" if meta['pkg_flags'] is not None else None,
                    "Package_Size":    pkg_size,
                    "PKG_MD5":         pkg_md5_str,
                    "PKG_SHA1":        pkg_sha1_str,
                    "NPDRM_Version":   meta['npdrm_version'],
                    "QA_Digest":       qa_digest.hex().upper(),
                    "Klicensee":       klicensee.hex().upper(),
                    "Key_Type":        used_key_name,
                    "File_Count":      len(file_entries),
                }

                json_dict = {
                    "PKG_INFO":        pkg_info,
                    "PARAM_SFO":       sfo_meta,
                    "PARAM_SFO_C00":   c00_sfo_meta,
                    "FILES":           files_json_list,
                }

                # Save JSON 
                original_filename = os.path.basename(pkg_path)
                base_name  = original_filename[:-4] if original_filename.lower().endswith('.pkg') else original_filename
                clean_name = re.sub(r'[<>:"/\\|?*]', '_', base_name)

                if output_dir:
                    os.makedirs(output_dir, exist_ok=True)
                    out_path = os.path.join(output_dir, f"{clean_name}.json")
                else:
                    out_path = os.path.join(os.path.dirname(os.path.abspath(pkg_path)),
                                            f"{clean_name}.json")

                def _default(obj):
                    if isinstance(obj, bytes):
                        return obj.hex()
                    return str(obj)

                with open(out_path, 'w', encoding='utf-8') as jf:
                    json.dump(json_dict, jf, indent=4, ensure_ascii=False, default=_default)

                print(f"JSON saved: {out_path}")
                if do_icons and icons_final_path:
                    print(f"Icons extracted ({icons_extracted}): {icons_final_path}")
                return True, out_path

        except Exception as e:
            print(f"generate_json_for_pkg error: {e}")
            return False, str(e)

    def process_links_from_json(self):
        json_file = filedialog.askopenfilename(
            title="Choose JSON file with PKG links",
            filetypes=[("JSON", "*.json")]
        )
        if not json_file:
            return
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                urls = json.load(f)
        except Exception as e:
            messagebox.showerror("Error", f"Could not read JSON file:\n{e}")
            return
        if not isinstance(urls, list):
            messagebox.showerror("Error", "JSON structure must be a list of URLs.")
            return
        threading.Thread(target=self.links_worker, args=(urls,), daemon=True).start()

    def download_and_process_single(self, url, json_dir, base_dir, current_idx, total):
        filename           = url.split('/')[-1] if '/' in url else f"temp_{current_idx}.pkg"
        base_name          = filename[:-4] if filename.lower().endswith('.pkg') else filename
        clean_filename_base = re.sub(r'[<>:"/\\|?*]', '_', base_name)
        temp_pkg_path      = os.path.join(base_dir, filename)
        expected_json_name = f"{clean_filename_base}.json"

        if expected_json_name in os.listdir(json_dir):
            print(f"Skipped: {filename} (JSON '{expected_json_name}' already exists)")
            return True

        try:
            print(f"Start: {filename}")

            pkg_md5  = hashlib.md5()
            pkg_sha1 = hashlib.sha1()

            request  = urllib.request.Request(
                url,
                headers={'User-Agent': 'PKGViewer/1.0', 'Accept-Encoding': 'identity'}
            )
            response   = urllib.request.urlopen(request, timeout=120)
            total_size = int(response.headers.get('Content-Length', 0))

            DOWNLOAD_CHUNK = 8 * 1024 * 1024
            downloaded     = 0
            last_ui_time   = 0.0

            with open(temp_pkg_path, 'wb') as f:
                while True:
                    chunk = response.read(DOWNLOAD_CHUNK)
                    if not chunk:
                        break
                    f.write(chunk)
                    pkg_md5.update(chunk)
                    pkg_sha1.update(chunk)
                    downloaded += len(chunk)

                    now = time.monotonic()
                    if now - last_ui_time >= 0.5:
                        last_ui_time = now
                        mb_done = downloaded / (1024 * 1024)
                        if total_size > 0:
                            mb_total = total_size / (1024 * 1024)
                            status   = f"[{current_idx+1}/{total}] {filename}: {mb_done:.0f}/{mb_total:.0f} MB"
                            pct      = downloaded / total_size
                        else:
                            status = f"[{current_idx+1}/{total}] {filename}: {mb_done:.0f} MB"
                            pct    = 0.0
                        self.after(0, lambda status=status: self.lbl_status.configure(text=status))
                        self.after(0, self.progress_bar.set, pct)

            pre_hashes = (pkg_md5.hexdigest(), pkg_sha1.hexdigest())
            success, msg = self.generate_json_for_pkg(
                temp_pkg_path, output_dir=json_dir, pre_hashes=pre_hashes
            )

            if os.path.exists(temp_pkg_path):
                os.remove(temp_pkg_path)
            return success

        except Exception as e:
            print(f"Error for {url}: {e}")
            if os.path.exists(temp_pkg_path):
                os.remove(temp_pkg_path)
            return False

    def links_worker(self, urls):
        self.after(0, self.toggle_buttons, "disabled")

        if hasattr(sys, '_MEIPASS'):
            base_dir = os.path.dirname(sys.executable)
        else:
            base_dir = os.path.dirname(os.path.abspath(__file__))

        json_dir = os.path.join(base_dir, "json")
        os.makedirs(json_dir, exist_ok=True)

        total         = len(urls)
        success_count = 0

        with ThreadPoolExecutor(max_workers=1) as executor:
            futures = [
                executor.submit(self.download_and_process_single,
                                url, json_dir, base_dir, i, total)
                for i, url in enumerate(urls)
            ]
            for i, future in enumerate(futures):
                if future.result():
                    success_count += 1
                pct = (i + 1) / total
                self.after(0, lambda i=i: self.lbl_status.configure(text=f"Processed {i+1}/{total}..."))
                self.after(0, self.progress_bar.set, pct)

        self.after(0, lambda: messagebox.showinfo(
            "Finished",
            f"Processed {success_count}/{total} links.\nJSON files are in the /json folder."
        ))
        self.after(0, self.reset_ui_after_work)

if __name__ == "__main__":
    ctk.set_appearance_mode("dark")
    initial_pkg = sys.argv[1] if len(sys.argv) > 1 else None
    app = PKGViewerApp(initial_filepath=initial_pkg)
    app.mainloop()