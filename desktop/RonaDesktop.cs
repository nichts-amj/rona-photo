using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.IO;
using System.Net;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

[assembly: System.Reflection.AssemblyTitle("Rona Photo")]
[assembly: System.Reflection.AssemblyVersion("1.0.0.0")]
[assembly: System.Runtime.Versioning.TargetFramework(".NETFramework,Version=v4.8")]

class RonaDesktop : Form {
    const string WindowTitle = "Rona Photo · Studio";
    readonly string root, profile, preferences;
    readonly JavaScriptSerializer json = new JavaScriptSerializer();
    readonly SplashPanel splash;
    readonly Button retry, exitSplash;
    readonly ToolTip actionTips = new ToolTip();
    WebView2 view;
    Process worker;
    string url, stopKey;
    bool owned, closing, starting, pageReady, closeRequest;
    TaskCompletionSource<bool> backendReady;
    readonly System.Windows.Forms.Timer animation = new System.Windows.Forms.Timer();
    [DllImport("user32.dll")] static extern IntPtr FindWindow(string cls, string title);
    [DllImport("user32.dll")] static extern bool SetForegroundWindow(IntPtr handle);
    [DllImport("user32.dll")] static extern bool ShowWindow(IntPtr handle, int command);
    [DllImport("user32.dll")] static extern IntPtr GetThreadDpiAwarenessContext();
    [DllImport("user32.dll")] [return: MarshalAs(UnmanagedType.Bool)]
    static extern bool AreDpiAwarenessContextsEqual(IntPtr first, IntPtr second);
    [DllImport("user32.dll", SetLastError = true)] [return: MarshalAs(UnmanagedType.Bool)]
    static extern bool SetProcessDpiAwarenessContext(IntPtr context);

