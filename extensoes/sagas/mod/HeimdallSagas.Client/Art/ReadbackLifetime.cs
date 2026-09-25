using System;
namespace Heimdall.Sagas.Mod;
// Pure nonblocking ownership policy. A cancelled job retains its resources until all issued requests finish.
internal sealed class ReadbackLifetime {
 int pending;bool retired,released;Action? cleanup;
 internal void Begin(){if(retired)throw new InvalidOperationException("Cannot submit retired capture.");pending++;}
 internal void Complete(){if(pending==0)throw new InvalidOperationException("Readback completed twice.");pending--;ReleaseIfReady();}
 internal void Retire(Action action){if(retired)return;retired=true;cleanup=action;ReleaseIfReady();}
 void ReleaseIfReady(){if(!retired||pending!=0||released)return;released=true;var action=cleanup;cleanup=null;action?.Invoke();}
}
