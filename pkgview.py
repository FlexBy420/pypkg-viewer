#!/usr/bin/env python3
import os
import sys
import struct
import threading
import hashlib
import customtkinter as ctk
from tkinter import ttk, filedialog, messagebox
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend

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

PKG_PS3_AES_KEY = bytes.fromhex("2E7B71D7C9C9A14EA3221F188828B8F8")
PKG_PS3_IDU_AES_KEY = bytes.fromhex("5DB911E6B7E50A7D321538FD7C66F17B")
PKG_PSP_AES_KEY = bytes.fromhex("07F2C68290B50D2C33818D709B60E62B")
PKG_PSP_IDU_AES_KEY = bytes.fromhex("7547EE76CA8C55AC1BA8D22535E05593")
PKG_PSP2_AES_KEY = bytes.fromhex("E31A70C9CE1DD72BF3C0622963F2ECCB") # psp2 is internal name for vita
PKG_PSP2_LIVEAREA_AES_KEY = bytes.fromhex("423ACA3A2BD5649F9686ABAD6FD8801F")
PKG_PSM_AES_KEY = bytes.fromhex("AF07FD59652527BAF13389668B17D9EA")
PKG_FILE_ENTRY_PSP = 0x10000000

PKG_RELEASE_TYPE_DEBUG = 0x0000
PKG_RELEASE_TYPE_RELEASE = 0x8000

PKG_PLATFORM_TYPE_PS3 = 0x0001
PKG_PLATFORM_TYPE_PSP_PSVITA = 0x0002

def get_debug_keystream_block(qa_digest, block_index):
    qa_0 = qa_digest[0:8]
    qa_1 = qa_digest[8:16]
    buffer = bytearray(64)
    buffer[0:8]   = qa_0 # input[0]
    buffer[8:16]  = qa_0 # input[1]
    buffer[16:24] = qa_1 # input[2]
    buffer[24:32] = qa_1 # input[3]
    buffer[56:64] = struct.pack(">Q", block_index)

    return hashlib.sha1(buffer).digest()[:16]

def decrypt_data_blocks(file, data_offset, relative_offset, size, key, klicensee, pkg_type, qa_digest):
    if size <= 0: return b""
    block_offset = relative_offset // 16
    byte_offset = relative_offset % 16
    num_blocks = (byte_offset + size + 15) // 16

    file.seek(data_offset + block_offset * 16)
    encrypted = file.read(num_blocks * 16)

    if pkg_type == PKG_RELEASE_TYPE_DEBUG:
        decrypted = bytearray()
        for i in range(num_blocks):
            keystream = get_debug_keystream_block(qa_digest, block_offset + i)
            chunk = encrypted[i * 16 : (i + 1) * 16]
            decrypted.extend(a ^ b for a, b in zip(chunk, keystream))
        return bytes(decrypted)[byte_offset : byte_offset + size]
    else:
        klic_int = int.from_bytes(klicensee, byteorder='big')
        nonce = ((klic_int + block_offset) % (1 << 128)).to_bytes(16, byteorder='big')
        cipher = Cipher(algorithms.AES(key), modes.CTR(nonce), backend=default_backend())
        decryptor = cipher.decryptor()
        decrypted = decryptor.update(encrypted) + decryptor.finalize()
        
    return decrypted[byte_offset : byte_offset + size]