    [STAThread] static void Main(string[] args) {
        // The embedded manifest normally sets this before Main. Keep a startup
        // fallback before WinForms, splash, WebView, or any HWND is created.
        IntPtr perMonitor = new IntPtr(-4);
        if (!AreDpiAwarenessContextsEqual(GetThreadDpiAwarenessContext(), perMonitor)) {
            if (!SetProcessDpiAwarenessContext(perMonitor))
                throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error(), "Per-Monitor V2 tidak dapat diaktifkan.");
        }
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        string project = Path.GetFullPath(Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "../.."));
        if (args.Length > 0 && args[0] == "--check-dpi") {
            bool perMonitorV2 = AreDpiAwarenessContextsEqual(GetThreadDpiAwarenessContext(), new IntPtr(-4));
            File.WriteAllText(Path.Combine(project, "desktop", "dpi-check.json"),
                "{\"perMonitorV2\":" + (perMonitorV2 ? "true" : "false") + ",\"checkedBeforeWindowCreation\":true}");
            Environment.ExitCode = perMonitorV2 ? 0 : 1;
            return;
        }
        if (args.Length > 0 && args[0] == "--render-splash") {
            using (var panel = new SplashPanel(project, false)) {
                panel.Size = new Size(900, 540);
                string state = args.Length > 1 ? args[1] : "startup";
                if (state == "error") {
                    panel.Status = "Halaman utama belum siap. Coba lagi."; panel.ShowLoading = false;
                    panel.Controls.Add(new SplashAction(false) { Location = new Point(404, 460) });
                    panel.Controls.Add(new SplashAction(true) { Location = new Point(456, 460) });
                } else if (state == "closing") { panel.Status = "Menutup Rona Photo…"; panel.Phase = .25f; }
                using (var bitmap = new Bitmap(900, 540)) {
                    panel.DrawToBitmap(bitmap, new Rectangle(0, 0, 900, 540));
                    bitmap.Save(Path.Combine(project, "desktop", state == "startup" ? "splash-preview.png" : "splash-" + state + "-preview.png"));
                }
            }
            return;
        }
        bool first;
        using (var mutex = new Mutex(true, "Local\\RonaPhotoDesktop-" + ProjectId(project), out first)) {
            if (!first) {
                IntPtr existing = FindWindow(null, WindowTitle);
                if (existing != IntPtr.Zero) { ShowWindow(existing, 9); SetForegroundWindow(existing); }
                return;
            }
            try { Application.Run(new RonaDesktop(project)); }
            catch (Exception error) { MessageBox.Show(error.Message, "Rona Photo", MessageBoxButtons.OK, MessageBoxIcon.Error); }
        }
    }

    static string ProjectId(string path) {
        using (var hash = SHA256.Create()) return BitConverter.ToString(hash.ComputeHash(Encoding.UTF8.GetBytes(path.ToLowerInvariant()))).Replace("-", "").Substring(0, 16);
    }

    public RonaDesktop(string project) {
        root = project;
        profile = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Rona Photo", "WebView", ProjectId(root));
        Directory.CreateDirectory(profile);
        preferences = Path.Combine(profile, "theme.txt");
        bool night = File.Exists(preferences) && File.ReadAllText(preferences).Trim() == "night";
        Text = WindowTitle; ClientSize = new Size(900, 540); MinimumSize = new Size(640, 420);
        StartPosition = FormStartPosition.CenterScreen; AutoScaleMode = AutoScaleMode.Dpi;
        Icon = new Icon(Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "rona.ico"));
        splash = new SplashPanel(root, night) { Dock = DockStyle.Fill };
        Controls.Add(splash);
        retry = new SplashAction(false) { Visible = false, AccessibleName = "Coba lagi" };
        exitSplash = new SplashAction(true) { Visible = false, AccessibleName = "Tutup aplikasi" };
        splash.Controls.Add(retry); splash.Controls.Add(exitSplash);
        actionTips.SetToolTip(retry, "Coba lagi"); actionTips.SetToolTip(exitSplash, "Tutup aplikasi");
        splash.Resize += (s, e) => LayoutSplashActions();
        LayoutSplashActions();
        retry.Click += async (s, e) => await StartDesktop();
        exitSplash.Click += (s, e) => Close();
        animation.Interval = 40;
        animation.Tick += (s, e) => { splash.Phase = (splash.Phase + 0.018f) % 1; splash.Invalidate(); };
        Shown += async (s, e) => await StartDesktop();
        FormClosing += OnClosing;
    }

    void LayoutSplashActions() {
        int gap = 12, width = retry.Width + exitSplash.Width + gap;
        int left = (splash.ClientSize.Width - width) / 2, top = splash.ClientSize.Height - 80;
        retry.Location = new Point(left, top);
        exitSplash.Location = new Point(left + retry.Width + gap, top);
    }

    void Stage(string text) { if (!IsDisposed) { splash.Status = text; splash.Invalidate(); } }
    void Fail(string text) {
        if (closing || closeRequest || IsDisposed) return;
        animation.Stop(); splash.Visible = true; splash.BringToFront();
        splash.ShowLoading = false;
        Stage(text); retry.Visible = true; exitSplash.Visible = true; starting = false;
        LayoutSplashActions();
        File.AppendAllText(Path.Combine(profile, "startup.log"), DateTime.Now + " " + text + Environment.NewLine);
    }
    void OnUi(Action action) { if (!IsDisposed && IsHandleCreated) BeginInvoke(action); }

    async Task StartDesktop() {
        if (starting || closing || closeRequest) return;
        starting = true; pageReady = false; retry.Visible = false; exitSplash.Visible = false;
        splash.ShowLoading = true; animation.Start();
        try {
            if (owned && worker != null && worker.HasExited) { url = null; stopKey = null; owned = false; }
            Stage("Memeriksa WebView2…");
            CoreWebView2Environment.GetAvailableBrowserVersionString();
            if (url == null) {
                Stage("Menyiapkan aplikasi…");
                backendReady = new TaskCompletionSource<bool>();
                var info = new ProcessStartInfo(Path.Combine(root, ".venv", "Scripts", "python.exe"), "-B \"" + Path.Combine(root, "desktop", "backend.py") + "\"") {
                    WorkingDirectory = root, UseShellExecute = false, CreateNoWindow = true,
                    RedirectStandardOutput = true, RedirectStandardError = true,
                    StandardOutputEncoding = Encoding.UTF8, StandardErrorEncoding = Encoding.UTF8
                };
                info.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8";
                worker = new Process { StartInfo = info, EnableRaisingEvents = true };
                worker.OutputDataReceived += (s, e) => {
                    if (e.Data == null) return;
                    try {
                        var data = json.Deserialize<Dictionary<string, object>>(e.Data);
                        string kind = Convert.ToString(data["kind"]);
                        if (kind == "stage") OnUi(() => Stage(Convert.ToString(data["text"])));
                        else if (kind == "ready") {
                            url = Convert.ToString(data["url"]); owned = Convert.ToBoolean(data["owned"]);
                            stopKey = data.ContainsKey("key") ? Convert.ToString(data["key"]) : null;
                            backendReady.TrySetResult(true);
                        } else if (kind == "error") backendReady.TrySetException(new Exception(Convert.ToString(data["text"])));
                    } catch (Exception error) { OnUi(() => Stage("Menyiapkan aplikasi…")); Debug.WriteLine(error); }
                };
                worker.ErrorDataReceived += (s, e) => { if (e.Data != null) Debug.WriteLine(e.Data); };
                worker.Exited += async (s, e) => {
                    await Task.Delay(500); // Let redirected output finish before inspecting the handshake.
                    if (url == null) backendReady.TrySetException(new Exception("Server berhenti saat startup. Coba jalankan ulang aplikasi."));
                    else if (owned && !closing && !closeRequest) OnUi(() => Fail("Server lokal berhenti. Tutup dan jalankan ulang Rona Photo."));
                };
                worker.Start(); worker.BeginOutputReadLine(); worker.BeginErrorReadLine();
                if (await Task.WhenAny(backendReady.Task, Task.Delay(180000)) != backendReady.Task) {
                    if (!worker.HasExited) worker.Kill();
                    throw new Exception("Startup terlalu lama. Coba lagi atau periksa jalur browser.");
                }
                try { await backendReady.Task; }
                catch { if (worker != null && !worker.HasExited && url == null) worker.Kill(); throw; }
            }
            if (closing || closeRequest || IsDisposed) return;
            Stage("Membuka ruang kerja…");
            if (view != null) { Controls.Remove(view); view.Dispose(); }
            view = new WebView2 { Dock = DockStyle.Fill, DefaultBackgroundColor = Color.FromArgb(12, 20, 24) };
            Controls.Add(view); splash.BringToFront();
            var environment = await CoreWebView2Environment.CreateAsync(null, profile);
            await view.EnsureCoreWebView2Async(environment);
            view.CoreWebView2.Settings.AreDevToolsEnabled = false;
            view.CoreWebView2.Settings.IsStatusBarEnabled = false;
            view.CoreWebView2.DownloadStarting += Download;
            view.CoreWebView2.NavigationStarting += (s, e) => {
                if (!LocalAddress(e.Uri)) {
                    e.Cancel = true;
                    if (e.IsUserInitiated) OpenExternal(e.Uri);
                }
            };
            view.CoreWebView2.NewWindowRequested += (s, e) => {
                e.Handled = true;
                if (LocalAddress(e.Uri)) view.CoreWebView2.Navigate(e.Uri);
                else if (e.IsUserInitiated) OpenExternal(e.Uri);
            };
            view.CoreWebView2.NavigationCompleted += (s, e) => {
                if (!e.IsSuccess && !pageReady) Fail("Halaman belum dapat dibuka: " + e.WebErrorStatus + ". Coba lagi.");
            };
            view.CoreWebView2.ProcessFailed += (s, e) => Fail("WebView berhenti: " + e.ProcessFailedKind + ". Coba lagi.");
            view.CoreWebView2.WebMessageReceived += (s, e) => {
                if (!LocalAddress(e.Source)) return;
                string message;
                try { message = e.TryGetWebMessageAsString(); } catch { return; }
                if (message == "rona-ready" && !pageReady) {
                    pageReady = true; starting = false; animation.Stop(); splash.Visible = false;
                    Size work = Screen.FromControl(this).WorkingArea.Size;
                    Size = new Size(Math.Min(1440, work.Width), Math.Min(960, work.Height));
                    CenterToScreen(); view.Focus();
                } else if (message.StartsWith("rona-theme:")) {
                    string theme = message.Substring(11);
                    if (theme == "day" || theme == "night") File.WriteAllText(preferences, theme);
                } else if (message == "rona-start-error") Fail("Halaman utama belum siap. Coba lagi.");
            };
            // The existing UI stays untouched; this bridge only signals first paint and theme preference.
            await view.CoreWebView2.AddScriptToExecuteOnDocumentCreatedAsync(@"
                (()=>{document.addEventListener('DOMContentLoaded',async()=>{
                  const notify=()=>chrome.webview.postMessage('rona-theme:'+document.documentElement.dataset.theme);
                  new MutationObserver(notify).observe(document.documentElement,{attributes:true,attributeFilter:['data-theme']});notify();
                  if(location.pathname!=='/')return;
                  try{
                    const r=await fetch('/api/bootstrap');const data=await r.json();if(!r.ok||data.app!=='rona-studio')throw Error();
                    await document.fonts.ready;
                    const night=document.documentElement.dataset.theme==='night';
                    await new Promise((resolve,reject)=>{const im=new Image();im.onload=resolve;im.onerror=reject;im.src=night?'/launcher-valley-night.png':'/launcher-valley.png';});
                    requestAnimationFrame(()=>requestAnimationFrame(()=>chrome.webview.postMessage('rona-ready')));
                  }catch{chrome.webview.postMessage('rona-start-error')}
                },{once:true})})();");
            view.CoreWebView2.Navigate(url + "/");
        } catch (WebView2RuntimeNotFoundException) {
            Fail("WebView2 Runtime belum terpasang. Pasang runtime Microsoft atau gunakan start-studio.cmd.");
        } catch (Exception error) { Fail(error.Message); }
    }

    bool LocalAddress(string address) {
        Uri uri, origin;
        return Uri.TryCreate(address, UriKind.Absolute, out uri) && Uri.TryCreate(url, UriKind.Absolute, out origin)
            && uri.Scheme == origin.Scheme && uri.Host == origin.Host && uri.Port == origin.Port;
    }
    static void OpenExternal(string address) {
        Uri uri;
        if (Uri.TryCreate(address, UriKind.Absolute, out uri) && (uri.Scheme == "https" || uri.Scheme == "http"))
            Process.Start(new ProcessStartInfo(address) { UseShellExecute = true });
    }
    void Download(object sender, CoreWebView2DownloadStartingEventArgs e) {
        var deferral = e.GetDeferral();
        try {
            e.Handled = true;
            using (var dialog = new SaveFileDialog { FileName = Path.GetFileName(e.ResultFilePath), Title = "Simpan hasil Rona Photo", OverwritePrompt = true, RestoreDirectory = true }) {
                if (dialog.ShowDialog(this) == DialogResult.OK) e.ResultFilePath = dialog.FileName;
                else e.Cancel = true;
            }
        } finally { deferral.Complete(); }
    }
    async void OnClosing(object sender, FormClosingEventArgs e) {
        if (closing) return;
        e.Cancel = true;
        if (closeRequest) return;
        closeRequest = true;
        bool previousSplash = splash.Visible, previousError = retry.Visible;
        string previousStatus = splash.Status;
        retry.Visible = false; exitSplash.Visible = false;
        if (view != null) view.Enabled = false;
        splash.ShowLoading = true; splash.Phase = .25f;
        Stage("Menutup Rona Photo…"); splash.Visible = true; splash.BringToFront();
        animation.Start(); splash.Update();
        try {
            await Task.Yield();
            if (starting && url == null) {
                if (worker != null && !worker.HasExited) {
                    worker.Kill();
                    await Task.Run(() => worker.WaitForExit(5000));
                }
            } else if (owned && worker != null && !worker.HasExited) {
                using (var client = new WebClient()) {
                    client.Headers["X-Desktop-Key"] = stopKey;
                    await client.UploadDataTaskAsync(new Uri(url + "/api/desktop/stop"), "POST", new byte[0]);
                }
                await Task.Run(() => worker.WaitForExit(10000));
            }
            closing = true; animation.Stop(); Close();
        } catch (Exception) {
            animation.Stop(); splash.Visible = previousSplash;
            splash.ShowLoading = !previousError; Stage(previousStatus);
            retry.Visible = previousError; exitSplash.Visible = previousError;
            if (view != null) { view.Enabled = true; if (!previousSplash) view.Focus(); }
            if (previousSplash && !previousError) animation.Start();
            MessageBox.Show("Tunggu pemrosesan selesai atau Cancel proses sebelum menutup aplikasi. Jika server tidak merespons, coba lagi setelah beberapa saat.", "Rona Photo", MessageBoxButtons.OK, MessageBoxIcon.Information);
        } finally { closeRequest = false; }
    }
    protected override void Dispose(bool disposing) {
        if (disposing) { animation.Dispose(); actionTips.Dispose(); if (worker != null) worker.Dispose(); }
        base.Dispose(disposing);
    }
}

