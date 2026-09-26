using System;
using System.Collections.Generic;
using System.IO;
using System.IO.Pipes;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;

namespace HeimdallNexus.Desktop
{
    /// <summary>
    /// JSON lines between the window (the signed-in user) and the elevated worker that
    /// installs or removes Heimdall. The browser engine never runs as administrator.
    /// </summary>
    sealed class Channel : IDisposable
    {
        static readonly JavaScriptSerializer Json = new JavaScriptSerializer();
        readonly PipeStream pipe;
        StreamWriter writer;
        readonly object gate = new object();

        Channel(PipeStream pipe) { this.pipe = pipe; }

        public static string NewName() => "HeimdallNexus-" + Guid.NewGuid().ToString("N");

        public static Channel Serve(string name) =>
            new Channel(new NamedPipeServerStream(name, PipeDirection.InOut, 1, PipeTransmissionMode.Byte, PipeOptions.Asynchronous));

        public static Channel Connect(string name)
        {
            var client = new NamedPipeClientStream(".", name, PipeDirection.InOut, PipeOptions.Asynchronous);
            client.Connect(15000);
            return new Channel(client);
        }

        /// <summary>Waits for the worker on a background thread, then reads until the pipe closes.</summary>
        public void Accept(Action<Dictionary<string, object>> onMessage, Action onClosed)
        {
            new Thread(() =>
            {
                try
                {
                    var server = (NamedPipeServerStream)pipe;
                    var waiting = server.BeginWaitForConnection(null, null);
                    if (!waiting.AsyncWaitHandle.WaitOne(TimeSpan.FromMinutes(2))) { onClosed(); return; }
                    server.EndWaitForConnection(waiting);
                }
                catch (Exception) { onClosed(); return; }
                Read(onMessage, onClosed);
            }) { IsBackground = true }.Start();
        }

        public void Listen(Action<Dictionary<string, object>> onMessage, Action onClosed) =>
            new Thread(() => Read(onMessage, onClosed)) { IsBackground = true }.Start();

        void Read(Action<Dictionary<string, object>> onMessage, Action onClosed)
        {
            try
            {
                using (var reader = new StreamReader(pipe, new UTF8Encoding(false), false, 4096, true))
                {
                    string line;
                    while ((line = reader.ReadLine()) != null)
                    {
                        Dictionary<string, object> message;
                        try { message = Json.Deserialize<Dictionary<string, object>>(line); }
                        catch (Exception) { continue; }
                        if (message != null) onMessage(message);
                    }
                }
            }
            catch (Exception) { }
            onClosed();
        }

        public void Send(object message)
        {
            lock (gate)
            {
                try
                {
                    if (!pipe.IsConnected) return;
                    if (writer == null) writer = new StreamWriter(pipe, new UTF8Encoding(false), 4096, true) { AutoFlush = true };
                    writer.WriteLine(Json.Serialize(message));
                }
                catch (IOException) { }
                catch (ObjectDisposedException) { }
            }
        }

        public void Dispose()
        {
            try { pipe.Dispose(); } catch (Exception) { }
        }
    }
}
