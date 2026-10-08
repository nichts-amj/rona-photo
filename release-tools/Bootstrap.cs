using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Web.Script.Serialization;
using System.Windows.Forms;

[assembly:System.Reflection.AssemblyVersion("1.3.0.0")]
class Bootstrap : Form {
    readonly string root = AppDomain.CurrentDomain.BaseDirectory;
    readonly Label status = new Label { Left=24,Top=75,Width=510,Height=100 };
    readonly ProgressBar progress = new ProgressBar { Left=24,Top=178,Width=510,Visible=false,Style=ProgressBarStyle.Marquee };
    readonly Button setup = new Button { Left=24,Top=220,Width=160,Height=36,Text="Siapkan komponen" };
    Process installer;
    [STAThread] static void Main() {
        Application.EnableVisualStyles(); Application.SetCompatibleTextRenderingDefault(false);
        Application.Run(new Bootstrap());
    }
    Bootstrap() {
        Text="Rona Photo · Persiapan"; ClientSize=new Size(560,285); StartPosition=FormStartPosition.CenterScreen;
        FormBorderStyle=FormBorderStyle.FixedDialog; MaximizeBox=false;
        BackColor=Color.FromArgb(232,240,227); ForeColor=Color.FromArgb(32,67,60);
        Font=new Font("Segoe UI",10);
        if(File.Exists(Path.Combine(root,"rona.ico"))) Icon=new Icon(Path.Combine(root,"rona.ico"));
        Controls.Add(new Label { Text="Rona Photo",Font=new Font("Georgia",24),Left=24,Top=20,Width=500,Height=48 });
        Controls.Add(status);Controls.Add(progress);Controls.Add(setup);
        setup.Click += (s,e)=>Install();
        Shown += (s,e)=>Check();
        FormClosing += (s,e)=>{if(installer!=null&&!installer.HasExited) { try{installer.Kill();}catch{} }};
    }
    void Check() {
        try {
            var manifest=new JavaScriptSerializer().Deserialize<Dictionary<string,object>>(File.ReadAllText(Path.Combine(root,"components.json")));
            long missing=0;
            foreach(Dictionary<string,object> component in (object[])manifest["components"]) {
                if(File.Exists(Path.Combine(root,".components",(string)component["id"]+".ready")))continue;
                foreach(Dictionary<string,object> asset in (object[])component["assets"])
                    if(!File.Exists(Path.Combine(root,(string)asset["name"])))missing+=Convert.ToInt64(asset["bytes"]);
            }
            bool ready=true;
            foreach(Dictionary<string,object> component in (object[])manifest["components"])
                ready &= File.Exists(Path.Combine(root,".components",(string)component["id"]+".ready"));
            if(ready&&File.Exists(Path.Combine(root,"Rona Photo Core.exe"))) { Open();return; }
            status.Text="Siapkan runtime dan model sebelum penggunaan pertama.\nPerkiraan unduhan: "+(missing/1e9).ToString("0.00")+" GB.\nZIP lokal dipakai tanpa unduhan. Setelah lengkap, aplikasi berjalan offline.";
        }catch(Exception error){status.Text="Manifest komponen belum tersedia: "+error.Message;setup.Enabled=false;}
    }
    void Install() {
        setup.Enabled=false;progress.Visible=true;
        var info=new ProcessStartInfo("powershell.exe","-NoProfile -ExecutionPolicy Bypass -File \""+Path.Combine(root,"install-components.ps1")+"\" -Root \""+root.TrimEnd('\\')+"\"") {
            WorkingDirectory=root,UseShellExecute=false,CreateNoWindow=true,RedirectStandardOutput=true,RedirectStandardError=true
        };
        installer=new Process {StartInfo=info,EnableRaisingEvents=true};
        installer.OutputDataReceived+=(s,e)=>{if(e.Data!=null&&!IsDisposed)BeginInvoke((Action)(()=>status.Text=e.Data));};
        installer.ErrorDataReceived+=(s,e)=>{if(e.Data!=null&&!IsDisposed)BeginInvoke((Action)(()=>status.Text=e.Data));};
        installer.Exited+=(s,e)=>{if(!IsDisposed)BeginInvoke((Action)(()=>{progress.Visible=false;setup.Enabled=true;if(installer.ExitCode==0)Open();}));};
        try{installer.Start();installer.BeginOutputReadLine();installer.BeginErrorReadLine();}
        catch(Exception error){status.Text=error.Message;setup.Enabled=true;progress.Visible=false;}
    }
    void Open(){Process.Start(new ProcessStartInfo(Path.Combine(root,"Rona Photo Core.exe")){WorkingDirectory=root,UseShellExecute=true});Close();}
}