class SplashPanel : Panel {
    readonly Image wallpaper;
    public string Status = "Menyiapkan aplikasi…";
    public float Phase;
    public bool ShowLoading = true;
    public SplashPanel(string root, bool night) {
        DoubleBuffered = true;
        wallpaper = Image.FromFile(Path.Combine(root, "web", night ? "launcher-valley-night.png" : "launcher-valley.png"));
    }
    protected override void OnPaint(PaintEventArgs e) {
        base.OnPaint(e); var g = e.Graphics; g.SmoothingMode = SmoothingMode.AntiAlias;
        float ratio = Math.Max((float)Width / wallpaper.Width, (float)Height / wallpaper.Height);
        var rectangle = new RectangleF((Width - wallpaper.Width * ratio) / 2, (Height - wallpaper.Height * ratio) / 2, wallpaper.Width * ratio, wallpaper.Height * ratio);
        g.DrawImage(wallpaper, rectangle);
        using (var overlay = new SolidBrush(Color.FromArgb(155, 4, 19, 23))) g.FillRectangle(overlay, ClientRectangle);
        float cx = Width / 2f, cy = Height * .37f;
        using (var mark = new SolidBrush(Color.FromArgb(221, 236, 203))) {
            g.FillPolygon(mark, Star(cx, cy, 31)); g.FillPolygon(mark, Star(cx + 40, cy - 28, 10));
        }
        using (var title = new Font("Georgia", 34, FontStyle.Regular))
        using (var status = new Font("Segoe UI", 10))
        using (var white = new SolidBrush(Color.White))
        using (var soft = new SolidBrush(Color.FromArgb(220, 229, 234)))
        using (var format = new StringFormat { Alignment = StringAlignment.Center, LineAlignment = StringAlignment.Center }) {
            g.DrawString("Rona Photo", title, white, new RectangleF(20, cy + 35, Width - 40, 65), format);
            g.DrawString(Status, status, soft, new RectangleF(40, Height - 144, Width - 80, 55), format);
        }
        if (!ShowLoading) return;
        int track = Math.Min(310, Width - 100), y = Height - 85;
        using (var faint = new SolidBrush(Color.FromArgb(65, 255, 255, 255))) g.FillRectangle(faint, cx - track / 2, y, track, 3);
        using (var bright = new SolidBrush(Color.FromArgb(220, 235, 211))) {
            var clip = g.Save(); g.SetClip(new RectangleF(cx - track / 2, y, track, 3));
            g.FillRectangle(bright, cx - track / 2 + Phase * (track + 90) - 90, y, 90, 3); g.Restore(clip);
        }
    }
    static PointF[] Star(float x, float y, float radius) {
        return new[] { new PointF(x, y-radius), new PointF(x+radius*.28f,y-radius*.28f), new PointF(x+radius,y), new PointF(x+radius*.28f,y+radius*.28f), new PointF(x,y+radius), new PointF(x-radius*.28f,y+radius*.28f), new PointF(x-radius,y), new PointF(x-radius*.28f,y-radius*.28f) };
    }
    protected override void Dispose(bool disposing) { if (disposing) wallpaper.Dispose(); base.Dispose(disposing); }
}