class PKGViewerApp(DragDropCTk):
    def __init__(self, initial_filepath=None):
        super().__init__()
        self.title("PKG Viewer")
        self.geometry("1000x820")
        self.current_pkg_path = None
        self.klicensee = None
        self.qa_digest = None
        self.pkg_type = None
        self.data_offset = 0
        self.file_entries = {}
        self.setup_ui()
        self.current_folder_name = "Extracted_PKG"

        if HAS_DND:
            self.drop_target_register(DND_FILES)
            self.dnd_bind('<<Drop>>', self.handle_drop)

        if initial_filepath and os.path.exists(initial_filepath):
            self.current_pkg_path = initial_filepath
            self.lbl_filepath.configure(text=os.path.basename(self.current_pkg_path), text_color="white")
            self.after(100, self.load_pkg)

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

        self.tabs = ctk.CTkTabview(self)
        self.tabs.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.tab_files = self.tabs.add("Content")
        self.tab_info = self.tabs.add("Information")
        self.setup_files_tab()
        self.setup_info_tab()

    def setup_files_tab(self):
        tree_frame = ctk.CTkFrame(self.tab_files)
        tree_frame.pack(fill="both", expand=True, padx=5, pady=5)

        style = ttk.Style()
        style.theme_use("default")
        style.layout("Treeview", [('Treeview.treearea', {'sticky': 'nswe'})])
        style.configure("Treeview", background="#2b2b2b", foreground="white", fieldbackground="#2b2b2b", borderwidth=0, rowheight=25)
        style.map('Treeview', background=[('selected', '#1f538d')])
        style.configure("Treeview.Heading", background="#383737", foreground="white", relief="flat")
        style.map("Treeview.Heading", background=[('active', '#1f538d')])

        self.tree = ttk.Treeview(tree_frame, columns=("Size", "Type"), show="tree headings")
        self.tree.heading("#0", text="Files", anchor="center")
        self.tree.heading("Size", text="Size", anchor="center")
        self.tree.heading("Type", text="Type", anchor="center")
        self.tree.column("#0", width=600)
        self.tree.column("Size", width=120, anchor="center")
        self.tree.column("Type", width=100, anchor="center")

        scrollbar = ctk.CTkScrollbar(tree_frame, command=self.tree.yview)
        self.tree.configure(yscrollcommand=lambda f, l: self.autohide_scrollbar(scrollbar, f, l))
        self.tree.pack(side="left", fill="both", expand=True)

        # Status & Progress Frame
        status_frame = ctk.CTkFrame(self.tab_files)
        status_frame.pack(fill="x", padx=10, pady=5)

        self.lbl_status = ctk.CTkLabel(status_frame, text="Ready")
        self.lbl_status.pack(side="left", padx=10)

        self.progress_bar = ctk.CTkProgressBar(status_frame)
        self.progress_bar.pack(side="right", fill="x", expand=True, padx=10)
        self.progress_bar.set(0)

        action_frame = ctk.CTkFrame(self.tab_files)
        action_frame.pack(fill="x", pady=5)
        self.btn_extract_sel = ctk.CTkButton(action_frame, text="Extract Highlighted", command=self.extract_selected, state="disabled")
        self.btn_extract_sel.pack(side="right", padx=10, pady=5)
        self.btn_extract_all = ctk.CTkButton(action_frame, text="Extract All", command=self.extract_all, state="disabled")
        self.btn_extract_all.pack(side="right", padx=5, pady=5)

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
            # Header: magic, version, key_table_start, data_table_start, num_entries
            key_ptr, data_ptr, count = struct.unpack('<I I I', data[8:20])
            entries = []
            for i in range(count):
                # key_off(2), fmt(2), len(4), max(4), data_off(4)
                entries.append(struct.unpack('<H H I I I', data[20 + i*16 : 36 + i*16]))

            sfo_dict = {}
            for k_off, fmt, d_len, d_max, d_off in entries:
                k_start = key_ptr + k_off
                k_end = data.find(b'\x00', k_start)
                key = data[k_start:k_end].decode('utf-8', errors='ignore')

                v_start = data_ptr + d_off
                val_raw = data[v_start : v_start + d_len]

                if fmt == 0x0204:
                    sfo_dict[key] = val_raw.decode('utf-8', errors='ignore').strip('\x00')
                elif fmt == 0x0404:
                    sfo_dict[key] = struct.unpack('<I', val_raw)[0]
                else:
                    sfo_dict[key] = val_raw
            return sfo_dict
        except:
            return {}

    def format_size(self, size):
        if size >= 1073741824:
            return f"{size} ({size / 1073741824:.2f} GB)"
        elif size >= 1048576:
            return f"{size} ({size / 1048576:.2f} MB)"
        elif size >= 1024:
            return f"{size} ({size / 1024:.2f} KB)"
        else:
            return f"{size} ({size} B)"

    def open_file(self):
        path = filedialog.askopenfilename(filetypes=[("PKG", ("*.pkg", "*.PKG"))])
        if path:
            self.current_pkg_path = path
            self.lbl_filepath.configure(text=os.path.basename(path), text_color="white")
            self.load_pkg()

    def load_pkg(self):
        for i in self.tree.get_children(): self.tree.delete(i)
        self.info_text.delete("0.0", "end")
        self.file_entries = {}

        try:
            with open(self.current_pkg_path, 'rb') as f:
                header_fmt = '> 4s H H I I I I Q Q Q 48s 16s 16s'
                header = struct.unpack(header_fmt, f.read(struct.calcsize(header_fmt)))

                if header[0] != b'\x7FPKG': raise ValueError("Invalid PKG")

                self.pkg_type = header[1]
                pkg_platform = header[2]
                meta_offset = header[3]
                meta_count = header[4]
                file_count = header[6]
                pkg_size = header[7]
                self.data_offset = header[8]
                content_id = header[10].decode('ascii', errors='ignore').strip('\x00')
                self.current_folder_name = content_id
                self.qa_digest = header[11]
                self.klicensee = header[12]

                npdrm_version = "N/A"
                f.seek(meta_offset)
                for _ in range(meta_count):
                    meta_id, meta_size = struct.unpack('>I I', f.read(8))
                    meta_data = f.read(meta_size)
                    if meta_id == 0x05 and meta_size >= 4:
                        npdrm_version = meta_data[:2].hex()

                entry_size = 32
                raw_table = None
                used_key_name = ""

                if self.pkg_type == PKG_RELEASE_TYPE_DEBUG:
                    candidate = decrypt_data_blocks(f, self.data_offset, 0, file_count * entry_size, None, self.klicensee, self.pkg_type, self.qa_digest)
                    if file_count > 0:
                        n_off, n_sz, _, _, _, _ = struct.unpack('>I I Q Q I I', candidate[:32])
                        if n_sz < 256:
                            raw_table = candidate
                            used_key_name = "Debug"
                else:
                    potential_keys = [(PKG_PS3_AES_KEY, "PS3 Retail"), (PKG_PS3_IDU_AES_KEY, "PS3 IDU")]
                    if pkg_platform == PKG_PLATFORM_TYPE_PSP_PSVITA: 
                        potential_keys = [(PKG_PSP_AES_KEY, "PSP Retail"), (PKG_PSP_IDU_AES_KEY, "PSP IDU"), (PKG_PSP2_AES_KEY, "PS Vita Retail"), (PKG_PSP2_LIVEAREA_AES_KEY, "PS Vita Live Area")]

                    for key, kname in potential_keys:
                        candidate = decrypt_data_blocks(f, self.data_offset, 0, file_count * entry_size, key, self.klicensee, self.pkg_type, self.qa_digest)
                        if file_count > 0:
                            n_off, n_sz, _, _, _, _ = struct.unpack('>I I Q Q I I', candidate[:32])
                            if n_sz < 256: 
                                raw_table = candidate
                                used_key_name = kname
                                break

                if not raw_table: raise ValueError("Failed to decrypt file table.")

                folders = {}
                sfo_entry = None

                for i in range(file_count):
                    e_raw = raw_table[i*entry_size : (i+1)*entry_size]
                    n_off, n_sz, f_off, f_sz, f_type, _ = struct.unpack('>I I Q Q I I', e_raw)
                    if n_sz == 0: continue

                    key = None
                    if self.pkg_type == PKG_RELEASE_TYPE_RELEASE:
                        possible_keys = [
                            (PKG_PSP_IDU_AES_KEY if used_key_name == "PSP IDU" else PKG_PSP_AES_KEY),
                            (PKG_PS3_IDU_AES_KEY if used_key_name == "PS3 IDU" else PKG_PS3_AES_KEY),
                            (PKG_PSP2_LIVEAREA_AES_KEY if used_key_name == "Live Area" else PKG_PSP2_AES_KEY)
                        ]

                        for test_key in possible_keys:
                            name_raw = decrypt_data_blocks(f, self.data_offset, n_off, n_sz, test_key, self.klicensee, self.pkg_type, self.qa_digest)
                            try:
                                decoded_name = name_raw.decode('utf-8').strip('\x00')
                                if all(31 < ord(c) < 127 or c in "/._-" for c in decoded_name):
                                    key = test_key
                                    full_path = decoded_name.replace("\\", "/")
                                    break
                            except:
                                continue

                        if key is None:
                            key = possible_keys[0]
                            name_raw = decrypt_data_blocks(f, self.data_offset, n_off, n_sz, key, self.klicensee, self.pkg_type, self.qa_digest)
                            full_path = name_raw.decode('utf-8', errors='ignore').strip('\x00').replace("\\", "/")
                    else:
                        name_raw = decrypt_data_blocks(f, self.data_offset, n_off, n_sz, None, self.klicensee, self.pkg_type, self.qa_digest)
                        full_path = name_raw.decode('utf-8', errors='ignore').strip('\x00').replace("\\", "/")

                    parts = [p for p in full_path.split('/') if p]
                    parent = ""
                    for j, part in enumerate(parts):
                        current_path = "/".join(parts[:j+1])
                        is_last = (j == len(parts) - 1)

                        if current_path not in folders:
                            if is_last and (f_type & 0xFF) not in (4, 0x12):
                                sz_str = f"{f_sz/1048576:.2f} MB" if f_sz > 1048576 else f"{f_sz/1024:.1f} KB"
                                node = self.tree.insert(parent, "end", text=part, values=(sz_str, "File"))
                                entry_data = {'path': full_path, 'off': f_off, 'sz': f_sz, 'key': key}
                                self.file_entries[node] = entry_data
                                if full_path.endswith("PARAM.SFO"):
                                    sfo_entry = entry_data
                            else:
                                node = self.tree.insert(parent, "end", text=part, values=("", "Folder"))
                                folders[current_path] = node
                        if current_path in folders:
                            parent = folders[current_path]

                # PKG INFO
                pkg_info = f"PKG INFO:\n{'-'*50}\n"
                pkg_info += f"Content ID:    {content_id}\n"
                pkg_info += f"Platform:      {'PS3' if pkg_platform == PKG_PLATFORM_TYPE_PS3 else 'PSP/Vita'}\n"
                pkg_info += f"Release Type:  {'Debug' if self.pkg_type == PKG_RELEASE_TYPE_DEBUG else 'Retail'}\n"
                pkg_info += f"Package Size:  {self.format_size(pkg_size)}\n"
                pkg_info += f"NPDRM Version: {npdrm_version}\n"
                pkg_info += f"QA Digest:     {self.qa_digest.hex().upper()}\n"
                pkg_info += f"Klicensee:     {self.klicensee.hex().upper()}\n"
                pkg_info += f"Key Type:      {used_key_name}\n"
                pkg_info += f"File Count:    {file_count}\n\n"

                # SFO INFO
                sfo_info = f"SFO INFO:\n{'-'*50}\n"
                if sfo_entry:
                    sfo_data_raw = decrypt_data_blocks(f, self.data_offset, sfo_entry['off'], sfo_entry['sz'], sfo_entry['key'], self.klicensee, self.pkg_type, self.qa_digest)
                    sfo_meta = self.parse_sfo(sfo_data_raw)

                    title = sfo_meta.get("TITLE", "N/A")
                    title_id = sfo_meta.get("TITLE_ID", "N/A")
                    comm_id = sfo_meta.get("NP_COMMUNICATION_ID", "N/A")
                    version = sfo_meta.get("VERSION", "N/A")
                    app_ver = sfo_meta.get("APP_VER", "N/A")
                    fw_ver = sfo_meta.get("PS3_SYSTEM_VER", "N/A")
                    parent_lvl = sfo_meta.get("PARENTAL_LEVEL", "N/A")
                    category = sfo_meta.get("CATEGORY", "N/A")
                    sound_format = sfo_meta.get("SOUND_FORMAT", "N/A")
                    resolution = sfo_meta.get("RESOLUTION", "N/A")
                    attribute = sfo_meta.get("ATTRIBUTE", "N/A")
                    bootable = sfo_meta.get("BOOTABLE", "N/A")

                    sfo_info += f"Game Title:           {title}\n"
                    sfo_info += f"Title ID:             {title_id}\n"
                    sfo_info += f"Communication ID:     {comm_id}\n"
                    sfo_info += f"Version:              {version}\n"
                    sfo_info += f"App Version:          {app_ver}\n"
                    sfo_info += f"Firmware Version:     {fw_ver}\n"
                    sfo_info += f"Parental Level:       {parent_lvl}\n"
                    sfo_info += f"Category:             {category}\n"

                    self.title(f"PKG Viewer - {title}")
                else:
                    sfo_info += "PARAM.SFO not found or corrupted.\n"

                self.info_text.insert("end", pkg_info + sfo_info)

            self.btn_extract_all.configure(state="normal")
            self.btn_extract_sel.configure(state="normal")

        except Exception as e:
            messagebox.showerror("Error", f"Unable to open PKG: {str(e)}")

    def extract_file(self, pkg_f, entry, dest_dir, current_progress_callback=None):
        out_path = os.path.join(dest_dir, entry['path'].lstrip('/'))
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        klic_int = int.from_bytes(self.klicensee, byteorder='big')

        with open(out_path, 'wb') as out_f:
            remaining = entry['sz']
            curr_off = entry['off']
            chunk = 1024 * 1024
            while remaining > 0:
                to_read = min(remaining, chunk)
                block_off = curr_off // 16
                byte_off = curr_off % 16
                num_blocks = (byte_off + to_read + 15) // 16

                pkg_f.seek(self.data_offset + block_off * 16)
                enc = pkg_f.read(num_blocks * 16)

                if self.pkg_type == PKG_RELEASE_TYPE_DEBUG:
                    dec = bytearray()
                    for i in range(num_blocks):
                        keystream = get_debug_keystream_block(self.qa_digest, block_off + i)
                        c_chunk = enc[i * 16 : (i + 1) * 16]
                        dec.extend(a ^ b for a, b in zip(c_chunk, keystream))
                    dec = bytes(dec)
                elif self.pkg_type == PKG_RELEASE_TYPE_RELEASE:
                    nonce = ((klic_int + block_off) % (1 << 128)).to_bytes(16, 'big')
                    cipher = Cipher(algorithms.AES(entry['key']), modes.CTR(nonce), backend=default_backend())
                    dec = cipher.decryptor().update(enc)
                else:
                    dec = enc

                out_f.write(dec[byte_off : byte_off + to_read])

                remaining -= to_read
                curr_off += to_read
                if current_progress_callback:
                    current_progress_callback(to_read)

    def update_progress(self, bytes_done, total_bytes):
        percent = (bytes_done / total_bytes)
        self.progress_bar.set(percent)
        self.lbl_status.configure(text=f"Extracting: {int(percent * 100)}%")

    def extraction_worker(self, nodes_to_extract, dest, mode="all"):
        self.btn_extract_all.configure(state="disabled")
        self.btn_extract_sel.configure(state="disabled")
        self.btn_open.configure(state="disabled")

        try:
            entries = []
            if mode == "all":
                entries = list(self.file_entries.values())
            else:
                # helper to collect entries from nodes (files and subfolders)
                def collect(nodes):
                    for n in nodes:
                        if n in self.file_entries:
                            entries.append(self.file_entries[n])
                        collect(self.tree.get_children(n))
                collect(nodes_to_extract)

            total_size = sum(e['sz'] for e in entries)
            current_done = 0

            if total_size == 0:
                self.after(0, lambda: messagebox.showinfo("Info", "Nothing to extract."))
                return

            with open(self.current_pkg_path, 'rb') as f:
                for entry in entries:
                    def cb(chunk):
                        nonlocal current_done
                        current_done += chunk
                        self.after(0, self.update_progress, current_done, total_size)

                    self.extract_file(f, entry, dest, current_progress_callback=cb)

            self.after(0, lambda: messagebox.showinfo("Success", "Extraction finished successfully."))
        except Exception as e:
            self.after(0, lambda: messagebox.showerror("Error", str(e)))
        finally:
            self.after(0, self.reset_ui_after_work)

    def reset_ui_after_work(self):
        self.btn_extract_all.configure(state="normal")
        self.btn_extract_sel.configure(state="normal")
        self.btn_open.configure(state="normal")
        self.progress_bar.set(0)
        self.lbl_status.configure(text="Ready")

    def extract_selected(self):
        selection = self.tree.selection()
        if not selection: return
        dest = filedialog.askdirectory()
        if not dest: return
        dest = os.path.join(dest, self.current_folder_name)
        threading.Thread(target=self.extraction_worker, args=(selection, dest, "selected"), daemon=True).start()

    def _recursive_extract(self, f, node, dest):
        if node in self.file_entries:
            self.extract_file(f, self.file_entries[node], dest)
        else:
            for child in self.tree.get_children(node):
                self._recursive_extract(f, child, dest)

    def extract_all(self):
        dest = filedialog.askdirectory()
        if not dest: return
        dest = os.path.join(dest, self.current_folder_name)
        threading.Thread(target=self.extraction_worker, args=(None, dest, "all"), daemon=True).start()

if __name__ == "__main__":
    initial_pkg = sys.argv[1] if len(sys.argv) > 1 else None
    app = PKGViewerApp(initial_filepath=initial_pkg)
    app.mainloop()