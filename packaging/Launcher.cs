using System;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Threading.Tasks;
using System.Windows.Forms;
using System.Drawing;
[assembly:System.Reflection.AssemblyTitle("Rona Photo")]
[assembly:System.Reflection.AssemblyVersion("1.0.0.0")]
class Rona : Form {
 Process worker; Label status; Button open; bool closing=false; const string Url="http://127.0.0.1:8773"; string logs;
 [STAThread] static void Main(){Application.EnableVisualStyles();Application.Run(new Rona());}
 public Rona(){Text="Rona Photo v1.0";Size=new Size(450,220);StartPosition=FormStartPosition.CenterScreen;FormBorderStyle=FormBorderStyle.FixedDialog;MaximizeBox=false;BackColor=Color.FromArgb(246,247,242);
 string root=AppDomain.CurrentDomain.BaseDirectory;try{Icon=new Icon(Path.Combine(root,"rona.ico"));}catch{}
 status=new Label(){Text="Menyiapkan Rona Photo…",Left=24,Top=22,Width=390,Height=65};Controls.Add(status);
 open=new Button(){Text="Buka Studio",Left=24,Top=106,Width=125,Enabled=false};open.Click+=(s,e)=>Browser();Controls.Add(open);
 var stop=new Button(){Text="Tutup aplikasi",Left=165,Top=106,Width=120};stop.Click+=(s,e)=>Close();Controls.Add(stop);
 var log=new Button(){Text="Folder data",Left=299,Top=106,Width=110};log.Click+=(s,e)=>Process.Start("explorer.exe",Path.GetDirectoryName(logs));Controls.Add(log);
 logs=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"Rona Photo","startup.log");Directory.CreateDirectory(Path.GetDirectoryName(logs));
 Shown+=async(s,e)=>await Start(root);FormClosing+=(s,e)=>{if(worker!=null&&!worker.HasExited&&!closing){if(MessageBox.Show("Tutup server Rona Photo? Pastikan pemrosesan foto sudah selesai.","Rona Photo",MessageBoxButtons.YesNo,MessageBoxIcon.Question)!=DialogResult.Yes){e.Cancel=true;return;}closing=true;worker.Kill();}};
 }
 bool Ready(){try{using(var c=new WebClient()){return c.DownloadString(Url+"/api/bootstrap").Contains("\"product\": \"Rona Photo\"");}}catch{return false;}}
 void Browser(){Process.Start(new ProcessStartInfo(Url){UseShellExecute=true});}
 async Task Start(string root){try{
 if(await Task.Run(()=>Ready())){status.Text="Rona Photo sudah berjalan. Jendela ini dapat ditutup.";open.Enabled=true;Browser();return;}
 var psi=new ProcessStartInfo(Path.Combine(root,"runtime","python.exe"),"-I -B \""+Path.Combine(root,"app","portable_start.py")+"\""){WorkingDirectory=root,UseShellExecute=false,CreateNoWindow=true,RedirectStandardError=true,RedirectStandardOutput=true};
 File.WriteAllText(logs,DateTime.Now+" Rona Photo v1.0\r\n");worker=new Process(){StartInfo=psi};object sync=new object();DataReceivedEventHandler capture=(s,e)=>{if(e.Data!=null)lock(sync)File.AppendAllText(logs,e.Data+Environment.NewLine);};worker.OutputDataReceived+=capture;worker.ErrorDataReceived+=capture;worker.Start();worker.BeginOutputReadLine();worker.BeginErrorReadLine();
 for(int i=0;i<120;i++){if(worker.HasExited)throw new Exception("Aplikasi berhenti saat startup. Lihat startup.log di Folder data.");if(await Task.Run(()=>Ready())){status.Text="Studio siap. Biarkan jendela ini terbuka selama menggunakan aplikasi.";open.Enabled=true;Browser();return;}await Task.Delay(1000);}
 throw new Exception("Startup belum selesai. Lihat startup.log di Folder data.");
 }catch(Exception ex){status.Text=ex.Message;MessageBox.Show(ex.Message,"Rona Photo",MessageBoxButtons.OK,MessageBoxIcon.Error);}}
}