class SplashAction : Button {
    readonly bool closeIcon;
    public SplashAction(bool close) {
        closeIcon = close; Size = new Size(40, 40); Cursor = Cursors.Hand;
        FlatStyle = FlatStyle.Flat; FlatAppearance.BorderSize = 0;
        BackColor = Color.FromArgb(28, 47, 48); ForeColor = Color.White;
        SetStyle(ControlStyles.UserPaint | ControlStyles.OptimizedDoubleBuffer | ControlStyles.AllPaintingInWmPaint, true);
    }
    protected override void OnPaint(PaintEventArgs e) {
        var g = e.Graphics; g.SmoothingMode = SmoothingMode.AntiAlias;
        using (var fill = new SolidBrush(BackColor)) g.FillEllipse(fill, 1, 1, Width - 2, Height - 2);
        using (var line = new Pen(ForeColor, 1.8f)) {
            float x = Width / 2f, y = Height / 2f;
            if (closeIcon) {
                g.DrawLine(line, x-6, y-6, x+6, y+6); g.DrawLine(line, x+6, y-6, x-6, y+6);
            } else {
                g.DrawArc(line, x-8, y-8, 16, 16, -45, 290);
                g.DrawLines(line, new[] { new PointF(x+2,y-9), new PointF(x+7,y-6), new PointF(x+8,y-12) });
            }
            if (Focused) { line.Color = Color.FromArgb(155, ForeColor); g.DrawEllipse(line, 3, 3, Width-6, Height-6); }
        }
    }
}
